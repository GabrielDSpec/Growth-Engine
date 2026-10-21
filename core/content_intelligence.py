from core.autopsia import _analisar_video_individual
from core.content_analysis_repository import (
    mark_processing,
    save_failure,
    save_result,
    select_analysis_status,
    select_pending_long_videos,
)
from core.database import get_connection, init_db
from core.transcriber import transcrever_video_youtube


def analisar_videos_longos(progress_callback=None, limite=None, perfil_id=1, video_ids=None):
    if video_ids:
        init_db()
        conn = get_connection()
        try:
            placeholders = ",".join("?" for _ in video_ids)
            rows = conn.execute(
                f"""
                SELECT video_id, titulo, descricao, data_publicacao, tipo, views, likes, transcricao
                FROM videos_historico
                WHERE perfil_id = ? AND tipo IN ('video', 'short')
                  AND video_id IN ({placeholders})
                ORDER BY CASE WHEN tipo = 'video' THEN 0 ELSE 1 END,
                         CAST(COALESCE(views, 0) AS INTEGER) DESC
                """,
                [perfil_id, *video_ids],
            ).fetchall()
        finally:
            conn.close()
    else:
        rows = select_pending_long_videos(limite, perfil_id)

    total = len(rows)
    if progress_callback:
        progress_callback(0, total, f"Fila de análise preparada: {total} vídeo(s) pendente(s)")
    for indice, row in enumerate(rows, 1):
        video = dict(row)
        video_id = video["video_id"]
        mark_processing(video_id, perfil_id)
        try:
            if progress_callback:
                progress_callback(indice - 1, total, f"1. A extrair métricas e transcrever vídeo {indice}/{total}")
            if not video.get("transcricao"):
                video["transcricao"] = transcrever_video_youtube(video_id, perfil_id=perfil_id)
            if progress_callback:
                progress_callback(indice - 1, total, f"2. A analisar a transcrição do vídeo {indice}/{total}")
            resultado = _analisar_video_individual(video)
            status = "concluida" if not resultado.get("erro") else "falhou"
            erro = resultado.get("erro")
            save_result(video_id, status, resultado, erro, perfil_id)
            if progress_callback:
                progress_callback(indice, total, f"3. A cruzar padrões de retenção do vídeo {indice}/{total}")
        except Exception as error:
            save_failure(video_id, error, perfil_id)
        if progress_callback:
            progress_callback(indice, total, f"Analisando vídeo longo {indice}/{total}")

    return {"processados": total, "status": "concluida"}


def analisar_video_individual(video_id, perfil_id=1):
    init_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT video_id, titulo, descricao, data_publicacao, tipo, views, likes, transcricao FROM videos_historico WHERE video_id=? AND perfil_id=?",
            (video_id, perfil_id),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError("Vídeo não encontrado para este perfil.")
    video = dict(row)
    mark_processing(video_id, perfil_id)
    try:
        if video.get("tipo") != "video":
            raise ValueError("A análise refinada está disponível apenas para vídeos longos.")
        if not video.get("transcricao"):
            video["transcricao"] = transcrever_video_youtube(video_id, perfil_id=perfil_id)
        resultado = _analisar_video_individual(video)
        status = "concluida" if not resultado.get("erro") else "falhou"
        save_result(video_id, status, resultado, resultado.get("erro"), perfil_id)
        return resultado
    except Exception as error:
        save_failure(video_id, error, perfil_id)
        raise


def obter_status_analises(perfil_id=1):
    return select_analysis_status(perfil_id)