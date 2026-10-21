import json
import os
import re
import time
from difflib import get_close_matches
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from core.database import get_connection, init_db
from core.google_oauth import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    SCOPES_PUBLISH,
    SCOPES_YOUTUBE,
    SCOPES_YOUTUBE_FORCE_SSL,
    decifrar_token,
)
from core.metadata_ai import gerar_metadados_blindados
from core.cutter import _titulo_tem_evidencia

PUBLISH_SCOPE = SCOPES_PUBLISH
YOUTUBE_WRITE_SCOPES = (SCOPES_PUBLISH, SCOPES_YOUTUBE, SCOPES_YOUTUBE_FORCE_SSL)
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_TITLE_LIMIT = 100
BEHAVIORAL_TIME_SCORES = {
    "manha": {"07:00": 100, "08:00": 98, "09:00": 92},
    "almoco": {"11:30": 100, "12:30": 98, "13:30": 92},
    "tarde": {"15:00": 78, "16:30": 72, "17:30": 68},
    "noite": {"18:00": 92, "20:00": 100, "21:00": 98, "22:00": 88},
}
BEHAVIORAL_CATEGORY_RULES = (
    ("manha", ("notícia", "noticias", "atualidade", "política", "politica", "produtividade", "trabalho", "negócio", "negocio")),
    ("almoco", ("humor", "comédia", "comedia", "curiosidade", "entretenimento", "viral", "rápido", "rapido")),
    ("noite", ("gaming", "gameplay", "jogo", "história", "historia", "relaxamento", "mistério", "misterio", "terror")),
)


def _youtube_client(perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        profile = conn.execute(
            "SELECT access_token_ciphertext, refresh_token_ciphertext, scopes FROM perfis_google WHERE perfil_id=? AND status='conectado' ORDER BY atualizado_em DESC LIMIT 1",
            (perfil_id,),
        ).fetchone()
    finally:
        conn.close()
    if not profile or not profile["refresh_token_ciphertext"]:
        raise RuntimeError("Conecte o Google novamente com permissão de publicação no YouTube.")
    try:
        scopes = json.loads(profile["scopes"] or "[]")
    except (TypeError, json.JSONDecodeError):
        scopes = []
    if PUBLISH_SCOPE not in scopes:
        raise RuntimeError("A conta Google está conectada apenas para leitura. Reconecte o perfil e autorize a permissão de publicação no YouTube.")
    missing_scopes = [scope for scope in YOUTUBE_WRITE_SCOPES if scope not in scopes]
    if missing_scopes:
        raise RuntimeError("A conta Google precisa renovar as permissões do YouTube para publicar e relacionar vídeos.")
    access_token = decifrar_token(profile["access_token_ciphertext"]) if profile["access_token_ciphertext"] else None
    credentials = Credentials(
        token=access_token,
        refresh_token=decifrar_token(profile["refresh_token_ciphertext"]),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=list(YOUTUBE_WRITE_SCOPES),
    )
    return build("youtube", "v3", credentials=credentials)


def _metadata_for_cut(cut):
    transcript = ""
    persisted_title = _metadata_text(cut.get("titulo"), cut.get("titulo_sugerido"))
    persisted_description = _metadata_text(cut.get("descricao_publicacao"), cut.get("descricao_sugerida"))
    has_persisted_editorial = _usable_metadata(persisted_title) and _usable_metadata(persisted_description)
    if has_persisted_editorial:
        metadata = {}
        tags = cut.get("tags") or []
        hashtags = cut.get("hashtags") or []
        title = persisted_title
        description = persisted_description
    else:
        transcript = _transcript_for_cut(cut)
        context = "\n".join(filter(None, [
            f"Título original: {cut.get('video_titulo', '')}",
            f"Título do corte: {cut.get('titulo', '')}",
            f"Transcrição literal do trecho (use para conferir fidelidade, não copie): {transcript}",
            f"Descrição manual para revisar (não copie se estiver inadequada): {cut.get('descricao_publicacao', '')}",
            f"Gancho: {cut.get('gancho', '')}",
            f"Promessa: {cut.get('promessa', '')}",
            f"Virada: {cut.get('virada', '')}",
            f"Conclusão: {cut.get('conclusao', '')}",
        ]))
        metadata = gerar_metadados_blindados(context)
        tags = metadata.get("tags") or []
        hashtags = metadata.get("hashtags") or []
        original_title = str(cut.get("video_titulo") or "").strip()
        title = _metadata_text(metadata.get("titulo"), cut.get("titulo"))
        title = _restore_entities(title, original_title)
        if not _titulo_tem_evidencia(title, transcript or original_title):
            title = _metadata_text(cut.get("titulo"), original_title)
        if not _usable_metadata(title):
            title = _restore_entities(_metadata_text(cut.get("titulo"), cut.get("gancho")), original_title)
        if not _usable_metadata(title):
            title = _restore_entities(_metadata_text(original_title, "Corte do canal"), original_title)
        description = _metadata_text(metadata.get("descricao") or metadata.get("descricao_short") or cut.get("descricao_publicacao"))
    original_title = str(cut.get("video_titulo") or "").strip()
    title = _truncate_youtube_title(title)
    description = _restore_entities(_dedupe_repeated_text(description), original_title)
    if not _usable_metadata(description):
        description = ""
    if transcript and _same_text(description, transcript):
        description = ""
    original_url = _original_video_url(cut.get("video_id"))
    if original_url and description:
        description = f"{description}\n\nVídeo original: {original_url}" if description else f"Vídeo original: {original_url}"
    if not description:
        return title, "", tags
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    tags = [str(tag).strip()[:30] for tag in tags if str(tag).strip()][:30]
    hashtags = _normalize_hashtags(hashtags or tags, description)
    if hashtags:
        description = f"{description.rstrip()}\n\n{' '.join(hashtags)}"
    return title, description, tags


def _truncate_youtube_title(title, limit=YOUTUBE_TITLE_LIMIT):
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    if len(title) <= limit:
        return title
    suffix = "..."
    budget = max(1, limit - len(suffix))
    truncated = title[:budget].rstrip()
    if " " in truncated and len(title) > budget and not title[budget:budget + 1].isspace():
        truncated = truncated.rsplit(" ", 1)[0].rstrip()
    return f"{truncated}{suffix}"


def _persist_final_metadata(cut, title, description, perfil_id=None):
    cut_id = cut.get("id") or cut.get("cut_id")
    if cut_id is None:
        return
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE cortes_gerados SET titulo=?, descricao_publicacao=?, atualizado_em=CURRENT_TIMESTAMP WHERE id=? AND perfil_id=?",
            (title, description, cut_id, int(perfil_id or cut.get("perfil_id") or 1)),
        )
        conn.commit()
    finally:
        conn.close()


def _transcript_for_cut(cut):
    video_id = str(cut.get("video_id") or "").strip()
    perfil_id = int(cut.get("perfil_id") or 1)
    if not video_id:
        return ""
    conn = get_connection()
    try:
        row = conn.execute("SELECT transcricao, transcricao_segmentos FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
    finally:
        conn.close()
    if not row:
        return ""
    try:
        segments = json.loads(row["transcricao_segmentos"] or "[]")
    except (TypeError, json.JSONDecodeError):
        segments = []
    start = cut.get("segmento_inicio")
    end = cut.get("segmento_fim")
    if start is not None and end is not None and segments:
        selected = [item.get("texto", "") for item in segments if int(item.get("indice", -1)) >= int(start) and int(item.get("indice", -1)) <= int(end)]
        if selected:
            return " ".join(selected)
    return str(row["transcricao"] or "").strip()


def _same_text(left, right):
    normalize = lambda value: re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    return bool(normalize(left)) and normalize(left) == normalize(right)


def _normalize_hashtags(values, description):
    if isinstance(values, str):
        values = re.split(r"[,\s]+", values)
    result = []
    generic = {"#viral", "#fyp", "#shorts", "#youtube", "#trend", "#paravoce"}
    for value in values if isinstance(values, list) else []:
        tag = re.sub(r"[^#\wÀ-ÿ]", "", str(value or "").strip().replace("#", "#", 1))
        if not tag.startswith("#"):
            tag = f"#{tag}"
        if len(tag) <= 1 or tag.casefold() in generic or tag.casefold() in {item.casefold() for item in result}:
            continue
        if tag.casefold() not in description.casefold():
            result.append(tag[:50])
        if len(result) == 4:
            break
    return result


def _original_video_url(video_id):
    video_id = str(video_id or "").strip()
    return f"https://www.youtube.com/watch?v={video_id}" if YOUTUBE_VIDEO_ID_RE.fullmatch(video_id) else ""


def _metadata_text(value, fallback=""):
    text = str(value or "").strip()
    if not _usable_metadata(text):
        text = str(fallback or "").strip()
    return re.sub(r"\s+", " ", text)


def _usable_metadata(value):
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    return bool(normalized) and normalized not in {"na", "naoindisponivel", "seminformacao", "null", "none"}


def _dedupe_repeated_text(text):
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", str(text or "")) if part.strip()]
    result = []
    for part in parts:
        if part.casefold() not in {item.casefold() for item in result}:
            result.append(part)
    return " ".join(result)


def _restore_entities(text, original_title):
    """Corrige apenas tokens parecidos com entidades comprovadas no título original."""
    original_tokens = [token for token in re.findall(r"[\wÀ-ÿ]+", original_title) if len(token) >= 3]
    comparable_tokens = {token.casefold(): token for token in original_tokens}
    if not original_tokens:
        return text
    replacements = {}
    for token in re.findall(r"[\wÀ-ÿ]+", text):
        match = get_close_matches(token.casefold(), list(comparable_tokens), n=1, cutoff=0.70)
        if match and token.casefold() != match[0]:
            replacements[token] = comparable_tokens[match[0]]
    for wrong, correct in replacements.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", correct, text, flags=re.IGNORECASE)
    return text


def _historical_hour_scores(perfil_id):
    scores = {}
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT data_publicacao, slot_hora, views, likes FROM videos_historico WHERE perfil_id=? AND status IN ('publicado_externo', 'publicado')", (perfil_id,)).fetchall()
    finally:
        conn.close()
    for row in rows:
        try:
            date = datetime.strptime(row["data_publicacao"], "%Y-%m-%d")
            hour = int(str(row["slot_hora"] or "17:30").split(":")[0])
        except (TypeError, ValueError):
            continue
        key = (date.weekday(), hour)
        scores[key] = scores.get(key, 0) + int(row["views"] or 0) + int(row["likes"] or 0) * 20
    return scores


def _behavioral_period(cut):
    recommendation = cut.get("horario_recomendado") or {}
    period = recommendation.get("periodo")
    if period in BEHAVIORAL_TIME_SCORES:
        return period
    context = " ".join(str(cut.get(field) or "") for field in ("categoria", "tema", "formato", "video_titulo", "titulo", "descricao_publicacao", "promessa", "gancho")).casefold()
    for candidate_period, keywords in BEHAVIORAL_CATEGORY_RULES:
        if any(keyword in context for keyword in keywords):
            return candidate_period
    return "noite"


def planejar_melhores_slots(quantidade, perfil_id=1, cuts=None):
    scores = _historical_hour_scores(perfil_id)
    agora = datetime.now().replace(second=0, microsecond=0)
    cuts = (cuts or [{}] * quantidade)[:quantidade]
    candidatos = []
    for dia_offset in range(0, 15):
        dia = agora + timedelta(days=dia_offset)
        for periodo, time_scores in BEHAVIORAL_TIME_SCORES.items():
            for hora_texto in time_scores:
                hora, minuto = (int(parte) for parte in hora_texto.split(":", 1))
                momento = dia.replace(hour=hora, minute=minuto)
                if momento <= agora:
                    continue
                historical_score = scores.get((momento.weekday(), hora), 0)
                candidatos.append((momento.date(), momento, periodo, time_scores[hora_texto], historical_score))
    escolhidos = []
    momentos_usados = set()
    posts_by_day = {}
    for cut in cuts:
        period = _behavioral_period(cut)
        recommendation = cut.get("horario_recomendado") or {}
        preferred_days = recommendation.get("dias_preferidos") or []
        confidence = float(recommendation.get("confianca") or 0)
        ranked_by_day = {}
        for date, momento, candidate_period, behavioral_score, historical_score in candidatos:
            if momento in momentos_usados:
                continue
            score = behavioral_score if candidate_period == period else 0
            score += historical_score / 1000
            if momento.weekday() in preferred_days:
                score += 20 * confidence
            ranked_by_day.setdefault(date, []).append((score, momento))
        next_date = min(ranked_by_day) if ranked_by_day else None
        ranked = sorted(ranked_by_day.get(next_date, []), key=lambda item: (-item[0], item[1]))
        momento = ranked[0][1] if ranked else None
        if momento:
            escolhidos.append(momento)
            momentos_usados.add(momento)
            posts_by_day[momento.date()] = posts_by_day.get(momento.date(), 0) + 1
    return [{"date": item.strftime("%Y-%m-%d"), "time": item.strftime("%H:%M")} for item in escolhidos]


def publicar_e_agendar_corte(cut, data_publicacao, hora_publicacao, perfil_id=1):
    caminho = cut.get("caminho_saida")
    if not caminho or not os.path.isfile(caminho):
        raise RuntimeError("O MP4 renderizado não foi encontrado.")
    titulo, descricao, tags = _metadata_for_cut(cut)
    if not descricao:
        raise RuntimeError("Resumo editorial não disponível; o Short não pode ser publicado.")
    publish_at = f"{data_publicacao}T{hora_publicacao}:00-03:00"
    youtube = _youtube_client(perfil_id)
    response = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": titulo, "description": descricao, "tags": tags, "categoryId": "22"},
            "status": {"privacyStatus": "private", "publishAt": publish_at, "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(caminho, mimetype="video/mp4", resumable=True),
    ).execute()
    _persist_final_metadata(cut, titulo, descricao, perfil_id)
    return {"youtube_id": response["id"], "titulo": titulo, "descricao": descricao, "tags": tags, "date": data_publicacao, "time": hora_publicacao}


def publicar_corte_imediato(cut, perfil_id=1):
    caminho = cut.get("caminho_saida")
    if not caminho or not os.path.isfile(caminho):
        raise RuntimeError("O MP4 renderizado não foi encontrado.")
    titulo, descricao, tags = _metadata_for_cut(cut)
    if not descricao:
        raise RuntimeError("Resumo editorial não disponível; o Short não pode ser publicado.")
    agora = datetime.now()
    youtube = _youtube_client(perfil_id)
    response = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": titulo, "description": descricao, "tags": tags, "categoryId": "22"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(caminho, mimetype="video/mp4", resumable=True),
    ).execute()
    _persist_final_metadata(cut, titulo, descricao, perfil_id)
    return {"youtube_id": response["id"], "titulo": titulo, "descricao": descricao, "tags": tags, "date": agora.strftime("%Y-%m-%d"), "time": agora.strftime("%H:%M")}


def aguardar_processamento_video(youtube_id, perfil_id=1, timeout_seconds=300, poll_seconds=5):
    """Aguarda o YouTube concluir o processamento antes de usar o vídeo no Studio."""
    youtube = _youtube_client(perfil_id)
    deadline = time.monotonic() + timeout_seconds
    last_status = "desconhecido"
    while time.monotonic() < deadline:
        response = youtube.videos().list(
            part="status,processingDetails",
            id=youtube_id,
        ).execute()
        items = response.get("items") or []
        if not items:
            raise RuntimeError(f"O YouTube não encontrou o vídeo enviado ({youtube_id}).")
        item = items[0]
        processing = item.get("processingDetails") or {}
        last_status = processing.get("processingStatus") or item.get("status", {}).get("uploadStatus") or last_status
        if last_status == "succeeded":
            return {"status": last_status, "youtube_id": youtube_id}
        if last_status in {"failed", "terminated", "rejected"}:
            reason = processing.get("processingFailureReason") or "processamento rejeitado pelo YouTube"
            raise RuntimeError(f"O YouTube não concluiu o processamento do vídeo: {reason}.")
        time.sleep(poll_seconds)
    raise TimeoutError(f"O vídeo {youtube_id} ainda está sendo processado pelo YouTube (status: {last_status}).")
