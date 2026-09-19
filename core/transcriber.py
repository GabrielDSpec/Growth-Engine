import os
import json
import time
import re
import subprocess
import tempfile
from pathlib import Path
import yt_dlp
from faster_whisper import WhisperModel
from core.database import DB_PATH, get_connection, init_db
from core.tenant import normalize_profile_id
from core.config import DIRETORIO_PROJETO
from core.media_tools import localizar_ferramentas, obter_duracao

_MODEL_WHISPER = None
_WHISPER_RUNTIME = {}


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
    global _WHISPER_RUNTIME
    if _MODEL_WHISPER is None:
        config = _whisper_config()
        _emit_progress(progress_callback, 2, "Validando backend Whisper", stage="preparing", **config)
        print(f"🧠 Carregando Whisper ({config['model']}, {config['device']} {config['compute_type']})...")
        if config["backend"] == "directcompute":
            _MODEL_WHISPER = config
        else:
            _MODEL_WHISPER = WhisperModel(config["model"], device=config["device"], compute_type=config["compute_type"])
        _WHISPER_RUNTIME = config
    elif _WHISPER_RUNTIME:
        _emit_progress(progress_callback, 2, "Modelo Whisper em cache", stage="model_ready", **_WHISPER_RUNTIME)
    return _MODEL_WHISPER

def transcrever_video_youtube(video_id: str, force=False, progress_callback=None, perfil_id=1) -> str:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    row = cursor.execute("SELECT transcricao, titulo FROM videos_historico WHERE video_id = ? AND perfil_id = ?", (video_id, perfil_id)).fetchone()
    if not row:
        print(f"⚠️ Vídeo {video_id} não encontrado na base.")
        conn.close()
        return ""
        
    titulo_video = row['titulo']
        
    if row['transcricao'] and not force:
        conn.close()
        return row['transcricao']

    url = f"https://www.youtube.com/watch?v={video_id}"
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f"temp_{video_id}.%(ext)s",
        'quiet': True,
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}]
    }
    
    real_audio = f"temp_{video_id}.m4a"
    if not os.path.exists(real_audio):
        try:
            if progress_callback:
                progress_callback(10, "Baixando áudio")
            print(f"\n📥 Baixando: '{titulo_video}' (ID: {video_id})...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            print(f"⚠️ Erro ao baixar áudio {video_id}: {e}")
            conn.close()
            return ""

    audio_file = None
    for f in os.listdir('.'):
        if f.startswith(f"temp_{video_id}") and not f.endswith('.part'):
            audio_file = f
            break

    transcricao_texto = ""
    if audio_file and os.path.exists(audio_file):
        try:
            if progress_callback:
                progress_callback(35, "Carregando Whisper")
            print(f"🎙️ Transcrevendo: '{titulo_video}'...")
            if _whisper_backend() == "directcompute":
                _WHISPER_RUNTIME.clear()
                _WHISPER_RUNTIME.update(_whisper_config())
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
            segments, info = model.transcribe(audio_file, language="pt", beam_size=5, vad_filter=True, condition_on_previous_text=False)
            
            print(f"⏱️ Duração: {info.duration:.1f}s. Acompanhe o progresso:")
            
            textos = []
            segmentos = []
            for indice, segment in enumerate(segments):
                # Cálculo exato da porcentagem em tempo real
                porcentagem = min(100.0, (segment.end / info.duration) * 100)
                print(f"  [{porcentagem:05.1f}%] {segment.start:.1f}s -> {segment.end:.1f}s | {segment.text}")
                texto = segment.text.strip()
                if texto:
                    textos.append(texto)
                    segmentos.append({
                        "indice": indice,
                        "inicio": round(float(segment.start), 3),
                        "fim": round(float(segment.end), 3),
                        "texto": texto,
                    })
                    if progress_callback and info.duration:
                        progress_callback(min(90, 40 + int((segment.end / info.duration) * 50)), "Transcrevendo áudio")
                
            transcricao_texto = " ".join(textos)
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
        finally:
            if os.path.exists(audio_file):
                os.remove(audio_file)

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


def _transcrever_directcompute(caminho_video, progress_callback=None, cancel_callback=None, cache_srt_path=None):
    executable, model = _directcompute_paths()
    gpu_index = int(os.getenv("WHISPER_DIRECTCOMPUTE_GPU", "0"))
    ffmpeg, _ = localizar_ferramentas()
    video_seconds = obter_duracao(caminho_video)
    estimated_speed_x = max(float(os.getenv("WHISPER_DIRECTCOMPUTE_SPEED_X", "7.0")), 0.05)
    started_at = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="growth_whisper_") as temp_dir:
        wav_path = Path(temp_dir) / "audio.wav"
        srt_path = wav_path.with_suffix(".srt")
        _emit_progress(progress_callback, 3, "Preparando áudio para GPU AMD", stage="preparing", **_WHISPER_RUNTIME)
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
            [str(executable), "-m", str(model), "-f", str(wav_path), "-l", "pt", "-gpu", str(gpu_index), "-osrt", "-nt"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        timeout = time.monotonic() + int(os.getenv("WHISPER_TIMEOUT", "3600"))
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
                progress = min(89, max(12, 12 + int((timestamp / video_seconds) * 77)))
                message = "Finalizando transcrição AMD e fechando SRT" if timestamp >= video_seconds else f"Transcrevendo na AMD Radeon RX 9060 XT ({'timestamp real' if timestamp_is_real else 'estimativa'})"
                _emit_progress(
                    progress_callback,
                    progress,
                    message,
                    stage="transcribing",
                    backend="directcompute",
                    device="AMD Radeon RX 9060 XT",
                    gpu_index=gpu_index,
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
        _emit_progress(progress_callback, 95, "Transcrição AMD segmentada pronta", stage="transcription_ready", backend="directcompute", device="AMD Radeon RX 9060 XT", model=str(model), elapsed_seconds=round(elapsed, 1), audio_seconds=round(audio_seconds, 1), processed_audio_seconds=round(audio_seconds, 1), segments_processed=len(segments), segments_accepted=len(segments), speed_x=round(audio_seconds / elapsed, 2) if audio_seconds else 0, eta_seconds=0)
        return segments


def transcrever_arquivo_local_segmentos(caminho_video: str, progress_callback=None, cancel_callback=None, cache_srt_path=None) -> list[dict]:
    if not os.path.exists(caminho_video):
        print(f"⚠️ Arquivo não encontrado para transcrição: {caminho_video}")
        return []

    try:
        cached_segments = _load_srt_cache(cache_srt_path)
        if cached_segments:
            _emit_progress(progress_callback, 100, "Transcrição carregada do cache SRT", stage="cache_hit", segments_processed=len(cached_segments), segments_accepted=len(cached_segments), timestamp_source="srt_cache")
            return cached_segments
        print(f"🎙️ Transcrevendo arquivo local: '{os.path.basename(caminho_video)}'...")
        started_at = time.monotonic()
        if _whisper_backend() == "directcompute":
            _WHISPER_RUNTIME.clear()
            _WHISPER_RUNTIME.update(_whisper_config())
            return _transcrever_directcompute(caminho_video, progress_callback=progress_callback, cancel_callback=cancel_callback, cache_srt_path=cache_srt_path)
        model = get_whisper_model(progress_callback=progress_callback)
        def coletar_segmentos(vad_filter):
            _emit_progress(progress_callback, 5, "Transcrevendo áudio", stage="transcribing", vad_filter=vad_filter, started_at=started_at, **_WHISPER_RUNTIME)
            segments, info = model.transcribe(
                caminho_video,
                language="pt",
                beam_size=5,
                vad_filter=vad_filter,
                condition_on_previous_text=False,
            )
            resultado = []
            segments_processed = 0
            for indice, segment in enumerate(segments):
                if cancel_callback and cancel_callback():
                    raise TranscriptionCancelled("Processamento cancelado pelo usuário.")
                segments_processed = indice + 1
                texto = segment.text.strip()
                if texto:
                    resultado.append({
                        "indice": indice,
                        "inicio": round(float(segment.start), 3),
                        "fim": round(float(segment.end), 3),
                        "texto": texto,
                    })
                    elapsed_seconds = max(time.monotonic() - started_at, 0.001)
                    processed_audio_seconds = min(float(segment.end), float(info.duration or segment.end))
                    speed_x = processed_audio_seconds / elapsed_seconds
                    eta_seconds = max((float(info.duration) - processed_audio_seconds) / speed_x, 0) if speed_x else None
                    _emit_progress(progress_callback, min(90, 10 + int((processed_audio_seconds / info.duration) * 80)) if info.duration else 10, "Transcrevendo áudio", stage="transcribing", elapsed_seconds=round(elapsed_seconds, 1), audio_seconds=round(float(info.duration or 0), 1), processed_audio_seconds=round(processed_audio_seconds, 1), segments_processed=segments_processed, segments_accepted=len(resultado), speed_x=round(speed_x, 2), eta_seconds=round(eta_seconds) if eta_seconds is not None else None, vad_filter=vad_filter, **_WHISPER_RUNTIME)
            _emit_progress(progress_callback, min(90, 10 + int((float(info.duration) / info.duration) * 80)) if info.duration else 10, "Transcrição de áudio concluída", stage="transcription_ready", elapsed_seconds=round(max(time.monotonic() - started_at, 0.001), 1), audio_seconds=round(float(info.duration or 0), 1), processed_audio_seconds=round(float(info.duration or 0), 1), segments_processed=segments_processed, segments_accepted=len(resultado), speed_x=round(float(info.duration or 0) / max(time.monotonic() - started_at, 0.001), 2), eta_seconds=0, vad_filter=vad_filter, **_WHISPER_RUNTIME)
            return resultado

        resultado = coletar_segmentos(vad_filter=True)
        if not resultado:
            print("⚠️ VAD não encontrou fala; repetindo transcrição sem filtro de silêncio...")
            _emit_progress(progress_callback, 10, "Nenhuma fala encontrada; reprocessando sem filtro de silêncio", stage="retry_without_vad", **_WHISPER_RUNTIME)
            resultado = coletar_segmentos(vad_filter=False)
        _emit_progress(progress_callback, 95, "Salvando transcrição no cache", stage="saving", segments_processed=len(resultado), segments_accepted=len(resultado), elapsed_seconds=round(max(time.monotonic() - started_at, 0.001), 1), **_WHISPER_RUNTIME)
        if cache_srt_path and resultado:
            _save_srt_cache(cache_srt_path, resultado)
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
    