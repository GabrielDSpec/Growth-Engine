from core.transcriber import TranscriptionCancelled, _parse_srt, transcrever_arquivo_local_segmentos, transcrever_video_youtube
import json
import filecmp
import glob
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import urllib.request
import tempfile
import yt_dlp
import traceback
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from core.database import get_connection, init_db, salvar_perfil_google
from core.cutter import GenerationCancelled, OLLAMA_CUTS_ENABLED, OLLAMA_MAX_SECONDS, _calcular_timeout_ollama, corrigir_transcricao_com_contexto, gerar_cortes_com_retry, garimpar_vacas_roxas, calcular_score_observavel, _gerar_resposta_ollama, _gerar_resposta_ollama_http, _gerar_indice_editorial_estrutural
from core.cutter import normalizar_titulo_corte, refinar_titulo_corte, _descricao_editorial_local, _titulo_editorial_local, _titulo_generico
from core.captions import CAPTION_FONTS, CAPTION_POSITIONS, CAPTION_STROKE_COLORS, CAPTION_STROKE_WIDTHS, CAPTION_STYLES
from core.caption_styles import get_caption_style, import_caption_style, list_caption_styles, validate_style_config
from core.caption_fonts import caption_fonts_dir, list_caption_fonts, store_caption_font
from core.config import MAX_UPLOAD_BYTES, PASTA_LONGOS, PASTA_SHORTS, UPLOAD_CHUNK_BYTES, obter_pastas_midia
from core.cuts_repository import create_cut, delete_cuts_for_job, list_cut_caption_transcript, list_cuts, prune_unavailable_cuts, repair_unavailable_completed_cuts, replace_cut_cycle_metadata, save_cut_caption_transcript, update_cut, update_cut_caption, update_cut_metadata, update_cut_related_video, update_cut_schedule_recommendation
from core.editorial_mapper import dossier_path, load_dossier, load_or_build_dossier, build_dossier, harvest_candidates
from core.media_tools import MediaToolError, validar_ferramentas, renderizar_corte, localizar_ferramentas, nome_seguro_arquivo, obter_duracao
from core.vision_tools import annotate_transcript_segments, format_annotated_segments_for_prompt, scan_media_triggers
from core.sync_channel import sincronizar_canal_youtube
from core.content_intelligence import analisar_video_individual, analisar_videos_longos, obter_status_analises
from core.radar import buscar_radar, obter_localizacao, salvar_localizacao
from core.opportunities import criar_oportunidade, gerar_briefing, listar_oportunidades, gerar_sugestoes_top15
from core.tasks import atualizar_tarefa, obter_tarefa
from core.task_runner import TaskRunner
from core.job_repository import create_job, list_active_jobs, list_resumable_jobs, recover_running_jobs, select_job, update_job
from core.content_profile import consolidar_perfil_canal, obter_perfil_canal
from core.notifications import criar_notificacao, listar_notificacoes, marcar_notificacao_lida, marcar_todas_notificacoes_lidas, limpar_notificacoes_lidas
from core.transcriber import transcrever_video_youtube, transcrever_arquivo_local_segmentos
from core.tenant import normalize_profile_id
from core.profiles_repository import create_profile, delete_profile
from core.utils import registrar_log
from core.utils import calcular_hash_arquivo
from core.google_oauth import criar_url_autorizacao, concluir_autorizacao, serializar_scopes, cifrar_token
from core.publisher import _metadata_for_cut, _transcript_for_cut, _youtube_client, arquivo_publicacao_corte, planejar_melhores_slots, publicar_corte_imediato, publicar_e_agendar_corte
from core.related_video_studio import aplicar_video_relacionado
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
MANUAL_ANALYSIS_STATUS = {}
OPPORTUNITY_STATUS = {}
CONTENT_SUMMARIES = {}
OPPORTUNITY_STATUS_DEFAULT = {"status": "idle", "message": "Nenhuma sugestão gerada"}
PROFILE_STATUS = {}
PROFILE_STATUS_DEFAULT = {"status": "idle", "processed": 0, "total": 0, "progress": 0, "eta_seconds": None, "message": "Nenhum perfil gerado"}
TASK_RUNNER = TaskRunner(max_workers=1)


class JobCancelled(RuntimeError):
    pass


def _cancel_event(job_id):
    return CANCEL_EVENTS.setdefault(job_id, threading.Event())


def _raise_if_cancelled(job_id):
    if _cancel_event(job_id).is_set():
        raise JobCancelled("Processamento cancelado pelo usuário.")


def _arquivo_corte_disponivel(caminho):
    try:
        return bool(caminho) and os.path.isfile(caminho) and os.path.getsize(caminho) > 0
    except OSError:
        return False


def _cleanup_cancelled_job(job_id, perfil_id, video_id=None):
    """Remove artefatos temporários sem tocar em uploads ou mídia de outros jobs."""
    perfil_id = normalize_profile_id(perfil_id)
    media_dirs = obter_pastas_midia(perfil_id)
    job = select_job(job_id, perfil_id) or {}
    video_id = video_id or job.get("video_id")
    cuts = delete_cuts_for_job(job_id, perfil_id=perfil_id)
    shorts_root = os.path.realpath(media_dirs["shorts"])
    downloads_root = os.path.realpath(media_dirs["downloads"])

    def inside(path, root):
        if not path:
            return False
        try:
            return os.path.commonpath((os.path.realpath(path), root)) == root
        except ValueError:
            return False

    for cut in cuts:
        output_path = cut.get("caminho_saida")
        if inside(output_path, shorts_root) and os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass

    temporary_dirs = set()
    if video_id:
        temporary_dirs.add(os.path.join(downloads_root, f"cut_source_{video_id}"))
    temporary_dirs.add(os.path.join(downloads_root, f"force_{job_id}"))
    for cut in cuts:
        source_path = cut.get("arquivo_origem")
        parent = os.path.dirname(os.path.realpath(source_path)) if source_path else ""
        if inside(parent, downloads_root) and os.path.basename(parent) in {f"cut_source_{video_id}", f"force_{job_id}"}:
            temporary_dirs.add(parent)

    for temporary_dir in temporary_dirs:
        if not inside(temporary_dir, downloads_root) or not os.path.isdir(temporary_dir):
            continue
        dirname = os.path.basename(temporary_dir)
        if dirname.startswith("cut_source_"):
            other_jobs = 0
            conn = get_connection()
            try:
                other_jobs = conn.execute(
                    "SELECT COUNT(*) FROM tarefas_jobs WHERE perfil_id=? AND video_id=? AND job_id<>? AND status NOT IN ('cancelled', 'cancelling', 'interrupted', 'rejected')",
                    (perfil_id, video_id, job_id),
                ).fetchone()[0]
            finally:
                conn.close()
            if other_jobs:
                continue
        try:
            shutil.rmtree(temporary_dir)
        except OSError:
            pass

    return len(cuts)


def _cleanup_cancelled_jobs():
    conn = get_connection()
    try:
        jobs = conn.execute("SELECT job_id, perfil_id, video_id FROM tarefas_jobs WHERE status='cancelled'").fetchall()
    finally:
        conn.close()
    for job in jobs:
        _cleanup_cancelled_job(job["job_id"], job["perfil_id"], job["video_id"])


def _cleanup_orphan_directcompute_processes():
    if os.name != "nt":
        return
    subprocess.run(
        ["taskkill", "/F", "/IM", "constme.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


recover_running_jobs()
_cleanup_orphan_directcompute_processes()
_cleanup_cancelled_jobs()
prune_unavailable_cuts()


def _update_runtime_job(store, job_id, perfil_id, **changes):
    store.setdefault(job_id, {}).update(changes)
    checkpoint = {key: value for key, value in changes.items() if key not in {"status", "progress", "message", "error", "suggestions", "segments"}}
    current_item = next((changes.get(key) for key in ("item_atual", "rendered_index", "segments_processed", "step_index") if changes.get(key) is not None), None)
    total_items = next((changes.get(key) for key in ("total_itens", "render_total", "segments_total", "step_total") if changes.get(key) is not None), None)
    update_job(
        job_id,
        status=changes.get("status"),
        progress=changes.get("progress"),
        message=changes.get("message"),
        error=changes.get("error"),
        result=json.dumps(changes.get("suggestions", changes.get("segments")), ensure_ascii=False) if "suggestions" in changes or "segments" in changes else None,
        perfil_id=perfil_id,
        stage=changes.get("stage"),
        current_item=current_item,
        total_items=total_items,
        checkpoint=checkpoint or None,
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
    return _youtube_video_id(url) is not None


def _youtube_video_id(url):
    parsed = urlparse((url or "").strip())
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        return None
    if hostname == "youtu.be":
        candidate = parsed.path.strip("/").split("/", 1)[0]
    else:
        candidate = parse_qs(parsed.query).get("v", [""])[0]
        if not candidate:
            path_parts = [part for part in parsed.path.split("/") if part]
            if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live"}:
                candidate = path_parts[1]
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else None


def _transcript_cache_path(path, perfil_id, youtube_video_id=None):
    digest = calcular_hash_arquivo(path)
    prefix = f"cache_transcricao_v={youtube_video_id}_" if youtube_video_id else "cache_transcricao_"
    return os.path.join(obter_pastas_midia(perfil_id)["transcripts"], f"{prefix}{digest}.srt"), digest


def _remove_video_artifacts(perfil_id, video_id, file_hashes, paths):
    media_dirs = obter_pastas_midia(perfil_id)
    allowed_roots = [os.path.realpath(media_dirs[key]) for key in ("uploads", "downloads", "shorts", "transcripts")]
    candidates = set(paths)
    transcript_dir = media_dirs["transcripts"]
    for extension in (".srt", ".json"):
        candidates.add(os.path.join(transcript_dir, f"cache_transcricao_v={video_id}_" + "*") + extension)
        for file_hash in file_hashes:
            candidates.update({
                os.path.join(transcript_dir, f"{file_hash}{extension}"),
                os.path.join(transcript_dir, f"cache_transcricao_{file_hash}{extension}"),
                os.path.join(transcript_dir, f"cache_transcricao_v={video_id}_{file_hash}{extension}"),
            })
    expanded = set()
    for candidate in candidates:
        if "*" in candidate:
            expanded.update(glob.glob(candidate))
        else:
            expanded.add(candidate)
    removed = 0
    for candidate in expanded:
        if not candidate or not os.path.isfile(candidate):
            continue
        real_path = os.path.realpath(candidate)
        if not any(os.path.commonpath([real_path, root]) == root for root in allowed_roots):
            continue
        try:
            os.remove(real_path)
            removed += 1
        except OSError:
            registrar_log(f"Não foi possível remover artefato do vídeo {video_id}: {real_path}")
    return removed


def _delete_editorial_dossier(video_id, perfil_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT 1 FROM videos_historico WHERE video_id=? AND perfil_id=? LIMIT 1",
            (video_id, perfil_id),
        ).fetchone()
    finally:
        conn.close()
    if not rows:
        raise LookupError("Vídeo não encontrado neste perfil.")
    path = dossier_path(video_id, perfil_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def _get_editorial_dossier(video_id, perfil_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM videos_historico WHERE video_id=? AND perfil_id=? LIMIT 1",
            (video_id, perfil_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise LookupError("Vídeo não encontrado neste perfil.")
    dossier = load_dossier(video_id, perfil_id)
    if dossier is None:
        raise LookupError("Este vídeo não possui Dossiê Editorial.")
    return dossier


def _clear_transcription_cache(video_id, perfil_id):
    conn = get_connection()
    try:
        video = conn.execute(
            "SELECT file_hash, arquivo_origem FROM videos_historico WHERE video_id=? AND perfil_id=?",
            (video_id, perfil_id),
        ).fetchone()
        if not video:
            raise LookupError("Vídeo não encontrado neste perfil.")
        file_hashes = {str(video["file_hash"]).strip()} if video["file_hash"] else set()
        source_path = video["arquivo_origem"]
        if source_path and os.path.isfile(source_path):
            try:
                file_hashes.add(calcular_hash_arquivo(source_path))
            except (OSError, ValueError):
                pass
        rows = conn.execute(
            "UPDATE videos_historico SET transcricao=NULL, transcricao_segmentos=NULL, duracao_segundos=NULL, file_hash=NULL, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
            (video_id, perfil_id),
        )
        conn.commit()
    finally:
        conn.close()
    removed = _remove_video_artifacts(perfil_id, video_id, file_hashes, set())
    dossier = dossier_path(video_id, perfil_id)
    if dossier.is_file():
        try:
            dossier.unlink()
            removed += 1
        except OSError:
            registrar_log(f"Não foi possível remover o dossiê editorial de {video_id}: {dossier}")
    return removed


def _cut_duration_range(minimum, maximum):
    try:
        minimum = max(5, min(300, int(minimum)))
        maximum = max(5, min(300, int(maximum)))
    except (TypeError, ValueError):
        return 30, 60
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    return minimum, maximum


def _process_local_media_job(job_id, path, perfil_id, duracao_minima=30, duracao_maxima=60, video_id=None):
    store = CUT_JOBS
    video_id = video_id or job_id
    media_dirs = obter_pastas_midia(perfil_id)
    store[job_id] = {"status": "running", "progress": 5, "message": "Preparando transcrição", "stage": "preparing", "video_id": video_id, "perfil_id": perfil_id}
    update_job(job_id, status="running", progress=5, message="Transcrevendo arquivo local", perfil_id=perfil_id, stage="transcription", attempt=1)
    try:
        _raise_if_cancelled(job_id)
        conn = get_connection()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO videos_historico (perfil_id, video_id, titulo, tipo, status, arquivo_origem, atualizado_em) VALUES (?, ?, ?, 'video', 'upload_local', ?, CURRENT_TIMESTAMP)",
                (perfil_id, video_id, _local_media_title(path), path),
            )
            conn.commit()
        finally:
            conn.close()
        def update_progress(progress, message, details=None):
            details = details or {}
            store[job_id].update({"progress": progress, "message": message, "perfil_id": perfil_id, **details})
            stage = details.get("stage", store[job_id].get("stage", "running"))
            current_item = details.get("segments_processed", details.get("rendered_index"))
            total_items = details.get("segments_total", details.get("render_total"))
            update_job(job_id, status="running", progress=progress, message=message, perfil_id=perfil_id, stage=stage, current_item=current_item, total_items=total_items, checkpoint=details)

        cache_srt_path, file_hash = _transcript_cache_path(path, perfil_id, youtube_video_id=video_id if len(str(video_id)) == 11 else None)
        segments = transcrever_arquivo_local_segmentos(path, progress_callback=update_progress, cancel_callback=lambda: _cancel_event(job_id).is_set(), cache_srt_path=cache_srt_path)
        _raise_if_cancelled(job_id)
        if not segments:
            raise RuntimeError("Nenhuma fala encontrada no arquivo local.")
        duration = max(segment["fim"] for segment in segments)
        try:
            media_duration = obter_duracao(path)
        except (MediaToolError, OSError, ValueError):
            media_duration = 0
        if media_duration > 0 and media_duration < duration:
            duration = media_duration
            segments = [
                {**segment, "fim": min(float(segment["fim"]), media_duration)}
                for segment in segments
                if float(segment["inicio"]) < media_duration and min(float(segment["fim"]), media_duration) > float(segment["inicio"])
            ]
        text = "\n".join(f"[{s['indice']}] {s['inicio']:.3f}-{s['fim']:.3f}: {s['texto']}" for s in segments)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE videos_historico SET file_hash=?, transcricao=?, transcricao_segmentos=?, duracao_segundos=?, arquivo_origem=?, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
                (file_hash, " ".join(segment["texto"] for segment in segments), json.dumps(segments, ensure_ascii=False), round(duration), path, video_id, perfil_id),
            )
            conn.commit()
        finally:
            conn.close()
        store[job_id].update({"progress": 92, "message": "IA editorial analisando candidatos", "stage": "editorial", "segments_processed": len(segments), "segments_accepted": len(segments), "perfil_id": perfil_id})
        update_job(job_id, status="running", progress=92, message="IA editorial analisando candidatos", perfil_id=perfil_id, stage="editorial", checkpoint={"segments": len(segments)})
        _raise_if_cancelled(job_id)
        titulo_original = _local_media_title(path)
        def update_editorial_progress(processed, total, phase, details=None):
            update_progress(92, "IA editorial analisando candidatos", {"stage": phase, **(details or {})})
        def editorial_partial_callback(partial_callback, partial):
            steps_total = partial.get("steps_total")
            steps_completed = partial.get("steps_completed")
            progress = 92
            if steps_total:
                progress = min(98, 92 + round(float(steps_completed or 0) / steps_total * 6))
            _update_runtime_job(
                CUT_JOBS,
                job_id,
                perfil_id,
                progress=progress,
                message=f"IA editorial analisando step {steps_completed}/{steps_total}",
                stage="editorial",
                step_name="editorial",
                step_index=steps_completed,
                step_total=steps_total,
                editorial_status=partial.get("status"),
            )
            if partial_callback:
                partial_callback(partial)
        previous_cuts = list_cuts(video_id=video_id, perfil_id=perfil_id)
        dossier, dossier_candidates, generated_analysis, dossier_cache_hit = load_or_build_dossier(
            video_id,
            perfil_id,
            path,
            segments,
            duration,
            "",
            previous_cuts,
            analysis_factory=lambda partial_callback=None, resume_analysis=None: gerar_cortes_com_retry(
                text,
                duration,
                segments,
                duracao_minima=duracao_minima,
                duracao_maxima=duracao_maxima,
                titulo_original=titulo_original,
                progress_callback=update_editorial_progress,
                cancel_callback=lambda: _cancel_event(job_id).is_set(),
                cortes_existentes=previous_cuts,
                partial_callback=lambda partial: editorial_partial_callback(partial_callback, partial),
                resume_analysis=resume_analysis,
            ),
            parameters={
                "duration_min": duracao_minima,
                "duration_max": duracao_maxima,
                "model": os.getenv("GROWTH_ENGINE_CUT_MODEL", "qwen2.5:14b"),
                "prompt_version": "editorial-steps-v3-interviews",
            },
            limit=15,
        )
        if generated_analysis is None:
            analysis = {
                "status": "completed" if dossier_candidates else "needs_review",
                "cortes": dossier_candidates,
                "candidatos": dossier_candidates,
                "diagnostico": [{"tentativa": 0, "candidatos": len(dossier_candidates), "aceitos": len(dossier_candidates), "status": "dossier_cache_hit"}],
                "rejeicoes": [],
                "minimo": 1,
            }
        else:
            analysis = generated_analysis
            generated_candidates = analysis.get("cortes") or analysis.get("candidatos") or []
            analysis["cortes"] = generated_candidates
            analysis["candidatos"] = generated_candidates
        analysis["dossier_cache_hit"] = dossier_cache_hit
        _raise_if_cancelled(job_id)
        if analysis.get("status") == "failed":
            message = str((analysis.get("rejeicoes") or ["Geração interrompida: a IA não produziu candidatos editoriais suficientes."])[0])
            result = {"analysis": analysis, "cortes": []}
            diagnostic_json = json.dumps(result, ensure_ascii=False)
            store[job_id].update({"status": "failed", "progress": 100, "message": message, "perfil_id": perfil_id, "suggestions": [], "resultado_json": diagnostic_json})
            update_job(job_id, status="failed", progress=100, message=message, result=diagnostic_json, perfil_id=perfil_id)
            return
        suggestions = analysis["cortes"]
        def update_render_progress(index, total):
            progress = 92 + (7 * index / max(total, 1))
            message = f"Renderizando corte {index} de {total}"
            store[job_id].update({"progress": progress, "message": message, "stage": "rendering", "rendered_index": index, "render_total": total, "perfil_id": perfil_id})
            update_job(job_id, status="running", progress=progress, message=message, perfil_id=perfil_id, stage="rendering", current_item=index, total_items=total, checkpoint={"rendered_index": index, "render_total": total})

        if analysis["status"] != "completed":
            validar_ferramentas()
            persisted_candidates = []
            render_candidates = analysis.get("candidatos", [])
            for index, candidate in enumerate(render_candidates, start=1):
                _raise_if_cancelled(job_id)
                inicio = candidate.get("inicio") if candidate.get("inicio") is not None else candidate.get("inicio_segundos")
                fim = candidate.get("fim") if candidate.get("fim") is not None else candidate.get("fim_segundos")
                if inicio is None or fim is None or float(fim) <= float(inicio):
                    registrar_log(f"Candidato descartado sem intervalo válido: job={job_id} indice={index}")
                    continue
                candidate = {**candidate, "inicio": float(inicio), "fim": float(fim)}
                update_render_progress(index, len(render_candidates))
                round_number = candidate.get("numero_rodada", 1)
                round_name = f"{_local_media_title(path)}-curadoria-{round_number:02d}"
                cut_id = create_cut(
                    job_id,
                    video_id,
                    path,
                    candidate,
                    perfil_id=perfil_id,
                    status="candidato",
                    video_title=_local_media_title(path),
                    round_name=round_name,
                )
                output_name = f"{nome_seguro_arquivo(job_id)}_{cut_id}_{nome_seguro_arquivo(normalizar_titulo_corte(candidate.get('titulo')), 'candidato')}.mp4"
                output_path = os.path.join(media_dirs["shorts"], output_name)
                try:
                    update_cut(cut_id, status="renderizando", perfil_id=perfil_id)
                    renderizar_corte(path, output_path, candidate["inicio"], candidate["fim"], intervalos=candidate.get("montagem_intervalos"), vertical=True)
                    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
                        raise MediaToolError("FFmpeg não produziu um arquivo final válido.")
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
            message = f"Revisão necessária: {len(suggestions)} corte(s) editorial(is); {len(persisted_candidates)} candidato(s) renderizado(s) para ponderação humana."
            result = {"analysis": analysis, "cortes": persisted_candidates}
            diagnostic_json = json.dumps(result, ensure_ascii=False)
            store[job_id].update({"status": "needs_review", "progress": 100, "message": message, "perfil_id": perfil_id, "suggestions": persisted_candidates, "resultado_json": diagnostic_json})
            update_job(job_id, status="needs_review", progress=100, message=message, result=diagnostic_json, perfil_id=perfil_id)
            return
        validar_ferramentas()
        results = []
        for index, suggestion in enumerate(suggestions, start=1):
            _raise_if_cancelled(job_id)
            inicio = suggestion.get("inicio") if suggestion.get("inicio") is not None else suggestion.get("inicio_segundos")
            fim = suggestion.get("fim") if suggestion.get("fim") is not None else suggestion.get("fim_segundos")
            if inicio is None or fim is None or float(fim) <= float(inicio):
                registrar_log(f"Candidato descartado sem intervalo válido: job={job_id} indice={index}")
                continue
            suggestion = {**suggestion, "inicio": float(inicio), "fim": float(fim)}
            update_render_progress(index, len(suggestions))
            cut_id = create_cut(job_id, video_id, path, suggestion, perfil_id=perfil_id)
            output = os.path.join(media_dirs["shorts"], f"{job_id}_{cut_id}.mp4")
            try:
                update_cut(cut_id, status="renderizando", perfil_id=perfil_id)
                renderizar_corte(path, output, suggestion["inicio"], suggestion["fim"], intervalos=suggestion.get("montagem_intervalos"), vertical=True)
                if not os.path.isfile(output) or os.path.getsize(output) <= 0:
                    raise MediaToolError("FFmpeg não produziu um arquivo final válido.")
                update_cut(cut_id, status="concluido", output_path=output, perfil_id=perfil_id)
                results.append({**suggestion, "cut_id": cut_id, "status": "concluido", "output_path": output})
            except Exception as error:
                update_cut(cut_id, status="falhou", error=str(error), perfil_id=perfil_id)
                results.append({**suggestion, "cut_id": cut_id, "status": "falhou", "error": str(error)})
        result_payload = {"analysis": analysis, "cortes": results}
        store[job_id].update({"status": "completed", "progress": 100, "message": "Upload processado", "suggestions": results})
        update_job(job_id, status="completed", progress=100, message="Upload processado", result=json.dumps(result_payload, ensure_ascii=False), perfil_id=perfil_id)
    except (JobCancelled, TranscriptionCancelled) as error:
        _cleanup_cancelled_job(job_id, perfil_id)
        store[job_id].update({"status": "cancelled", "message": str(error), "perfil_id": perfil_id})
        update_job(job_id, status="cancelled", message=str(error), perfil_id=perfil_id)
    except Exception as error:
        store[job_id].update({"status": "failed", "progress": 0, "message": str(error)})
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)


def _force_download_job(job_id, url, perfil_id, video_id, duracao_minima=30, duracao_maxima=60):
    output_dir = os.path.join(obter_pastas_midia(perfil_id)["downloads"], f"force_{job_id}")
    os.makedirs(output_dir, exist_ok=True)
    try:
        CUT_JOBS[job_id] = {"status": "running", "progress": 10, "message": "Baixando sem usar cache", "video_id": video_id, "perfil_id": perfil_id}
        opts = {"format": "bestvideo+bestaudio/best", "outtmpl": os.path.join(output_dir, "source.%(ext)s"), "overwrites": True, "nooverwrites": False, "quiet": True, "merge_output_format": "mp4"}
        with yt_dlp.YoutubeDL(opts) as downloader:
            downloader.download([url])
        source = next((
            os.path.join(output_dir, name)
            for name in os.listdir(output_dir)
            if name.lower().endswith((".mp4", ".mkv", ".webm"))
        ), None)
        if not source:
            raise RuntimeError("yt-dlp não produziu um arquivo de vídeo local.")
        _process_local_media_job(job_id, source, perfil_id, duracao_minima, duracao_maxima, video_id=video_id)
    except Exception as error:
        CUT_JOBS[job_id] = {"status": "failed", "progress": 0, "message": str(error), "video_id": video_id, "perfil_id": perfil_id}
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)


def _download_cut_source(video_id, perfil_id, job_id):
    output_dir = os.path.join(obter_pastas_midia(perfil_id)["downloads"], f"cut_source_{video_id}")
    os.makedirs(output_dir, exist_ok=True)
    _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=15, message="Baixando vídeo original para renderizar os cortes")
    opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": os.path.join(output_dir, "source.%(ext)s"),
        "overwrites": True,
        "nooverwrites": False,
        "quiet": True,
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as downloader:
        downloader.download([f"https://www.youtube.com/watch?v={video_id}"])
    source_path = next((
        os.path.join(output_dir, name) for name in os.listdir(output_dir)
        if name.lower().endswith((".mp4", ".mkv", ".webm"))
    ), None)
    if not source_path or not os.path.isfile(source_path):
        raise MediaToolError("O download não produziu um arquivo de vídeo local.")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE videos_historico SET arquivo_origem=?, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
            (source_path, video_id, perfil_id),
        )
        conn.commit()
    finally:
        conn.close()
    _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=25, message="Vídeo baixado; preparando análise da IA")
    return source_path


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


def _receive_srt_upload(handler, content_type, content_length, upload_dir):
    if content_length <= 0 or content_length > 50 * 1024 * 1024:
        raise ValueError("O arquivo SRT excede o limite de 50 MB.")
    boundary_token = content_type.split("boundary=", 1)[-1].strip().strip('"')
    if not boundary_token:
        raise ValueError("Cabeçalho multipart inválido.")
    boundary = ("--" + boundary_token).encode()
    body = handler.rfile.read(content_length)
    for part in body.split(boundary):
        if b"\r\n\r\n" not in part:
            continue
        headers, payload = part.split(b"\r\n\r\n", 1)
        disposition = headers.decode("latin-1", errors="replace")
        if 'name="file"' not in disposition:
            continue
        filename = disposition.split("filename=", 1)[-1].split("\r\n", 1)[0].strip().strip('"') if "filename=" in disposition else "transcricao.srt"
        if os.path.splitext(filename)[1].lower() != ".srt":
            raise ValueError("Envie um arquivo SRT.")
        payload = payload.rstrip(b"\r\n")
        if not payload:
            raise ValueError("Upload SRT vazio.")
        os.makedirs(upload_dir, exist_ok=True)
        path = os.path.join(upload_dir, f"upload_{uuid.uuid4().hex}.srt")
        with open(path, "wb") as output:
            output.write(payload)
        return path
    raise ValueError("Campo multipart 'file' ausente.")


def _receive_font_upload(handler, content_type, content_length, upload_dir):
    if content_length <= 0 or content_length > 50 * 1024 * 1024:
        raise ValueError("A fonte excede o limite de 50 MB.")
    boundary_token = content_type.split("boundary=", 1)[-1].strip().strip('"')
    if not boundary_token:
        raise ValueError("Cabeçalho multipart inválido.")
    boundary = ("--" + boundary_token).encode()
    body = handler.rfile.read(content_length)
    for part in body.split(boundary):
        if b"\r\n\r\n" not in part:
            continue
        headers, payload = part.split(b"\r\n\r\n", 1)
        disposition = headers.decode("latin-1", errors="replace")
        if 'name="file"' not in disposition:
            continue
        filename = disposition.split("filename=", 1)[-1].split("\r\n", 1)[0].strip().strip('"') if "filename=" in disposition else "fonte.ttf"
        payload = payload.rstrip(b"\r\n")
        if not payload:
            raise ValueError("Upload de fonte vazio.")
        os.makedirs(upload_dir, exist_ok=True)
        path = os.path.join(upload_dir, f"upload_{uuid.uuid4().hex}{os.path.splitext(filename)[1].lower()}")
        with open(path, "wb") as output:
            output.write(payload)
        return path, os.path.basename(filename)
    raise ValueError("Campo multipart 'file' ausente.")


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


def _require_admin(handler):
    perfil_id = getattr(handler, "request_profile_id", None) or _request_profile_id(handler)
    conn = get_connection()
    try:
        row = conn.execute("SELECT is_admin FROM perfis WHERE id=? AND ativo=1", (perfil_id,)).fetchone()
    finally:
        conn.close()
    if not row or not row["is_admin"]:
        raise PermissionError("Acesso restrito a administradores.")
    return perfil_id


def _admin_clear_cache():
    init_db()
    conn = get_connection()
    try:
        profiles = [row[0] for row in conn.execute("SELECT id FROM perfis WHERE ativo=1").fetchall()]
        known_video_ids = {str(row[0]) for row in conn.execute("SELECT video_id FROM videos_historico WHERE video_id IS NOT NULL").fetchall()}
    finally:
        conn.close()
    removed = []
    temporary_suffixes = (".part", ".ytdl", ".tmp", ".temp")
    for perfil_id in profiles:
        for directory_key in ("uploads", "downloads", "transcripts"):
            directory = obter_pastas_midia(perfil_id)[directory_key]
            for root, _, filenames in os.walk(directory):
                for filename in filenames:
                    path = os.path.join(root, filename)
                    lower_name = filename.lower()
                    is_temporary = lower_name.startswith(("temp_", ".growth-")) or (directory_key == "transcripts" and lower_name.startswith("upload_")) or lower_name.endswith(temporary_suffixes)
                    is_orphan_transcript = directory_key == "transcripts" and lower_name.endswith((".srt", ".json")) and not any(video_id in filename for video_id in known_video_ids)
                    if not is_temporary and not is_orphan_transcript:
                        continue
                    try:
                        os.remove(path)
                        removed.append(path)
                    except OSError:
                        pass
    return {"removidos": len(removed), "arquivos": [os.path.basename(path) for path in removed]}


def _admin_reset_jobs():
    init_db()
    conn = get_connection()
    try:
        jobs = conn.execute("SELECT job_id FROM tarefas_jobs WHERE status IN ('queued', 'running', 'cancelling')").fetchall()
        conn.execute("""
            UPDATE tarefas_jobs
            SET status='cancelled', mensagem='Cancelada pelo Painel Admin',
                concluido_em=CURRENT_TIMESTAMP, atualizado_em=CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'running', 'cancelling')
        """)
        conn.execute("""
            UPDATE cortes_gerados
            SET status='pendente', erro=NULL, atualizado_em=CURRENT_TIMESTAMP
            WHERE status IN ('renderizando', 'processando')
        """)
        conn.execute("""
            UPDATE tarefas_processamento
            SET status='idle', processados=0, total=0, progresso=0,
                mensagem='Fila resetada pelo Painel Admin', erro=NULL,
                concluido_em=CURRENT_TIMESTAMP, atualizado_em=CURRENT_TIMESTAMP
            WHERE status IN ('queued', 'running', 'cancelling')
        """)
        conn.commit()
        job_ids = [row[0] for row in jobs]
    finally:
        conn.close()
    for job_id in job_ids:
        CANCEL_EVENTS.pop(job_id, None)
        TRANSCRIPTION_JOBS.pop(job_id, None)
        CUT_JOBS.pop(job_id, None)
    return {"cancelados": len(job_ids)}


def _admin_clear_finished_jobs(perfil_id):
    init_db()
    finished_statuses = ("completed", "failed", "cancelled", "interrupted", "rejected", "needs_review", "needs_review_fallback")
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in finished_statuses)
        removed = conn.execute(
            f"DELETE FROM tarefas_jobs WHERE perfil_id=? AND status IN ({placeholders})",
            (perfil_id, *finished_statuses),
        ).rowcount
        conn.commit()
    finally:
        conn.close()
    return {"removidos": removed}


def _admin_vacuum_db():
    conn = get_connection()
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()
    return {"status": "ok"}


def _admin_restart_server():
    def restart_process():
        time.sleep(0.25)
        os.execv(sys.executable, [sys.executable, os.path.join(DIRETORIO_PROJETO, "iniciar_servidor.py")])

    threading.Thread(target=restart_process, daemon=True).start()
    return {"status": "restarting", "message": "Servidor será reiniciado."}


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
    prune_unavailable_cuts(perfil_id)
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
    channel = _channel_metrics(perfil_id)
    daily_views = views_total / max(1, len(all_videos)) if all_videos else 0
    subscriber_rate = channel["subscribers"] / views_total if channel["subscribers"] is not None and views_total else None
    channel_projections = {}
    for label, days in (("1_week", 7), ("15_days", 15), ("1_month", 30), ("6_months", 180), ("1_year", 365)):
        added_views = round(daily_views * days)
        channel_projections[label] = {
            "views": views_total + added_views,
            "subscribers": channel["subscribers"] + round(added_views * subscriber_rate) if subscriber_rate is not None else None,
        }
    conn = get_connection()
    try:
        content_pending = conn.execute(
            "SELECT COUNT(*) FROM videos_historico WHERE perfil_id=? AND tipo='video' AND NOT EXISTS (SELECT 1 FROM analises_conteudo WHERE analises_conteudo.perfil_id=? AND analises_conteudo.video_id=videos_historico.video_id AND status='concluida')",
            (perfil_id, perfil_id),
        ).fetchone()[0]
        cuts_in_review = conn.execute(
            "SELECT COUNT(*) FROM cortes_gerados cuts WHERE cuts.perfil_id=? AND cuts.status IN ('candidato', 'selecionado', 'concluido', 'renderizando') AND NOT EXISTS (SELECT 1 FROM tarefas_jobs jobs WHERE jobs.job_id=cuts.job_id AND jobs.perfil_id=cuts.perfil_id AND jobs.status IN ('cancelled', 'cancelling', 'interrupted', 'rejected'))",
            (perfil_id,),
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
            "views_total": views_total,
            "views_total_display": _format_count(views_total),
            **channel,
            "projections": channel_projections,
            "analises_conteudo_pendentes": content_pending,
            "cortes_em_revisao": cuts_in_review,
        },
    }


def _fetch_cut_sources(perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
                 SELECT video_id, file_hash, titulo, tipo, views, likes, data_publicacao,
                     hora_publicacao, transcricao, transcricao_segmentos, arquivo_origem, status, atualizado_em
            FROM videos_historico
            WHERE perfil_id = ? AND tipo = 'video' AND status IN ('upload_local', 'publicado_externo', 'publicado')
            ORDER BY CASE WHEN data_publicacao IS NULL OR data_publicacao = '' THEN 1 ELSE 0 END,
                     data_publicacao DESC,
                     hora_publicacao DESC,
                     atualizado_em DESC
        """, (perfil_id,)).fetchall()
        videos = []
        for row in rows:
            video = {
                **_video_dict(row),
                "has_transcription": bool(row["transcricao"]),
                "has_segments": bool(row["transcricao_segmentos"]),
                "has_editorial": load_dossier(row["video_id"], perfil_id) is not None,
            }
            if not video["thumbnail_url"]:
                video["thumbnail_url"] = f"/api/cuts/source-thumbnail?video_id={video['id']}&perfil_id={perfil_id}"
            videos.append(video)
        return videos
    finally:
        conn.close()


def _fetch_related_videos(perfil_id=1, query=""):
    init_db()
    conn = get_connection()
    try:
        params = [perfil_id]
        where = "perfil_id=? AND length(video_id)=11 AND tipo='video' AND status IN ('publicado', 'publicado_externo', 'programado', 'agendado')"
        if query:
            where += " AND titulo LIKE ?"
            params.append(f"%{query}%")
        rows = conn.execute(f"""
                 SELECT id, video_id, titulo, tipo, status, data_publicacao, hora_publicacao,
                     views, likes, related_video_id, related_video_title, related_video_status,
                     related_video_error, arquivo_origem, atualizado_em
            FROM videos_historico
            WHERE {where}
            ORDER BY CASE WHEN status IN ('publicado', 'programado', 'agendado') THEN 0 ELSE 1 END,
                     CASE WHEN NULLIF(data_publicacao, '') IS NULL THEN substr(atualizado_em, 1, 10) ELSE data_publicacao END DESC,
                     CASE WHEN NULLIF(hora_publicacao, '') IS NULL THEN substr(atualizado_em, 12, 8) ELSE hora_publicacao END DESC,
                     id DESC
            LIMIT 200
        """, params).fetchall()
        videos = []
        for row in rows:
            video = dict(row)
            video["thumbnail_url"] = f"https://i.ytimg.com/vi/{row['video_id']}/hqdefault.jpg"
            video["thumbnail_local_url"] = (
                f"/api/cuts/source-thumbnail?video_id={row['video_id']}&perfil_id={perfil_id}"
                if row["arquivo_origem"] and os.path.isfile(row["arquivo_origem"])
                else ""
            )
            video["eligible"] = row["status"] not in {"privado", "excluido"}
            videos.append(video)
        return videos
    finally:
        conn.close()


def _validar_ids_video_relacionado(short_video_id, related_video_id):
    if len(short_video_id) != 11 or len(related_video_id) != 11:
        raise ValueError("Selecione vídeos válidos do canal.")
    if short_video_id == related_video_id:
        raise ValueError("O Short não pode ser relacionado a ele mesmo.")


def _fetch_library_videos(perfil_id=1, tipo=None, query="", ordem="recent"):
    init_db()
    conn = get_connection()
    try:
        clauses = ["perfil_id=?"]
        params = [perfil_id]
        if tipo in ("video", "short"):
            clauses.append("tipo=?")
            params.append(tipo)
        if query:
            clauses.append("titulo LIKE ?")
            params.append(f"%{query}%")
        order_by = {
            "recent": "CASE WHEN data_publicacao IS NULL OR data_publicacao = '' THEN 1 ELSE 0 END, data_publicacao DESC, hora_publicacao DESC, atualizado_em DESC",
            "views": "CAST(COALESCE(views, 0) AS INTEGER) DESC, data_publicacao DESC, atualizado_em DESC",
            "likes": "CAST(COALESCE(likes, 0) AS INTEGER) DESC, data_publicacao DESC, atualizado_em DESC",
            "score": "CASE WHEN CAST(COALESCE(views, 0) AS INTEGER) > 0 THEN CAST(COALESCE(likes, 0) AS REAL) / CAST(views AS REAL) ELSE 0 END DESC, data_publicacao DESC, atualizado_em DESC",
        }.get(ordem, "CASE WHEN data_publicacao IS NULL OR data_publicacao = '' THEN 1 ELSE 0 END, data_publicacao DESC, hora_publicacao DESC, atualizado_em DESC")
        rows = conn.execute(f"""
            SELECT video_id, titulo, tipo, status, data_publicacao, hora_publicacao,
                   views, likes, duracao_segundos, descricao, arquivo_origem,
                   related_video_id, related_video_title, related_video_status,
                   related_video_error, atualizado_em
            FROM videos_historico
            WHERE {' AND '.join(clauses)}
            ORDER BY {order_by}
            LIMIT 500
        """, params).fetchall()
        videos = []
        for row in rows:
            video = _video_dict(row)
            video.update({
                "video_id": row["video_id"],
                "titulo": row["titulo"] or "Sem título",
                "tipo": row["tipo"],
                "status": row["status"],
                "descricao": row["descricao"] or "",
                "arquivo_origem": row["arquivo_origem"] or "",
                "related_video_id": row["related_video_id"],
                "related_video_title": row["related_video_title"],
                "related_video_status": row["related_video_status"],
                "related_video_error": row["related_video_error"],
                "thumbnail_local_url": f"/api/cuts/source-thumbnail?video_id={row['video_id']}&perfil_id={perfil_id}" if row["arquivo_origem"] and os.path.isfile(row["arquivo_origem"]) else "",
            })
            videos.append(video)
        return videos
    finally:
        conn.close()


def _channel_metrics(perfil_id=1):
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT inscritos, views_canal, videos_canal
            FROM perfis_google
            WHERE perfil_id=? AND status='conectado'
            ORDER BY atualizado_em DESC LIMIT 1
        """, (perfil_id,)).fetchone()
    finally:
        conn.close()
    return {
        "subscribers": row["inscritos"] if row and row["inscritos"] is not None else None,
        "channel_views": row["views_canal"] if row and row["views_canal"] is not None else None,
        "channel_videos": row["videos_canal"] if row and row["videos_canal"] is not None else None,
    }


def _video_detail(video_id, perfil_id=1):
    videos = _fetch_library_videos(perfil_id=perfil_id)
    video = next((item for item in videos if item["video_id"] == video_id), None)
    if not video:
        return None
    conn = get_connection()
    try:
        analysis_row = conn.execute("SELECT resultado_json, status, erro, atualizado_em FROM analises_conteudo WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
    finally:
        conn.close()
    analysis = {}
    if analysis_row and analysis_row["resultado_json"]:
        try:
            analysis = json.loads(analysis_row["resultado_json"])
        except json.JSONDecodeError:
            analysis = {}
    published = video.get("date")
    try:
        age_days = max(1, (datetime.now() - datetime.fromisoformat(str(published))).days)
    except (TypeError, ValueError):
        age_days = 1
    daily_views = video["views"] / age_days
    projections = {}
    for label, days in (("1_week", 7), ("15_days", 15), ("1_month", 30), ("6_months", 180), ("1_year", 365)):
        projections[label] = {"views": round(video["views"] + daily_views * days), "basis": "ritmo médio desde a publicação"}
    return {**video, "analysis": analysis, "analysis_status": analysis_row["status"] if analysis_row else "pendente", "projections": projections, "age_days": age_days, "daily_views": round(daily_views, 1), "channel": _channel_metrics(perfil_id)}


def _autopsy_payload(perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT v.video_id, v.titulo, v.tipo, v.views, v.likes, v.data_publicacao,
                     v.status,
                   v.transcricao, COALESCE(a.status, 'pendente') AS analise_status,
                   a.resultado_json, a.erro
            FROM videos_historico v
            LEFT JOIN analises_conteudo a ON a.video_id = v.video_id AND a.perfil_id = v.perfil_id
                        WHERE v.perfil_id = ? AND length(v.video_id) = 11
                            AND COALESCE(v.status, '') NOT IN ('privado', 'excluido')
            ORDER BY CAST(COALESCE(v.views, 0) AS INTEGER) DESC
        """, (perfil_id,)).fetchall()
    finally:
        conn.close()

    def serialize(row):
        views = int(row["views"] or 0)
        likes = int(row["likes"] or 0)
        video_type = str(row["tipo"] or "").lower()
        title = row["titulo"] or "Sem título"
        format_name = "short" if video_type == "short" or "#shorts" in title.lower() else "live" if video_type in {"live", "livestream", "live_stream"} else "video" if video_type == "video" else "general"
        result = {}
        if row["resultado_json"]:
            try:
                result = json.loads(row["resultado_json"])
            except json.JSONDecodeError:
                result = {}
        return {
            "id": row["video_id"],
            "title": title,
            "format": format_name,
            "views": views,
            "views_display": _format_count(views),
            "likes": likes,
            "likes_rate": round((likes / views) * 100, 2) if views else None,
            "date": row["data_publicacao"] or "Data não informada",
            "status": row["status"] or "",
            "analysis_status": row["analise_status"],
            "transcribed": bool((row["transcricao"] or "").strip()),
            "observations": result.get("observacoes_comprovadas", [])[:3],
            "evidence": result.get("trechos_literais_relevantes", [])[:3],
            "hypotheses": result.get("hipoteses", [])[:2],
            "missing": result.get("dados_ausentes", [])[:2],
            "error": row["erro"],
        }

    items_by_id = {}
    for row in rows:
        item = serialize(row)
        previous = items_by_id.get(item["id"])
        if previous is None or item["views"] > previous["views"]:
            items_by_id[item["id"]] = item
    items = list(items_by_id.values())
    real_performance = [item for item in items if item["views"] > 0]
    top = items[:3]
    flops = list(reversed(real_performance[-3:])) if real_performance else []
    observations = [text for item in items if item["analysis_status"] == "concluida" for text in item["observations"]]
    evidence = [text for item in items if item["analysis_status"] == "concluida" for text in item["evidence"]]
    hypotheses = [text for item in items if item["analysis_status"] == "concluida" for text in item["hypotheses"]]
    return {
        "metrics": {
            "total": len(items),
            "analyzed": sum(item["analysis_status"] == "concluida" for item in items),
            "pending": sum(item["analysis_status"] != "concluida" for item in items),
            "transcribed": sum(item["transcribed"] for item in items),
            "top_views": sum(item["views"] for item in top),
        },
        "top_performers": top,
        "flops": flops,
        "videos": items,
        "semantic": {
            "observations": observations[:6],
            "evidence": evidence[:5],
            "hypotheses": hypotheses[:4],
            "structure": "Gancho, desenvolvimento e prova concreta" if observations else "Aguardando transcrições analisadas",
        },
    }


def _fetch_transcription(video_id, perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT video_id, titulo, transcricao, transcricao_segmentos, transcricao_original, transcricao_original_segmentos, transcricao_corrigida, transcricao_corrigida_segmentos, transcricao_correcoes, transcricao_status, duracao_segundos FROM videos_historico WHERE video_id = ? AND perfil_id = ?",
            (video_id, perfil_id),
        ).fetchone()
        if not row:
            return None
        try:
            segments = json.loads(row["transcricao_segmentos"] or "[]")
        except json.JSONDecodeError:
            segments = []
        try:
            corrected_segments = json.loads(row["transcricao_corrigida_segmentos"] or "[]")
        except json.JSONDecodeError:
            corrected_segments = []
        try:
            original_segments = json.loads(row["transcricao_original_segmentos"] or "[]")
        except json.JSONDecodeError:
            original_segments = []
        try:
            corrections = json.loads(row["transcricao_correcoes"] or "{}")
        except json.JSONDecodeError:
            corrections = {}
        if corrected_segments:
            segments = corrected_segments
        duration = float(row["duracao_segundos"] or 0)
        if duration <= 0:
            duration = max((float(segment.get("fim", 0)) for segment in segments), default=0)
        return {
            "id": row["video_id"],
            "title": row["titulo"] or "Sem título",
            "text": row["transcricao_corrigida"] or row["transcricao"] or "",
            "segments": segments,
            "original_text": row["transcricao_original"] or row["transcricao"] or "",
            "original_segments": original_segments or ([] if corrected_segments else segments),
            "corrections": corrections,
            "transcription_status": row["transcricao_status"] or "original",
            "duration_seconds": duration,
        }
    finally:
        conn.close()


def _review_transcription(video_id, perfil_id, decisions, edits=None):
    transcription = _fetch_transcription(video_id, perfil_id)
    if transcription is None:
        raise ValueError("Vídeo não encontrado")
    corrections = transcription.get("corrections") or {}
    applied = corrections.get("aplicadas") if isinstance(corrections, dict) else []
    original_segments = transcription.get("original_segments") or transcription.get("segments") or []
    corrected_segments = [dict(segment) for segment in original_segments]
    by_index = {int(segment.get("indice")): segment for segment in corrected_segments if segment.get("indice") is not None}
    reviewed = []
    for correction in applied if isinstance(applied, list) else []:
        try:
            index = int(correction.get("indice"))
        except (TypeError, ValueError):
            continue
        accepted = decisions.get(str(index), correction.get("aceita", True)) if isinstance(decisions, dict) else correction.get("aceita", True)
        target = by_index.get(index)
        if target is None:
            continue
        edited_text = edits.get(str(index), "").strip() if isinstance(edits, dict) else ""
        target["texto"] = edited_text if accepted and edited_text else (correction.get("corrigido") if accepted else correction.get("original", target.get("texto", "")))
        reviewed.append({**correction, "aceita": bool(accepted)})
    text = " ".join(segment.get("texto", "") for segment in corrected_segments)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE videos_historico SET transcricao_corrigida=?, transcricao_corrigida_segmentos=?, transcricao_correcoes=?, transcricao_status=?, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
            (text, json.dumps(corrected_segments, ensure_ascii=False), json.dumps({"aplicadas": reviewed}, ensure_ascii=False), "revisada_manual", video_id, perfil_id),
        )
        conn.commit()
    finally:
        conn.close()
    return _fetch_transcription(video_id, perfil_id)


def _format_srt_timestamp(seconds):
    try:
        total_milliseconds = max(0, int(round(float(seconds or 0) * 1000)))
    except (TypeError, ValueError):
        total_milliseconds = 0
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_value, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_value:02d},{milliseconds:03d}"


def _transcription_as_srt(transcription):
    blocks = []
    for index, segment in enumerate(transcription.get("segments") or [], 1):
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("texto") or segment.get("text") or "").strip()
        if not text:
            continue
        inicio = segment.get("inicio", segment.get("start", 0))
        fim = segment.get("fim", segment.get("end", inicio))
        blocks.append(f"{index}\n{_format_srt_timestamp(inicio)} --> {_format_srt_timestamp(fim)}\n{text}")
    return "\n\n".join(blocks) + ("\n\n" if blocks else "")


def _local_content_summary(segments):
    if segments:
        return "A transcrição foi concluída, mas a IA não terminou o resumo dentro do limite. Tente novamente para obter o resumo semântico."
    return "Não foi possível gerar o resumo porque a transcrição não possui conteúdo suficiente."


def _content_summary(video_id, perfil_id):
    cache_key = (int(perfil_id), str(video_id))
    if cache_key in CONTENT_SUMMARIES:
        return CONTENT_SUMMARIES[cache_key]
    transcription = _fetch_transcription(video_id, perfil_id)
    if not transcription or not transcription.get("segments"):
        return {"status": "unavailable", "summary": "Resumo indisponível até a transcrição ser concluída."}
    context = "\n".join(
        f"[{segment.get('inicio', 0):.1f}-{segment.get('fim', 0):.1f}] {segment.get('texto', '')}"
        for segment in transcription["segments"]
    )[:6000]
    prompt = f"""Você é um editor que resume vídeos em português do Brasil.
Resuma o conteúdo do vídeo a partir da transcrição abaixo em uma única descrição breve de 1 ou 2 frases, com no máximo 240 caracteres.
Explique o assunto, a situação e o foco principal do vídeo. Não copie frases da transcrição, não liste falas, não mencione timestamps,
ruídos ou música, não invente informações e não use o título como substituto do conteúdo. Retorne somente JSON válido no formato:
{{"resumo":"..."}}

TRANSCRIÇÃO:
{context}"""
    timeout_seconds = _calcular_timeout_ollama(transcription.get("duration_seconds"))
    try:
        resposta = _gerar_resposta_ollama_http(prompt, timeout=timeout_seconds, num_predict=180, num_ctx=1536)
        if resposta.get("status_code") != 200:
            raise RuntimeError(f"provider_http_{resposta.get('status_code')}")
        payload = json.loads(resposta.get("response", "{}"))
        summary = str(payload.get("resumo") or "").strip()[:240]
        if not summary:
            raise ValueError("resumo vazio")
        result = {"status": "completed", "summary": summary}
    except Exception as error:
        error_type = type(error).__name__
        if error_type in {"ReadTimeout", "Timeout"}:
            result = {"status": "fallback_local", "summary": _local_content_summary(transcription["segments"]), "error": error_type, "message": f"Resumo local exibido porque a IA excedeu o limite de {timeout_seconds:.0f} segundos."}
        else:
            result = {"status": "unavailable", "summary": "Resumo de conteúdo indisponível no momento.", "error": error_type}
    if result["status"] == "completed":
        CONTENT_SUMMARIES[cache_key] = result
    return result


def _local_source_path(video_id, perfil_id, allow_persisted_media=False):
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT titulo, arquivo_origem, status FROM videos_historico WHERE video_id=? AND perfil_id=?",
            (video_id, perfil_id),
        ).fetchone()
    finally:
        conn.close()
    if not row or (not allow_persisted_media and row["status"] != "upload_local"):
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
    source_path = _local_source_path(video_id, perfil_id, allow_persisted_media=True)
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


def _resume_interrupted_jobs():
    for job in list_resumable_jobs():
        job_id = job["job_id"]
        perfil_id = job["perfil_id"]
        video_id = job["video_id"]
        checkpoint = {}
        try:
            checkpoint = json.loads(job.get("checkpoint_json") or "{}")
        except (TypeError, ValueError):
            checkpoint = {}
        try:
            if job["tipo"] == "upload_local":
                conn = get_connection()
                try:
                    row = conn.execute("SELECT arquivo_origem FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
                finally:
                    conn.close()
                source = row["arquivo_origem"] if row else ""
                if not source or not os.path.isfile(source):
                    continue
                target = _process_local_media_job
                args = (job_id, source, perfil_id, checkpoint.get("duracao_minima", 30), checkpoint.get("duracao_maxima", 60), video_id)
                key = f"perfil:{perfil_id}:upload:{job_id}"
            elif job["tipo"] == "transcription":
                target, args, key = _run_transcription_job, (job_id, video_id, perfil_id), f"transcription:{perfil_id}:{video_id}"
            elif job["tipo"] == "editorial":
                target, args, key = _run_editorial_job, (job_id, video_id, perfil_id, checkpoint.get("duracao_minima", 30), checkpoint.get("duracao_maxima", 60)), f"editorial:{perfil_id}:{video_id}"
            else:
                target, args, key = _run_cut_job, (job_id, video_id, perfil_id, checkpoint.get("duracao_minima", 30), checkpoint.get("duracao_maxima", 60)), f"video:{perfil_id}:{video_id}"
            update_job(job_id, status="queued", message="Retomada automática após reinicialização", perfil_id=perfil_id, stage=job.get("etapa") or "queued", checkpoint=checkpoint)
            TASK_RUNNER.submit(job["tipo"], target, *args, key=key)
        except (OSError, TypeError, ValueError):
            continue


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
    _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, status="running", progress=5, message="Preparando transcrição", stage="transcription", step_name="transcription", step_index=0)

    def update(progress, message, details=None):
        step_details = dict(details or {})
        step_details.setdefault("step_name", "transcription")
        if step_details.get("step_index") is None and step_details.get("segments_processed") is not None:
            step_details["step_index"] = step_details["segments_processed"]
        _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, progress=progress, message=message, **step_details)

    try:
        _raise_if_cancelled(job_id)
        source_path = _local_source_path(video_id, perfil_id)
        transcription_started_at = time.time()
        try:
            if source_path:
                cache_srt_path, file_hash = _transcript_cache_path(source_path, perfil_id, youtube_video_id=video_id if len(str(video_id)) == 11 else None)
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
        finally:
            registrar_log(f"PROFILE transcricao video={video_id} segundos={time.time() - transcription_started_at:.2f}")
        _raise_if_cancelled(job_id)
        transcription = _fetch_transcription(video_id, perfil_id)
        if not text:
            raise RuntimeError(f"A transcrição do vídeo {video_id} terminou sem produzir texto.")
        editorial_job_id = _queue_editorial_after_transcription(video_id, perfil_id)
        _update_runtime_job(
            TRANSCRIPTION_JOBS,
            job_id,
            perfil_id,
            status="completed",
            progress=100,
            message="Transcrição concluída; editorial enfileirado" if editorial_job_id else "Transcrição concluída; editorial pendente",
            segments=transcription["segments"] if transcription else [],
            editorial_job_id=editorial_job_id,
        )
    except JobCancelled as error:
        _cleanup_cancelled_job(job_id, perfil_id, video_id)
        _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
    except Exception as error:
        _update_runtime_job(TRANSCRIPTION_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))


def _queue_editorial_after_transcription(video_id, perfil_id):
    editorial_job_id = uuid.uuid4().hex
    create_job(editorial_job_id, "editorial", video_id, perfil_id=perfil_id)
    _update_runtime_job(
        CUT_JOBS,
        editorial_job_id,
        perfil_id,
        status="queued",
        progress=0,
        message="Aguardando transcrição concluída",
        video_id=video_id,
        stage="editorial",
        step_name="editorial",
        step_index=0,
    )
    if not TASK_RUNNER.submit(
        "editorial",
        _run_editorial_job,
        editorial_job_id,
        video_id,
        perfil_id,
        key=f"editorial:{perfil_id}:{video_id}",
    ):
        update_job(editorial_job_id, status="failed", message="Não foi possível enfileirar o editorial", perfil_id=perfil_id)
        _update_runtime_job(CUT_JOBS, editorial_job_id, perfil_id, status="failed", progress=0, message="Não foi possível enfileirar o editorial", error="Fila indisponível")
        return None
    criar_notificacao(
        "Editorial enfileirado",
        f"A transcrição do vídeo {video_id} terminou; a geração editorial foi iniciada.",
        perfil_id=perfil_id,
    )
    return editorial_job_id


def _run_editorial_job(job_id, video_id, perfil_id, duracao_minima=30, duracao_maxima=60):
    _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=10, message="Carregando transcrição editorial", stage="editorial", step_name="editorial", step_index=0)
    try:
        _raise_if_cancelled(job_id)
        transcription = _fetch_transcription(video_id, perfil_id)
        if not transcription or not transcription["segments"]:
            raise RuntimeError("Este vídeo ainda não possui transcrição segmentada.")
        segments = transcription["segments"]
        duration = max(float(segment["fim"]) for segment in segments)
        conn = get_connection()
        try:
            source_row = conn.execute("SELECT titulo, arquivo_origem FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
        finally:
            conn.close()
        source_path = source_row["arquivo_origem"] if source_row else ""
        text = "\n".join(f"[{segment['indice']}] {segment['inicio']:.3f}-{segment['fim']:.3f}: {segment['texto']}" for segment in segments)
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=20, message="IA editorial analisando capítulos", stage="editorial", step_name="editorial", step_index=1, step_total=2, segments_total=len(segments))
        editorial_index = _gerar_indice_editorial_estrutural(
            text,
            duration,
            segments,
            titulo_original=source_row["titulo"] if source_row else "",
            cancel_callback=lambda: _cancel_event(job_id).is_set(),
        )
        original_segments = [dict(segment) for segment in segments]
        corrected_segments = original_segments
        corrections = []
        correction_error = None
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=55, message="Revisando transcrição com contexto editorial", stage="transcription_review", step_name="transcription_review", step_index=2, step_total=4)
        try:
            corrected_segments, corrections = corrigir_transcricao_com_contexto(
                original_segments,
                list(editorial_index),
                titulo_original=source_row["titulo"] if source_row else "",
                caminho_audio=source_path,
                cancel_callback=lambda: _cancel_event(job_id).is_set(),
            )
        except Exception as error:
            correction_error = str(error)
            corrected_segments = original_segments
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE videos_historico SET transcricao_original=?, transcricao_original_segmentos=?, transcricao_corrigida=?, transcricao_corrigida_segmentos=?, transcricao_correcoes=?, transcricao_status=?, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
                (
                    " ".join(segment.get("texto", "") for segment in original_segments),
                    json.dumps(original_segments, ensure_ascii=False),
                    " ".join(segment.get("texto", "") for segment in corrected_segments),
                    json.dumps(corrected_segments, ensure_ascii=False),
                    json.dumps({"aplicadas": corrections, "erro": correction_error}, ensure_ascii=False),
                    "corrigida" if corrections else "revisada",
                    video_id,
                    perfil_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        if corrections:
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=68, message=f"{len(corrections)} correção(ões) aplicada(s); regenerando editorial final", stage="editorial_final", step_name="editorial_final", step_index=3, step_total=4)
            corrected_text = "\n".join(f"[{segment['indice']}] {segment['inicio']:.3f}-{segment['fim']:.3f}: {segment['texto']}" for segment in corrected_segments)
            editorial_index = _gerar_indice_editorial_estrutural(
                corrected_text,
                duration,
                corrected_segments,
                titulo_original=source_row["titulo"] if source_row else "",
                cancel_callback=lambda: _cancel_event(job_id).is_set(),
            )
            segments = corrected_segments
        analysis = {
            "status": "completed",
            "capitulos": list(editorial_index),
            "resumo_conteudo": editorial_index.resumo_conteudo,
            "diagnostico": list(editorial_index.diagnostics),
            "rejeicoes": [],
            "minimo": 1,
        }
        dossier = build_dossier(video_id, perfil_id, source_path, segments, duration, "", analysis, {
            "duration_min": duracao_minima,
            "duration_max": duracao_maxima,
            "model": os.getenv("GROWTH_ENGINE_CUT_MODEL", "qwen2.5:14b"),
            "prompt_version": "editorial-steps-v2",
        })
        result = {"editorial": dossier, "analysis": analysis, "transcricao_correcoes": corrections, "transcricao_correcao_erro": correction_error}
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="completed", progress=100, message="Editorial final gerado; nenhum corte foi criado", video_id=video_id, editorial=dossier, transcription_corrections=corrections, transcription_correction_error=correction_error, stage="completed", step_name="completed", step_index=4, step_total=4)
        update_job(job_id, status="completed", progress=100, message="Editorial gerado; nenhum corte foi criado", result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
    except (JobCancelled, GenerationCancelled) as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
        update_job(job_id, status="cancelled", message=str(error), perfil_id=perfil_id)
    except Exception as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)


def _run_cut_job(job_id, video_id, perfil_id, duracao_minima=30, duracao_maxima=60):
    job_started_at = time.monotonic()
    _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=10, message="Carregando transcrição", elapsed_seconds=0)
    try:
        _raise_if_cancelled(job_id)
        persisted_job = select_job(job_id, perfil_id) or {}
        try:
            job_checkpoint = json.loads(persisted_job.get("checkpoint_json") or "{}")
        except (TypeError, ValueError):
            job_checkpoint = {}
        transcription = _fetch_transcription(video_id, perfil_id)
        if not transcription or not transcription["segments"]:
            raise RuntimeError("Este vídeo ainda não possui transcrição segmentada.")
        segments = transcription["segments"]
        conn = get_connection()
        try:
            source_row = conn.execute("SELECT titulo, arquivo_origem FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
            titulo_original = source_row["titulo"] if source_row else ""
        finally:
            conn.close()
        source_path = source_row["arquivo_origem"] if source_row and source_row["arquivo_origem"] else ""
        if not source_path or not os.path.isfile(source_path):
            media_dirs = obter_pastas_midia(perfil_id)
            source_path = next((os.path.join(media_dirs["uploads"], name) for name in os.listdir(media_dirs["uploads"]) if video_id in name), "")
        if not source_path:
            download_started_at = time.time()
            try:
                source_path = _download_cut_source(video_id, perfil_id, job_id)
            finally:
                registrar_log(f"PROFILE download_extracao video={video_id} segundos={time.time() - download_started_at:.2f}")
        _raise_if_cancelled(job_id)
        duration = max(segment["fim"] for segment in segments)
        try:
            media_duration = obter_duracao(source_path)
        except (MediaToolError, OSError, ValueError):
            media_duration = 0
        if media_duration > 0 and media_duration < duration:
            duration = media_duration
            segments = [
                {**segment, "fim": min(float(segment["fim"]), media_duration)}
                for segment in segments
                if float(segment["inicio"]) < media_duration and min(float(segment["fim"]), media_duration) > float(segment["inicio"])
            ]
        segmented_text = "\n".join(
            f"[{segment['indice']}] {segment['inicio']:.3f}-{segment['fim']:.3f}: {segment['texto']}"
            for segment in segments
        )
        contexto_multimodal = ""
        multimodal_started_at = time.time()
        try:
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=32, message="Analisando cortes de câmera e picos de áudio")
            media_triggers = scan_media_triggers(source_path)
            annotated_segments = annotate_transcript_segments(segments, media_triggers)
            contexto_multimodal = format_annotated_segments_for_prompt(annotated_segments)
            registrar_log(f"Contexto multimodal preparado: {len(media_triggers)} gatilho(s) para {video_id}.")
        except (MediaToolError, OSError, ValueError) as error:
            registrar_log(f"Contexto multimodal indisponível para {video_id}: {type(error).__name__}: {error}")
        finally:
            registrar_log(f"PROFILE multimodal video={video_id} segundos={time.time() - multimodal_started_at:.2f}")
        def update_analysis_progress(attempt, total_attempts, phase, details):
            if phase == "fallback":
                _update_runtime_job(
                    CUT_JOBS,
                    job_id,
                    perfil_id,
                    progress=40,
                    message="Gerando cortes localmente · preparando renderização",
                    candidatos=details.get("candidatos", 0),
                    candidatos_gerados=details.get("candidatos_gerados", 0),
                    analysis_round=0,
                    analysis_total=0,
                )
                return
            progress = min(75, 35 + round((attempt - 1) / max(total_attempts, 1) * 35))
            if phase == "validando":
                message = f"IA analisando conteúdo · step {attempt}/{total_attempts} · {details.get('candidatos', 0)} candidatos, {details.get('validos', 0)} válidos"
            else:
                message = f"IA analisando conteúdo · step {attempt}/{total_attempts}"
            elapsed = round(time.monotonic() - analysis_started_at)
            fraction = min(0.95, max(0.05, (attempt - 0.5) / max(total_attempts, 1)))
            eta_seconds = max(1, round(elapsed * (1 - fraction) / fraction)) if elapsed else None
            progress_data = {**details, "analysis_round": attempt, "analysis_total": total_attempts}
            if eta_seconds is not None:
                progress_data["eta_seconds"] = eta_seconds
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=progress, message=message, **progress_data)

        _update_runtime_job(CUT_JOBS, job_id, perfil_id, progress=30, message="IA analisando conteúdo · preparando contexto")
        _raise_if_cancelled(job_id)
        analysis_started_at = time.monotonic()
        analysis_heartbeat_stop = threading.Event()
        def analysis_heartbeat():
            while not analysis_heartbeat_stop.wait(2):
                try:
                    elapsed = round(time.monotonic() - analysis_started_at)
                    current_step = int(CUT_JOBS[job_id].get('analysis_round', 1) or 1)
                    total_steps = int(CUT_JOBS[job_id].get('analysis_total', 1) or 1)
                    fraction = min(0.95, max(0.05, (current_step - 0.5) / total_steps))
                    eta_seconds = max(1, round(elapsed * (1 - fraction) / fraction))
                    _update_runtime_job(
                        CUT_JOBS,
                        job_id,
                        perfil_id,
                        message=(f"IA processando resposta · step {current_step}/{total_steps} · {elapsed}s" if OLLAMA_CUTS_ENABLED else f"Gerando cortes localmente · {elapsed}s"),
                        elapsed_seconds=elapsed,
                        eta_seconds=eta_seconds,
                    )
                except Exception as error:
                    registrar_log(f"Heartbeat de cortes interrompido ({job_id}): {type(error).__name__}: {error}")
        heartbeat_thread = threading.Thread(target=analysis_heartbeat, daemon=True)
        heartbeat_thread.start()
        try:
            previous_cuts = list_cuts(video_id=video_id, perfil_id=perfil_id)
            dossier = load_dossier(video_id, perfil_id)
            if dossier is None:
                raise RuntimeError("Gere o editorial antes de gerar os cortes deste vídeo.")
            contexto_editorial = json.dumps({
                "resumo_conteudo": dossier.get("resumo_global", ""),
                "capitulos": dossier.get("capitulos", []),
            }, ensure_ascii=False)
            analysis = gerar_cortes_com_retry(
                segmented_text,
                duration,
                segments,
                minimo=1,
                max_tentativas=2,
                duracao_minima=duracao_minima,
                duracao_maxima=duracao_maxima,
                progress_callback=update_analysis_progress,
                titulo_original=titulo_original,
                cancel_callback=lambda: _cancel_event(job_id).is_set(),
                cortes_existentes=previous_cuts,
                contexto_multimodal=contexto_multimodal,
                contexto_editorial=contexto_editorial,
                partial_callback=lambda partial: _update_runtime_job(
                    CUT_JOBS,
                    job_id,
                    perfil_id,
                    stage="editorial",
                    step_name="editorial",
                    step_index=partial.get("steps_completed", 0),
                    step_total=partial.get("steps_total", 0),
                    editorial_partial=partial,
                    analysis=partial,
                ),
                resume_analysis=job_checkpoint.get("editorial_partial") or job_checkpoint.get("analysis"),
            )
            analysis["editorial_consultado"] = True
            registrar_log(f"PROFILE cortes_com_contexto_editorial video={video_id} candidatos={len(analysis.get('candidatos', []))}")
        finally:
            analysis_heartbeat_stop.set()
            heartbeat_thread.join(timeout=1)
        _raise_if_cancelled(job_id)
        if analysis.get("status") == "failed":
            message = str((analysis.get("rejeicoes") or ["Geração interrompida: a IA não produziu candidatos editoriais suficientes."])[0])
            result = {"analysis": analysis, "cortes": []}
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=100, message=message, video_id=video_id, suggestions=[], diagnostics=analysis)
            update_job(job_id, status="failed", progress=100, message=message, result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
            return
        suggestions = analysis["cortes"]
        if not source_path:
            raise MediaToolError("Arquivo de origem não encontrado na mídia do perfil.")
        conn = get_connection()
        try:
            video_row = conn.execute("SELECT titulo FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).fetchone()
        finally:
            conn.close()
        video_title = video_row["titulo"] if video_row else video_id
        render_started_at = None

        def update_render_runtime(completed, total, message):
            nonlocal render_started_at
            if render_started_at is None:
                render_started_at = time.monotonic()
            render_elapsed = max(0, round(time.monotonic() - render_started_at))
            elapsed = max(0, round(time.monotonic() - job_started_at))
            eta_seconds = None
            if completed > 0 and total > completed:
                eta_seconds = max(1, round(render_elapsed * (total - completed) / completed))
            progress = 40 + round(completed / max(1, total) * 55)
            _update_runtime_job(
                CUT_JOBS,
                job_id,
                perfil_id,
                progress=progress,
                message=message,
                stage="rendering",
                rendered_index=completed,
                render_total=total,
                elapsed_seconds=elapsed,
                eta_seconds=eta_seconds,
                video_id=video_id,
            )

        if analysis["status"] != "completed":
            validar_ferramentas()
            persisted_candidates = []
            cycle_name = _cut_cycle_name(video_title, job_id)
            candidates = analysis.get("candidatos", [])
            total_candidates = len(candidates)
            for candidate_index, candidate in enumerate(candidates, start=1):
                update_render_runtime(candidate_index - 1, total_candidates, f"Renderizando corte local {candidate_index}/{total_candidates}")
                round_name = cycle_name
                cut_id = create_cut(job_id, video_id, source_path, candidate, perfil_id=perfil_id, status="candidato", video_title=video_title, round_name=round_name)
                output_name = f"{nome_seguro_arquivo(video_id)}_{cut_id}_{nome_seguro_arquivo(normalizar_titulo_corte(candidate.get('titulo')), 'candidato')}.mp4"
                output_path = os.path.join(obter_pastas_midia(perfil_id)["shorts"], output_name)
                try:
                    update_cut(cut_id, status="renderizando", perfil_id=perfil_id)
                    renderizar_corte(source_path, output_path, candidate["inicio"], candidate["fim"], intervalos=candidate.get("montagem_intervalos"), vertical=True)
                    recommendation_context = "\n".join(filter(None, [
                        f"Título original: {video_title}", f"Título do corte: {candidate.get('titulo', '')}",
                        f"Gancho: {candidate.get('gancho', '')}", f"Promessa: {candidate.get('promessa', '')}",
                        f"Virada: {candidate.get('virada', '')}", f"Conclusão: {candidate.get('conclusao', '')}",
                    ]))
                    update_cut_schedule_recommendation(cut_id, {"periodo": "noite", "dias_preferidos": [], "confianca": 0, "justificativa": "Horário local padrão; a IA editorial já foi consultada nesta execução."}, perfil_id=perfil_id)
                    publication_description = str(candidate.get("descricao_publicacao") or candidate.get("descricao") or "").strip()
                    if publication_description:
                        update_cut_metadata(cut_id, candidate.get("titulo", ""), publication_description, perfil_id=perfil_id)
                    update_cut(cut_id, status="concluido", output_path=output_path, perfil_id=perfil_id)
                    candidate_status = "concluido"
                except Exception as error:
                    update_cut(cut_id, status="falhou", error=str(error), perfil_id=perfil_id)
                    candidate_status = "falhou"
                update_render_runtime(candidate_index, total_candidates, f"Corte local {candidate_index}/{total_candidates} pronto")
                persisted_candidates.append({**candidate, "cut_id": cut_id, "descricao_publicacao": publication_description if candidate_status == "concluido" else "", "status": candidate_status, "output_path": output_path if candidate_status == "concluido" else "", "nome_rodada": round_name, "video_titulo": video_title})
            ai_unavailable = any(item.get("status") in {"timeout_or_network", "http_error", "provider_disabled", "editorial_unavailable"} for item in analysis.get("diagnostico", []))
            rendered_candidates = [candidate for candidate in persisted_candidates if candidate.get("status") == "concluido"]
            overlap_rejection = any("sobreposição com cortes existentes" in str(reason) for reason in analysis.get("rejeicoes", []))
            if overlap_rejection:
                prefix = "IA indisponível; candidatos locais descartados por sobreposição com cortes existentes. "
            else:
                prefix = "IA indisponível; fallback local concluído. " if ai_unavailable else ""
            message = f"{prefix}Revisão humana: {len(rendered_candidates)} candidato(s) renderizado(s); {len(suggestions)} aprovado(s) automaticamente pela IA."
            result = {"analysis": analysis, "cortes": persisted_candidates}
            review_status = "needs_review_fallback" if analysis.get("status") == "needs_review_fallback" else "needs_review"
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, status=review_status, progress=100, message=message, video_id=video_id, suggestions=persisted_candidates, diagnostics=analysis)
            update_job(job_id, status=review_status, progress=100, message=message, result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
            return
        validar_ferramentas()
        persisted = []
        cycle_name = _cut_cycle_name(video_title, job_id)
        total_suggestions = len(suggestions)
        for suggestion_index, suggestion in enumerate(suggestions, start=1):
            _raise_if_cancelled(job_id)
            update_render_runtime(suggestion_index - 1, total_suggestions, f"Renderizando corte {suggestion_index}/{total_suggestions}")
            existing = next(
                (
                    cut for cut in previous_cuts
                    if _arquivo_corte_disponivel(cut.get("caminho_saida"))
                    and abs(float(cut.get("inicio", 0)) - float(suggestion.get("inicio", 0))) < 0.05
                    and abs(float(cut.get("fim", 0)) - float(suggestion.get("fim", 0))) < 0.05
                ),
                None,
            )
            if existing:
                persisted.append({**suggestion, "cut_id": existing["id"], "output_path": existing["caminho_saida"], "status": "concluido", "retomado": True})
                update_render_runtime(suggestion_index, total_suggestions, f"Corte {suggestion_index}/{total_suggestions} já renderizado")
                continue
            cut_id = create_cut(job_id, video_id, source_path, suggestion, perfil_id=perfil_id, video_title=video_title, round_name=cycle_name)
            output_name = f"{nome_seguro_arquivo(video_id)}_{cut_id}_{nome_seguro_arquivo(normalizar_titulo_corte(suggestion.get('titulo')), 'corte')}.mp4"
            output_path = os.path.join(obter_pastas_midia(perfil_id)["shorts"], output_name)
            try:
                update_cut(cut_id, status="renderizando", perfil_id=perfil_id)
                renderizar_corte(source_path, output_path, suggestion["inicio"], suggestion["fim"], intervalos=suggestion.get("montagem_intervalos"), vertical=True)
                recommendation_context = "\n".join(filter(None, [
                    f"Título original: {video_title}", f"Título do corte: {suggestion.get('titulo', '')}",
                    f"Gancho: {suggestion.get('gancho', '')}", f"Promessa: {suggestion.get('promessa', '')}",
                    f"Virada: {suggestion.get('virada', '')}", f"Conclusão: {suggestion.get('conclusao', '')}",
                ]))
                update_cut_schedule_recommendation(cut_id, {"periodo": "noite", "dias_preferidos": [], "confianca": 0, "justificativa": "Horário local padrão; a IA editorial já foi consultada nesta execução."}, perfil_id=perfil_id)
                publication_description = _save_publication_description(cut_id, suggestion, perfil_id)
                update_cut(cut_id, status="concluido", output_path=output_path, perfil_id=perfil_id)
                persisted.append({**suggestion, "cut_id": cut_id, "descricao_publicacao": publication_description, "output_path": output_path, "status": "concluido"})
            except Exception as error:
                update_cut(cut_id, status="falhou", error=str(error), perfil_id=perfil_id)
                persisted.append({**suggestion, "cut_id": cut_id, "status": "falhou", "error": str(error)})
            update_render_runtime(suggestion_index, total_suggestions, f"Corte {suggestion_index}/{total_suggestions} pronto")
        all_failed = bool(persisted) and all(item.get("status") == "falhou" for item in persisted)
        final_status = "failed" if all_failed else "completed"
        final_message = "Nenhum corte pôde ser renderizado." if all_failed else "Cortes analisados e validados"
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, **{
            "status": final_status,
            "progress": 100,
            "message": final_message,
            "video_id": video_id,
            "suggestions": persisted,
        })
        update_job(job_id, status=final_status, progress=100, message=final_message, result=json.dumps({"analysis": analysis, "cortes": persisted}, ensure_ascii=False), perfil_id=perfil_id)
    except (JobCancelled, GenerationCancelled) as error:
        _cleanup_cancelled_job(job_id, perfil_id, video_id)
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
        update_job(job_id, status="cancelled", message=str(error), error=str(error), perfil_id=perfil_id)
    except Exception as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)

def _fallback_editorial_description(cut):
    title = re.sub(r"\s+", " ", str(cut.get("titulo") or "Corte do vídeo")).strip()
    try:
        inicio = max(0, int(round(float(cut.get("inicio", 0)))))
        fim = max(inicio, int(round(float(cut.get("fim", inicio)))))
        inicio_min, inicio_seg = divmod(inicio, 60)
        fim_min, fim_seg = divmod(fim, 60)
        intervalo = f"Trecho entre {inicio_min:02d}:{inicio_seg:02d} e {fim_min:02d}:{fim_seg:02d}."
    except (TypeError, ValueError):
        intervalo = "Trecho selecionado para revisão editorial."
    video_titulo = re.sub(r"\s+", " ", str(cut.get("video_titulo") or "")).strip()
    contexto = f" Contexto: {video_titulo}." if video_titulo else ""
    return f"{title}. {intervalo}{contexto}"


def _save_publication_description(cut_id, cut, perfil_id):
    description = str(cut.get("descricao_publicacao") or cut.get("descricao_sugerida") or cut.get("descricao") or "").strip()
    if not description:
        try:
            _, description, _ = _metadata_for_cut(cut)
        except Exception:
            description = ""
    if not description:
        description = _fallback_editorial_description(cut)
    update_cut_metadata(cut_id, cut.get("titulo", ""), description, perfil_id=perfil_id)
    return description


def _published_short_for_cut(cut, perfil_id):
    source_path = arquivo_publicacao_corte(cut)
    title = str(cut.get("titulo") or "").strip()
    description = str(cut.get("descricao_publicacao") or "").strip()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT video_id, status, titulo, descricao, arquivo_origem FROM videos_historico WHERE perfil_id=? AND tipo='short' AND status IN ('publicado_externo', 'programado') AND (arquivo_origem=? OR (? <> '' AND titulo=?) OR (? <> '' AND descricao=?)) ORDER BY atualizado_em DESC",
            (perfil_id, source_path, title, title, description, description),
        ).fetchall()
    finally:
        conn.close()
    for candidate in rows:
        try:
            youtube = _youtube_client(perfil_id)
            exists = youtube.videos().list(part="id", id=candidate["video_id"]).execute().get("items")
        except Exception:
            exists = []
        if exists:
            return dict(candidate)
    return None


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
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=round((index - 1) / len(cuts) * 100), message=f"Renderizando corte {index}/{len(cuts)}", stage="rendering", step_name="rendering", step_index=index, step_total=len(cuts))
            output_name = f"{nome_seguro_arquivo(cut['video_id'])}_{cut['id']}_{nome_seguro_arquivo(normalizar_titulo_corte(cut.get('titulo')), 'corte')}.mp4"
            output_path = os.path.join(output_dir, output_name)
            if cut.get("status") == "concluido" and _arquivo_corte_disponivel(cut.get("caminho_saida")):
                results.append({**cut, "status": "concluido", "output_path": cut["caminho_saida"], "retomado": True})
                continue
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
        _cleanup_cancelled_job(job_id, perfil_id)
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
    except Exception as error:
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))


def _run_caption_job(job_id, cut_id, style, font, size, position, stroke_color, stroke_size, perfil_id, style_id=None, style_config=None, primary_color="#FFFFFF", highlight_color="#FF0000", background_color="#000000", background_alpha=50, position_y=None, position_x=None, uma_linha=False):
    try:
        _raise_if_cancelled(job_id)
        if style_config:
            style = style_config["style"]
            font = style_config["font"]
            size = style_config["size"]
            position = style_config["position"]
            stroke_color = style_config["stroke_color"]
            stroke_size = style_config["stroke_size"]
            primary_color = style_config["primary_color"]
            highlight_color = style_config["highlight_color"]
            background_color = style_config["background_color"]
            background_alpha = style_config["background_alpha"]
            position_y = style_config.get("position_y")
            position_x = style_config.get("position_x")
            uma_linha = style_config.get("uma_linha", False)
        cut = next((item for item in list_cuts(perfil_id=perfil_id) if item["id"] == cut_id), None)
        if not cut:
            raise RuntimeError("Corte não encontrado para gerar legendas.")
        if style not in CAPTION_STYLES:
            raise ValueError(f"Estilo de legenda desconhecido: {style}")
        fontes_permitidas = list_caption_fonts(perfil_id)
        if font not in set(CAPTION_FONTS) | set(fontes_permitidas):
            raise ValueError(f"Fonte de legenda não permitida: {font}")
        size = int(size)
        if not 32 <= size <= 160:
            raise ValueError("O tamanho da legenda deve estar entre 32 e 160.")
        if position not in CAPTION_POSITIONS:
            raise ValueError(f"Posição de legenda desconhecida: {position}")
        if stroke_color not in CAPTION_STROKE_COLORS and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(stroke_color)):
            raise ValueError(f"Cor de stroke inválida: {stroke_color}.")
        if int(stroke_size) not in CAPTION_STROKE_WIDTHS:
            raise ValueError(f"Espessura de stroke inválida: {stroke_size}.")
        stroke_size = int(stroke_size)
        transcription = _fetch_transcription(cut["video_id"], perfil_id=perfil_id) or {}
        segments = transcription.get("segments") or []
        inicio_corte = float(cut["inicio_segundos"])
        fim_corte = float(cut["fim_segundos"])
        edited_segments = {int(segment["indice"]): segment for segment in list_cut_caption_transcript(cut_id, perfil_id=perfil_id)}
        for index, segment in enumerate(segments):
            segment_index = int(segment.get("indice", index))
            edited = edited_segments.get(segment_index)
            if edited is not None:
                segment["texto"] = edited["texto"]
                segment["palavras"] = []
                segment["words"] = []
        segments = [
            segment for segment in segments
            if float(segment.get("fim", segment.get("end", 0)) or 0) > inicio_corte
            and float(segment.get("inicio", segment.get("start", 0)) or 0) < fim_corte
        ]
        if not segments:
            raise RuntimeError("A transcrição do vídeo não possui segmentos para gerar legendas.")
        source_path = cut.get("caminho_saida") if cut.get("caminho_saida") and os.path.isfile(cut["caminho_saida"]) else cut.get("arquivo_origem")
        if not source_path or not os.path.isfile(source_path):
            raise RuntimeError("O arquivo do corte não foi encontrado no disco.")
        source_is_rendered_cut = source_path == cut.get("caminho_saida")
        render_start = 0.0 if source_is_rendered_cut else inicio_corte
        render_end = obter_duracao(source_path) if source_is_rendered_cut else fim_corte
        render_vertical = not source_is_rendered_cut
        render_intervals = None if source_is_rendered_cut else cut.get("montagem_intervalos")
        if source_is_rendered_cut:
            relative_segments = []
            for segment in segments:
                shifted = dict(segment)
                for start_key, end_key in (("inicio", "fim"), ("start", "end")):
                    if start_key in shifted:
                        shifted[start_key] = max(0.0, float(shifted[start_key]) - inicio_corte)
                    if end_key in shifted:
                        shifted[end_key] = max(0.0, float(shifted[end_key]) - inicio_corte)
                words = shifted.get("palavras") or shifted.get("words")
                if words:
                    shifted_words = []
                    for word in words:
                        shifted_word = dict(word)
                        for start_key, end_key in (("inicio", "fim"), ("start", "end")):
                            if start_key in shifted_word:
                                shifted_word[start_key] = max(0.0, float(shifted_word[start_key]) - inicio_corte)
                            if end_key in shifted_word:
                                shifted_word[end_key] = max(0.0, float(shifted_word[end_key]) - inicio_corte)
                        shifted_words.append(shifted_word)
                    if "palavras" in shifted:
                        shifted["palavras"] = shifted_words
                    if "words" in shifted:
                        shifted["words"] = shifted_words
                relative_segments.append(shifted)
            segments = relative_segments
        output_dir = obter_pastas_midia(perfil_id)["shorts"]
        output_name = (
            f"{nome_seguro_arquivo(cut['video_id'])}_{cut_id}_"
            f"{nome_seguro_arquivo(normalizar_titulo_corte(cut.get('titulo')), 'corte')}_legenda_{style}_{size}_{job_id[:8]}.mp4"
        )
        output_path = os.path.join(output_dir, output_name)
        snapshot = style_config or {"style_id": style_id or style, "style": style, "font": font, "size": size, "position": position, "stroke_color": stroke_color, "stroke_size": stroke_size, "animation": "none"}
        update_cut_caption(cut_id, style=style, font=font, size=size, position=position, stroke_color=stroke_color, stroke_size=stroke_size, style_id=style_id or style, config_json=json.dumps(snapshot, ensure_ascii=False), caption_path=output_path, status="renderizando", error=None, perfil_id=perfil_id)
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=10, message="Gerando arquivo de legendas", stage="captions")
        renderizar_corte(
            source_path,
            output_path,
            render_start,
            render_end,
            intervalos=render_intervals,
            vertical=render_vertical,
            legenda_segmentos=segments,
            legenda_estilo=style,
            legenda_titulo=cut.get("titulo") or "Growth Engine",
            legenda_fonte=font,
            legenda_tamanho=size,
            legenda_posicao=position,
            legenda_stroke_cor=stroke_color,
            legenda_stroke_tamanho=stroke_size,
            legenda_cor_texto=primary_color,
            legenda_cor_destaque=highlight_color,
            legenda_cor_fundo=background_color,
            legenda_opacidade_fundo=background_alpha,
            legenda_posicao_y=position_y,
            legenda_posicao_x=position_x,
            legenda_uma_linha=uma_linha,
            legenda_animacao=(style_config or {}).get("animation", "none"),
            legenda_diretorio_fontes=str(caption_fonts_dir(perfil_id)),
            legenda_fontes_permitidas=fontes_permitidas,
        )
        original_output = cut.get("caminho_saida")
        if original_output and os.path.isfile(original_output) and filecmp.cmp(output_path, original_output, shallow=False):
            raise RuntimeError("O renderizador produziu uma saída idêntica ao corte sem legendas.")
        update_cut_caption(cut_id, style=style, font=font, size=size, position=position, stroke_color=stroke_color, stroke_size=stroke_size, style_id=style_id or style, config_json=json.dumps(snapshot, ensure_ascii=False), caption_path=output_path, status="concluido", error=None, perfil_id=perfil_id)
        result = {"cut_id": cut_id, "style_id": style_id or style, "config": snapshot, "caption_output_path": output_path, "status": "concluido"}
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="completed", progress=100, message="Legendas geradas", result=result)
        update_job(job_id, status="completed", progress=100, message="Legendas geradas", result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
    except JobCancelled as error:
        update_cut_caption(cut_id, status="cancelado", error=str(error), perfil_id=perfil_id)
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
        update_job(job_id, status="cancelled", message=str(error), error=str(error), perfil_id=perfil_id)
    except Exception as error:
        update_cut_caption(cut_id, status="falhou", error=str(error), perfil_id=perfil_id)
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=0, message=str(error), error=str(error))
        update_job(job_id, status="failed", progress=0, message=str(error), error=str(error), perfil_id=perfil_id)


def _run_immediate_publish_job(job_id, cut_ids, perfil_id):
    published_ids = []
    try:
        cuts = [cut for cut in list_cuts(perfil_id=perfil_id) if cut["id"] in cut_ids]
        results = []
        criar_notificacao(
            "Postagem imediata iniciada",
            f"A fila recebeu {len(cuts)} corte(s). O resultado de cada envio aparecerá nas notificações.",
            perfil_id=perfil_id,
        )
        for index, cut in enumerate(cuts):
            _raise_if_cancelled(job_id)
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=round(index / len(cuts) * 100), message=f"Publicando corte {index + 1}/{len(cuts)} no YouTube")
            existing = _published_short_for_cut(cut, perfil_id)
            if existing:
                results.append({"cut_id": cut["id"], "youtube_id": existing["video_id"], "status": "already_published", "idempotent": True})
                continue
            published = publicar_corte_imediato(cut, perfil_id=perfil_id)
            published_ids.append(published["youtube_id"])
            conn = get_connection()
            try:
                conn.execute("""
                    INSERT INTO videos_historico
                    (video_id, titulo, descricao, tipo, status, data_publicacao, slot_hora, arquivo_origem, perfil_id,
                     related_video_id, related_video_title, related_video_status, atualizado_em)
                    VALUES (?, ?, ?, 'short', 'publicado_externo', ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(video_id) DO UPDATE SET
                        titulo=excluded.titulo, descricao=excluded.descricao, status='publicado_externo',
                        data_publicacao=excluded.data_publicacao, slot_hora=excluded.slot_hora,
                        arquivo_origem=excluded.arquivo_origem, perfil_id=excluded.perfil_id,
                        related_video_id=excluded.related_video_id, related_video_title=excluded.related_video_title,
                        related_video_status=excluded.related_video_status,
                        atualizado_em=CURRENT_TIMESTAMP
                """, (published["youtube_id"], published["titulo"], published["descricao"], published["date"], published["time"], arquivo_publicacao_corte(cut), perfil_id, cut.get("related_video_id"), cut.get("related_video_title"), "pendente" if cut.get("related_video_id") else "sem_relacao"))
                conn.commit()
            finally:
                conn.close()
            related_result = None
            if cut.get("related_video_id"):
                related_result = aplicar_video_relacionado(published["youtube_id"], cut["related_video_id"], perfil_id=perfil_id)
            criar_notificacao(
                "Short publicado no YouTube",
                f"{published['titulo']} foi publicado. Abrir: https://www.youtube.com/watch?v={published['youtube_id']} | Studio: https://studio.youtube.com/video/{published['youtube_id']}/edit",
                perfil_id=perfil_id,
            )
            results.append({"cut_id": cut["id"], "related_video": related_result, **published})
        result = {"published": results}
        message = f"{len(results)} corte(s) publicado(s) imediatamente no YouTube"
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="completed", progress=100, message=message, suggestions=results)
        update_job(job_id, status="completed", progress=100, message=message, result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
    except JobCancelled as error:
        _cleanup_cancelled_job(job_id, perfil_id)
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="cancelled", message=str(error))
        update_job(job_id, status="cancelled", message=str(error), perfil_id=perfil_id)
    except Exception as error:
        message = str(error)
        if published_ids:
            message = f"{message} O YouTube já aceitou {len(published_ids)} upload(s), mas o histórico local falhou ao registrar o resultado. IDs: {', '.join(published_ids)}. Não tente repostar esses cortes sem conferir o canal."
        criar_notificacao("Falha na postagem imediata", message, tipo="erro", perfil_id=perfil_id)
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="failed", progress=0, message=message, error=message)
        update_job(job_id, status="failed", progress=0, message=message, error=message, perfil_id=perfil_id)


def _run_publish_job(job_id, cut_ids, perfil_id, requested_slots=None, schedule_start_at=None):
    try:
        cuts = [cut for cut in list_cuts(perfil_id=perfil_id) if cut["id"] in cut_ids]
        slots = requested_slots or planejar_melhores_slots(len(cuts), perfil_id=perfil_id, cuts=cuts, start_at=schedule_start_at)
        if len(slots) != len(cuts):
            raise RuntimeError("Não foi possível encontrar slots futuros para todos os cortes.")
        results = []
        for index, cut in enumerate(cuts):
            _raise_if_cancelled(job_id)
            slot = slots[index]
            _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="running", progress=round(index / len(cuts) * 100), message=f"Enviando corte {index + 1}/{len(cuts)} para o YouTube")
            existing = _published_short_for_cut(cut, perfil_id)
            if existing:
                results.append({"cut_id": cut["id"], "youtube_id": existing["video_id"], "status": "already_scheduled", "idempotent": True})
                continue
            published = publicar_e_agendar_corte(cut, slot["date"], slot["time"], perfil_id=perfil_id)
            conn = get_connection()
            try:
                conn.execute("""
                    INSERT INTO videos_historico
                    (video_id, titulo, descricao, tipo, status, data_publicacao, slot_hora, arquivo_origem, perfil_id,
                     related_video_id, related_video_title, related_video_status, atualizado_em)
                    VALUES (?, ?, ?, 'short', 'programado', ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(video_id) DO UPDATE SET
                        titulo=excluded.titulo, descricao=excluded.descricao, status='programado',
                        data_publicacao=excluded.data_publicacao, slot_hora=excluded.slot_hora,
                        arquivo_origem=excluded.arquivo_origem, perfil_id=excluded.perfil_id,
                        related_video_id=excluded.related_video_id, related_video_title=excluded.related_video_title,
                        related_video_status=excluded.related_video_status,
                        atualizado_em=CURRENT_TIMESTAMP
                """, (published["youtube_id"], published["titulo"], published["descricao"], published["date"], published["time"], arquivo_publicacao_corte(cut), perfil_id, cut.get("related_video_id"), cut.get("related_video_title"), "pendente" if cut.get("related_video_id") else "sem_relacao"))
                conn.commit()
            finally:
                conn.close()
            related_result = None
            if cut.get("related_video_id"):
                related_result = aplicar_video_relacionado(published["youtube_id"], cut["related_video_id"], perfil_id=perfil_id)
            results.append({"cut_id": cut["id"], "related_video": related_result, **published})
        result = {"scheduled": results}
        message = f"{len(results)} corte(s) enviado(s) e agendado(s) no YouTube"
        _update_runtime_job(CUT_JOBS, job_id, perfil_id, status="completed", progress=100, message=message, suggestions=results)
        update_job(job_id, status="completed", progress=100, message=message, result=json.dumps(result, ensure_ascii=False), perfil_id=perfil_id)
    except JobCancelled as error:
        _cleanup_cancelled_job(job_id, perfil_id)
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
        sync_result = sincronizar_canal_youtube(channel_url, perfil_id=perfil_id, progress_callback=update_progress) or {}
        status.update({
            "status": "completed",
            "processed": sync_result.get("processed", status["total"]),
            "progress": 100,
            "eta_seconds": 0,
            "message": f"Sincronização concluída: {sync_result.get('videos', 0)} vídeos longos e {sync_result.get('shorts', 0)} Shorts encontrados.",
            "processed_videos": sync_result.get("videos", 0),
            "processed_shorts": sync_result.get("shorts", 0),
        })
    except Exception as error:
        status.update({"status": "failed", "message": str(error)})


def _run_content_analysis(perfil_id, video_ids=None):
    started_at = time.monotonic()
    status = _profile_status(CONTENT_STATUS, perfil_id, CONTENT_STATUS_DEFAULT)
    heartbeat_stop = threading.Event()
    heartbeat_eta = None
    atualizar_tarefa("content_analysis", status="running", processados=0, total=0, progresso=0, mensagem="Preparando análise de conteúdo", iniciado=True, perfil_id=perfil_id)
    status.update({"status": "running", "processed": 0, "total": 0, "progress": 0, "eta_seconds": None, "message": "Preparando análise de conteúdo"})

    def update_progress(processed, total, message):
        nonlocal heartbeat_eta
        elapsed = time.monotonic() - started_at
        if message.startswith("1."):
            current_video_progress = 0.2
        elif message.startswith("2."):
            current_video_progress = 0.55
        elif message.startswith("3."):
            current_video_progress = 0.85
        else:
            current_video_progress = 1.0 if processed else 0
        completed_units = processed + current_video_progress
        rate = completed_units / elapsed if completed_units and elapsed else 0
        eta_seconds = round(max(total - completed_units, 0) / rate) if rate else None
        heartbeat_eta = eta_seconds
        progress = round((completed_units / total) * 100, 1) if total else 0
        status.update({
            "processed": processed,
            "total": total,
            "progress": progress,
            "eta_seconds": eta_seconds,
            "message": message,
        })
        atualizar_tarefa("content_analysis", status="running", processados=processed, total=total, progresso=progress, mensagem=message, perfil_id=perfil_id)

    def refresh_eta():
        nonlocal heartbeat_eta
        while not heartbeat_stop.wait(1):
            if heartbeat_eta is not None and heartbeat_eta > 0:
                heartbeat_eta = max(1, heartbeat_eta - 1)
                status["eta_seconds"] = heartbeat_eta

    heartbeat = threading.Thread(target=refresh_eta, daemon=True)
    heartbeat.start()

    try:
        result = analisar_videos_longos(progress_callback=update_progress, perfil_id=perfil_id, video_ids=video_ids)
        status.update({"status": "completed", "processed": result["processados"], "progress": 100, "eta_seconds": 0, "message": "Análise de conteúdo concluída"})
        atualizar_tarefa("content_analysis", status="completed", processados=result["processados"], progresso=100, mensagem="Análise de conteúdo concluída", concluido=True, perfil_id=perfil_id)
    except Exception as error:
        status.update({"status": "failed", "message": str(error)})
        atualizar_tarefa("content_analysis", status="failed", mensagem=str(error), erro=str(error), concluido=True, perfil_id=perfil_id)
    finally:
        heartbeat_stop.set()


def _run_manual_video_analysis(video_id, perfil_id):
    key = f"{perfil_id}:{video_id}"
    status = MANUAL_ANALYSIS_STATUS[key]
    started_at = time.monotonic()
    heartbeat_stop = threading.Event()
    heartbeat = None

    def update(progress, message, eta_seconds=None):
        elapsed = time.monotonic() - started_at
        eta_seconds = eta_seconds if eta_seconds is not None else round(max(100 - progress, 0) * elapsed / progress) if progress else None
        status.update({"status": "running", "progress": progress, "message": message, "eta_seconds": eta_seconds})

    try:
        criar_notificacao("Análise refinada iniciada", f"A análise do vídeo {video_id} foi colocada em execução.", perfil_id=perfil_id)
        update(5, "Preparando vídeo")
        update(30, "Transcrevendo vídeo")
        update(75, "Gerando diagnóstico refinado", 60)

        def refresh_eta():
            remaining = 60
            while not heartbeat_stop.wait(1):
                remaining = max(1, remaining - 1)
                status.update({"status": "running", "progress": 75, "message": "Gerando diagnóstico refinado", "eta_seconds": remaining})

        heartbeat = threading.Thread(target=refresh_eta, daemon=True)
        heartbeat.start()
        analisar_video_individual(video_id, perfil_id)
        heartbeat_stop.set()
        update(100, "Análise concluída")
        status.update({"status": "completed", "eta_seconds": 0})
        criar_notificacao("Análise refinada concluída", f"A análise do vídeo {video_id} foi concluída e já está disponível na Biblioteca.", perfil_id=perfil_id)
    except Exception as error:
        heartbeat_stop.set()
        status.update({"status": "failed", "message": str(error), "eta_seconds": None})
        criar_notificacao("Falha na análise refinada", str(error), tipo="erro", perfil_id=perfil_id)


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
    started_at = time.monotonic()
    heartbeat_stop = threading.Event()
    stage_started_at = started_at
    stage_progress = 0
    stage_target = 100
    stage_eta = None
    status.update({"status": "running", "progress": 0, "eta_seconds": None, "message": "Preparando geração de ideias"})

    def update_progress(progress, message, eta_seconds=None):
        nonlocal stage_started_at, stage_progress, stage_target, stage_eta
        elapsed = time.monotonic() - started_at
        stage_started_at = time.monotonic()
        stage_progress = progress
        stage_target = {10: 25, 25: 40, 40: 78, 78: 100}.get(progress, 100)
        stage_eta = eta_seconds
        status.update({
            "progress": progress,
            "message": message,
            "eta_seconds": eta_seconds if eta_seconds is not None else round(max(100 - progress, 0) * elapsed / progress) if progress else None,
        })

    def refresh_progress():
        while not heartbeat_stop.wait(1):
            if stage_eta is None or stage_eta <= 0 or stage_target <= stage_progress:
                continue
            elapsed = time.monotonic() - stage_started_at
            fraction = min(0.95, elapsed / max(stage_eta, 1))
            status.update({
                "progress": round(stage_progress + (stage_target - stage_progress) * fraction, 1),
                "eta_seconds": max(1, round(stage_eta - elapsed)),
            })

    heartbeat = threading.Thread(target=refresh_progress, daemon=True)
    heartbeat.start()

    try:
        created = gerar_sugestoes_top15(perfil_id=perfil_id, progress_callback=update_progress)
        status.update({"status": "completed", "progress": 100, "eta_seconds": 0, "message": f"{len(created)} sugestões geradas"})
        criar_notificacao("Sugestões geradas", f"{len(created)} sugestões baseadas na Autópsia dos Top 15.", perfil_id=perfil_id)
    except Exception as error:
        status.update({"status": "failed", "eta_seconds": None, "message": str(error)})
        criar_notificacao("Falha ao gerar sugestões", str(error), tipo="erro", perfil_id=perfil_id)
    finally:
        heartbeat_stop.set()


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
            if parsed.path.startswith("/api/admin/"):
                try:
                    _require_admin(self)
                except PermissionError as error:
                    self._send_json({"error": str(error)}, status=403)
                    return
        if parsed.path == "/api/me":
            conn = get_connection()
            try:
                row = conn.execute("SELECT id, nome, is_admin FROM perfis WHERE id=? AND ativo=1", (self.request_profile_id,)).fetchone()
            finally:
                conn.close()
            self._send_json({"profile": dict(row), "is_admin": bool(row["is_admin"])})
            return
        if parsed.path == "/api/admin/status":
            self._send_json({"is_admin": True})
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
            created_profile_id = None
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
                account = {}
                try:
                    account = build("oauth2", "v2", credentials=credentials).userinfo().get().execute()
                    account_email = account.get("email", "")
                except Exception:
                    pass
                response = youtube.channels().list(part="snippet,statistics", mine=True).execute()
                canais = response.get("items", [])
                if not canais:
                    raise RuntimeError("A conta Google não possui um canal YouTube disponível.")
                canal = canais[0]
                snippet = canal.get("snippet", {})
                channel_statistics = canal.get("statistics", {})
                oauth_state = OAUTH_STATES[state]
                perfil_id = oauth_state.get("perfil_id")
                account_id = account.get("id", "")
                existing_account = get_connection()
                try:
                    existing = existing_account.execute("""
                        SELECT perfil_id FROM perfis_google
                        WHERE (? <> '' AND google_account_email = ?)
                           OR (? <> '' AND google_account_id = ?)
                        ORDER BY atualizado_em DESC LIMIT 1
                    """, (account_email, account_email, account_id, account_id)).fetchone()
                finally:
                    existing_account.close()
                if existing:
                    perfil_id = existing["perfil_id"]
                if not perfil_id:
                    perfil_id = create_profile(oauth_state.get("perfil_nome") or snippet.get("title", "Canal YouTube"))
                    created_profile_id = perfil_id
                avatar_url = snippet.get("thumbnails", {}).get("high", {}).get("url", "")
                expires_at = credentials.expiry.isoformat() if credentials.expiry else None
                salvar_perfil_google(
                    nome=snippet.get("title", "Canal YouTube"),
                    canal_url=f"https://www.youtube.com/channel/{canal['id']}",
                    canal_id=canal["id"],
                    canal_nome=snippet.get("title", ""),
                    google_account_id=account_id,
                    google_account_email=account_email,
                    avatar_url=avatar_url,
                    scopes=serializar_scopes(credentials.scopes),
                    access_token_ciphertext=cifrar_token(credentials.token),
                    refresh_token_ciphertext=cifrar_token(credentials.refresh_token) if credentials.refresh_token else None,
                    token_expira_em=expires_at,
                    perfil_id=perfil_id,
                )
                conn = get_connection()
                try:
                    current_metrics = conn.execute(
                        "SELECT inscritos, views_canal, videos_canal FROM perfis_google WHERE perfil_id=? AND canal_id=?",
                        (perfil_id, canal["id"]),
                    ).fetchone()
                    subscribers = channel_statistics.get("subscriberCount")
                    channel_views = channel_statistics.get("viewCount")
                    channel_videos = channel_statistics.get("videoCount")
                    conn.execute(
                        "UPDATE perfis_google SET inscritos=?, views_canal=?, videos_canal=?, atualizado_em=CURRENT_TIMESTAMP WHERE perfil_id=? AND canal_id=?",
                        (
                            int(subscribers) if subscribers is not None else current_metrics["inscritos"],
                            int(channel_views) if channel_views is not None else current_metrics["views_canal"],
                            int(channel_videos) if channel_videos is not None else current_metrics["videos_canal"],
                            perfil_id,
                            canal["id"],
                        ),
                    )
                    conn.commit()
                finally:
                    conn.close()
                del OAUTH_STATES[state]
                self.send_response(302)
                self.send_header("Location", "/?oauth=success")
                self.end_headers()
            except Exception as error:
                if created_profile_id:
                    try:
                        delete_profile(created_profile_id)
                    except Exception:
                        pass
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
        if parsed.path == "/api/editorial/dossier":
            video_id = parse_qs(parsed.query).get("video_id", [None])[0]
            if not video_id:
                self._send_json({"error": "video_id é obrigatório"}, status=400)
                return
            try:
                self._send_json({"video_id": video_id, "dossier": _get_editorial_dossier(video_id, self.request_profile_id)})
            except LookupError as error:
                self._send_json({"error": str(error)}, status=404)
            return
        if parsed.path == "/api/cuts/caption-transcript":
            try:
                cut_id = int(parse_qs(parsed.query).get("cut_id", [""])[0])
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut:
                    self._send_json({"error": "Corte não encontrado."}, status=404)
                    return
                self._send_json({"cut_id": cut_id, "segments": list_cut_caption_transcript(cut_id, perfil_id=self.request_profile_id)})
            except (ValueError, TypeError) as error:
                self._send_json({"error": f"Corte inválido: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts":
            video_id = parse_qs(parsed.query).get("video_id", [None])[0]
            repair_unavailable_completed_cuts(self.request_profile_id, video_id=video_id)
            source_ids = {str(video["id"]) for video in _fetch_cut_sources(self.request_profile_id)}
            cuts = list_cuts(video_id=video_id, perfil_id=self.request_profile_id)
            cuts = [cut for cut in cuts if str(cut.get("video_id") or "") in source_ids]
            self._send_json({"cortes": [_present_cut_score(cut) for cut in cuts]})
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
        if parsed.path == "/api/cuts/source-file":
            video_id = parse_qs(parsed.query).get("video_id", [""])[0]
            perfil_query = parse_qs(parsed.query).get("perfil_id", [""])[0]
            try:
                media_profile_id = int(perfil_query) if perfil_query else self.request_profile_id
            except (TypeError, ValueError):
                self.send_error(400, "Perfil inválido")
                return
            with get_connection() as conn:
                row = conn.execute("SELECT arquivo_origem FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, media_profile_id)).fetchone()
            source_path = row["arquivo_origem"] if row else ""
            if not source_path or not os.path.isfile(source_path):
                self.send_error(404, "Mídia original não disponível")
                return
            file_size = os.path.getsize(source_path)
            range_header = self.headers.get("Range", "")
            start, end = 0, file_size - 1
            if range_header.startswith("bytes="):
                first, _, last = range_header[6:].split(",", 1)[0].strip().partition("-")
                start = int(first) if first else max(file_size - int(last), 0)
                end = int(last) if first and last else end
                if start >= file_size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return
                end = min(end, file_size - 1)
            content_length = end - start + 1
            self.send_response(206 if range_header.startswith("bytes=") else 200)
            self.send_header("Content-Type", mimetypes.guess_type(source_path)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(content_length))
            if range_header.startswith("bytes="):
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.end_headers()
            with open(source_path, "rb") as media:
                media.seek(start)
                self.wfile.write(media.read(content_length))
            return
        if parsed.path == "/api/caption-styles":
            self._send_json({"styles": list_caption_styles(self.request_profile_id)})
            return
        if parsed.path == "/api/caption-fonts":
            self._send_json({"fonts": list_caption_fonts(self.request_profile_id)})
            return
        if parsed.path == "/api/cuts/file":
            cut_id = parse_qs(parsed.query).get("id", [""])[0]
            captioned = parse_qs(parsed.query).get("captions", ["0"])[0] == "1"
            try:
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if str(item["id"]) == cut_id), None)
                output_path = (cut.get("legenda_caminho") if captioned else cut.get("caminho_saida")) if cut else None
                if not cut or not output_path or not os.path.isfile(output_path):
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
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
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
        if parsed.path == "/api/transcription/export":
            video_id = parse_qs(parsed.query).get("video_id", [""])[0]
            transcription = _fetch_transcription(video_id, self.request_profile_id)
            if transcription is None:
                self.send_error(404, "Transcrição não encontrada")
                return
            content = _transcription_as_srt(transcription).encode("utf-8")
            filename = f"{nome_seguro_arquivo(transcription.get('title'), 'transcricao')}.srt"
            self.send_response(200)
            self.send_header("Content-Type", "application/x-subrip; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(content)
            return
        if parsed.path == "/api/transcription/summary":
            video_id = parse_qs(parsed.query).get("video_id", [""])[0]
            self._send_json(_content_summary(video_id, self.request_profile_id))
            return
        if parsed.path == "/api/publishing/scheduled":
            self._send_json({"videos": _fetch_scheduled(self.request_profile_id)})
            return
        if parsed.path == "/api/youtube/related-videos":
            query = parse_qs(parsed.query).get("q", [""])[0].strip()
            self._send_json({"videos": _fetch_related_videos(self.request_profile_id, query)})
            return
        if parsed.path == "/api/library/videos":
            params = parse_qs(parsed.query)
            tipo = params.get("tipo", [None])[0]
            query = params.get("q", [""])[0].strip()
            ordem = params.get("ordem", ["recent"])[0]
            self._send_json({"videos": _fetch_library_videos(self.request_profile_id, tipo=tipo, query=query, ordem=ordem)})
            return
        if parsed.path == "/api/library/video":
            video_id = parse_qs(parsed.query).get("video_id", [""])[0]
            detail = _video_detail(video_id, self.request_profile_id)
            if detail is None:
                self._send_json({"error": "Vídeo não encontrado"}, status=404)
            else:
                self._send_json(detail)
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
            cache = obter_status_analises(self.request_profile_id)
            self._send_json({**status, "persisted": obter_tarefa("content_analysis", self.request_profile_id), "cache": cache, "processing_video_ids": cache.get("processing_video_ids", [])})
            return
        if parsed.path == "/api/autopsy":
            self._send_json(_autopsy_payload(self.request_profile_id))
            return
        if parsed.path == "/api/content-analysis/video/status":
            video_id = parse_qs(parsed.query).get("video_id", [""])[0].strip()
            self._send_json(MANUAL_ANALYSIS_STATUS.get(f"{self.request_profile_id}:{video_id}", {"status": "idle", "progress": 0, "message": "Nenhuma análise manual executada", "eta_seconds": None}))
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

    def do_DELETE(self):
        parsed = urlparse(self.path)
        prefix = "/api/videos/"
        if not parsed.path.startswith(prefix):
            self.send_error(404, "Rota não encontrada")
            return
        video_id = unquote(parsed.path[len(prefix):].strip("/"))
        if not video_id or "/" in video_id:
            self._send_json({"error": "video_id inválido."}, status=400)
            return
        try:
            perfil_id = _request_profile_id(self)
            init_db()
            conn = get_connection()
            try:
                video = conn.execute(
                    "SELECT video_id, file_hash, arquivo_origem FROM videos_historico WHERE video_id=? AND perfil_id=?",
                    (video_id, perfil_id),
                ).fetchone()
                if not video:
                    self._send_json({"error": "Vídeo não encontrado neste perfil."}, status=404)
                    return
                active = conn.execute(
                    "SELECT COUNT(*) FROM tarefas_jobs WHERE video_id=? AND perfil_id=? AND status IN ('queued', 'running', 'cancelling')",
                    (video_id, perfil_id),
                ).fetchone()[0]
                if active:
                    self._send_json({"error": "Finalize ou cancele os jobs deste vídeo antes de excluí-lo."}, status=409)
                    return
                cuts = conn.execute(
                    "SELECT caminho_saida, arquivo_origem FROM cortes_gerados WHERE video_id=? AND perfil_id=?",
                    (video_id, perfil_id),
                ).fetchall()
                file_hashes = {str(video["file_hash"]).strip()} if video["file_hash"] else set()
                paths = {video["arquivo_origem"]} if video["arquivo_origem"] else set()
                paths.update(cut["caminho_saida"] for cut in cuts if cut["caminho_saida"])
                paths.update(cut["arquivo_origem"] for cut in cuts if cut["arquivo_origem"])
                conn.execute("BEGIN IMMEDIATE")
                for table in ("cortes_gerados", "tarefas_jobs", "analises_conteudo", "classificacoes_conteudo", "falhas_classificacao_conteudo"):
                    conn.execute(f"DELETE FROM {table} WHERE video_id=? AND perfil_id=?", (video_id, perfil_id))
                deleted = conn.execute("DELETE FROM videos_historico WHERE video_id=? AND perfil_id=?", (video_id, perfil_id)).rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            for store in (TRANSCRIPTION_JOBS, CUT_JOBS):
                for job_id, job in list(store.items()):
                    if str(job.get("video_id")) == video_id and int(job.get("perfil_id", perfil_id)) == perfil_id:
                        store.pop(job_id, None)
            removed_files = _remove_video_artifacts(perfil_id, video_id, file_hashes, paths)
            self._send_json({"deleted": bool(deleted), "video_id": video_id, "removed_files": removed_files})
        except (ValueError, TypeError) as error:
            self._send_json({"error": str(error)}, status=400)
        except Exception as error:
            registrar_log(f"Falha ao excluir vídeo {video_id}: {type(error).__name__}: {error}")
            self._send_json({"error": "Não foi possível excluir o vídeo."}, status=500)

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
            if parsed.path.startswith("/api/admin/"):
                try:
                    _require_admin(self)
                except PermissionError as error:
                    self._send_json({"error": str(error)}, status=403)
                    return
        if parsed.path == "/api/admin/clear-cache":
            try:
                self._send_json({"status": "ok", **_admin_clear_cache()})
            except Exception as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/admin/reset-jobs":
            try:
                self._send_json({"status": "ok", **_admin_reset_jobs()})
            except Exception as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/admin/clear-finished-jobs":
            try:
                self._send_json({"status": "ok", **_admin_clear_finished_jobs(self.request_profile_id)})
            except Exception as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/admin/vacuum-db":
            try:
                self._send_json({"status": "ok", **_admin_vacuum_db()})
            except Exception as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if parsed.path == "/api/admin/restart-server":
            try:
                self._send_json(_admin_restart_server())
            except Exception as error:
                self._send_json({"error": str(error)}, status=500)
            return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
            job_id = parsed.path.split("/")[-2]
            runtime_job = TRANSCRIPTION_JOBS.get(job_id) or CUT_JOBS.get(job_id)
            job = runtime_job if runtime_job and runtime_job.get("perfil_id") == self.request_profile_id else select_job(job_id, self.request_profile_id)
            if not job:
                self._send_json({"error": "Tarefa não encontrada"}, status=404)
                return
            if job.get("status") == "interrupted":
                update_job(
                    job_id,
                    status="cancelled",
                    message="Retomada descartada pelo usuário.",
                    perfil_id=self.request_profile_id,
                )
                _cleanup_cancelled_job(job_id, self.request_profile_id, job.get("video_id"))
                self._send_json({"job_id": job_id, "status": "cancelled", "message": "Retomada descartada."})
                return
            if job.get("status") in {"completed", "failed", "cancelled", "rejected", "needs_review", "needs_review_fallback", "cancelling"}:
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
        if parsed.path == "/api/profiles/disconnect":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                perfil_id = normalize_profile_id(payload.get("perfil_id"))
                conn = get_connection()
                try:
                    deleted = conn.execute("DELETE FROM perfis_google WHERE perfil_id=?", (perfil_id,)).rowcount
                    conn.commit()
                finally:
                    conn.close()
                self._send_json({"perfil_id": perfil_id, "disconnected": bool(deleted)})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Perfil inválido: {error}"}, status=400)
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
        if parsed.path == "/api/uploads/local-path":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("O corpo da requisição precisa ser um objeto JSON.")
                source = os.path.realpath(os.path.expanduser(str(payload.get("path") or "").strip()))
                if not source:
                    raise ValueError("Informe o caminho de um arquivo ou pasta local.")
                if os.path.isdir(source):
                    raise ValueError("Informe o caminho completo de um arquivo MP4 ou MKV, não de uma pasta.")
                if not os.path.isfile(source):
                    raise ValueError("O arquivo informado não existe.")
                if not source.lower().endswith((".mp4", ".mkv")):
                    raise ValueError("O arquivo local precisa ser MP4 ou MKV.")
                if os.path.getsize(source) <= 0:
                    raise ValueError("O arquivo local está vazio.")
                duracao_minima, duracao_maxima = _cut_duration_range(payload.get("duracao_minima"), payload.get("duracao_maxima"))
                job_id = uuid.uuid4().hex
                create_job(job_id, "upload_local", job_id, perfil_id=self.request_profile_id)
                _cancel_event(job_id)
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Arquivo local selecionado", "video_id": job_id, "perfil_id": self.request_profile_id, "source_path": source}
                if not TASK_RUNNER.submit("upload_local", _process_local_media_job, job_id, source, self.request_profile_id, duracao_minima, duracao_maxima, key=f"perfil:{self.request_profile_id}:upload:{job_id}"):
                    update_job(job_id, status="rejected", message="Fila de mídia indisponível", error="lock", perfil_id=self.request_profile_id)
                    self._send_json({"error": "Fila de mídia indisponível", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued", "source_path": source}, status=202)
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/transcription/upload-srt":
            temp_path = None
            try:
                video_id = self.headers.get("X-Video-Id", "").strip()
                if not video_id:
                    raise ValueError("Selecione um vídeo antes de enviar a transcrição.")
                content_type = self.headers.get("Content-Type", "")
                if not content_type.lower().startswith("multipart/form-data"):
                    raise ValueError("Use multipart/form-data com o campo file.")
                length = int(self.headers.get("Content-Length", "0"))
                temp_path = _receive_srt_upload(self, content_type, length, obter_pastas_midia(self.request_profile_id)["transcripts"])
                segments = _parse_srt(temp_path)
                if not segments:
                    raise ValueError("O SRT não possui blocos de legenda válidos.")
                duration = max(segment["fim"] for segment in segments)
                text = " ".join(segment["texto"] for segment in segments)
                conn = get_connection()
                try:
                    updated = conn.execute(
                        "UPDATE videos_historico SET transcricao=?, transcricao_segmentos=?, duracao_segundos=?, atualizado_em=CURRENT_TIMESTAMP WHERE video_id=? AND perfil_id=?",
                        (text, json.dumps(segments, ensure_ascii=False), round(duration), video_id, self.request_profile_id),
                    ).rowcount
                    conn.commit()
                finally:
                    conn.close()
                if not updated:
                    raise ValueError("Vídeo não encontrado no perfil atual.")
                self._send_json({"video_id": video_id, "segments": segments, "transcription": {"text": text, "segments": segments}})
            except (ValueError, OSError, UnicodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.remove(temp_path)
            return
        if parsed.path == "/api/downloads/force":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                url = str(payload.get("url", "")).strip()
                duracao_minima, duracao_maxima = _cut_duration_range(payload.get("duracao_minima"), payload.get("duracao_maxima"))
                video_id = _youtube_video_id(url)
                if not video_id:
                    self._send_json({"error": "Informe uma URL válida do YouTube."}, status=400)
                    return
                job_id = uuid.uuid4().hex
                create_job(job_id, "force_download", video_id, perfil_id=self.request_profile_id)
                _cancel_event(job_id)
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Download forçado na fila", "video_id": video_id, "perfil_id": self.request_profile_id, "url": url}
                if not TASK_RUNNER.submit("force_download", _force_download_job, job_id, url, self.request_profile_id, video_id, duracao_minima, duracao_maxima, key=f"media:{self.request_profile_id}:{video_id}"):
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
        if parsed.path == "/api/notifications/read-all":
            marcadas = marcar_todas_notificacoes_lidas(perfil_id=self.request_profile_id)
            self._send_json({**listar_notificacoes(perfil_id=self.request_profile_id), "marcadas": marcadas})
            return
        if parsed.path == "/api/notifications/clear-read":
            removidas = limpar_notificacoes_lidas(perfil_id=self.request_profile_id)
            self._send_json({**listar_notificacoes(perfil_id=self.request_profile_id), "removidas": removidas})
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
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            requested_ids = payload.get("video_ids")
            if not isinstance(requested_ids, list) or not requested_ids:
                self._send_json({"error": "Selecione pelo menos um vídeo para analisar."}, status=400)
                return
            video_ids = list(dict.fromkeys(str(video_id).strip() for video_id in requested_ids if str(video_id).strip()))
            if not video_ids:
                self._send_json({"error": "Selecione pelo menos um vídeo para analisar."}, status=400)
                return
            init_db()
            conn = get_connection()
            try:
                placeholders = ",".join("?" for _ in video_ids)
                valid_count = conn.execute(
                    f"SELECT COUNT(*) FROM videos_historico WHERE perfil_id=? AND tipo IN ('video', 'short') AND video_id IN ({placeholders})",
                    [self.request_profile_id, *video_ids],
                ).fetchone()[0]
            finally:
                conn.close()
            if valid_count != len(video_ids):
                self._send_json({"error": "Um ou mais vídeos não pertencem a este perfil."}, status=400)
                return
            status = _profile_status(CONTENT_STATUS, self.request_profile_id, CONTENT_STATUS_DEFAULT)
            if status["status"] == "running":
                self._send_json(status, status=202)
                return
            if not TASK_RUNNER.submit("content_analysis", _run_content_analysis, self.request_profile_id, video_ids, key=f"content_analysis:{self.request_profile_id}"):
                self._send_json(status, status=202)
                return
            self._send_json({"status": "running", "message": f"Análise de {len(video_ids)} vídeo(s) iniciada", "video_ids": video_ids}, status=202)
            return
        if parsed.path == "/api/content-analysis/video":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                video_id = str(payload.get("video_id", "")).strip()
                if not video_id:
                    raise ValueError("video_id é obrigatório.")
                init_db()
                conn = get_connection()
                try:
                    video_row = conn.execute(
                        "SELECT tipo FROM videos_historico WHERE video_id=? AND perfil_id=?",
                        (video_id, self.request_profile_id),
                    ).fetchone()
                finally:
                    conn.close()
                if not video_row:
                    self._send_json({"error": "Vídeo não encontrado neste perfil."}, status=404)
                    return
                if video_row["tipo"] != "video":
                    self._send_json({"error": "A análise refinada está disponível apenas para vídeos longos."}, status=400)
                    return
                key = f"{self.request_profile_id}:{video_id}"
                current = MANUAL_ANALYSIS_STATUS.get(key, {})
                if current.get("status") == "running":
                    self._send_json(current, status=202)
                    return
                MANUAL_ANALYSIS_STATUS[key] = {"status": "queued", "progress": 0, "message": "Análise na fila", "eta_seconds": None}
                criar_notificacao("Análise refinada na fila", f"A análise manual do vídeo {video_id} foi enfileirada.", perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit("manual_content_analysis", _run_manual_video_analysis, video_id, self.request_profile_id, key=f"manual_content_analysis:{key}"):
                    self._send_json(MANUAL_ANALYSIS_STATUS[key], status=202)
                    return
                self._send_json({"status": "queued", "video_id": video_id, "message": "Análise na fila"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            except Exception as error:
                self._send_json({"error": str(error)}, status=500)
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
        if parsed.path == "/api/transcription/review":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                video_id = str(body.get("video_id") or "").strip()
                decisions = body.get("decisions") or {}
                edits = body.get("edits") or {}
                if not video_id or not isinstance(decisions, dict) or not isinstance(edits, dict):
                    self._send_json({"error": "Vídeo e decisões são obrigatórios."}, status=400)
                    return
                transcription = _review_transcription(video_id, self.request_profile_id, decisions, edits=edits)
                editorial_job_id = _queue_editorial_after_transcription(video_id, self.request_profile_id)
                if editorial_job_id:
                    _delete_editorial_dossier(video_id, self.request_profile_id)
                self._send_json({"transcription": transcription, "editorial_job_id": editorial_job_id, "status": "queued" if editorial_job_id else "pending"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/transcription/clear-cache":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                video_id = body.get("video_id")
                if not video_id or not isinstance(video_id, str):
                    self._send_json({"error": "video_id é obrigatório"}, status=400)
                    return
                active = any(
                    str(job.get("video_id")) == video_id
                    and int(job.get("perfil_id", self.request_profile_id)) == self.request_profile_id
                    and job.get("status") in {"queued", "running", "cancelling"}
                    for job in TRANSCRIPTION_JOBS.values()
                )
                if active:
                    self._send_json({"error": "Finalize ou cancele a transcrição antes de limpar o cache."}, status=409)
                    return
                removed_files = _clear_transcription_cache(video_id, self.request_profile_id)
                self._send_json({"video_id": video_id, "cache_cleared": True, "removed_files": removed_files})
            except LookupError as error:
                self._send_json({"error": str(error)}, status=404)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Solicitação inválida: {error}"}, status=400)
            return
        if parsed.path == "/api/editorial/delete-dossier":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                video_id = body.get("video_id")
                if not video_id or not isinstance(video_id, str):
                    self._send_json({"error": "video_id é obrigatório"}, status=400)
                    return
                deleted = _delete_editorial_dossier(video_id, self.request_profile_id)
                self._send_json({"video_id": video_id, "deleted": deleted})
            except LookupError as error:
                self._send_json({"error": str(error)}, status=404)
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
        if parsed.path == "/api/cuts/related-video":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                cut_id = int(body.get("cut_id"))
                no_related_video = body.get("no_related_video") is True
                video_id = str(body.get("video_id") or "").strip()
                video_title = str(body.get("video_title") or "").strip()
                if not no_related_video and (len(video_id) != 11 or not video_title):
                    raise ValueError("Selecione um vídeo válido do canal.")
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut:
                    self._send_json({"error": "Corte não encontrado."}, status=404)
                    return
                video = None if no_related_video else next((item for item in _fetch_related_videos(self.request_profile_id) if item["video_id"] == video_id and item["eligible"]), None)
                if not no_related_video and not video:
                    raise ValueError("O vídeo relacionado não está disponível para seleção.")
                update_cut_related_video(cut_id, None if no_related_video else video_id, None if no_related_video else video["titulo"], perfil_id=self.request_profile_id, status="sem_relacao" if no_related_video else "pendente")
                criar_notificacao(
                    "Vídeo relacionado salvo" if video else "Corte sem vídeo relacionado",
                    f"O corte {cut_id} será relacionado ao vídeo “{video['titulo']}” após a publicação." if video else f"O corte {cut_id} será publicado sem vídeo relacionado.",
                    perfil_id=self.request_profile_id,
                )
                self._send_json({"cut_id": cut_id, "related_video_id": None if no_related_video else video_id, "related_video_title": None if no_related_video else video["titulo"], "status": "sem_relacao" if no_related_video else "pendente"})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
            return
        if parsed.path == "/api/library/related-video":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                short_video_id = str(body.get("short_video_id") or "").strip()
                no_related_video = body.get("no_related_video") is True
                related_video_id = str(body.get("related_video_id") or "").strip()
                if len(short_video_id) != 11:
                    raise ValueError("ID do Short inválido.")
                if not no_related_video:
                    _validar_ids_video_relacionado(short_video_id, related_video_id)
                related = next((item for item in _fetch_related_videos(self.request_profile_id) if item["video_id"] == related_video_id and item["eligible"]), None) if not no_related_video else None
                if not no_related_video and not related:
                    raise ValueError("O vídeo relacionado não está disponível para seleção.")
                conn = get_connection()
                try:
                    updated = conn.execute("""
                        UPDATE videos_historico
                        SET related_video_id=?, related_video_title=?, related_video_status=?,
                            related_video_error=NULL, related_video_updated_at=CURRENT_TIMESTAMP,
                            atualizado_em=CURRENT_TIMESTAMP
                        WHERE perfil_id=? AND video_id=? AND tipo='short'
                    """, (None if no_related_video else related_video_id, None if no_related_video else related["titulo"], "sem_relacao" if no_related_video else "pendente", self.request_profile_id, short_video_id)).rowcount
                    conn.commit()
                finally:
                    conn.close()
                if not updated:
                    self._send_json({"error": "Short não encontrado na Biblioteca."}, status=404)
                    return
                if no_related_video:
                    self._send_json({"short_video_id": short_video_id, "related_video_id": None, "related_video_title": None, "status": "sem_relacao"})
                    return
                if not TASK_RUNNER.submit(
                    "related_video_apply",
                    aplicar_video_relacionado,
                    short_video_id,
                    related_video_id,
                    self.request_profile_id,
                    key=f"related-video:{self.request_profile_id}:{short_video_id}",
                ):
                    self._send_json({"error": "Este Short já possui uma aplicação em execução."}, status=409)
                    return
                criar_notificacao(
                    "Vídeo relacionado em processamento",
                    f"A relação do Short “{short_video_id}” com “{related['titulo']}” foi enviada ao YouTube Studio.",
                    perfil_id=self.request_profile_id,
                )
                self._send_json({"short_video_id": short_video_id, "related_video_id": related_video_id, "related_video_title": related["titulo"], "status": "aplicando"})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
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
        if parsed.path == "/api/cuts/metadata":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                cut_id = int(body.get("cut_id"))
                title = str(body.get("title") or "").strip()
                description = str(body.get("description") or "").strip()
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut:
                    self._send_json({"error": "Corte não encontrado."}, status=404)
                    return
                title = refinar_titulo_corte(title, cut.get("gancho"), limite=100)
                if _titulo_generico(title):
                    context = " ".join(filter(None, (cut.get("gancho"), cut.get("promessa"), cut.get("virada"), cut.get("conclusao"))))
                    title = refinar_titulo_corte(_titulo_editorial_local(context), cut.get("gancho"), limite=100)
                if not title:
                    self._send_json({"error": "Informe um título para o corte."}, status=400)
                    return
                if len(title) > 100:
                    self._send_json({"error": "O título pode ter no máximo 100 caracteres."}, status=400)
                    return
                update_cut_metadata(cut_id, title, description, perfil_id=self.request_profile_id)
                self._send_json({"cut_id": cut_id, "titulo": title, "descricao_publicacao": description})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Metadados inválidos: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/caption-transcript":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                cut_id = int(body.get("cut_id"))
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut:
                    self._send_json({"error": "Corte não encontrado."}, status=404)
                    return
                transcription = _fetch_transcription(cut["video_id"], perfil_id=self.request_profile_id) or {}
                inicio_corte = float(cut["inicio_segundos"])
                fim_corte = float(cut["fim_segundos"])
                source_segments = [
                    (index, segment) for index, segment in enumerate(transcription.get("segments") or [])
                    if float(segment.get("fim", segment.get("end", 0)) or 0) > inicio_corte
                    and float(segment.get("inicio", segment.get("start", 0)) or 0) < fim_corte
                ]
                source_by_index = {int(segment.get("indice", index)): segment for index, segment in source_segments}
                submitted = {int(item["indice"]): str(item.get("texto") or "").strip() for item in body.get("segments", [])}
                if set(submitted) != set(source_by_index):
                    raise ValueError("A transcrição recebida não corresponde aos segmentos deste corte.")
                edited_segments = []
                for segment_index, source in source_by_index.items():
                    text = submitted[segment_index]
                    if not text or len(text) > 2000:
                        raise ValueError("Cada segmento precisa ter entre 1 e 2000 caracteres.")
                    edited_segments.append({
                        "indice": segment_index,
                        "inicio": float(source.get("inicio", source.get("start", 0)) or 0),
                        "fim": float(source.get("fim", source.get("end", 0)) or 0),
                        "texto": text,
                    })
                saved = save_cut_caption_transcript(cut_id, edited_segments, perfil_id=self.request_profile_id)
                self._send_json({"cut_id": cut_id, "segments": saved, "saved": True})
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Transcrição inválida: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/replace-cycle-metadata":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                job_id = str(body.get("job_id") or "").strip()
                source = str(body.get("source") or "").strip()
                replacement = str(body.get("replacement") or "").strip()
                if not job_id:
                    raise ValueError("O ciclo de cortes é obrigatório.")
                if len(source) > 200 or len(replacement) > 200:
                    raise ValueError("A palavra ou substituição pode ter no máximo 200 caracteres.")
                result = replace_cut_cycle_metadata(job_id, source, replacement, perfil_id=self.request_profile_id)
                self._send_json({"job_id": job_id, **result})
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Substituição inválida: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/regenerate-metadata":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                cut_id = int(body.get("cut_id"))
                field = str(body.get("field") or "").strip().lower()
                if field not in {"title", "description"}:
                    raise ValueError("Escolha se deseja regenerar o título ou a descrição.")
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut:
                    self._send_json({"error": "Corte não encontrado."}, status=404)
                    return
                source = {**cut, "titulo": "", "titulo_sugerido": "", "descricao_publicacao": "", "descricao_sugerida": ""}
                title, description, _ = _metadata_for_cut(source)
                value = title if field == "title" else description
                if not value:
                    raise RuntimeError(f"A IA não retornou {('um título' if field == 'title' else 'uma descrição')} válido.")
                update_cut_metadata(
                    cut_id,
                    value if field == "title" else cut.get("titulo", ""),
                    value if field == "description" else cut.get("descricao_publicacao", ""),
                    perfil_id=self.request_profile_id,
                )
                self._send_json({"cut_id": cut_id, "field": field, "value": value})
            except (ValueError, TypeError, RuntimeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Não foi possível regenerar o metadado: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/generate-descriptions":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                cut_ids = sorted({int(cut_id) for cut_id in body.get("cut_ids", [])})
                cuts = [cut for cut in list_cuts(perfil_id=self.request_profile_id) if cut["id"] in cut_ids]
                generated = []
                for cut in cuts:
                    if cut.get("descricao_publicacao"):
                        continue
                    description = _save_publication_description(cut["id"], cut, self.request_profile_id)
                    if description:
                        generated.append({"cut_id": cut["id"], "descricao_publicacao": description})
                self._send_json({"generated": generated})
            except (ValueError, TypeError, RuntimeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Não foi possível gerar as descrições: {error}"}, status=400)
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
                schedule_start_at = str(body.get("start_at") or "").strip() or None
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut or cut.get("status") != "concluido" or not cut.get("caminho_saida"):
                    self._send_json({"error": "O corte precisa estar renderizado antes do agendamento."}, status=400)
                    return
                if not _arquivo_corte_disponivel(cut["caminho_saida"]):
                    self._send_json({"error": "O arquivo de vídeo não foi encontrado no disco."}, status=400)
                    return
                requested_slots = [{"date": date, "time": slot}] if date and slot else None
                job_id = uuid.uuid4().hex
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Publicação na fila", "cut_ids": [cut_id], "perfil_id": self.request_profile_id}
                _cancel_event(job_id)
                create_job(job_id, "cut_publish", cut["video_id"], perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit("cut_publish", _run_publish_job, job_id, [cut_id], self.request_profile_id, requested_slots, schedule_start_at, key=f"cut-publish:{self.request_profile_id}:{cut_id}"):
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
                schedule_start_at = str(body.get("start_at") or "").strip() or None
                if not cut_ids:
                    self._send_json({"error": "Selecione ao menos um corte."}, status=400)
                    return
                cuts = [cut for cut in list_cuts(perfil_id=self.request_profile_id) if cut["id"] in cut_ids]
                unavailable = [cut["id"] for cut in cuts if cut.get("status") != "concluido" or not cut.get("caminho_saida")]
                unavailable.extend(cut["id"] for cut in cuts if cut.get("caminho_saida") and not _arquivo_corte_disponivel(cut["caminho_saida"]))
                if len(cuts) != len(cut_ids) or unavailable:
                    error = "O arquivo de vídeo não foi encontrado no disco." if unavailable else "Todos os cortes precisam estar renderizados antes do agendamento."
                    self._send_json({"error": error, "unavailable": unavailable}, status=400)
                    return
                requested_slots = ([{"date": date, "time": slot}] * len(cuts)) if date and slot else None
                job_id = uuid.uuid4().hex
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Publicação em massa na fila", "cut_ids": cut_ids, "perfil_id": self.request_profile_id}
                _cancel_event(job_id)
                create_job(job_id, "cut_publish", cuts[0]["video_id"], perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit("cut_publish", _run_publish_job, job_id, cut_ids, self.request_profile_id, requested_slots, schedule_start_at, key=f"bulk-publish:{self.request_profile_id}"):
                    self._send_json({"error": "Já existe uma publicação em massa em execução.", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Agendamento em massa inválido: {error}"}, status=400)
            return
        if parsed.path == "/api/cuts/publish-now-bulk":
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                cut_ids = sorted({int(cut_id) for cut_id in body.get("cut_ids", [])})
                if not cut_ids:
                    self._send_json({"error": "Selecione ao menos um corte."}, status=400)
                    return
                cuts = [cut for cut in list_cuts(perfil_id=self.request_profile_id) if cut["id"] in cut_ids]
                unavailable = [cut["id"] for cut in cuts if cut.get("status") != "concluido" or not cut.get("caminho_saida")]
                unavailable.extend(cut["id"] for cut in cuts if cut.get("caminho_saida") and not _arquivo_corte_disponivel(cut["caminho_saida"]))
                if len(cuts) != len(cut_ids) or unavailable:
                    error = "O arquivo de vídeo não foi encontrado no disco." if unavailable else "Todos os cortes precisam estar renderizados antes da postagem."
                    self._send_json({"error": error, "unavailable": unavailable}, status=400)
                    return
                job_id = uuid.uuid4().hex
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Postagem imediata na fila", "cut_ids": cut_ids, "perfil_id": self.request_profile_id}
                _cancel_event(job_id)
                create_job(job_id, "cut_publish_now", cuts[0]["video_id"], perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit("cut_publish_now", _run_immediate_publish_job, job_id, cut_ids, self.request_profile_id, key=f"bulk-publish-now:{self.request_profile_id}"):
                    self._send_json({"error": "Já existe uma fila de postagem em execução.", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Postagem imediata inválida: {error}"}, status=400)
            return
        if parsed.path == "/api/caption-styles/import":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                style_config = import_caption_style(payload, perfil_id=self.request_profile_id)
                self._send_json({"style": style_config}, status=201)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Estilo de legenda inválido: {error}"}, status=400)
            return
        if parsed.path == "/api/caption-fonts/import":
            temporary_path = None
            try:
                length = int(self.headers.get("Content-Length", "0"))
                content_type = self.headers.get("Content-Type", "")
                if not content_type.lower().startswith("multipart/form-data"):
                    raise ValueError("Use multipart/form-data com o campo file.")
                temporary_path, filename = _receive_font_upload(self, content_type, length, str(caption_fonts_dir(self.request_profile_id)))
                result = store_caption_font(temporary_path, filename, self.request_profile_id)
                self._send_json({"font": result}, status=201)
            except (ValueError, OSError) as error:
                self._send_json({"error": f"Fonte inválida: {error}"}, status=400)
            finally:
                if temporary_path and os.path.exists(temporary_path):
                    os.remove(temporary_path)
            return
        if parsed.path == "/api/cuts/generate-captions":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                cut_id = int(body.get("cut_id"))
                style_id = str(body.get("style_id") or body.get("style") or "clean").strip().lower()
                stored_config = get_caption_style(style_id, perfil_id=self.request_profile_id)
                style_config = validate_style_config({**stored_config, **{key: body[key] for key in ("style", "font", "size", "position", "stroke_color", "stroke_size", "primary_color", "highlight_color", "background_color", "background_alpha", "position_y", "position_x", "uma_linha") if key in body}, "style_id": style_id}, perfil_id=self.request_profile_id)
                style = style_config["style"]
                font = style_config["font"]
                size = style_config["size"]
                position = style_config["position"]
                stroke_color = style_config["stroke_color"]
                stroke_size = style_config["stroke_size"]
                primary_color = style_config["primary_color"]
                highlight_color = style_config["highlight_color"]
                background_color = style_config["background_color"]
                background_alpha = style_config["background_alpha"]
                position_y = style_config.get("position_y")
                position_x = style_config.get("position_x")
                uma_linha = style_config.get("uma_linha", False)
                cut = next((item for item in list_cuts(perfil_id=self.request_profile_id) if item["id"] == cut_id), None)
                if not cut:
                    self._send_json({"error": "Corte não encontrado."}, status=404)
                    return
                job_id = uuid.uuid4().hex
                cut_duration_seconds = max(1, float(cut["fim_segundos"]) - float(cut["inicio_segundos"]))
                rendered_cut_available = bool(cut.get("caminho_saida") and os.path.isfile(cut["caminho_saida"]))
                estimated_duration_seconds = max(45, round(cut_duration_seconds * (1.5 if rendered_cut_available else 5.3)))
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Geração de legendas na fila", "video_id": cut["video_id"], "estimated_duration_seconds": estimated_duration_seconds}
                _cancel_event(job_id)
                create_job(job_id, "caption_render", cut["video_id"], perfil_id=self.request_profile_id)
                update_job(job_id, perfil_id=self.request_profile_id, checkpoint={"kind": "captions", "cut_id": cut_id, "cut_ids": [cut_id], "style_id": style_id, "estimated_duration_seconds": estimated_duration_seconds})
                if not TASK_RUNNER.submit("caption_render", _run_caption_job, job_id, cut_id, style, font, size, position, stroke_color, stroke_size, self.request_profile_id, style_id, style_config, primary_color, highlight_color, background_color, background_alpha, position_y, position_x, uma_linha, key=f"caption-render:{self.request_profile_id}:{cut_id}"):
                    self._send_json({"error": "Este corte já possui uma geração de legendas em execução.", "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "cut_id": cut_id, "style_id": style_id, "style": style_config, "status": "queued", "estimated_duration_seconds": estimated_duration_seconds}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Geração de legendas inválida: {error}"}, status=400)
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
        if parsed.path == "/api/editorial/generate":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                video_id = body.get("video_id")
                duracao_minima, duracao_maxima = _cut_duration_range(body.get("duracao_minima"), body.get("duracao_maxima"))
                if not video_id:
                    self._send_json({"error": "video_id é obrigatório."}, status=400)
                    return
                job_id = uuid.uuid4().hex
                CUT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Editorial na fila", "video_id": video_id}
                _cancel_event(job_id)
                create_job(job_id, "editorial", video_id, perfil_id=self.request_profile_id)
                if not TASK_RUNNER.submit("editorial", _run_editorial_job, job_id, video_id, self.request_profile_id, duracao_minima, duracao_maxima, key=f"editorial:{self.request_profile_id}:{video_id}"):
                    message = "Este vídeo já possui uma tarefa editorial em execução."
                    CUT_JOBS[job_id].update({"status": "rejected", "message": message})
                    update_job(job_id, status="rejected", message=message, perfil_id=self.request_profile_id)
                    self._send_json({"error": message, "job_id": job_id}, status=409)
                    return
                self._send_json({"job_id": job_id, "status": "queued", "kind": "editorial"}, status=202)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._send_json({"error": f"Solicitação editorial inválida: {error}"}, status=400)
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
    _resume_interrupted_jobs()
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
