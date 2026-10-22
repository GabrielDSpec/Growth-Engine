import os
import json
import math
import time
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import yt_dlp
from faster_whisper import WhisperModel
from core.database import DB_PATH, get_connection, init_db
from core.tenant import normalize_profile_id
from core.config import DIRETORIO_PROJETO
from core.media_tools import localizar_ferramentas, obter_duracao

_MODEL_WHISPER = None
_WHISPER_RUNTIME = threading.local()
_TRANSCRIPTION_CACHE_VERSION = 3
_TRANSCRIPTION_CHUNK_CACHE_VERSION = 2
_AUDIO_MARKER_PATTERN = re.compile(r"^\s*\[[^\]]+\]\s*$")


def _get_whisper_runtime():
    return getattr(_WHISPER_RUNTIME, "config", {})


def _set_whisper_runtime(config):
    _WHISPER_RUNTIME.config = dict(config)


class TranscriptionCancelled(RuntimeError):
    pass


def _directcompute_paths():
    executable = Path(os.getenv("WHISPER_DIRECTCOMPUTE_EXE", str(Path(DIRETORIO_PROJETO) / "constme.exe")))
    model = Path(os.getenv("WHISPER_DIRECTCOMPUTE_MODEL", str(Path(DIRETORIO_PROJETO) / "ggml-large-v2.bin")))
    return executable, model


def _whisper_backend():
    requested = os.getenv("WHISPER_BACKEND", "auto").lower()
    executable, model = _directcompute_paths()
    directcompute_available = executable.is_file() and model.is_file()
    if requested in {"directcompute", "amd", "vulkan"}:
        if not directcompute_available:
            raise RuntimeError(f"Backend DirectCompute AMD indisponível: {executable} ou {model} não encontrado.")
        return "directcompute"
    if requested == "faster_whisper":
        return "faster_whisper"
    if requested == "auto" and directcompute_available and os.getenv("WHISPER_DEVICE", "auto").lower() not in {"cpu", "cuda"}:
        return "directcompute"
    return "faster_whisper"


def _whisper_config():
    backend = _whisper_backend()
    if backend == "directcompute":
        executable, model = _directcompute_paths()
        return {
            "backend": backend,
            "model": str(model),
            "device": "AMD Radeon RX 9060 XT via DirectCompute",
            "compute_type": "float32",
            "gpu_index": int(os.getenv("WHISPER_DIRECTCOMPUTE_GPU", "0")),
            "fallback_reason": "",
        }
    requested_device = os.getenv("WHISPER_DEVICE", "auto").lower()
    model_name = os.getenv("WHISPER_MODEL", "large-v3")
    requested_compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
    allow_cpu_fallback = os.getenv("WHISPER_ALLOW_CPU_FALLBACK", "1").lower() in {"1", "true", "yes"}
    cuda_devices = 0
    try:
        import ctranslate2
        cuda_devices = ctranslate2.get_cuda_device_count()
    except (ImportError, RuntimeError):
        pass
    if requested_device == "cuda" and not cuda_devices:
        if not allow_cpu_fallback:
            raise RuntimeError("CUDA solicitado, mas nenhum dispositivo CUDA foi detectado pelo CTranslate2.")
        device = "cpu"
        compute_type = "int8"
        fallback_reason = "CUDA solicitado, mas indisponível; fallback CPU explícito"
    elif requested_device == "cpu" or (requested_device == "auto" and not cuda_devices):
        device = "cpu"
        compute_type = "int8" if requested_compute_type == "float16" else requested_compute_type
        fallback_reason = "CUDA indisponível; usando CPU"
    else:
        device = "cuda"
        compute_type = requested_compute_type
        fallback_reason = ""
    return {
        "backend": backend,
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "cuda_devices": cuda_devices,
        "fallback_reason": fallback_reason,
    }


def _emit_progress(progress_callback, progress, message, **details):
    if not progress_callback:
        return
    try:
        progress_callback(progress, message, details)
    except TypeError:
        progress_callback(progress, message)


def get_whisper_model(progress_callback=None):
    global _MODEL_WHISPER
    if _MODEL_WHISPER is None:
        config = _whisper_config()
        _emit_progress(progress_callback, 2, "Validando backend Whisper", stage="preparing", **config)
        print(f"🧠 Carregando Whisper ({config['model']}, {config['device']} {config['compute_type']})...")
        if config["backend"] == "directcompute":
            _MODEL_WHISPER = config
        else:
            _MODEL_WHISPER = WhisperModel(config["model"], device=config["device"], compute_type=config["compute_type"])
        _set_whisper_runtime(config)
    elif not _get_whisper_runtime():
        _set_whisper_runtime(_whisper_config())
    if _get_whisper_runtime():
        _emit_progress(progress_callback, 2, "Modelo Whisper em cache", stage="model_ready", **_get_whisper_runtime())
    return _MODEL_WHISPER


def _transcription_chunks_cache_path(cache_json_path):
    return f"{cache_json_path}.chunks"


def _load_transcription_chunks_cache(path, chunk_seconds, overlap_seconds):
    if not path or not os.path.isfile(path):
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("version") != _TRANSCRIPTION_CHUNK_CACHE_VERSION
            or payload.get("chunk_seconds") != chunk_seconds
            or payload.get("overlap_seconds") != overlap_seconds
            or not isinstance(payload.get("chunks"), dict)
        ):
            return {}
        return payload["chunks"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, AttributeError):
        return {}


def _save_transcription_chunks_cache(path, chunks, chunk_seconds, overlap_seconds):
    if not path:
        return
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    payload = {
        "version": _TRANSCRIPTION_CHUNK_CACHE_VERSION,
        "chunk_seconds": chunk_seconds,
        "overlap_seconds": overlap_seconds,
        "chunks": chunks,
    }
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary_path.replace(cache_path)


def _deduplicate_transcription_segments(segments):
    ordered = sorted(segments, key=lambda item: (float(item["inicio"]), float(item["fim"]), item.get("texto", "")))
    result = []
    seen = set()
    for segment in ordered:
        key = (round(float(segment["inicio"]), 3), round(float(segment["fim"]), 3), segment.get("texto", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append({**segment, "inicio": key[0], "fim": key[1]})
    for indice, segment in enumerate(result):
        segment["indice"] = indice
    return result


def _extrair_palavras(segment):
    resultado = []
    for palavra in getattr(segment, "words", None) or []:
        texto = str(getattr(palavra, "word", "") or "").strip()
        inicio = getattr(palavra, "start", None)
        fim = getattr(palavra, "end", None)
        if not texto or inicio is None or fim is None or float(fim) <= float(inicio):
            continue
        resultado.append({"inicio": round(float(inicio), 3), "fim": round(float(fim), 3), "texto": texto})
    return resultado


def _transcricao_dominada_por_marcadores_audio(segments):
    """Detecta quando a saída descreve o áudio ambiente, mas perdeu a fala."""
    if not segments:
        return False
    marcadores = [segmento for segmento in segments if _AUDIO_MARKER_PATTERN.fullmatch(str(segmento.get("texto", "")))]
    if len(marcadores) < 3 or len(marcadores) / len(segments) < 0.5:
        return False
    duracao_total = sum(max(float(segmento.get("fim", 0)) - float(segmento.get("inicio", 0)), 0) for segmento in segments)
    duracao_marcadores = sum(max(float(segmento.get("fim", 0)) - float(segmento.get("inicio", 0)), 0) for segmento in marcadores)
    return not duracao_total or duracao_marcadores / duracao_total >= 0.5


def _transcrever_faster_whisper_em_chunks(
    caminho_audio,
    model,
    duration,
    vad_filter,
    progress_callback=None,
    cancel_callback=None,
    started_at=None,
    chunk_cache_path=None,
):
    chunk_seconds = max(int(os.getenv("WHISPER_CHUNK_SECONDS", "600")), 60)
    overlap_seconds = min(max(float(os.getenv("WHISPER_CHUNK_OVERLAP_SECONDS", "15")), 0), chunk_seconds / 2)
    total_chunks = max(1, math.ceil(duration / chunk_seconds))
    cached_chunks = _load_transcription_chunks_cache(chunk_cache_path, chunk_seconds, overlap_seconds)
    all_segments = []
    for chunk_index in range(total_chunks):
        if cancel_callback and cancel_callback():
            raise TranscriptionCancelled("Processamento cancelado pelo usuário.")
        start = max(0.0, chunk_index * chunk_seconds - (overlap_seconds if chunk_index else 0))
        end = min(duration, (chunk_index + 1) * chunk_seconds + (overlap_seconds if chunk_index + 1 < total_chunks else 0))
        chunk_key = f"{start:.3f}-{end:.3f}"
        segments = cached_chunks.get(chunk_key)
        if segments is None:
            _emit_progress(progress_callback, min(90, 10 + int(chunk_index / total_chunks * 80)), "Transcrevendo janela de áudio", stage="transcribing", step_name="transcription", step_index=chunk_index, step_total=total_chunks, chunk_start=round(start, 3), chunk_end=round(end, 3), vad_filter=vad_filter, **_get_whisper_runtime())
            generated, info = model.transcribe(
                caminho_audio,
                language="pt",
                beam_size=5,
                word_timestamps=True,
                vad_filter=vad_filter,
                condition_on_previous_text=False,
                clip_timestamps=[start, end],
            )
            segments = []
            for segment in generated:
                texto = segment.text.strip()
                if not texto:
                    continue
                inicio = float(segment.start)
                fim = float(segment.end)
                deslocar = start > 0 and fim <= start + 0.001
                if deslocar:
                    inicio += start
                    fim += start
                palavras = _extrair_palavras(segment)
                if deslocar and palavras:
                    for palavra in palavras:
                        palavra["inicio"] += start
                        palavra["fim"] += start
                item = {"inicio": round(inicio, 3), "fim": round(fim, 3), "texto": texto}
                if palavras:
                    item["palavras"] = palavras
                segments.append(item)
            cached_chunks[chunk_key] = segments
            _save_transcription_chunks_cache(chunk_cache_path, cached_chunks, chunk_seconds, overlap_seconds)
        all_segments.extend(segments)
        merged = _deduplicate_transcription_segments(all_segments)
        elapsed_seconds = max(time.monotonic() - started_at, 0.001)
        processed_audio_seconds = min(duration, end)
        speed_x = processed_audio_seconds / elapsed_seconds
        eta_seconds = max((duration - processed_audio_seconds) / speed_x, 0) if speed_x else None
        _emit_progress(progress_callback, min(90, 10 + int((processed_audio_seconds / duration) * 80)), "Janela de áudio concluída", stage="transcribing", step_name="transcription", step_index=chunk_index + 1, step_total=total_chunks, elapsed_seconds=round(elapsed_seconds, 1), audio_seconds=round(duration, 1), processed_audio_seconds=round(processed_audio_seconds, 1), segments_processed=len(merged), segments_total=len(merged), segments_accepted=len(merged), speed_x=round(speed_x, 2), eta_seconds=round(eta_seconds) if eta_seconds is not None else 0, vad_filter=vad_filter, **_get_whisper_runtime())
    return _deduplicate_transcription_segments(all_segments), SimpleNamespace(duration=duration)


def _transcrever_faster_whisper_adaptativo(caminho_audio, model, progress_callback=None, cancel_callback=None, started_at=None, chunk_cache_path=None):
    started_at = started_at or time.monotonic()

    def coletar(vad_filter):
        duration = obter_duracao(caminho_audio) if chunk_cache_path else 0
        if duration > 0:
            return _transcrever_faster_whisper_em_chunks(caminho_audio, model, duration, vad_filter, progress_callback=progress_callback, cancel_callback=cancel_callback, started_at=started_at, chunk_cache_path=chunk_cache_path)
        _emit_progress(progress_callback, 5, "Transcrevendo áudio", stage="transcribing", vad_filter=vad_filter, started_at=started_at, **_get_whisper_runtime())
        segments, info = model.transcribe(
            caminho_audio,
            language="pt",
            beam_size=5,
            word_timestamps=True,
            vad_filter=vad_filter,
            condition_on_previous_text=False,
        )
        resultado = []
        for indice, segment in enumerate(segments):
            if cancel_callback and cancel_callback():
                raise TranscriptionCancelled("Processamento cancelado pelo usuário.")
            texto = segment.text.strip()
            if not texto:
                continue
            item = {
                "indice": indice,
                "inicio": round(float(segment.start), 3),
                "fim": round(float(segment.end), 3),
                "texto": texto,
            }
            palavras = _extrair_palavras(segment)
            if palavras:
                item["palavras"] = palavras
            resultado.append(item)
            if info.duration:
                elapsed_seconds = max(time.monotonic() - started_at, 0.001)
                processed_audio_seconds = min(float(segment.end), float(info.duration))
                speed_x = processed_audio_seconds / elapsed_seconds
                eta_seconds = max((float(info.duration) - processed_audio_seconds) / speed_x, 0) if speed_x else None
                _emit_progress(progress_callback, min(90, 10 + int((processed_audio_seconds / info.duration) * 80)), "Transcrevendo áudio", stage="transcribing", elapsed_seconds=round(elapsed_seconds, 1), audio_seconds=round(float(info.duration), 1), processed_audio_seconds=round(processed_audio_seconds, 1), segments_processed=indice + 1, segments_accepted=len(resultado), speed_x=round(speed_x, 2), eta_seconds=round(eta_seconds) if eta_seconds is not None else None, vad_filter=vad_filter, **_get_whisper_runtime())
        return resultado, info

    resultado, info = coletar(True)
    duracao = float(getattr(info, "duration", 0) or 0)
    ultimo_fim = max((segmento["fim"] for segmento in resultado), default=0.0)
    cobertura_minima = float(os.getenv("WHISPER_ADAPTIVE_COVERAGE", "0.75"))
    limiar_reprocessamento = max(120.0, duracao * cobertura_minima)
    if duracao >= 300 and (ultimo_fim < limiar_reprocessamento or _transcricao_dominada_por_marcadores_audio(resultado)):
        _emit_progress(progress_callback, 10, "Cobertura parcial; reprocessando sem filtro de silêncio", stage="retry_without_vad", coverage_seconds=round(ultimo_fim, 1), audio_seconds=round(duracao, 1), **_get_whisper_runtime())
        resultado_sem_vad, info_sem_vad = coletar(False)
        ultimo_fim_sem_vad = max((segmento["fim"] for segmento in resultado_sem_vad), default=0.0)
        if ultimo_fim_sem_vad > ultimo_fim:
            resultado, info = resultado_sem_vad, info_sem_vad
    return resultado


def _modelo_faster_whisper_fallback(progress_callback=None):
    requested_device = os.getenv("WHISPER_DEVICE", "auto").lower()
    model_name = os.getenv("WHISPER_MODEL", "large-v3")
    try:
        import ctranslate2
        cuda_available = ctranslate2.get_cuda_device_count() > 0
    except (ImportError, RuntimeError):
        cuda_available = False
    device = "cuda" if requested_device == "cuda" or (requested_device == "auto" and cuda_available) else "cpu"
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "float16") if device == "cuda" else "int8"
    config = {"backend": "faster_whisper", "model": model_name, "device": device, "compute_type": compute_type, "fallback_reason": "cobertura DirectCompute insuficiente"}
    _emit_progress(progress_callback, 10, "Carregando fallback adaptativo Whisper", stage="adaptive_fallback_model", **config)
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    _set_whisper_runtime(config)
    return model

def _youtube_audio_options(audio_stem):
    options = {
        "format": "bestaudio/best",
        "outtmpl": f"{audio_stem}.%(ext)s",
        "quiet": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 4,
        "fragment_retries": 4,
        "extractor_retries": 3,
        "retry_sleep_functions": {"http": lambda attempt: min(15, attempt * 3)},
        "sleep_interval_requests": 1,
        "continuedl": True,
        "js_runtimes": {"node": {}},
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"},
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
    }
    cookies_file = os.getenv("GROWTH_ENGINE_YOUTUBE_COOKIES", "").strip()
    cookies_browser = os.getenv("GROWTH_ENGINE_YOUTUBE_COOKIES_FROM_BROWSER", "").strip()
    if cookies_file:
        options["cookiefile"] = cookies_file
    elif cookies_browser:
        options["cookiesfrombrowser"] = (cookies_browser,)
    return options


def transcrever_video_youtube(video_id: str, force=False, progress_callback=None, perfil_id=1) -> str:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    row = cursor.execute("SELECT transcricao, titulo FROM videos_historico WHERE video_id = ? AND perfil_id = ?", (video_id, perfil_id)).fetchone()
    if not row:
        print(f"⚠️ Vídeo {video_id} não encontrado na base.")
        conn.close()
        raise RuntimeError(f"Vídeo {video_id} não encontrado no perfil {perfil_id}.")
        
    titulo_video = row['titulo']
        
    if row['transcricao'] and not force:
        conn.close()
        return row['transcricao']

    url = f"https://www.youtube.com/watch?v={video_id}"
    transcricao_texto = ""
    with tempfile.TemporaryDirectory(prefix="growth_youtube_") as temp_dir:
        audio_stem = os.path.join(temp_dir, "audio")
        ydl_opts = _youtube_audio_options(audio_stem)
        audio_file = f"{audio_stem}.m4a"
        try:
            if progress_callback:
                progress_callback(10, "Baixando áudio")
            print(f"\n📥 Baixando: '{titulo_video}' (ID: {video_id})...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            print(f"⚠️ Erro ao baixar áudio {video_id}: {e}")
            conn.close()
            detail = str(e)
            if "403" in detail:
                detail += ". O YouTube bloqueou a URL; atualize yt-dlp ou configure GROWTH_ENGINE_YOUTUBE_COOKIES_FROM_BROWSER=chrome para vídeos que exigem sessão."
            raise RuntimeError(f"Falha ao baixar o áudio do YouTube {video_id}: {detail}") from e

        if not os.path.isfile(audio_file):
            conn.close()
            raise RuntimeError(f"O download do vídeo {video_id} não produziu um arquivo de áudio local.")

        try:
            if progress_callback:
                progress_callback(35, "Carregando Whisper")
            print(f"🎙️ Transcrevendo: '{titulo_video}'...")
            if _whisper_backend() == "directcompute":
                _set_whisper_runtime(_whisper_config())
                segmentos = _transcrever_directcompute(audio_file, progress_callback=progress_callback)
                transcricao_texto = " ".join(segmento["texto"] for segmento in segmentos)
                cursor.execute(
                    "UPDATE videos_historico SET transcricao = ?, transcricao_segmentos = ? WHERE video_id = ? AND perfil_id = ?",
                    (transcricao_texto, json.dumps(segmentos, ensure_ascii=False), video_id, perfil_id),
                )
                conn.commit()
                if progress_callback:
                    progress_callback(100, "Transcrição concluída")
                return transcricao_texto
            model = get_whisper_model()
            segmentos = _transcrever_faster_whisper_adaptativo(audio_file, model, progress_callback=progress_callback)
            
            transcricao_texto = " ".join(segmento["texto"] for segmento in segmentos)
            print(f"✅ Transcrição de '{titulo_video}' concluída!\n")
            
            cursor.execute(
                "UPDATE videos_historico SET transcricao = ?, transcricao_segmentos = ? WHERE video_id = ? AND perfil_id = ?",
                (transcricao_texto, json.dumps(segmentos, ensure_ascii=False), video_id, perfil_id),
            )
            if progress_callback:
                progress_callback(100, "Transcrição concluída")
            conn.commit()
        except Exception as e:
            print(f"⚠️ Erro no Whisper: {e}")
            raise RuntimeError(f"Falha ao transcrever o áudio {video_id}: {e}") from e

    conn.close()
    return transcricao_texto


def transcrever_arquivo_local(caminho_video: str) -> str:
    return " ".join(segmento["texto"] for segmento in transcrever_arquivo_local_segmentos(caminho_video))


def _parse_srt_timestamp(value):
    hours, minutes, seconds, millis = map(int, re.split(r"[:,]", value.strip()))
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _parse_srt(path):
    content = Path(path).read_text(encoding="utf-8-sig")
    segments = []
    blocks = re.split(r"\r?\n\r?\n+", content.strip())
    for index, block in enumerate(blocks):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = (part.strip() for part in lines[1].split("-->", 1))
        text = " ".join(lines[2:]).strip()
        if not text:
            continue
        segments.append({
            "indice": index,
            "inicio": round(_parse_srt_timestamp(start), 3),
            "fim": round(_parse_srt_timestamp(end), 3),
            "texto": text,
        })
    return segments


def _format_srt_timestamp(seconds):
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _save_srt_cache(path, segments):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n{_format_srt_timestamp(segment['inicio'])} --> {_format_srt_timestamp(segment['fim'])}\n{segment['texto']}"
        )
    Path(path).write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")


def _load_srt_cache(path):
    if not path or not os.path.isfile(path):
        return []
    try:
        return _parse_srt(path)
    except (OSError, UnicodeDecodeError, ValueError):
        return []


def _transcription_json_cache_path(video_path, cache_srt_path=None):
    if cache_srt_path:
        return str(Path(cache_srt_path).with_suffix(".json"))
    return str(Path(video_path).with_suffix(".transcription_cache.json"))


def _load_transcription_json_cache(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != _TRANSCRIPTION_CACHE_VERSION:
            return None
        segments = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(segments, list) or any(
            not isinstance(segment, dict)
            or not all(key in segment for key in ("inicio", "fim", "texto"))
            for segment in segments
        ):
            return None
        return segments
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, AttributeError):
        return None


def _save_transcription_json_cache(path, segments):
    if not path:
        return
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
    temporary_path.write_text(json.dumps({"version": _TRANSCRIPTION_CACHE_VERSION, "segments": segments}, ensure_ascii=False), encoding="utf-8")
    temporary_path.replace(cache_path)


def _directcompute_finalization_timeout():
    try:
        return max(float(os.getenv("WHISPER_DIRECTCOMPUTE_FINALIZATION_TIMEOUT", "300")), 1.0)
    except ValueError:
        return 300.0


def _directcompute_threads():
    try:
        return max(int(os.getenv("WHISPER_DIRECTCOMPUTE_THREADS", "8")), 1)
    except ValueError:
        return 8


def _directcompute_reached_finalization(timestamp, video_seconds, timestamp_is_real):
    return bool(timestamp_is_real and timestamp >= video_seconds)


def _transcrever_directcompute(caminho_video, progress_callback=None, cancel_callback=None, cache_srt_path=None):
    executable, model = _directcompute_paths()
    gpu_index = int(os.getenv("WHISPER_DIRECTCOMPUTE_GPU", "0"))
    threads = _directcompute_threads()
    ffmpeg, _ = localizar_ferramentas()
    video_seconds = obter_duracao(caminho_video)
    estimated_speed_x = max(float(os.getenv("WHISPER_DIRECTCOMPUTE_SPEED_X", "7.0")), 0.05)
    started_at = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="growth_whisper_") as temp_dir:
        wav_path = Path(temp_dir) / "audio.wav"
        srt_path = wav_path.with_suffix(".srt")
        _emit_progress(progress_callback, 3, "Preparando áudio para GPU AMD", stage="preparing", **_get_whisper_runtime())
        if cancel_callback and cancel_callback():
            raise TranscriptionCancelled("Processamento cancelado pelo usuário.")
        extract = subprocess.run(
            [ffmpeg, "-y", "-i", caminho_video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path)],
            capture_output=True,
            text=True,
            timeout=int(os.getenv("WHISPER_AUDIO_TIMEOUT", "600")),
            check=False,
        )
        if extract.returncode != 0:
            raise RuntimeError(f"Falha ao extrair áudio para DirectCompute: {(extract.stderr or '')[-500:]}")
        _emit_progress(progress_callback, 12, "Transcrevendo na AMD Radeon RX 9060 XT", stage="transcribing", backend="directcompute", device="AMD Radeon RX 9060 XT", gpu_index=gpu_index, model=str(model))
        process = subprocess.Popen(
            [str(executable), "-m", str(model), "-f", wav_path.name, "-l", "pt", "-gpu", str(gpu_index), "-t", str(threads), "-osrt"],
            cwd=str(temp_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        timeout = time.monotonic() + int(os.getenv("WHISPER_TIMEOUT", "3600"))
        finalization_started_at = None
        finalization_timeout = _directcompute_finalization_timeout()
        last_progress_at = 0.0
        while process.poll() is None:
            if cancel_callback and cancel_callback():
                process.terminate()
                process.wait(timeout=10)
                raise TranscriptionCancelled("Processamento cancelado pelo usuário.")
            if time.monotonic() > timeout:
                process.kill()
                raise RuntimeError("DirectCompute excedeu o timeout configurado.")
            now = time.monotonic()
            if now - last_progress_at >= 1:
                elapsed = max(now - started_at, 0.001)
                timestamp = 0.0
                timestamp_is_real = False
                if srt_path.is_file():
                    try:
                        partial_segments = _parse_srt(srt_path)
                        timestamp = max((segment["fim"] for segment in partial_segments), default=0.0)
                        timestamp_is_real = timestamp > 0
                    except (OSError, UnicodeDecodeError, ValueError):
                        timestamp = 0.0
                if not timestamp_is_real:
                    timestamp = min(video_seconds, elapsed * estimated_speed_x)
                speed_x = timestamp / elapsed if timestamp_is_real else estimated_speed_x
                eta_seconds = max((video_seconds - timestamp) / speed_x, 0) if speed_x else None
                reached_finalization = _directcompute_reached_finalization(timestamp, video_seconds, timestamp_is_real)
                progress = min(89 if reached_finalization else 88, max(12, 12 + int((timestamp / video_seconds) * 77)))
                message = "Finalizando transcrição AMD e fechando SRT" if reached_finalization else f"Transcrevendo na AMD Radeon RX 9060 XT ({'timestamp real' if timestamp_is_real else 'estimativa'})"
                if reached_finalization:
                    if finalization_started_at is None:
                        finalization_started_at = now
                    elif now - finalization_started_at >= finalization_timeout:
                        process.kill()
                        process.wait(timeout=10)
                        raise RuntimeError(
                            "DirectCompute excedeu o timeout de finalização do SRT "
                            f"({finalization_timeout:.0f}s)."
                        )
                _emit_progress(
                    progress_callback,
                    progress,
                    message,
                    stage="transcribing",
                    backend="directcompute",
                    device="AMD Radeon RX 9060 XT",
                    gpu_index=gpu_index,
                    threads=threads,
                    model=str(model),
                    elapsed_seconds=round(elapsed, 1),
                    audio_seconds=round(video_seconds, 1),
                    processed_audio_seconds=round(timestamp, 1),
                    speed_x=round(speed_x, 2),
                    eta_seconds=round(eta_seconds) if eta_seconds is not None else None,
                    timestamp_source="srt" if timestamp_is_real else "estimated",
                )
                last_progress_at = now
            time.sleep(0.25)
        result = process
        if result.returncode != 0:
            raise RuntimeError(f"DirectCompute retornou {result.returncode}.")
        if not srt_path.is_file():
            raise RuntimeError("DirectCompute terminou sem produzir SRT segmentado.")
        segments = _parse_srt(srt_path)
        if cache_srt_path:
            _save_srt_cache(cache_srt_path, segments)
        elapsed = max(time.monotonic() - started_at, 0.001)
        audio_seconds = max((segment["fim"] for segment in segments), default=0)
        coverage_threshold = float(os.getenv("WHISPER_ADAPTIVE_COVERAGE", "0.75"))
        marcadores_audio_detectados = _transcricao_dominada_por_marcadores_audio(segments)
        if video_seconds >= 300 and (audio_seconds < max(120.0, video_seconds * coverage_threshold) or marcadores_audio_detectados):
            motivo_fallback = "marcadores acústicos dominaram a saída" if marcadores_audio_detectados else "cobertura insuficiente"
            fallback_progress = dict(_get_whisper_runtime())
            fallback_progress["fallback_reason"] = motivo_fallback
            _emit_progress(progress_callback, 90, "Reprocessando fala com Whisper large-v3", stage="adaptive_fallback", **fallback_progress)
            fallback_model = _modelo_faster_whisper_fallback(progress_callback=progress_callback)
            fallback_segments = _transcrever_faster_whisper_adaptativo(
                caminho_video,
                fallback_model,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
                started_at=started_at,
            )
            fallback_audio_seconds = max((segment["fim"] for segment in fallback_segments), default=0)
            fallback_tem_fala = not _transcricao_dominada_por_marcadores_audio(fallback_segments)
            if fallback_audio_seconds > audio_seconds or (marcadores_audio_detectados and fallback_tem_fala):
                segments = fallback_segments
                audio_seconds = fallback_audio_seconds
                if cache_srt_path:
                    _save_srt_cache(cache_srt_path, segments)
        _emit_progress(progress_callback, 95, "Transcrição AMD segmentada pronta", stage="transcription_ready", backend="directcompute", device="AMD Radeon RX 9060 XT", model=str(model), elapsed_seconds=round(elapsed, 1), audio_seconds=round(audio_seconds, 1), processed_audio_seconds=round(audio_seconds, 1), segments_processed=len(segments), segments_accepted=len(segments), speed_x=round(audio_seconds / elapsed, 2) if audio_seconds else 0, eta_seconds=0)
        return segments


def transcrever_arquivo_local_segmentos(caminho_video: str, progress_callback=None, cancel_callback=None, cache_srt_path=None) -> list[dict]:
    if not os.path.exists(caminho_video):
        print(f"⚠️ Arquivo não encontrado para transcrição: {caminho_video}")
        return []

    try:
        cache_json_path = _transcription_json_cache_path(caminho_video, cache_srt_path)
        chunk_cache_path = _transcription_chunks_cache_path(cache_json_path)
        cached_json_segments = _load_transcription_json_cache(cache_json_path)
        if cached_json_segments is not None:
            _emit_progress(progress_callback, 100, "Transcrição carregada do cache JSON", stage="cache_hit", segments_processed=len(cached_json_segments), segments_accepted=len(cached_json_segments), timestamp_source="json_cache")
            return cached_json_segments
        cached_segments = _load_srt_cache(cache_srt_path) if not os.path.isfile(cache_json_path) else []
        if cached_segments:
            _save_transcription_json_cache(cache_json_path, cached_segments)
            _emit_progress(progress_callback, 100, "Transcrição carregada do cache SRT", stage="cache_hit", segments_processed=len(cached_segments), segments_accepted=len(cached_segments), timestamp_source="srt_cache")
            return cached_segments
        print(f"🎙️ Transcrevendo arquivo local: '{os.path.basename(caminho_video)}'...")
        started_at = time.monotonic()
        if _whisper_backend() == "directcompute":
            _set_whisper_runtime(_whisper_config())
            resultado = _transcrever_directcompute(caminho_video, progress_callback=progress_callback, cancel_callback=cancel_callback, cache_srt_path=cache_srt_path)
            _save_transcription_json_cache(cache_json_path, resultado)
            return resultado
        model = get_whisper_model(progress_callback=progress_callback)
        resultado = _transcrever_faster_whisper_adaptativo(
            caminho_video,
            model,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
            started_at=started_at,
            chunk_cache_path=chunk_cache_path,
        )
        _emit_progress(progress_callback, 95, "Salvando transcrição no cache", stage="saving", segments_processed=len(resultado), segments_accepted=len(resultado), elapsed_seconds=round(max(time.monotonic() - started_at, 0.001), 1), **_get_whisper_runtime())
        if cache_srt_path and resultado:
            _save_srt_cache(cache_srt_path, resultado)
        if resultado:
            _save_transcription_json_cache(cache_json_path, resultado)
            try:
                Path(chunk_cache_path).unlink(missing_ok=True)
            except OSError:
                pass
        return resultado
    except Exception as e:
        print(f"⚠️ Erro ao transcrever arquivo local: {e}")
        return []
    
def pre_transcrever_pendentes(limite=15, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
# O CAST(views AS INTEGER) força a ordenação matemática real
    rows = cursor.execute("""
        SELECT video_id, titulo, views 
        FROM videos_historico 
        WHERE perfil_id = ? AND (transcricao IS NULL OR transcricao = '')
        ORDER BY CAST(views AS INTEGER) DESC
        LIMIT ?
    """, (perfil_id, limite)).fetchall()
    conn.close()
    
    if not rows:
        print(f"✅ O seu TOP {limite} mais visto já está 100% transcrito e no cache!")
        return
        
    print(f"🎙️ Estratégia Sniper: Focando nos {len(rows)} vídeos mais vistos pendentes...")
    
    for idx, r in enumerate(rows, 1):
        print(f"\n[{idx}/{len(rows)}] 🎯 Alvo de Ouro: {r['views']} visualizações")
        transcrever_video_youtube(r['video_id'], perfil_id=perfil_id)
        
    print(f"✅ TOP {limite} processado! A base de inteligência está pronta.")
    