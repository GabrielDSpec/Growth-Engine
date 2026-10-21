"""Dossiê editorial persistente e colheita ranqueada de momentos."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from core.config import obter_pastas_midia


DOSSIER_SCHEMA_VERSION = 1
DOSSIER_ALGORITHM_VERSION = "dossier-v5-global-index-then-cut-editorial"
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _json_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_video_id(video_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(video_id)).strip("._") or "video"


def dossier_path(video_id, perfil_id=1):
    return Path(obter_pastas_midia(perfil_id)["editorial_dossiers"]) / f"{_safe_video_id(video_id)}_dossier.json"


def _source_signature(source_path):
    if not source_path:
        return None
    try:
        stat = os.stat(source_path)
    except OSError:
        return None
    digest = hashlib.sha256()
    try:
        with open(source_path, "rb") as source_file:
            for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return {"path": os.path.abspath(source_path), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest.hexdigest()}


def _fingerprints(source_path, segments, multimodal_context, parameters):
    return {
        "source": _json_hash(_source_signature(source_path)),
        "transcription": _json_hash(segments),
        "multimodal": _json_hash(multimodal_context or ""),
        "parameters": _json_hash(parameters),
    }


def _atomic_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp-{os.getpid()}-{threading.get_ident()}")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _lock_key(video_id, perfil_id):
    return int(perfil_id), str(video_id)


@contextmanager
def dossier_lock(video_id, perfil_id=1):
    key = _lock_key(video_id, perfil_id)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        yield


def load_dossier(video_id, perfil_id=1):
    path = dossier_path(video_id, perfil_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != DOSSIER_SCHEMA_VERSION:
        return None
    if (payload.get("editorial_run") or {}).get("algorithm_version") != DOSSIER_ALGORITHM_VERSION:
        return None
    chapters = payload.get("capitulos")
    if not isinstance(chapters, list):
        return None
    return payload


def _is_valid_dossier(dossier, source_path, segments, multimodal_context, parameters):
    if not segments:
        return False
    if source_path and not os.path.isfile(source_path):
        return False
    chapters = dossier.get("capitulos")
    if not isinstance(chapters, list):
        return False
    if not chapters and not dossier.get("melhores_momentos"):
        return False
    if (dossier.get("editorial_run") or {}).get("algorithm_version") != DOSSIER_ALGORITHM_VERSION:
        return False
    editorial_run = dossier.get("editorial_run") or {}
    if str(editorial_run.get("status") or "completed").casefold() != "completed":
        return False
    steps_total = editorial_run.get("steps_total")
    steps_completed = editorial_run.get("steps_completed")
    if steps_total is not None and steps_completed is not None and steps_completed < steps_total:
        return False
    diagnostics = editorial_run.get("diagnostics") or []
    failure_statuses = {"timeout_or_network", "failed", "error", "invalid_json", "editorial_unavailable", "editorial_below_minimum"}
    if any(str(item.get("status") or "").casefold() in failure_statuses for item in diagnostics if isinstance(item, dict)):
        return False
    return dossier.get("fingerprints") == _fingerprints(source_path, segments, multimodal_context, parameters)


def _moment_from_candidate(candidate, index):
    try:
        inicio = float(candidate.get("inicio") if candidate.get("inicio") is not None else candidate.get("inicio_segundos"))
        fim = float(candidate.get("fim") if candidate.get("fim") is not None else candidate.get("fim_segundos"))
    except (KeyError, TypeError, ValueError):
        return None
    if fim <= inicio:
        return None
    score = candidate.get("score_viralidade", candidate.get("score_vaca_roxa", 0))
    try:
        score = max(0, min(100, int(round(float(score)))))
    except (TypeError, ValueError):
        score = 0
    moment = dict(candidate)
    moment.update({
        "id": str(candidate.get("id") or f"moment-{index:04d}"),
        "inicio": inicio,
        "fim": fim,
        "titulo_sugerido": candidate.get("titulo_sugerido") or candidate.get("titulo") or "",
        "motivo_da_escolha": candidate.get("motivo_da_escolha") or candidate.get("descricao_publicacao") or candidate.get("gancho") or "",
        "score_viralidade": score,
    })
    return moment


def _multimodal_signals(multimodal_context):
    signals = []
    for line in str(multimodal_context or "").splitlines():
        match = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", line)
        if not match:
            continue
        signals.append({
            "inicio": float(match.group(1)),
            "fim": float(match.group(2)),
            "tipo": "camera" if "CÂMERA" in line.upper() or "CAMERA" in line.upper() else "audio",
            "descricao": line.strip(),
        })
    return signals


def _overlap_ratio(start, end, moment):
    overlap = max(0.0, min(end, moment["fim"]) - max(start, moment["inicio"]))
    duration = max(end - start, 0.001)
    return min(1.0, overlap / duration)


def build_semantic_heatmap(segments, moments, multimodal_context):
    """Create an explainable interval map from transcript and editorial evidence."""
    signals = _multimodal_signals(multimodal_context)
    intervals = []
    for segment in segments or []:
        try:
            start = float(segment["inicio"])
            end = float(segment["fim"])
        except (KeyError, TypeError, ValueError):
            continue
        overlapping = [moment for moment in moments if _overlap_ratio(start, end, moment) > 0]
        matching_signals = [signal for signal in signals if _overlap_ratio(start, end, signal) > 0]
        best_score = max((moment.get("score_viralidade", 0) * _overlap_ratio(start, end, moment) for moment in overlapping), default=0)
        intensity = int(round(min(100, best_score + min(20, len(matching_signals) * 10))))
        hooks = []
        entities = []
        for moment in overlapping:
            hook = moment.get("gancho") or moment.get("promessa") or moment.get("titulo_sugerido")
            if hook and hook not in hooks:
                hooks.append(hook)
            for entity in moment.get("entidades", []) or []:
                if entity not in entities:
                    entities.append(entity)
        intervals.append({
            "inicio": start,
            "fim": end,
            "intensidade": intensity,
            "texto": segment.get("texto", ""),
            "ganchos": hooks,
            "entidades": entities,
            "sinais_multimodais": matching_signals,
        })
    return {"intervalos": intervals, "sinais": signals}


def build_dossier(video_id, perfil_id, source_path, segments, duration_seconds, multimodal_context, analysis, parameters=None):
    parameters = parameters or {}
    chapters = []
    for index, chapter in enumerate(analysis.get("capitulos") or [], 1):
        if not isinstance(chapter, dict):
            continue
        try:
            inicio = float(chapter.get("inicio", chapter.get("inicio_segundos")))
            fim = float(chapter.get("fim", chapter.get("fim_segundos")))
        except (TypeError, ValueError):
            continue
        if fim <= inicio:
            continue
        chapters.append({"id": f"chapter-{index:04d}", "titulo": str(chapter.get("titulo") or f"Capítulo {index}"), "inicio": inicio, "fim": fim})
    textos = [str(segment.get("texto") or "").strip() for segment in segments if segment.get("texto")]
    resumo_global = analysis.get("resumo_conteudo") or parameters.get("resumo_global") or (
        " ".join(textos) if len(textos) <= 16 else " ".join(textos[:8] + ["..."] + textos[-8:])
    )[:3500]
    raw_moments = analysis.get("candidatos") or analysis.get("editorial_candidatos") or analysis.get("melhores_momentos") or []
    moments = [
        moment
        for index, candidate in enumerate(raw_moments, 1)
        if isinstance(candidate, dict)
        for moment in [_moment_from_candidate(candidate, index)]
        if moment is not None
    ]
    moments.sort(key=lambda item: (-item["score_viralidade"], item["inicio"], item["fim"]))
    heatmap = build_semantic_heatmap(segments, moments, multimodal_context)
    themes = parameters.get("temas_principais") or [
        moment.get("angulo_diferente") or moment.get("titulo_sugerido")
        for moment in moments[:5]
        if moment.get("angulo_diferente") or moment.get("titulo_sugerido")
    ]
    entities = []
    for interval in heatmap["intervalos"]:
        for entity in interval["entidades"]:
            if entity not in entities:
                entities.append(entity)
    dossier = {
        "schema_version": DOSSIER_SCHEMA_VERSION,
        "video_id": str(video_id),
        "perfil_id": int(perfil_id),
        "source": {"path": source_path, "duration_seconds": duration_seconds},
        "transcription": {"segments_count": len(segments), "segments_hash": _json_hash(segments)},
        "multimodal": {"context_hash": _json_hash(multimodal_context or "")},
        "editorial_run": {
            "algorithm_version": DOSSIER_ALGORITHM_VERSION,
            "created_at": _now(),
            "model": parameters.get("model", "qwen2.5:14b"),
            "prompt_version": parameters.get("prompt_version", "editorial-steps-v2"),
            "status": analysis.get("status", "completed"),
            "steps_total": analysis.get("steps_total"),
            "steps_completed": analysis.get("steps_completed"),
            "diagnostics": analysis.get("diagnostico", []),
            "rejections": analysis.get("rejeicoes", []),
        },
        "resumo_global": resumo_global,
        "capitulos": chapters,
        "temas_principais": themes,
        "mapa_calor_semantico": {
            **heatmap,
            "temas": themes,
            "entidades": entities,
        },
        "melhores_momentos": moments,
        "fingerprints": _fingerprints(source_path, segments, multimodal_context, parameters),
    }
    _atomic_write(dossier_path(video_id, perfil_id), dossier)
    return dossier


def _overlaps(first, second):
    intersection = max(0.0, min(first["fim"], second["fim"]) - max(first["inicio"], second["inicio"]))
    shortest = min(first["fim"] - first["inicio"], second["fim"] - second["inicio"])
    return shortest > 0 and intersection / shortest > 0.4


def harvest_candidates(dossier, existing_cuts, limit=None):
    moments = list(dossier.get("melhores_momentos", []))
    moments.sort(key=lambda item: (-item.get("score_viralidade", 0), item["inicio"], item["fim"]))
    blocked = [
        cut for cut in (existing_cuts or [])
        if isinstance(cut, dict) and str(cut.get("status") or "").casefold() not in {"excluido", "falhou", "cancelado"}
    ]
    available = [moment for moment in moments if not any(_overlaps(moment, cut) for cut in blocked)]
    if limit is None:
        return available
    return available[:max(0, int(limit))]


def load_or_build_dossier(video_id, perfil_id, source_path, segments, duration_seconds, multimodal_context, existing_cuts, analysis_factory, parameters=None, limit=None):
    parameters = parameters or {}
    with dossier_lock(video_id, perfil_id):
        dossier = load_dossier(video_id, perfil_id)
        if dossier is None or not _is_valid_dossier(dossier, source_path, segments, multimodal_context, parameters):
            resume_analysis = None
            if dossier:
                resume_analysis = {
                    "status": "running",
                    "resumo_conteudo": dossier.get("resumo_global", ""),
                    "candidatos": dossier.get("melhores_momentos", []),
                    "diagnostico": (dossier.get("editorial_run") or {}).get("diagnostics", []),
                }

            def persist_partial(partial_analysis):
                build_dossier(video_id, perfil_id, source_path, segments, duration_seconds, multimodal_context, partial_analysis, parameters)

            try:
                accepts_resume = len(inspect.signature(analysis_factory).parameters) >= 2
            except (TypeError, ValueError):
                accepts_resume = True
            analysis = analysis_factory(persist_partial, resume_analysis) if accepts_resume else analysis_factory(persist_partial)
            dossier = build_dossier(video_id, perfil_id, source_path, segments, duration_seconds, multimodal_context, analysis, parameters)
            cache_hit = False
        else:
            analysis = None
            cache_hit = True
        candidates = harvest_candidates(dossier, existing_cuts, limit=limit)
        return dossier, candidates, analysis, cache_hit