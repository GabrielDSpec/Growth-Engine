from core.transcriber import TranscriptionCancelled, transcrever_arquivo_local_segmentos, transcrever_video_youtube
import json
import mimetypes
import os
import subprocess
import threading
import time
import uuid
import urllib.request
import tempfile
import yt_dlp
import traceback
from urllib.parse import parse_qs, urlparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from core.database import get_connection, init_db, salvar_perfil_google
from core.cutter import gerar_cortes_com_retry, garimpar_vacas_roxas, calcular_score_observavel, refinar_titulos_com_ia
from core.cutter import normalizar_titulo_corte, refinar_titulo_corte
from core.config import MAX_UPLOAD_BYTES, PASTA_LONGOS, PASTA_SHORTS, UPLOAD_CHUNK_BYTES, obter_pastas_midia
from core.cuts_repository import create_cut, update_cut, update_cut_schedule_recommendation, list_cuts
from core.media_tools import MediaToolError, validar_ferramentas, renderizar_corte, localizar_ferramentas
from core.sync_channel import sincronizar_canal_youtube
from core.content_intelligence import analisar_videos_longos, obter_status_analises
from core.radar import buscar_radar, obter_localizacao, salvar_localizacao
from core.opportunities import criar_oportunidade, gerar_briefing, listar_oportunidades, gerar_sugestoes_top15
from core.tasks import atualizar_tarefa, obter_tarefa
from core.task_runner import TaskRunner
from core.job_repository import create_job, list_active_jobs, recover_running_jobs, select_job, update_job
from core.content_profile import consolidar_perfil_canal, obter_perfil_canal
from core.notifications import criar_notificacao, listar_notificacoes, marcar_notificacao_lida, limpar_notificacoes_lidas
from core.transcriber import transcrever_video_youtube, transcrever_arquivo_local_segmentos
from core.tenant import normalize_profile_id
from core.profiles_repository import create_profile, delete_profile
from core.utils import registrar_log
from core.utils import calcular_hash_arquivo
from core.google_oauth import criar_url_autorizacao, concluir_autorizacao, serializar_scopes, cifrar_token
from core.publisher import planejar_melhores_slots, publicar_e_agendar_corte
from core.metadata_ai import recomendar_horario_corte
from googleapiclient.discovery import build

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_ROOT = os.path.join(PROJECT_ROOT, "frontend")
TRANSCRIPTION_JOBS = {}
CUT_JOBS = {}
CANCEL_EVENTS = {}
OAUTH_STATES = {}
OAUTH_STATE_TTL = 300
SYNC_STATUS = {}
SYNC_STATUS_DEFAULT = {
    "status": "idle",
    "message": "Nenhuma sincronização executada",
    "processed": 0,
    "total": 0,
    "progress": 0,
    "eta_seconds": None,
}
CONTENT_STATUS = {}
CONTENT_STATUS_DEFAULT = {"status": "idle", "processed": 0, "total": 0, "progress": 0, "eta_seconds": None, "message": "Nenhuma análise executada"}
OPPORTUNITY_STATUS = {}
OPPORTUNITY_STATUS_DEFAULT = {"status": "idle", "message": "Nenhuma sugestão gerada"}
PROFILE_STATUS = {}
PROFILE_STATUS_DEFAULT = {"status": "idle", "processed": 0, "total": 0, "progress": 0, "eta_seconds": None, "message": "Nenhum perfil gerado"}
TASK_RUNNER = TaskRunner(max_workers=1)
recover_running_jobs()


class JobCancelled(RuntimeError):
    pass


def _cancel_event(job_id):
    return CANCEL_EVENTS.setdefault(job_id, threading.Event())


def _raise_if_cancelled(job_id):
    if _cancel_event(job_id).is_set():
        raise JobCancelled("Processamento cancelado pelo usuário.")


def _update_runtime_job(store, job_id, perfil_id, **changes):
    store[job_id].update(changes)
    update_job(
        job_id,
        status=changes.get("status"),
        progress=changes.get("progress"),
        message=changes.get("message"),
        error=changes.get("error"),
        result=json.dumps(changes.get("suggestions", changes.get("segments")), ensure_ascii=False) if "suggestions" in changes or "segments" in changes else None,
        perfil_id=perfil_id,
    )


def _profile_status(store, perfil_id, default):
    return store.setdefault(perfil_id, dict(default))


def _local_media_title(path):
    filename = os.path.basename(path)
    parts = filename.split("_", 2)
    return parts[2] if filename.startswith("upload_") and len(parts) == 3 else filename


def _present_cut_score(cut):
    titled = {**cut, "titulo": refinar_titulo_corte(cut.get("titulo"), cut.get("gancho"))}
    if float(cut.get("score_vaca_roxa") or 0) > 0:
        return titled
    text = " ".join(filter(None, (cut.get("gancho"), cut.get("promessa"), cut.get("virada"), cut.get("conclusao"))))
    if not text:
        return titled
    score = calcular_score_observavel(text, [{"texto": cut.get("gancho") or text}])
    return {**titled, "score_vaca_roxa": score["score"], "pontuacoes": score["pontuacoes"]}


def _youtube_video_url(url):
    parsed = urlparse((url or "").strip())
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


def _transcript_cache_path(path, perfil_id):
    digest = calcular_hash_arquivo(path)
    return os.path.join(obter_pastas_midia(perfil_id)["transcripts"], f"{digest}.srt"), digest


def _cut_duration_range(minimum, maximum):
    try:
        minimum = max(5, min(300, int(minimum)))
        maximum = max(5, min(300, int(maximum)))
    except (TypeError, ValueError):
        return 30, 60
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    return minimum, maximum


def _process_local_media_job(job_id, path, perfil_id, duracao_minima=30, duracao_maxima=60):
    store = CUT_JOBS
    media_dirs = obter_pastas_midia(perfil_id)
    store[job_id] = {"status": "running", "progress": 5, "message": "Preparando transcrição", "stage": "preparing", "video_id": job_id, "perfil_id": perfil_id}
    update_job(job_id, status="running", progress=5, message="Transcrevendo arquivo local", perfil_id=perfil_id)
    try:
        _raise_if_cancelled(job_id)
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO videos_historico (perfil_id, video_id, titulo, tipo, status, arquivo_origem, atualizado_em) VALUES (?, ?, ?, 'video', 'upload_local', ?, CURRENT_TIMESTAMP)",
                (perfil_id, job_id, _local_media_title(path), path),
            )
            conn.commit()
        finally:
            conn.close()
        def update_progress(progress, message, details=None):
            details = details or {}
            store[job_id].update({"progress": progress, "message": message, "perfil_id": perfil_id, **details})
            update_job(job_id, status="running", progress=progress, message=message, perfil_id=perfil_id)

        cache_srt_path, file_hash = _transcript_cache_path(path, perfil_id)
        segments = transcrever_arquivo_local_segmentos(path, progress_callback=update_progress, cancel_callback=lambda: _cancel_event(job_id).is_set(), cache_srt_path=cache_srt_path)
        _raise_if_cancelled(job_id)
        if not segments:
            raise RuntimeError("Nenhuma fala encontrada no arquivo local.")
        duration = max(segment["fim"] for segment in segments)
        text = "\n".join(f"[{s['indice']}] {s['inicio']:.3f}-{s['fim']:.3f}: {s['texto']}" for s in segments)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE videos_historico SET file_hash=?, transcricao=?, transcricao_segmentos=?, duracao_segundos=?, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
                (file_hash, " ".join(segment["texto"] for segment in segments), json.dumps(segments, ensure_ascii=False), round(duration), job_id, perfil_id),
            )
            conn.commit()
        finally:
            conn.close()
        store[job_id].update({"progress": 92, "message": "Qwen analisando segmentos", "stage": "analyzing", "segments_processed": len(segments), "segments_accepted": len(segments), "perfil_id": perfil_id})
        update_job(job_id, status="running", progress=92, message="Qwen analisando segmentos", perfil_id=perfil_id)
        _raise_if_cancelled(job_id)
        titulo_original = _local_media_title(path)
        analysis = gerar_cortes_com_retry(text, duration, segments, duracao_minima=duracao_minima, duracao_maxima=duracao_maxima, titulo_original=titulo_original)
        refinar_titulos_com_ia(analysis.get("cortes", []), titulo_original=titulo_original)
        refinar_titulos_com_ia(analysis.get("candidatos", []), titulo_original=titulo_original)
        _raise_if_cancelled(job_id)
        suggestions = analysis["cortes"]
        if analysis["status"] != "completed":
            validar_ferramentas()
            persisted_candidates = []
            for candidate in analysis.get("candidatos", []):
                round_number = candidate.get("numero_rodada", 1)
                round_name = f"{_local_media_title(path)}-curadoria-{round_number:02d}"
                cut_id = create_cut(
                    job_id,
                    job_id,
                    path,
                    candidate,
                    perfil_id=perfil_id,
                    status="candidato",
                    video_title=_local_media_title(path),
                    round_name=round_name,
                )
                output_name = f"{job_id}_{cut_id}_{normalizar_titulo_corte(candidate.get('titulo')) or 'candidato'}.mp4"
                output_path = os.path.join(media_dirs["shorts"], output_name)
                try:
                    update_cut(cut_id, status="renderizando", perfil_id=perfil_id)
                    renderizar_corte(path, output_path, candidate["inicio"], candidate["fim"], intervalos=candidate.get("montagem_intervalos"), vertical=True)
                    update_cut(cut_id, status="concluido", output_path=output_path, perfil_id=perfil_id)
                    candidate_status = "concluido"
                except Exception as error:
                    update_cut(cut_id, status="falhou", error=str(error), perfil_id=perfil_id)
                    candidate_status = "falhou"
                persisted_candidates.append({
                    **candidate,
                    "cut_id": cut_id,
                    "status": candidate_status,
                    "output_path": output_path if candidate_status == "concluido" else "",
                    "nome_rodada": round_name,
                    "video_titulo": _local_media_title(path),
                })
            message = f"Revisão necessária: {len(suggestions)} de 9 cortes recomendados; {len(persisted_candidates)} candidato(s) renderizado(s) para ponderação humana."
            result = {"analysis": analysis, "cortes": persisted_candidates}
            diagnostic_json = json.dumps(result, ensure_ascii=False)
            store[job_id].update({"status": "needs_review", "progress": 100, "message": message, "perfil_id": perfil_id, "suggestions": persisted_candidates, "resultado_json": diagnostic_json})
            update_job(job_id, status="needs_review", progress=100, message=message, result=diagnostic_json, perfil_id=perfil_id)
            return
        validar_ferramentas()
        results = []
        for suggestion in suggestions:
            _raise_if_cancelled(job_id)
            cut_id = create_cut(job_id, job_id, path, suggestion, perfil_id=perfil_id)
            output = os.path.join(media_dirs["shorts"], f"{job_id}_{cut_id}.mp4")
            try:
                update_cut(cut_id, status="renderizando", perfil_id=perfil_id)
                renderizar_corte(path, output, suggestion["inicio"], suggestion["fim"], intervalos=suggestion.get("montagem_intervalos"), vertical=True)
                update_cut(cut_id, status="concluido", output_path=output, perfil_id=perfil_id)
                results.append({**suggestion, "cut_id": cut_id, "status": "concluido", "output_path": output})
            except Exception as error:
                update_cut(cut_id, status="falhou", error=str(error), perfil_id=perfil_id)
                results.append({**suggestion, "cut_id": cut_id, "status": "falhou", "error": str(error)})
        result_payload = {"analysis": analysis, "cortes": results}
        store[job_id].update({"status": "completed", "progress": 100, "message": "Upload processado", "suggestions": results})
        update_job(job_id, status="completed", progress=100, message="Upload processado", result=json.dumps(result_payload, ensure_ascii=False), perfil_id=perfil_id)
    except (JobCancelled, TranscriptionCancelled) as error:
        store[job_id].update({"status": "cancelled", "message": str(error), "perfil_id": perfil_id})
        update_job(job_id, status="cancelled", message=str(error), perfil_id=perfil_id)
    except Exception as error:
        store[job_id].update({"status": "failed", "progress": 0, "message": str(error)})
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)


def _force_download_job(job_id, url, perfil_id, duracao_minima=30, duracao_maxima=60):
    output_dir = os.path.join(obter_pastas_midia(perfil_id)["downloads"], f"force_{job_id}")
    os.makedirs(output_dir, exist_ok=True)
    try:
        CUT_JOBS[job_id] = {"status": "running", "progress": 10, "message": "Baixando sem usar cache", "video_id": job_id, "perfil_id": perfil_id}
        opts = {"format": "bestvideo+bestaudio/best", "outtmpl": os.path.join(output_dir, "source.%(ext)s"), "overwrites": True, "nooverwrites": False, "quiet": True, "merge_output_format": "mp4"}
        with yt_dlp.YoutubeDL(opts) as downloader:
            downloader.download([url])
        source = next((os.path.join(output_dir, name) for name in os.listdir(output_dir) if name.endswith(".mp4")), None)
        if not source:
            raise RuntimeError("yt-dlp não produziu um MP4.")
        _process_local_media_job(job_id, source, perfil_id, duracao_minima, duracao_maxima)
    except Exception as error:
        CUT_JOBS[job_id] = {"status": "failed", "progress": 0, "message": str(error), "video_id": job_id, "perfil_id": perfil_id}
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)


def _receive_mp4_upload(handler, content_type, content_length, upload_dir):
    if content_length <= 0 or content_length > MAX_UPLOAD_BYTES:
        raise ValueError(f"Upload excede o limite de {MAX_UPLOAD_BYTES} bytes.")
    boundary_token = content_type.split("boundary=", 1)[-1].strip().strip('"')
    if not boundary_token:
        raise ValueError("multipart boundary ausente.")
    boundary = ("--" + boundary_token).encode()
    buffer = bytearray()
    while b"\r\n\r\n" not in buffer and len(buffer) < 65536:
        buffer.extend(handler.rfile.read(min(UPLOAD_CHUNK_BYTES, content_length - len(buffer))))
    separator = b"\r\n\r\n"
    header_end = buffer.find(separator)
    if header_end < 0:
        raise ValueError("Cabeçalho multipart inválido.")
    headers = buffer[:header_end].decode("latin-1", errors="replace")
    disposition = next((line for line in headers.split("\r\n") if line.lower().startswith("content-disposition:")), "")
    if 'name="file"' not in disposition:
        raise ValueError("Campo multipart 'file' ausente.")
    filename = disposition.split("filename=", 1)[-1].strip().strip('"') if "filename=" in disposition else "upload.mp4"
    extension = os.path.splitext(filename)[1].lower()
    if extension not in {".mp4", ".mkv"}:
        raise ValueError("Envie um vídeo MP4 ou MKV.")
    safe_name = os.path.basename(filename).replace("\x00", "") or f"upload{extension}"
    os.makedirs(upload_dir, exist_ok=True)
    temp_path = os.path.join(upload_dir, f"upload_{uuid.uuid4().hex}_{safe_name}")
    payload = buffer[header_end + len(separator):]
    remaining = content_length - len(buffer)
    with open(temp_path, "wb") as output:
        while True:
            marker = payload.find(b"\r\n" + boundary)
            if marker >= 0:
                output.write(payload[:marker])
                break
            if remaining <= 0:
                output.write(payload)
                break
            keep = max(len(boundary) + 4, 1024)
            if len(payload) > keep:
                output.write(payload[:-keep])
                payload = payload[-keep:]
            chunk = handler.rfile.read(min(UPLOAD_CHUNK_BYTES, remaining))
            remaining -= len(chunk)
            if not chunk:
                break
            payload += chunk
    if not os.path.isfile(temp_path) or os.path.getsize(temp_path) <= 0:
        if os.path.exists(temp_path): os.remove(temp_path)
        raise ValueError("Upload vazio ou inválido.")
    return temp_path


def _format_count(value):
    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


PUBLIC_PROFILE_PATHS = {"/api/profiles", "/api/profiles/active", "/api/profiles/create", "/api/backlog"}


def _request_profile_id(handler):
    raw = handler.headers.get("X-Profile-Id") or parse_qs(urlparse(handler.path).query).get("perfil_id", [None])[0]
    if raw is None or not raw.strip():
        raise ValueError("X-Profile-Id é obrigatório.")
    try:
        perfil_id = normalize_profile_id(raw)
    except (TypeError, ValueError):
        raise ValueError("X-Profile-Id é obrigatório e deve ser um inteiro positivo.")
    conn = get_connection()
    try:
        if not conn.execute("SELECT 1 FROM perfis WHERE id=? AND ativo=1", (perfil_id,)).fetchone():
            raise ValueError("Perfil ativo inválido.")
    finally:
        conn.close()
    return perfil_id


def _video_dict(row):
    views = int(row["views"] or 0)
    likes = int(row["likes"] or 0)
    return {
        "id": row["video_id"],
        "title": row["titulo"] or "Sem título",
        "thumbnail_url": f"https://i.ytimg.com/vi/{row['video_id']}/hqdefault.jpg" if len(str(row["video_id"] or "")) == 11 else "",
        "type": "Short" if row["tipo"] == "short" else "Longo" if row["tipo"] == "video" else "Não classificado",
        "views": views,
        "views_display": _format_count(views),
        "likes": likes,
        "likes_display": _format_count(likes),
        "date": row["data_publicacao"] or "Data não informada",
        "score": round((likes / views) * 100, 2) if views else None,
        "duration_seconds": row["duracao_segundos"] if "duracao_segundos" in row.keys() else None,
    }


def _fetch_videos(tipo=None, limit=15, perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        query = """
            SELECT video_id, titulo, tipo, views, likes, data_publicacao, duracao_segundos
            FROM videos_historico
        """
        params = [perfil_id]
        query += " WHERE perfil_id = ?"
        if tipo in ("video", "short"):
            query += " AND tipo = ?"
            params.append(tipo)
        query += " ORDER BY CAST(views AS INTEGER) DESC LIMIT ?"
        params.append(limit)
        return [_video_dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def _dashboard_payload(perfil_id=1):
    all_videos = _fetch_videos(limit=10000, perfil_id=perfil_id)
    conn = get_connection()
    try:
        last_sync_at = conn.execute("SELECT MAX(atualizado_em) FROM videos_historico WHERE perfil_id=?", (perfil_id,)).fetchone()[0]
    finally:
        conn.close()
    longos = [video for video in all_videos if video["type"] == "Longo"]
    shorts = [video for video in all_videos if video["type"] == "Short"]
    top = sorted(all_videos, key=lambda video: video["views"], reverse=True)[:4]
    top_15 = sorted(all_videos, key=lambda video: video["views"], reverse=True)[:15]
    views_top_15 = sum(video["views"] for video in top_15)
    views_total = sum(video["views"] for video in all_videos)
    likes_total = sum(video["likes"] for video in all_videos)
    conn = get_connection()
    try:
        content_pending = conn.execute(
            "SELECT COUNT(*) FROM videos_historico WHERE perfil_id=? AND tipo='video' AND NOT EXISTS (SELECT 1 FROM analises_conteudo WHERE analises_conteudo.perfil_id=? AND analises_conteudo.video_id=videos_historico.video_id AND status='concluida')",
            (perfil_id, perfil_id),
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "videos": top,
        "last_sync_at": last_sync_at,
        "metrics": {
            "videos_analisados": len(all_videos),
            "longos": len(longos),
            "shorts": len(shorts),
            "views_top_15": views_top_15,
            "views_top_15_display": _format_count(views_top_15),
            "taxa_likes": round((likes_total / views_total) * 100, 2) if views_total else None,
            "analises_conteudo_pendentes": content_pending,
        },
    }


def _fetch_cut_sources(perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
                 SELECT video_id, titulo, tipo, views, likes, data_publicacao,
                     transcricao, transcricao_segmentos, arquivo_origem
            FROM videos_historico
            WHERE perfil_id = ? AND tipo = 'video' AND status IN ('publicado_externo', 'upload_local')
            ORDER BY CASE WHEN status = 'upload_local' THEN 0 ELSE 1 END,
                     CAST(COALESCE(views, 0) AS INTEGER) DESC,
                     atualizado_em DESC
            LIMIT 30
        """, (perfil_id,)).fetchall()
        videos = []
        for row in rows:
            video = {
                **_video_dict(row),
                "has_transcription": bool(row["transcricao"]),
                "has_segments": bool(row["transcricao_segmentos"]),
            }
            if not video["thumbnail_url"]:
                video["thumbnail_url"] = f"/api/cuts/source-thumbnail?video_id={video['id']}&perfil_id={perfil_id}"
            videos.append(video)
        return videos
    finally:
        conn.close()


def _fetch_transcription(video_id, perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT video_id, titulo, transcricao, transcricao_segmentos FROM videos_historico WHERE video_id = ? AND perfil_id = ?",
            (video_id, perfil_id),
        ).fetchone()
        if not row:
            return None
        try:
            segments = json.loads(row["transcricao_segmentos"] or "[]")
        except json.JSONDecodeError:
            segments = []
        return {
            "id": row["video_id"],
            "title": row["titulo"] or "Sem título",
            "text": row["transcricao"] or "",
            "segments": segments,
        }
    finally:
        conn.close()


def _local_source_path(video_id, perfil_id):
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT titulo, arquivo_origem, status FROM videos_historico WHERE video_id=? AND perfil_id=?",
            (video_id, perfil_id),
        ).fetchone()
    finally:
        conn.close()
    if not row or row["status"] != "upload_local":
        return None
    source_path = row["arquivo_origem"]
    if source_path and os.path.isfile(source_path):
        return source_path
    uploads_dir = obter_pastas_midia(perfil_id)["uploads"]
    title = (row["titulo"] or "").strip().lower()
    matches = [
        entry.path for entry in os.scandir(uploads_dir)
        if entry.is_file() and entry.name.lower().endswith((".mp4", ".mkv"))
        and (not title or entry.name.split("_", 2)[-1].lower() == title)
    ]
    return max(matches, key=os.path.getmtime) if matches else None


def _cut_cycle_name(video_title, job_id):
    return f"{video_title} · ciclo {str(job_id)[:8]}"


def _source_thumbnail_path(video_id, perfil_id):
    source_path = _local_source_path(video_id, perfil_id)
    if not source_path:
        return None
    thumbnail_dir = os.path.join(obter_pastas_midia(perfil_id)["downloads"], ".thumbnails")
    thumbnail_path = os.path.join(thumbnail_dir, f"{video_id}.jpg")
    if os.path.isfile(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
        return thumbnail_path
    try:
        ffmpeg, _ = localizar_ferramentas()
        os.makedirs(thumbnail_dir, exist_ok=True)
        result = subprocess.run(
            [ffmpeg, "-y", "-ss", "1", "-i", source_path, "-frames:v", "1", "-vf", "scale=640:-2", thumbnail_path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0 and os.path.isfile(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
            return thumbnail_path
    except (OSError, subprocess.SubprocessError, MediaToolError):
        pass
    return None


def _save_local_transcription(video_id, perfil_id, source_path, segments):
    text = " ".join(segment["texto"] for segment in segments)
    duration = round(max((segment["fim"] for segment in segments), default=0))
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE videos_historico SET transcricao=?, transcricao_segmentos=?, duracao_segundos=?, arquivo_origem=?, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
            (text, json.dumps(segments, ensure_ascii=False), duration, source_path, video_id, perfil_id),
        )
        conn.commit()
    finally:
        conn.close()
    return text


def _fetch_scheduled(perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT video_id, titulo, tipo, views, likes, data_publicacao,
                   slot_hora, status, atualizado_em
            FROM videos_historico
            WHERE perfil_id = ? AND status IN ('programado', 'agendado')
            ORDER BY data_publicacao, slot_hora, atualizado_em DESC
        """, (perfil_id,)).fetchall()
        return [{
            **_video_dict(row),
            "status": row["status"],
            "scheduled_date": row["data_publicacao"] or "Data não informada",
            "scheduled_time": row["slot_hora"] or "Horário não informado",
            "performance_score": None,
            "score_note": "Ainda não publicado; sem métricas reais",
        } for row in rows]
    finally:
        conn.close()


def _run_transcription_job(job_id, video_id, perfil_id):
    _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, status="running", progress=5, message="Preparando transcrição")

    def update(progress, message, details=None):
        _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, progress=progress, message=message, **(details or {}))

    try:
        _raise_if_cancelled(job_id)
        source_path = _local_source_path(video_id, perfil_id)
        if source_path:
            cache_srt_path, file_hash = _transcript_cache_path(source_path, perfil_id)
            segments = transcrever_arquivo_local_segmentos(source_path, progress_callback=update, cancel_callback=lambda: _cancel_event(job_id).is_set(), cache_srt_path=cache_srt_path)
            if not segments:
                raise RuntimeError("A transcrição local não encontrou segmentos de fala no arquivo.")
            text = _save_local_transcription(video_id, perfil_id, source_path, segments)
            conn = get_connection()
            try:
                conn.execute("UPDATE videos_historico SET file_hash=? WHERE video_id=? AND perfil_id=?", (file_hash, video_id, perfil_id))
                conn.commit()
            finally:
                conn.close()
        else:
            text = transcrever_video_youtube(video_id, progress_callback=update, perfil_id=perfil_id)
        _raise_if_cancelled(job_id)
        transcription = _fetch_transcription(video_id, perfil_id)
        _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, **{
            "status": "completed" if text else "failed",
            "progress": 100 if text else 0,
            "message": "Transcrição concluída" if text else "Não foi possível transcrever",
            "segments": transcription["segments"] if transcription else [],
        })
    except JobCancelled as error:
        _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
    except Exception as error:
        _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))


def _run_cut_job(job_id, video_id, perfil_id, duracao_minima=30, duracao_maxima=60):
    _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=10, message="Carregando transcrição")
    try:
        _raise_if_cancelled(job_id)
        transcription = _fetch_transcription(video_id, perfil_id)
        if not transcription or not transcription["segments"]:
            raise RuntimeError("Este vídeo ainda não possui transcrição segmentada.")
        segments = transcription["segments"]
        conn = get_connection()
        try:
            source_row = conn.execute("SELECT titulo FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
            titulo_original = source_row["titulo"] if source_row else ""
        finally:
            conn.close()
        duration = max(segment["fim"] for segment in segments)
        segmented_text = "\n".join(
            f"[{segment['indice']}] {segment['inicio']:.3f}-{segment['fim']:.3f}: {segment['texto']}"
            for segment in segments
        )
        def update_analysis_progress(attempt, total_attempts, phase, details):
            progress = min(75, 35 + round((attempt - 1) / max(total_attempts, 1) * 35))
            if phase == "validando":
                message = f"IA analisando conteúdo · rodada {attempt}/{total_attempts} · {details.get('candidatos', 0)} candidatos, {details.get('validos', 0)} válidos"
            else:
                message = f"IA analisando conteúdo · rodada {attempt}/{total_attempts}"
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=progress, message=message, analysis_round=attempt, analysis_total=total_attempts, **details)

        _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=30, message="IA analisando conteúdo · preparando contexto")
        _raise_if_cancelled(job_id)
        analysis = gerar_cortes_com_retry(segmented_text, duration, segments, duracao_minima=duracao_minima, duracao_maxima=duracao_maxima, progress_callback=update_analysis_progress, titulo_original=titulo_original)
        _raise_if_cancelled(job_id)
        refinar_titulos_com_ia(analysis.get("cortes", []), titulo_original=titulo_original)
        refinar_titulos_com_ia(analysis.get("candidatos", []), titulo_original=titulo_original)
        suggestions = analysis["cortes"]
        conn = get_connection()
        try:
            source_row = conn.execute("SELECT arquivo_origem FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
        finally:
            conn.close()
        source_path = source_row["arquivo_origem"] if source_row and source_row["arquivo_origem"] else ""
        if not source_path or not os.path.isfile(source_path):
            media_dirs = obter_pastas_midia(perfil_id)
            source_path = next((os.path.join(media_dirs["uploads"], name) for name in os.listdir(media_dirs["uploads"]) if video_id in name), "")
        if not source_path:
            raise MediaToolError("Arquivo de origem não encontrado na mídia do perfil.")
        conn = get_connection()
        try:
            video_row = conn.execute("SELECT titulo FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
        finally:
            conn.close()
        video_title = video_row["titulo"] if video_row else video_id
        if analysis["status"] != "completed":
            validar_ferramentas()
            persisted_candidates = []
            cycle_name = _cut_cycle_name(video_title, job_id)
            for candidate in analysis.get("candidatos", []):
                round_name = cycle_name
                cut_id = create_cut(job_id, video_id, source_path, candidate, perfil_id=perfil_id, status="candidato", video_title=video_title, round_name=round_name)
                output_name = f"{video_id}_{cut_id}_{normalizar_titulo_corte(candidate.get('titulo')) or 'candidato'}.mp4"
                output_path = os.path.join(obter_pastas_midia(perfil_id)["shorts"], output_name)
                try:
                    update_cut(cut_id, status="renderizando", perfil_id=perfil_id)
                    renderizar_corte(source_path, output_path, candidate["inicio"], candidate["fim"], intervalos=candidate.get("montagem_intervalos"), vertical=True)
                    recommendation_context = "\n".join(filter(None, [
                        f"Título original: {video_title}", f"Título do corte: {candidate.get('titulo', '')}",
                        f"Gancho: {candidate.get('gancho', '')}", f"Promessa: {candidate.get('promessa', '')}",
                        f"Virada: {candidate.get('virada', '')}", f"Conclusão: {candidate.get('conclusao', '')}",
                    ]))
                    try:
                        update_cut_schedule_recommendation(cut_id, recomendar_horario_corte(recommendation_context), perfil_id=perfil_id)
                    except Exception:
                        update_cut_schedule_recommendation(cut_id, {"periodo": "noite", "dias_preferidos": [], "confianca": 0, "justificativa": "Recomendação indisponível; usando o histórico do canal."}, perfil_id=perfil_id)
                    update_cut(cut_id, status="concluido", output_path=output_path, perfil_id=perfil_id)
                    candidate_status = "concluido"
                except Exception as error:
                    update_cut(cut_id, status="falhou", error=str(error), perfil_id=perfil_id)
                    candidate_status = "falhou"
                persisted_candidates.append({**candidate, "cut_id": cut_id, "status": candidate_status, "output_path": output_path if candidate_status == "concluido" else "", "nome_rodada": round_name, "video_titulo": video_title})
            message = f"Revisão humana: {len(persisted_candidates)} candidato(s) renderizado(s); {len(suggestions)} aprovado(s) automaticamente pela IA."
            result = {"analysis": analysis, "cortes": persisted_candidates}
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="needs_review", progress=100, message=message, video_id=video_id, suggestions=persisted_candidates, diagnostics=analysis)
            update_job(job_id, status="needs_review", progress=100, message=message, result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
            return
        validar_ferramentas()
        persisted = []
        cycle_name = _cut_cycle_name(video_title, job_id)
        for suggestion in suggestions:
            _raise_if_cancelled(job_id)
            cut_id = create_cut(job_id, video_id, source_path, suggestion, perfil_id=perfil_id, video_title=video_title, round_name=cycle_name)
            output_name = f"{video_id}_{cut_id}_{normalizar_titulo_corte(suggestion.get('titulo')) or 'corte'}.mp4"
            output_path = os.path.join(obter_pastas_midia(perfil_id)["shorts"], output_name)
            try:
                update_cut(cut_id, status="renderizando", perfil_id=perfil_id)
                renderizar_corte(source_path, output_path, suggestion["inicio"], suggestion["fim"], intervalos=suggestion.get("montagem_intervalos"), vertical=True)
                recommendation_context = "\n".join(filter(None, [
                    f"Título original: {video_title}", f"Título do corte: {suggestion.get('titulo', '')}",
                    f"Gancho: {suggestion.get('gancho', '')}", f"Promessa: {suggestion.get('promessa', '')}",
                    f"Virada: {suggestion.get('virada', '')}", f"Conclusão: {suggestion.get('conclusao', '')}",
                ]))
                try:
                    update_cut_schedule_recommendation(cut_id, recomendar_horario_corte(recommendation_context), perfil_id=perfil_id)
                except Exception:
                    update_cut_schedule_recommendation(cut_id, {"periodo": "noite", "dias_preferidos": [], "confianca": 0, "justificativa": "Recomendação indisponível; usando o histórico do canal."}, perfil_id=perfil_id)
                update_cut(cut_id, status="concluido", output_path=output_path, perfil_id=perfil_id)
                persisted.append({**suggestion, "cut_id": cut_id, "output_path": output_path, "status": "concluido"})
            except Exception as error:
                update_cut(cut_id, status="falhou", error=str(error), perfil_id=perfil_id)
                persisted.append({**suggestion, "cut_id": cut_id, "status": "falhou", "error": str(error)})
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, **{
            "status": "completed",
            "progress": 100,
            "message": "Cortes analisados e validados",
            "video_id": video_id,
            "suggestions": persisted,
        })
    except JobCancelled as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
    except Exception as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))

def _run_selected_cuts_job(job_id, cut_ids, perfil_id):
    try:
        _raise_if_cancelled(job_id)
        cuts = [cut for cut in list_cuts(perfil_id=perfil_id) if cut["id"] in cut_ids and cut.get("selecionado")]
        if not cuts:
            raise RuntimeError("Nenhum candidato foi selecionado para renderização.")
        validar_ferramentas()
        output_dir = obter_pastas_midia(perfil_id)["shorts"]
        results = []
        for index, cut in enumerate(cuts, start=1):
            _raise_if_cancelled(job_id)
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=round((index - 1) / len(cuts) * 100), message=f"Renderizando corte {index}/{len(cuts)}")
            output_name = f"{cut['video_id']}_{cut['id']}_{normalizar_titulo_corte(cut.get('titulo')) or 'corte'}.mp4"
            output_path = os.path.join(output_dir, output_name)
            try:
                update_cut(cut["id"], status="renderizando", perfil_id=perfil_id)
                renderizar_corte(cut["arquivo_origem"], output_path, cut["inicio_segundos"], cut["fim_segundos"], intervalos=cut.get("montagem_intervalos"), vertical=True)
                update_cut(cut["id"], status="concluido", output_path=output_path, perfil_id=perfil_id)
                results.append({**cut, "status": "concluido", "output_path": output_path})
            except Exception as error:
                update_cut(cut["id"], status="falhou", error=str(error), perfil_id=perfil_id)
                results.append({**cut, "status": "falhou", "error": str(error)})
        result = {"cortes": results}
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="completed", progress=100, message="Candidatos selecionados renderizados", suggestions=results)
        update_job(job_id, status="completed", progress=100, message="Candidatos selecionados renderizados", result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
    except JobCancelled as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
    except Exception as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))


def _run_publish_job(job_id, cut_ids, perfil_id, requested_slots=None):
    try:
        cuts = [cut for cut in list_cuts(perfil_id=perfil_id) if cut["id"] in cut_ids]
        slots = requested_slots or planejar_melhores_slots(len(cuts), perfil_id=perfil_id, cuts=cuts)
        if len(slots) != len(cuts):
            raise RuntimeError("Não foi possível encontrar slots futuros para todos os cortes.")
        results = []
        for index, cut in enumerate(cuts):
            _raise_if_cancelled(job_id)
            slot = slots[index]
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=round(index / len(cuts) * 100), message=f"Enviando corte {index + 1}/{len(cuts)} para o YouTube")
            published = publicar_e_agendar_corte(cut, slot["date"], slot["time"], perfil_id=perfil_id)
            conn = get_connection()
            try:
                conn.execute("""
                    INSERT INTO videos_historico
                    (video_id, titulo, descricao, tipo, status, data_publicacao, slot_hora, arquivo_origem, perfil_id, atualizado_em)
                    VALUES (?, ?, ?, 'short', 'programado', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(video_id) DO UPDATE SET
                        titulo=excluded.titulo, descricao=excluded.descricao, status='programado',
                        data_publicacao=excluded.data_publicacao, slot_hora=excluded.slot_hora,
                        arquivo_origem=excluded.arquivo_origem, perfil_id=excluded.perfil_id,
                        atualizado_em=CURRENT_TIMESTAMP
                """, (published["youtube_id"], published["titulo"], published["descricao"], published["date"], published["time"], cut["caminho_saida"], perfil_id))
                conn.commit()
            finally:
                conn.close()
            results.append({"cut_id": cut["id"], **published})
        result = {"scheduled": results}
        message = f"{len(results)} corte(s) enviado(s) e agendado(s) no YouTube"
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="completed", progress=100, message=message, suggestions=results)
        update_job(job_id, status="completed", progress=100, message=message, result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
    except JobCancelled as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
        update_job(job_id, status="cancelled", message=str(error), perfil_id=perfil_id)
    except Exception as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)


def _run_sync_job(channel_url, perfil_id):
    started_at = time.monotonic()
    status = _profile_status(SYNC_STATUS, perfil_id, SYNC_STATUS_DEFAULT)
    status.update({
        "status": "running",
        "message": "Preparando sincronização",
        "processed": 0,
        "total": 0,
        "progress": 0,
        "eta_seconds": None,
    })

    def update_progress(processed, total, message):
        elapsed = time.monotonic() - started_at
        is_discovery = message.startswith("Buscando ")
        rate = processed / elapsed if processed and elapsed and not is_discovery else 0
        remaining = max(total - processed, 0)
        status.update({
            "message": message,
            "processed": processed,
            "total": total,
            "progress": round((processed / total) * 100, 1) if total else 0,
            "eta_seconds": round(remaining / rate) if rate else None,
        })

    try:
        sincronizar_canal_youtube(channel_url, perfil_id=perfil_id, progress_callback=update_progress)
        status.update({
            "status": "completed",
            "processed": status["total"],
            "progress": 100,
            "eta_seconds": 0,
            "message": "Sincronização concluída",
        })
    except Exception as error:
        status.update({"status": "failed", "message": str(error)})


def _run_content_analysis(perfil_id):
    started_at = time.monotonic()
    status = _profile_status(CONTENT_STATUS, perfil_id, CONTENT_STATUS_DEFAULT)
    atualizar_tarefa("content_analysis", status="running", processados=0, total=0, progresso=0, mensagem="Preparando análise de conteúdo", iniciado=True, perfil_id=perfil_id)
    status.update({"status": "running", "processed": 0, "total": 0, "progress": 0, "eta_seconds": None, "message": "Preparando análise de conteúdo"})

    def update_progress(processed, total, message):
        elapsed = time.monotonic() - started_at
        rate = processed / elapsed if processed and elapsed else 0
        eta_seconds = round(max(total - processed, 0) / rate) if rate else None
        status.update({
            "processed": processed,
            "total": total,
            "progress": round((processed / total) * 100, 1) if total else 100,
            "eta_seconds": eta_seconds,
            "message": message,
        })
        atualizar_tarefa("content_analysis", status="running", processados=processed, total=total, progresso=status["progress"], mensagem=message, perfil_id=perfil_id)

    try:
        result = analisar_videos_longos(progress_callback=update_progress, perfil_id=perfil_id)
        status.update({"status": "completed", "processed": result["processados"], "progress": 100, "eta_seconds": 0, "message": "Análise de conteúdo concluída"})
        atualizar_tarefa("content_analysis", status="completed", processados=result["processados"], progresso=100, mensagem="Análise de conteúdo concluída", concluido=True, perfil_id=perfil_id)
    except Exception as error:
        status.update({"status": "failed", "message": str(error)})
        atualizar_tarefa("content_analysis", status="failed", mensagem=str(error), erro=str(error), concluido=True, perfil_id=perfil_id)


def _run_profile_rebuild(perfil_id):
    started_at = time.monotonic()
    status = _profile_status(PROFILE_STATUS, perfil_id, PROFILE_STATUS_DEFAULT)
    status.update({"status": "running", "processed": 0, "total": 3, "progress": 0, "eta_seconds": None, "message": "Preparando perfil semântico"})

    def update_progress(processed, total, message):
        elapsed = time.monotonic() - started_at
        rate = processed / elapsed if processed and elapsed else 0
        status.update({
            "processed": processed,
            "total": total,
            "progress": round((processed / total) * 100, 1),
            "eta_seconds": round(max(total - processed, 0) / rate) if rate else None,
            "message": message,
        })

    try:
        consolidar_perfil_canal(progress_callback=update_progress, perfil_id=perfil_id)
        status.update({"status": "completed", "processed": 3, "progress": 100, "eta_seconds": 0, "message": "Perfil semântico concluído"})
        criar_notificacao("Perfil semântico concluído", "O perfil da conta foi atualizado e já pode alimentar o Radar.", perfil_id=perfil_id)
    except Exception as error:
        status.update({"status": "failed", "message": str(error)})
        criar_notificacao("Falha no perfil semântico", str(error), tipo="erro", perfil_id=perfil_id)


def _run_opportunity_generation(perfil_id):
    status = _profile_status(OPPORTUNITY_STATUS, perfil_id, OPPORTUNITY_STATUS_DEFAULT)
    status.update({"status": "running", "message": "Qwen analisando padrões dos Top 15"})
    try:
        created = gerar_sugestoes_top15(perfil_id=perfil_id)
        status.update({"status": "completed", "message": f"{len(created)} sugestões geradas"})
        criar_notificacao("Sugestões geradas", f"{len(created)} sugestões baseadas na Autópsia dos Top 15.", perfil_id=perfil_id)
    except Exception as error:
        status.update({"status": "failed", "message": str(error)})
        criar_notificacao("Falha ao gerar sugestões", str(error), tipo="erro", perfil_id=perfil_id)


class GrowthEngineHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://unpkg.com; style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com; img-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'",
        )
        super().end_headers()

    def _send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        now = time.time()
        for state, data in list(OAUTH_STATES.items()):
            if now - data.get("created", now) > OAUTH_STATE_TTL:
                OAUTH_STATES.pop(state, None)
        if len(OAUTH_STATES) > 100:
            oldest = sorted(OAUTH_STATES.items(), key=lambda item: item[1].get("created", 0))[:len(OAUTH_STATES) - 100]
            for state, _ in oldest:
                OAUTH_STATES.pop(state, None)
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and parsed.path not in PUBLIC_PROFILE_PATHS:
            try:
                self.request_profile_id = _request_profile_id(self)
            except ValueError as error:
                self._send_json({"error": str(error)}, status=400)
                return
        if parsed.path == "/api/profiles/active":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            perfil_id = normalize_profile_id(payload.get("perfil_id"))
            conn = get_connection()
            try:
                row = conn.execute("SELECT id, nome, tipo, canal_url, canal_id, ativo FROM perfis WHERE id=? AND ativo=1", (perfil_id,)).fetchone()
            finally:
                conn.close()
            if not row:
                self._send_json({"error": "Perfil inválido."}, status=400)
            else:
                self._send_json(dict(row))
            return
        if parsed.path == "/api/profiles":
            init_db()
            conn = get_connection()
            try:
                rows = conn.execute("""
                    SELECT p.id, p.nome, p.tipo, p.canal_url, p.canal_id, p.ativo,
                           g.canal_nome, g.google_account_email, g.avatar_url, g.status
                    FROM perfis p LEFT JOIN perfis_google g ON g.perfil_id=p.id
                    ORDER BY p.atualizado_em DESC
                """).fetchall()
                self._send_json({"profiles": [dict(row) for row in rows]})
            finally:
                conn.close()
            return
        if parsed.path == "/api/backlog":
            try:
                with open(os.path.join(PROJECT_ROOT, "docs", "backlog", "index.json"), "r", encoding="utf-8") as manifest:
                    self._send_json(json.load(manifest))
            except (OSError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Manifesto do backlog indisponível: {error}"}, status=500)
            return
        if parsed.path == "/api/profiles/active":
            self._send_json({"perfil_id": normalize_profile_id(self.headers.get("X-Profile-Id", 1))})
            return
        if parsed.path == "/oauth/google/start":
            try:
                perfil_param = parse_qs(parsed.query).get("perfil_id", [None])[0]
                perfil_id = normalize_profile_id(perfil_param) if perfil_param else None
                perfil_nome = parse_qs(parsed.query).get("nome", [""])[0].strip()
                state, url, code_verifier = criar_url_autorizacao(include_publish=True)
                OAUTH_STATES[state] = {
                    "created": __import__("time").time(),
                    "code_verifier": code_verifier,
                    "perfil_id": perfil_id,
                    "perfil_nome": perfil_nome,
                }
                self.send_response(302)
                self.send_header("Location", url)
                self.end_headers()
            except RuntimeError as error:
                self._send_json({"error": "OAuth indisponível. Verifique a configuração local."}, status=503)
            return
        if parsed.path == "/oauth/google/callback":
            params = parse_qs(parsed.query)
            state = params.get("state", [""])[0]
            if not state or state not in OAUTH_STATES:
                self._send_json({"error": "OAuth state inválido ou expirado."}, status=400)
                return
            try:
                authorization_response = f"http://{self.headers.get('Host', '127.0.0.1:4174')}{self.path}"
                credentials = concluir_autorizacao(
                    state,
                    authorization_response,
                    OAUTH_STATES[state].get("code_verifier"),
                    include_publish=True,
                )
                youtube = build("youtube", "v3", credentials=credentials)
                account_email = ""
                try:
                    account = build("oauth2", "v2", credentials=credentials).userinfo().get().execute()
                    account_email = account.get("email", "")
                except Exception:
                    pass
                response = youtube.channels().list(part="snippet", mine=True).execute()
                canais = response.get("items", [])
                if not canais:
                    raise RuntimeError("A conta Google não possui um canal YouTube disponível.")
                canal = canais[0]
                snippet = canal.get("snippet", {})
                oauth_state = OAUTH_STATES[state]
                perfil_id = oauth_state.get("perfil_id")
                if not perfil_id:
                    perfil_id = create_profile(oauth_state.get("perfil_nome") or snippet.get("title", "Canal YouTube"))
                avatar_url = snippet.get("thumbnails", {}).get("high", {}).get("url", "")
                expires_at = credentials.expiry.isoformat() if credentials.expiry else None
                salvar_perfil_google(
                    nome=snippet.get("title", "Canal YouTube"),
                    canal_url=f"https://www.youtube.com/channel/{canal['id']}",
                    canal_id=canal["id"],
                    canal_nome=snippet.get("title", ""),
                    google_account_id="",
                    google_account_email=account_email,
                    avatar_url=avatar_url,
                    scopes=serializar_scopes(credentials.scopes),
                    access_token_ciphertext=cifrar_token(credentials.token),
                    refresh_token_ciphertext=cifrar_token(credentials.refresh_token or credentials.token),
                    token_expira_em=expires_at,
                    perfil_id=perfil_id,
                )
                del OAUTH_STATES[state]
                self.send_response(302)
                self.send_header("Location", "/?oauth=success")
                self.end_headers()
            except Exception as error:
                print(f"Falha OAuth ({type(error).__name__}): {error}")
                trace = traceback.format_exc()
                traceback.print_exc()
                registrar_log(f"Falha OAuth ({type(error).__name__}): {error}\n{trace}")
                self._send_json({"error": "Falha ao conectar o YouTube. Consulte o log local."}, status=502)
            return
        if parsed.path == "/api/jobs/active":
            jobs = list_active_jobs(self.request_profile_id)
            for job in jobs:
                runtime_job = TRANSCRIPTION_JOBS.get(job["job_id"]) or CUT_JOBS.get(job["job_id"])
                if runtime_job and runtime_job.get("perfil_id") == self.request_profile_id:
                    job.update(runtime_job)
                    job["job_id"] = runtime_job.get("id", job["job_id"])
            self._send_json({"jobs": jobs})
            return
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.rsplit("/", 1)[-1]
            job = TRANSCRIPTION_JOBS.get(job_id) or CUT_JOBS.get(job_id)
            job = job or select_job(job_id, self.request_profile_id)
            if not job:
                self._send_json({"error": "Tarefa não encontrada"}, status=404)
            else:
                self._send_json(job)
            return
        if parsed.path == "/api/dashboard":
            self._send_json(_dashboard_payload(self.request_profile_id))
            return
        if parsed.path == "/api/ranking":
            params = parse_qs(parsed.query)
            tipo = params.get("tipo", [None])[0]
            try:
                limit = min(max(int(params.get("limit", [15])[0]), 1), 100)
            except ValueError:
                limit = 15
            self._send_json({"videos": _fetch_videos(tipo=tipo, limit=limit, perfil_id=self.request_profile_id)})
            return
        if parsed.path == "/api/cut-sources":
            self._send_json({"videos": _fetch_cut_sources(self.request_profile_id)})
            return
        if parsed.path == "/api/cuts":
            video_id = parse_qs(parsed.query).get("video_id", [None])[0]
            self._send_json({"cortes": [_present_cut_score(cut) for cut in list_cuts(video_id=video_id, perfil_id=self.request_profile_id)]})
            return
        if parsed.path == "/api/cuts/source-thumbnail":
            video_id = parse_qs(parsed.query).get("video_id", [""])[0]
            thumbnail_path = _source_thumbnail_path(video_id, self.request_profile_id)
            if not thumbnail_path:
                self.send_error(404, "Miniatura não disponível")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(os.path.getsize(thumbnail_path)))
            self.end_headers()
            with open(thumbnail_path, "rb") as thumbnail:
                self.wfile.write(thumbnail.read())
            return
        if parsed.path == "/api/cuts/file":
            cut_id = parse_qs(parsed.query).get("id", [""])[0]
            try:
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if str(item["id"]) == cut_id), None)
                output_path = cut.get("caminho_saida") if cut else None
                if not cut or cut.get("status") != "concluido" or not output_path or not os.path.isfile(output_path):
                    self.send_error(404, "Corte não disponível")
                    return
                file_size = os.path.getsize(output_path)
                range_header = self.headers.get("Range", "")
                start, end = 0, file_size - 1
                if range_header.startswith("bytes="):
                    requested = range_header[6:].split(",", 1)[0].strip()
                    first, _, last = requested.partition("-")
                    if first:
                        start = int(first)
                        end = int(last) if last else end
                    elif last:
                        start = max(file_size - int(last), 0)
                    if start >= file_size or start > end:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{file_size}")
                        self.end_headers()
                        return
                    end = min(end, file_size - 1)
                content_length = end - start + 1
                self.send_response(206 if range_header.startswith("bytes=") else 200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(content_length))
                if range_header.startswith("bytes="):
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Disposition", f"inline; filename={os.path.basename(output_path)}")
                self.end_headers()
                with open(output_path, "rb") as media:
                    media.seek(start)
                    remaining = content_length
                    while remaining:
                        chunk = media.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (OSError, ValueError):
                self.send_error(404, "Arquivo do corte indisponível")
            return
        if parsed.path == "/api/transcription":
            video_id = parse_qs(parsed.query).get("video_id", [""])[0]
            transcription = _fetch_transcription(video_id, self.request_profile_id)
            if transcription is None:
                self._send_json({"error": "Vídeo não encontrado"}, status=404)
            else:
                self._send_json(transcription)
            return
        if parsed.path == "/api/publishing/scheduled":
            self._send_json({"videos": _fetch_scheduled(self.request_profile_id)})
            return
        if parsed.path == "/api/profiles/google/status":
            init_db()
            conn = get_connection()
            try:
                rows = conn.execute("SELECT id, perfil_id, nome, canal_id, canal_nome, google_account_email, avatar_url, fuso_horario, status FROM perfis_google WHERE perfil_id=? ORDER BY atualizado_em DESC", (self.request_profile_id,)).fetchall()
                self._send_json({"profiles": [dict(row) for row in rows]})
            finally:
                conn.close()
            return
        if parsed.path == "/api/profiles/google/avatar":
            init_db()
            conn = get_connection()
            try:
                avatar_url = conn.execute(
                    "SELECT avatar_url FROM perfis_google WHERE perfil_id=? AND status='conectado' ORDER BY atualizado_em DESC LIMIT 1",
                    (self.request_profile_id,),
                ).fetchone()[0]
            finally:
                conn.close()
            if not avatar_url:
                self.send_error(404, "Avatar não disponível")
                return
            try:
                request = urllib.request.Request(avatar_url, headers={"User-Agent": "GrowthEngine/1.0"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    data = response.read()
                    content_type = response.headers.get_content_type()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception:
                self.send_error(502, "Não foi possível carregar o avatar")
            return
        if parsed.path == "/api/sync/status":
            self._send_json(_profile_status(SYNC_STATUS, self.request_profile_id, SYNC_STATUS_DEFAULT))
            return
        if parsed.path == "/api/content-analysis/status":
            status = _profile_status(CONTENT_STATUS, self.request_profile_id, CONTENT_STATUS_DEFAULT)
            self._send_json({**status, "persisted": obter_tarefa("content_analysis", self.request_profile_id), "cache": obter_status_analises(self.request_profile_id)})
            return
        if parsed.path == "/api/radar/location":
            self._send_json(obter_localizacao())
            return
        if parsed.path == "/api/radar":
            try:
                force = parse_qs(parsed.query).get("force", ["0"])[0] == "1"
                self._send_json(buscar_radar(force=force))
            except Exception as error:
                self._send_json({"error": str(error)}, status=502)
            return
        if parsed.path == "/api/opportunities":
            self._send_json({"oportunidades": listar_oportunidades(perfil_id=self.request_profile_id)})
            return
        if parsed.path == "/api/opportunities/status":
            self._send_json(_profile_status(OPPORTUNITY_STATUS, self.request_profile_id, OPPORTUNITY_STATUS_DEFAULT))
            return
        if parsed.path == "/api/content-profile":
            self._send_json({"profile": obter_perfil_canal(self.request_profile_id), "task": _profile_status(PROFILE_STATUS, self.request_profile_id, PROFILE_STATUS_DEFAULT)})
            return
        if parsed.path == "/api/content-profile/status":
            self._send_json(_profile_status(PROFILE_STATUS, self.request_profile_id, PROFILE_STATUS_DEFAULT))
            return
        if parsed.path == "/api/notifications":
            self._send_json(listar_notificacoes(perfil_id=self.request_profile_id))
            return
        if parsed.path.startswith("/api/opportunities/") and parsed.path.endswith("/briefing"):
            try:
                opportunity_id = int(parsed.path.split("/")[3])
                self._send_json(gerar_briefing(opportunity_id))
            except (ValueError, TypeError) as error:
                self._send_json({"error": str(error)}, status=404)
            return
        super().do_GET()

    def do_POST(self):
        origin = self.headers.get("Origin")
        allowed_origins = {"http://127.0.0.1:4174", "http://localhost:4174"}
        if origin and origin not in allowed_origins:
            self._send_json({"error": "Origem não autorizada."}, status=403)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/profiles/create":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                nome = str(payload.get("nome", "")).strip()
                if not nome:
                    raise ValueError("Nome do perfil é obrigatório.")
                perfil_id = create_profile(nome)
                self._send_json({"id": perfil_id, "nome": nome}, status=201)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/profiles/active":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                perfil_id = normalize_profile_id(payload.get("perfil_id"))
                conn = get_connection()
                try:
                    row = conn.execute("SELECT id, nome, tipo, canal_url, canal_id, ativo FROM perfis WHERE id=? AND ativo=1", (perfil_id,)).fetchone()
                finally:
                    conn.close()
                if not row:
                    self._send_json({"error": "Perfil inválido."}, status=400)
                else:
                    self._send_json(dict(row))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path.startswith("/api/") and parsed.path not in PUBLIC_PROFILE_PATHS:
            try:
                self.request_profile_id = _request_profile_id(self)
            except ValueError as error:
                self._send_json({"error": str(error)}, status=400)
                return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
            job_id = parsed.path.split("/")[-2]
            runtime_job = TRANSCRIPTION_JOBS.get(job_id) or CUT_JOBS.get(job_id)
            job = runtime_job if runtime_job and runtime_job.get("perfil_id") == self.request_profile_id else select_job(job_id, self.request_profile_id)
            if not job:
                self._send_json({"error": "Tarefa não encontrada"}, status=404)
                return
            if job.get("status") in {"completed", "failed", "cancelled", "interrupted", "rejected", "needs_review", "cancelling"}:
                self._send_json({"error": "Esta tarefa já terminou.", "status": job.get("status")}, status=409)
                return
            _cancel_event(job_id).set()
            store = TRANSCRIPTION_JOBS if job_id in TRANSCRIPTION_JOBS else CUT_JOBS
            if job_id in store:
                store[job_id].update({"status": "cancelling", "message": "Cancelamento em andamento; aguardando a tarefa liberar o vídeo."})
            update_job(job_id, status="cancelling", message="Cancelamento em andamento; aguardando a tarefa liberar o vídeo.", perfil_id=self.request_profile_id)
            self._send_json({"job_id": job_id, "status": "cancelling", "message": "Cancelamento em andamento; aguarde a liberação do vídeo."}, status=202)
            return
        if parsed.path == "/api/profiles/remove":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                perfil_id = normalize_profile_id(payload.get("perfil_id"))
                delete_profile(perfil_id)
                self._send_json({"status": "removed", "perfil_id": perfil_id})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/uploads/local":
            try:
                content_type = self.headers.get("Content-Type", "")
                if not content_type.lower().startswith("multipart/form-data"):
                    raise ValueError("Use multipart/form-data com o campo file.")
                length = int(self.headers.get("Content-Length", "0"))
                source_path = _receive_mp4_upload(self, content_type, length, obter_pastas_midia(self.request_profile_id)["uploads"])
                duracao_minima, duracao_maxima = _cut_duration_range(self.headers.get("X-Cut-Min-Seconds"), self.headers.get("X-Cut-Max-Seconds"))
                job_id = uuid.uuid4().hex
                create_job(job_id, "upload_local", job_id, perfil_id=self.request_profile_id)
                _cancel_event(job_id)
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Upload recebido", "video_id": job_id, "perfil_id": self.request_profile_id, "source_path": source_path}
                if not TASK_RUNNER.submit("upload_local", _process_local_media_job, job_id, source_path, self.request_profile_id, duracao_minima, duracao_maxima, key=f"perfil:{self.request_profile_id}:upload:{job_id}"):
                    update_job(job_id, status="rejected", message="Fila de mídia indisponível", error="lock", perfil_id=self.request_profile_id)
                    self._send_json({"error": "Fila de mídia indisponível", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            except (ValueError, OSError) as error:
                self._send_json({"error": str(error)}, status=413 if "limite" in str(error) else 400)
            return
        if parsed.path == "/api/downloads/force":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                url = str(payload.get("url", "")).strip()
                duracao_minima, duracao_maxima = _cut_duration_range(payload.get("duracao_minima"), payload.get("duracao_maxima"))
                if not _youtube_video_url(url):
                    self._send_json({"error": "Informe uma URL válida do YouTube."}, status=400)
                    return
                job_id = uuid.uuid4().hex
                create_job(job_id, "force_download", job_id, perfil_id=self.request_profile_id)
                _cancel_event(job_id)
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Download forçado na fila", "video_id": job_id, "url": url}
                if not TASK_RUNNER.submit("force_download", _force_download_job, job_id, url, self.request_profile_id, duracao_minima, duracao_maxima, key=f"media:{self.request_profile_id}:{job_id}"):
                    self._send_json({"error": "Fila de mídia indisponível", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/notifications/read":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            marcar_notificacao_lida(payload.get("id"), perfil_id=self.request_profile_id)
            self._send_json(listar_notificacoes(perfil_id=self.request_profile_id))
            return
        if parsed.path == "/api/notifications/clear-read":
            limpar_notificacoes_lidas(perfil_id=self.request_profile_id)
            self._send_json(listar_notificacoes(perfil_id=self.request_profile_id))
            return
        if parsed.path == "/api/radar/location":
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            salvar_localizacao(body.get("bairro", ""), body.get("cidade", ""), body.get("estado", ""))
            self._send_json(obter_localizacao())
            return
        if parsed.path == "/api/opportunities":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self._send_json(criar_oportunidade(payload), status=201)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/opportunities/generate":
            status = _profile_status(OPPORTUNITY_STATUS, self.request_profile_id, OPPORTUNITY_STATUS_DEFAULT)
            if status["status"] == "running":
                self._send_json(status, status=202)
                return
            if not TASK_RUNNER.submit("opportunities", _run_opportunity_generation, self.request_profile_id, key=f"opportunities:{self.request_profile_id}"):
                self._send_json(status, status=202)
                return
            self._send_json({"status": "running", "message": "Geração de sugestões iniciada"}, status=202)
            return
        if parsed.path == "/api/content-profile/rebuild":
            status = _profile_status(PROFILE_STATUS, self.request_profile_id, PROFILE_STATUS_DEFAULT)
            if status["status"] == "running":
                self._send_json(status, status=202)
                return
            if not TASK_RUNNER.submit("profile", _run_profile_rebuild, self.request_profile_id, key=f"profile:{self.request_profile_id}"):
                self._send_json(status, status=202)
                return
            self._send_json({"status": "running", "message": "Consolidação do perfil iniciada"}, status=202)
            return
        if parsed.path == "/api/content-analysis/start":
            status = _profile_status(CONTENT_STATUS, self.request_profile_id, CONTENT_STATUS_DEFAULT)
            if status["status"] == "running":
                self._send_json(status, status=202)
                return
            if not TASK_RUNNER.submit("content_analysis", _run_content_analysis, self.request_profile_id, key=f"content_analysis:{self.request_profile_id}"):
                self._send_json(status, status=202)
                return
            self._send_json({"status": "running", "message": "Análise de conteúdo iniciada"}, status=202)
            return
        if parsed.path == "/api/sync":
            init_db()
            conn = get_connection()
            try:
                profile = conn.execute(
                    "SELECT canal_url FROM perfis_google WHERE perfil_id=? AND status = 'conectado' ORDER BY atualizado_em DESC LIMIT 1",
                    (self.request_profile_id,),
                ).fetchone()
            finally:
                conn.close()
            if not profile:
                self._send_json({"error": "Conecte um canal Google antes de sincronizar."}, status=400)
                return
            status = _profile_status(SYNC_STATUS, self.request_profile_id, SYNC_STATUS_DEFAULT)
            if status["status"] == "running":
                self._send_json(status, status=202)
                return
            if not TASK_RUNNER.submit("sync", _run_sync_job, profile["canal_url"], self.request_profile_id, key=f"sync:{self.request_profile_id}"):
                self._send_json(status, status=202)
                return
            self._send_json({"status": "running", "message": "Sincronização iniciada"}, status=202)
            return
        if parsed.path == "/api/transcription/run":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                video_id = body.get("video_id")
                if not video_id or not isinstance(video_id, str):
                    self._send_json({"error": "video_id é obrigatório"}, status=400)
                    return
                job_id = uuid.uuid4().hex
                TRANSCRIPTION_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Na fila", "video_id": video_id}
                _cancel_event(job_id)
                create_job(job_id, "transcription", video_id, perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit(
                    "transcription",
                    _run_transcription_job,
                    job_id,
                    video_id,
                    self.request_profile_id,
                    key=f"video:{self.request_profile_id}:{video_id}",
                ):
                    TRANSCRIPTION_JOBS[job_id].update({"status": "rejected", "message": "Este vídeo já possui uma tarefa pesada em execução."})
                    self._send_json({"error": TRANSCRIPTION_JOBS[job_id]["message"], "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Solicitação inválida: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/select":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cut_ids = {int(cut_id) for cut_id in body.get("cut_ids", [])}
                available = {cut["id"] for cut in list_cuts(perfil_id=self.request_profile_id)}
                selected = sorted(cut_ids & available)
                for cut_id in selected:
                    update_cut(cut_id, status="selecionado", selected=1, perfil_id=self.request_profile_id)
                self._send_json({"selected": selected})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Seleção inválida: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/delete":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cut_id = int(body.get("cut_id"))
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut:
                    self._send_json({"error": "Corte não encontrado."}, status=404)
                    return
                output_path = cut.get("caminho_saida")
                if output_path and os.path.isfile(output_path):
                    os.remove(output_path)
                update_cut(cut_id, status="excluido", selected=0, perfil_id=self.request_profile_id)
                self._send_json({"deleted": cut_id})
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Exclusão inválida: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/delete-cycle":
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                video_id = str(payload.get("video_id") or "")
                round_name = str(payload.get("nome_rodada") or "")
                cycle_cuts = [cut for cut in list_cuts(video_id=video_id, perfil_id=self.request_profile_id) if cut.get("nome_rodada") == round_name]
                if not video_id or not round_name or not cycle_cuts:
                    raise ValueError("Ciclo de cortes não encontrado.")
                for cut in cycle_cuts:
                    output_path = cut.get("caminho_saida")
                    if output_path and os.path.isfile(output_path):
                        try:
                            os.remove(output_path)
                        except OSError:
                            pass
                    update_cut(cut["id"], status="excluido", selected=0, perfil_id=self.request_profile_id)
                self._send_json({"deleted": len(cycle_cuts)})
            except (ValueError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/cuts/schedule":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cut_id = int(body.get("cut_id"))
                date = str(body.get("date") or "").strip()
                slot = str(body.get("time") or "").strip()
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut or cut.get("status") != "concluido" or not cut.get("caminho_saida"):
                    self._send_json({"error": "O corte precisa estar renderizado antes do agendamento."}, status=400)
                    return
                requested_slots = [{"date": date, "time": slot}] if date and slot else None
                job_id = uuid.uuid4().hex
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Publicação na fila"}
                _cancel_event(job_id)
                create_job(job_id, "cut_publish", cut["video_id"], perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit("cut_publish", _run_publish_job, job_id, [cut_id], self.request_profile_id, requested_slots, key=f"cut-publish:{self.request_profile_id}:{cut_id}"):
                    self._send_json({"error": "Este corte já possui uma publicação em execução.", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Agendamento inválido: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/schedule-bulk":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cut_ids = sorted({int(cut_id) for cut_id in body.get("cut_ids", [])})
                date = str(body.get("date") or "").strip()
                slot = str(body.get("time") or "").strip()
                if not cut_ids:
                    self._send_json({"error": "Selecione ao menos um corte."}, status=400)
                    return
                cuts = [cut for cut in list_cuts(perfil_id=self.request_profile_id) if cut["id"] in cut_ids]
                unavailable = [cut["id"] for cut in cuts if cut.get("status") != "concluido" or not cut.get("caminho_saida")]
                if len(cuts) != len(cut_ids) or unavailable:
                    self._send_json({"error": "Todos os cortes precisam estar renderizados antes do agendamento.", "unavailable": unavailable}, status=400)
                    return
                requested_slots = ([{"date": date, "time": slot}] * len(cuts)) if date and slot else None
                job_id = uuid.uuid4().hex
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Publicação em massa na fila"}
                _cancel_event(job_id)
                create_job(job_id, "cut_publish", cuts[0]["video_id"], perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit("cut_publish", _run_publish_job, job_id, cut_ids, self.request_profile_id, requested_slots, key=f"bulk-publish:{self.request_profile_id}"):
                    self._send_json({"error": "Já existe uma publicação em massa em execução.", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Agendamento em massa inválido: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/render-selected":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cut_ids = sorted({int(cut_id) for cut_id in body.get("cut_ids", [])})
                selected = [cut for cut in list_cuts(perfil_id=self.request_profile_id) if cut["id"] in cut_ids]
                if not selected:
                    self._send_json({"error": "Nenhum candidato selecionado."}, status=400)
                    return
                if len({cut["video_id"] for cut in selected}) != 1:
                    self._send_json({"error": "Selecione candidatos de um único vídeo por vez."}, status=400)
                    return
                job_id = uuid.uuid4().hex
                video_id = selected[0]["video_id"]
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Renderização na fila", "video_id": video_id}
                _cancel_event(job_id)
                create_job(job_id, "cut_render", video_id, perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit("cut_render", _run_selected_cuts_job, job_id, cut_ids, self.request_profile_id, key=f"video-render:{self.request_profile_id}:{video_id}"):
                    self._send_json({"error": "Este vídeo já possui uma renderização em execução.", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Renderização inválida: {error}"}, status=400)
            return
        if parsed.path != "/api/cuts/suggest":
            self._send_json({"error": "Rota não encontrada"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            video_id = body.get("video_id")
            duracao_minima, duracao_maxima = _cut_duration_range(body.get("duracao_minima"), body.get("duracao_maxima"))
            job_id = uuid.uuid4().hex
            CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Na fila", "video_id": video_id}
            _cancel_event(job_id)
            if video_id:
                create_job(job_id, "cut", video_id, perfil_id=self.request_profile_id)
            if not video_id or not TASK_RUNNER.submit(
                "cut",
                _run_cut_job,
                job_id,
                video_id,
                self.request_profile_id,
                duracao_minima,
                duracao_maxima,
                key=f"video:{self.request_profile_id}:{video_id}",
            ):
                message = "video_id é obrigatório." if not video_id else "Este vídeo já possui uma tarefa pesada em execução."
                CUT_JOBS[job_id].update({"status": "rejected", "message": message})
                update_job(job_id, status="rejected", message=message, perfil_id=self.request_profile_id)
                self._send_json({"error": message, "job_id": job_id}, status=400 if not video_id else 409)
                return
            self._send_json({"job_id": job_id, "status": "queued"}, status=202)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self._send_json({"error": f"Solicitação inválida: {error}"}, status=400)


def start_server(host="127.0.0.1", port=4174):
    server = ThreadingHTTPServer((host, port), GrowthEngineHandler)
    print(f"Growth Engine web central: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    start_server()
