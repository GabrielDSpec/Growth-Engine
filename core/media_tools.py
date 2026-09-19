import os
import shutil
import subprocess
from pathlib import Path

from core.config import DIRETORIO_PROJETO


class MediaToolError(RuntimeError):
    pass


def _resolve_tool(name):
    local = Path(DIRETORIO_PROJETO) / f"{name}.exe"
    return str(local) if local.exists() else shutil.which(name)


def localizar_ferramentas():
    ffmpeg = _resolve_tool("ffmpeg")
    ffprobe = _resolve_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise MediaToolError("FFmpeg e FFprobe precisam estar disponíveis.")
    return ffmpeg, ffprobe


def _run(command, timeout):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise MediaToolError(f"Processo excedeu o timeout de {timeout}s.") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "sem detalhes").strip()[-1000:]
        raise MediaToolError(f"Processo retornou {result.returncode}: {detail}")
    return result


def validar_ferramentas(timeout=10):
    ffmpeg, ffprobe = localizar_ferramentas()
    _run([ffmpeg, "-version"], timeout)
    _run([ffprobe, "-version"], timeout)
    return {"ffmpeg": ffmpeg, "ffprobe": ffprobe}


def obter_duracao(caminho, timeout=30):
    _, ffprobe = localizar_ferramentas()
    if not os.path.isfile(caminho):
        raise MediaToolError("Arquivo de origem não encontrado.")
    result = _run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", caminho], timeout)
    try:
        duration = float(result.stdout.strip())
    except ValueError as error:
        raise MediaToolError("FFprobe não retornou duração válida.") from error
    if duration <= 0:
        raise MediaToolError("Arquivo sem duração válida.")
    return duration


def renderizar_corte(caminho_origem, caminho_saida, inicio, fim, filtro=None, timeout=600):
    ffmpeg, _ = localizar_ferramentas()
    duration = obter_duracao(caminho_origem)
    if not 0 <= float(inicio) < float(fim) <= duration:
        raise MediaToolError("Timestamps do corte estão fora da duração do arquivo.")
    os.makedirs(os.path.dirname(caminho_saida), exist_ok=True)
    command = [ffmpeg, "-y", "-ss", str(inicio), "-to", str(fim), "-i", caminho_origem]
    if filtro:
        command.extend(["-vf", filtro])
    command.extend(["-c:v", "libx264", "-c:a", "aac", caminho_saida])
    try:
        _run(command, timeout)
    except Exception:
        if os.path.exists(caminho_saida):
            os.remove(caminho_saida)
        raise
    if not os.path.isfile(caminho_saida) or os.path.getsize(caminho_saida) <= 0:
        raise MediaToolError("FFmpeg não produziu um arquivo final válido.")
    return caminho_saida
