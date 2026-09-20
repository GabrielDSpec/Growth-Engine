import json
import os
import re
from difflib import get_close_matches
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from core.config import HORARIOS_PICO
from core.database import get_connection, init_db
from core.google_oauth import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, decifrar_token
from core.metadata_ai import gerar_metadados_blindados

PUBLISH_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _youtube_client(perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        profile = conn.execute(
            "SELECT refresh_token_ciphertext, scopes FROM perfis_google WHERE perfil_id=? AND status='conectado' ORDER BY atualizado_em DESC LIMIT 1",
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
    credentials = Credentials(
        token=None,
        refresh_token=decifrar_token(profile["refresh_token_ciphertext"]),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=[PUBLISH_SCOPE],
    )
    return build("youtube", "v3", credentials=credentials)


def _metadata_for_cut(cut):
    context = "\n".join(filter(None, [
        f"Título original: {cut.get('video_titulo', '')}",
        f"Título do corte: {cut.get('titulo', '')}",
        f"Gancho: {cut.get('gancho', '')}",
        f"Promessa: {cut.get('promessa', '')}",
        f"Virada: {cut.get('virada', '')}",
        f"Conclusão: {cut.get('conclusao', '')}",
    ]))
    metadata = gerar_metadados_blindados(context)
    tags = metadata.get("tags") or []
    original_title = str(cut.get("video_titulo") or "").strip()
    title = _metadata_text(metadata.get("titulo"), cut.get("titulo"))
    title = _restore_entities(title, original_title)[:100]
    if not _usable_metadata(title):
        title = _restore_entities(_metadata_text(cut.get("titulo"), cut.get("gancho")), original_title)[:100]
    if not _usable_metadata(title):
        title = _restore_entities(_metadata_text(original_title, "Corte do canal"), original_title)[:100]
    description = _metadata_text(metadata.get("descricao") or metadata.get("descricao_short"), cut.get("promessa") or cut.get("gancho") or cut.get("conclusao"))
    description = _restore_entities(_dedupe_repeated_text(description), original_title)
    if not _usable_metadata(description):
        description = _restore_entities(_dedupe_repeated_text(" ".join(filter(None, [cut.get("gancho"), cut.get("promessa"), cut.get("conclusao")]))) or title, original_title)
    original_url = _original_video_url(cut.get("video_id"))
    if original_url and original_url not in description:
        description = f"{description}\n\nVídeo original: {original_url}"
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    tags = [str(tag).strip()[:30] for tag in tags if str(tag).strip()][:30]
    return title, description, tags


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


def planejar_melhores_slots(quantidade, perfil_id=1, cuts=None):
    scores = _historical_hour_scores(perfil_id)
    agora = datetime.now().replace(second=0, microsecond=0)
    candidatos = []
    periodos = {"manha": range(6, 12), "almoco": range(12, 15), "tarde": range(15, 18), "noite": range(18, 24)}
    for dia_offset in range(0, 15):
        dia = agora + timedelta(days=dia_offset)
        for hora_texto in HORARIOS_PICO:
            hora, minuto = (int(parte) for parte in hora_texto.split(":", 1))
            momento = dia.replace(hour=hora, minute=minuto)
            if momento <= agora:
                continue
            score = scores.get((momento.weekday(), hora), 0)
            candidatos.append((score, momento))
    escolhidos = []
    momentos_usados = set()
    cuts = (cuts or [{}] * quantidade)[:quantidade]
    # Mantém a cadência editorial: ocupa os melhores horários do mesmo dia
    # antes de avançar, permitindo três Shorts por dia com os slots configurados.
    candidatos_por_dia = {}
    for item in candidatos:
        candidatos_por_dia.setdefault(item[1].date(), []).append(item)
    dias = sorted(candidatos_por_dia)
    for index, cut in enumerate(cuts):
        recommendation = cut.get("horario_recomendado") or {}
        preferred_days = recommendation.get("dias_preferidos") or []
        period = recommendation.get("periodo")
        confidence = float(recommendation.get("confianca") or 0)
        ranked = []
        for dia in dias:
            for channel_score, momento in candidatos_por_dia[dia]:
                semantic_score = 0
                if momento.weekday() in preferred_days:
                    semantic_score += 30 * confidence
                if period in periodos and momento.hour in periodos[period]:
                    semantic_score += 25 * confidence
                ranked.append((dia, channel_score + semantic_score, momento))
        ranked.sort(key=lambda item: (item[0], -item[1], item[2]))
        momento = next((momento for _, _, momento in ranked if momento not in momentos_usados), None)
        if momento:
            escolhidos.append(momento)
            momentos_usados.add(momento)
    return [{"date": item.strftime("%Y-%m-%d"), "time": item.strftime("%H:%M")} for item in escolhidos]


def publicar_e_agendar_corte(cut, data_publicacao, hora_publicacao, perfil_id=1):
    caminho = cut.get("caminho_saida")
    if not caminho or not os.path.isfile(caminho):
        raise RuntimeError("O MP4 renderizado não foi encontrado.")
    titulo, descricao, tags = _metadata_for_cut(cut)
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
    return {"youtube_id": response["id"], "titulo": titulo, "descricao": descricao, "tags": tags, "date": data_publicacao, "time": hora_publicacao}
