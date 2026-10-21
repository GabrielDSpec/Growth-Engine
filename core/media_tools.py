import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from core.config import DIRETORIO_PROJETO
from core.utils import registrar_log


class MediaToolError(RuntimeError):
    pass


def arquivo_media_valido(caminho):
    try:
        return bool(caminho) and os.path.isfile(caminho) and os.path.getsize(caminho) > 0
    except OSError:
        return False


def nome_seguro_arquivo(nome, fallback="corte", limite=100):
    """Remove caracteres que impedem a criação de arquivos no Windows."""
    valor = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", str(nome or ""))
    valor = re.sub(r"\s+", " ", valor).strip(" .")
    return valor[:limite].rstrip(" .") or fallback


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
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
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


def _filtro_vertical(caminho_origem, inicio, fim):
    try:
        from core.cutter import calcular_corte_com_rosto
        return calcular_corte_com_rosto(caminho_origem, inicio, fim)
    except Exception:
        return "crop=ih*9/16:ih:(iw-ih*9/16)/2:0"


def _opcoes_encoder_cpu():
    return ["-c:v", "libx264", "-preset", "faster", "-crf", "20", "-pix_fmt", "yuv420p"]


def _opcoes_encoder_amf():
    return ["-c:v", "h264_amf", "-quality", "quality", "-rc", "vbr_peak", "-pix_fmt", "yuv420p"]


@lru_cache(maxsize=4)
def _encoders_disponiveis(ffmpeg):
    try:
        resultado = _run([ffmpeg, "-hide_banner", "-encoders"], 15)
    except MediaToolError:
        return ""
    return f"{resultado.stdout}\n{resultado.stderr}".lower()


def obter_opcoes_encoder(ffmpeg, encoder=None):
    """Seleciona AMF quando disponível e mantém x264 como fallback explícito."""
    preferencia = (encoder or os.getenv("SHORTS_ENCODER", "auto")).strip().lower()
    if preferencia in {"libx264", "cpu"}:
        return {"name": "libx264", "args": _opcoes_encoder_cpu()}
    if preferencia in {"h264_amf", "amf", "auto"} and "h264_amf" in _encoders_disponiveis(ffmpeg):
        return {"name": "h264_amf", "args": _opcoes_encoder_amf()}
    if preferencia not in {"auto", "amf", "h264_amf", "libx264", "cpu"}:
        raise MediaToolError(f"Encoder de vídeo não suportado: {preferencia}")
    return {"name": "libx264", "args": _opcoes_encoder_cpu()}


def _falha_encoder_hardware(error):
    mensagem = str(error).lower()
    marcadores = (
        "h264_amf", "amf", "d3d", "device", "hardware", "encoder not found",
        "cannot load", "not supported", "no capable", "initialization",
    )
    return any(marcador in mensagem for marcador in marcadores)


def montar_comando_render(ffmpeg, caminho_origem, caminho_saida, inicio_render, fim_render, filtro=None, encoder=None):
    duracao_render = max(0.001, float(fim_render) - float(inicio_render))
    opcoes_encoder = obter_opcoes_encoder(ffmpeg, encoder)
    comando = [
        ffmpeg, "-y", "-i", caminho_origem, "-ss", f"{float(inicio_render):.3f}",
        "-t", f"{duracao_render:.3f}",
    ]
    usa_filtro_complexo = str(filtro or "").startswith("filter_complex:")
    if filtro:
        if usa_filtro_complexo:
            comando.extend(["-filter_complex", str(filtro)[len("filter_complex:"):]])
        else:
            filtro_base = str(filtro).split(",scale=", 1)[0]
            filtro_final = f"{filtro_base},scale=1080:1920:flags=bicubic,format=yuv420p"
            comando.extend(["-vf", filtro_final])
    comando.extend([
        "-avoid_negative_ts", "make_zero",
        "-map", "[outv]" if usa_filtro_complexo else "0:v:0", "-map", "0:a?",
        *opcoes_encoder["args"],
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", caminho_saida,
    ])
    return comando


def _executar_render_com_fallback(ffmpeg, caminho_origem, caminho_saida, inicio_render, fim_render, filtro, timeout):
    comando = montar_comando_render(ffmpeg, caminho_origem, caminho_saida, inicio_render, fim_render, filtro)
    try:
        _run(comando, timeout)
    except MediaToolError as error:
        if "h264_amf" not in comando or not _falha_encoder_hardware(error):
            raise
        registrar_log(f"Falha no AMF, caindo para CPU: {error}")
        if os.path.exists(caminho_saida):
            os.remove(caminho_saida)
        comando_cpu = montar_comando_render(
            ffmpeg, caminho_origem, caminho_saida, inicio_render, fim_render, filtro, encoder="libx264"
        )
        _run(comando_cpu, timeout)


def renderizar_corte(caminho_origem, caminho_saida, inicio, fim, filtro=None, timeout=600, intervalos=None, vertical=False):
    ffmpeg, _ = localizar_ferramentas()
    duration = obter_duracao(caminho_origem)
    if not 0 <= float(inicio) < float(fim) <= duration:
        raise MediaToolError("Timestamps do corte estão fora da duração do arquivo.")
    os.makedirs(os.path.dirname(caminho_saida), exist_ok=True)
    intervalos = intervalos or []
    if intervalos:
        normalizados = []
        for intervalo in intervalos:
            trecho_inicio = float(intervalo["inicio"])
            trecho_fim = float(intervalo["fim"])
            if not 0 <= trecho_inicio < trecho_fim <= duration:
                raise MediaToolError("Intervalo de montagem fora da duração do arquivo.")
            normalizados.append((trecho_inicio, trecho_fim))
        with tempfile.TemporaryDirectory(prefix="growth-cut-") as pasta_temporaria:
            partes = []
            for indice, (trecho_inicio, trecho_fim) in enumerate(normalizados):
                parte = os.path.join(pasta_temporaria, f"parte-{indice}.mp4")
                filtro_parte = _filtro_vertical(caminho_origem, trecho_inicio, trecho_fim) if vertical else filtro
                _executar_render_com_fallback(
                    ffmpeg, caminho_origem, parte, trecho_inicio, trecho_fim, filtro_parte, timeout
                )
                partes.append(parte)
            lista = os.path.join(pasta_temporaria, "concat.txt")
            with open(lista, "w", encoding="utf-8") as arquivo:
                for parte in partes:
                    arquivo.write(f"file '{parte.replace(chr(92), '/')}'\n")
            _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", lista, "-c", "copy", caminho_saida], timeout)
        if not arquivo_media_valido(caminho_saida):
            raise MediaToolError("FFmpeg não produziu um arquivo composto válido.")
        return caminho_saida
    filtro_final = _filtro_vertical(caminho_origem, float(inicio), float(fim)) if vertical else filtro
    try:
        _executar_render_com_fallback(ffmpeg, caminho_origem, caminho_saida, inicio, fim, filtro_final, timeout)
    except Exception:
        if os.path.exists(caminho_saida):
            os.remove(caminho_saida)
        raise
    if not arquivo_media_valido(caminho_saida):
        raise MediaToolError("FFmpeg não produziu um arquivo final válido.")
    return caminho_saida
