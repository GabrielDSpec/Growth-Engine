"""Detecção multimodal leve para enriquecer a seleção de cortes."""

from __future__ import annotations

import math
import json
import re
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.media_tools import MediaToolError, localizar_ferramentas


SCENE_THRESHOLD = 0.3
AUDIO_RESET_SECONDS = 0.5
AUDIO_PEAK_DB_ABOVE_MEAN = 6.0

_SCENE_TIMESTAMP_RE = re.compile(r"pts_time:(?P<timestamp>\d+(?:\.\d+)?)")
_FRAME_TIMESTAMP_RE = re.compile(r"frame:\s*\d+.*?pts_time:(?P<timestamp>\d+(?:\.\d+)?)")
_AUDIO_LEVEL_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(?P<level>-?(?:\d+(?:\.\d*)?|\.\d+)|-inf)")


@dataclass(frozen=True)
class MediaTrigger:
    timestamp: float
    kind: str
    score: float = 0.0


_TRIGGER_LABELS = {
    "scene_change": "[🎬 CORTE DE CÂMERA]",
    "audio_peak": "[🔊 PICO DE ÁUDIO]",
}


def _run_ffmpeg(command: list[str], timeout: int = 180) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise MediaToolError(f"Análise multimodal excedeu o timeout de {timeout}s.") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "sem detalhes").strip()[-1000:]
        raise MediaToolError(f"FFmpeg retornou {result.returncode}: {detail}")
    return f"{result.stdout}\n{result.stderr}"


def _parse_scene_timestamps(output: str) -> list[float]:
    timestamps = {round(float(match.group("timestamp")), 3) for match in _SCENE_TIMESTAMP_RE.finditer(output)}
    return sorted(timestamps)


def _parse_audio_samples(output: str) -> list[tuple[float, float]]:
    samples = []
    current_timestamp = None
    for line in output.splitlines():
        frame_match = _FRAME_TIMESTAMP_RE.search(line)
        if frame_match:
            current_timestamp = float(frame_match.group("timestamp"))
        level_match = _AUDIO_LEVEL_RE.search(line)
        if level_match and current_timestamp is not None:
            raw_level = level_match.group("level")
            if raw_level != "-inf":
                samples.append((current_timestamp, float(raw_level)))
    return samples


def _audio_peak_triggers(samples: list[tuple[float, float]], threshold_db: float) -> list[MediaTrigger]:
    if not samples:
        return []
    baseline = statistics.fmean(level for _, level in samples)
    return [
        MediaTrigger(timestamp=timestamp, kind="audio_peak", score=level - baseline)
        for timestamp, level in samples
        if level >= baseline + threshold_db
    ]


def _trigger_cache_path(video_path: str | Path, kind: str) -> Path:
    source = Path(video_path)
    return source.with_name(f"{source.stem}_{kind}_cache.json")


def _load_trigger_cache(video_path: str | Path, kind: str, parameters: dict) -> list[MediaTrigger] | None:
    source = Path(video_path)
    cache_path = _trigger_cache_path(source, kind)
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        stat = source.stat()
        if payload.get("version") != 1 or payload.get("source_size") != stat.st_size or payload.get("source_mtime_ns") != stat.st_mtime_ns or payload.get("parameters") != parameters:
            return None
        return [MediaTrigger(float(item["timestamp"]), item["kind"], float(item.get("score", 0.0))) for item in payload.get("triggers", [])]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError, ValueError):
        return None


def _save_trigger_cache(video_path: str | Path, kind: str, parameters: dict, triggers: list[MediaTrigger]) -> None:
    source = Path(video_path)
    try:
        stat = source.stat()
        payload = {
            "version": 1,
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "parameters": parameters,
            "triggers": [{"timestamp": item.timestamp, "kind": item.kind, "score": item.score} for item in triggers],
        }
        _trigger_cache_path(source, kind).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def detect_scene_changes(
    video_path: str | Path,
    *,
    threshold: float = SCENE_THRESHOLD,
    timeout: int = 180,
) -> list[MediaTrigger]:
    """Detecta cortes secos com o filtro nativo de cena do FFmpeg."""
    parameters = {"threshold": threshold}
    cached = _load_trigger_cache(video_path, "scene", parameters)
    if cached is not None:
        return cached
    ffmpeg, _ = localizar_ferramentas()
    output = _run_ffmpeg(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(video_path),
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ],
        timeout=timeout,
    )
    triggers = [MediaTrigger(timestamp=timestamp, kind="scene_change") for timestamp in _parse_scene_timestamps(output)]
    _save_trigger_cache(video_path, "scene", parameters, triggers)
    return triggers


def detect_audio_peaks(
    video_path: str | Path,
    *,
    reset_seconds: float = AUDIO_RESET_SECONDS,
    threshold_db: float = AUDIO_PEAK_DB_ABOVE_MEAN,
    timeout: int = 180,
) -> list[MediaTrigger]:
    """Detecta janelas de energia de áudio acima da média em decibéis RMS."""
    parameters = {"reset_seconds": reset_seconds, "threshold_db": threshold_db}
    cached = _load_trigger_cache(video_path, "audio", parameters)
    if cached is not None:
        return cached
    ffmpeg, _ = localizar_ferramentas()
    output = _run_ffmpeg(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(video_path),
            "-vn",
            "-af",
            f"astats=metadata=1:reset={reset_seconds},ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f",
            "null",
            "-",
        ],
        timeout=timeout,
    )
    triggers = _audio_peak_triggers(_parse_audio_samples(output), threshold_db)
    _save_trigger_cache(video_path, "audio", parameters, triggers)
    return triggers


def scan_visual_triggers(video_path: str | Path, **kwargs) -> list[MediaTrigger]:
    """Executa a detecção visual atualmente suportada: cortes secos de câmera."""
    return detect_scene_changes(video_path, **kwargs)


def scan_media_triggers(video_path: str | Path, **kwargs) -> list[MediaTrigger]:
    """Combina cortes de câmera e picos de áudio em uma lista temporal."""
    triggers = detect_scene_changes(video_path, **kwargs)
    triggers.extend(detect_audio_peaks(video_path, **kwargs))
    return sorted(triggers, key=lambda trigger: (trigger.timestamp, trigger.kind))


def annotate_transcript_segments(
    segments: list[dict],
    triggers: list[MediaTrigger],
    *,
    tolerance_seconds: float = 0.5,
) -> list[dict]:
    """Anexa tags de roteiro aos segmentos sem expor scores matemáticos ao LLM."""
    annotated = []
    for segment in segments:
        start = float(segment.get("inicio", 0))
        end = float(segment.get("fim", start))
        matching_kinds = {
            trigger.kind
            for trigger in triggers
            if start - tolerance_seconds <= trigger.timestamp <= end + tolerance_seconds
        }
        tags = [_TRIGGER_LABELS[kind] for kind in ("scene_change", "audio_peak") if kind in matching_kinds]
        annotated.append({
            "indice": segment.get("indice"),
            "inicio": start,
            "fim": end,
            "texto": str(segment.get("texto", "")),
            "roteiro_tags": tags,
        })
    return annotated


def format_annotated_segments_for_prompt(segments: list[dict]) -> str:
    """Formata segmentos no estilo de roteiro usado pelo prompt do Ollama."""
    lines = []
    for segment in segments:
        start = float(segment.get("inicio", 0))
        end = float(segment.get("fim", start))
        minutes_start, seconds_start = divmod(int(start), 60)
        minutes_end, seconds_end = divmod(int(end), 60)
        tags = " ".join(segment.get("roteiro_tags", []))
        prefix = f"[{minutes_start:02d}:{seconds_start:02d} - {minutes_end:02d}:{seconds_end:02d}]"
        indice = segment.get("indice")
        indice_prefix = f"[{indice}] " if indice is not None else ""
        lines.append(f"{indice_prefix}{prefix} {tags} Texto: '{segment.get('texto', '')}'".strip())
    return "\n".join(lines)
