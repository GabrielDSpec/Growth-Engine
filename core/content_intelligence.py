from core.autopsia import _analisar_video_individual
from core.content_analysis_repository import (
    mark_processing,
    save_failure,
    save_result,
    select_analysis_status,
    select_pending_long_videos,
)
from core.transcriber import transcrever_video_youtube


def analisar_videos_longos(progress_callback=None, limite=None, perfil_id=1):
    rows = select_pending_long_videos(limite, perfil_id)

    total = len(rows)
    if progress_callback:
        progress_callback(0, total, f"Fila de análise preparada: {total} vídeo(s) pendente(s)")
    for indice, row in enumerate(rows, 1):
        video = dict(row)
        video_id = video["video_id"]
        mark_processing(video_id, perfil_id)
        try:
            if not video.get("transcricao"):
                video["transcricao"] = transcrever_video_youtube(video_id, perfil_id=perfil_id)
            resultado = _analisar_video_individual(video)
            status = "concluida" if not resultado.get("erro") else "falhou"
            erro = resultado.get("erro")
            save_result(video_id, status, resultado, erro, perfil_id)
        except Exception as error:
            save_failure(video_id, error, perfil_id)
        if progress_callback:
            progress_callback(indice, total, f"Analisando vídeo longo {indice}/{total}")

    return {"processados": total, "status": "concluida"}


def obter_status_analises(perfil_id=1):
    return select_analysis_status(perfil_id)