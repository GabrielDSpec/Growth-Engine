"""Galeria segura de estilos de legenda por perfil."""

import json
import re

from core.captions import CAPTION_FONTS, CAPTION_POSITIONS, CAPTION_STROKE_COLORS, CAPTION_STROKE_WIDTHS
from core.caption_fonts import list_caption_fonts
from core.database import get_connection, init_db
from core.tenant import normalize_profile_id


_STYLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,48}$")
_ALLOWED_ANIMATIONS = {"none", "karaoke"}


def _base_config(style_id, name, style, font, size, position, stroke_color, stroke_size, animation="none", primary_color="#FFFFFF", highlight_color="#FFE45C", background_color="#000000", background_alpha=50, position_y=None, position_x=None, uma_linha=False):
    return {
        "style_id": style_id,
        "name": name,
        "style": style,
        "font": font,
        "size": size,
        "position": position,
        "stroke_color": stroke_color,
        "stroke_size": stroke_size,
        "animation": animation,
        "primary_color": primary_color,
        "highlight_color": highlight_color,
        "background_color": background_color,
        "background_alpha": background_alpha,
        "position_y": position_y,
        "position_x": position_x,
        "uma_linha": uma_linha,
    }


INTERNAL_CAPTION_STYLES = {
    "clean": _base_config("clean", "Clean", "clean", "Arial", 54, "bottom", "black", 3),
    "bold": _base_config("bold", "Bold", "bold", "Arial", 60, "bottom", "black", 4),
    "highlight": _base_config("highlight", "Highlight", "highlight", "Arial", 56, "bottom", "black", 3, "karaoke", primary_color="#FFFFFF", highlight_color="#FFE45C"),
}


def validate_style_config(payload, perfil_id=1):
    if not isinstance(payload, dict):
        raise ValueError("O estilo deve ser um objeto JSON.")
    style_id = str(payload.get("style_id") or payload.get("id") or "").strip().lower()
    name = str(payload.get("name") or "").strip()
    style = str(payload.get("style") or "clean").strip().lower()
    font = str(payload.get("font") or "Arial").strip()
    size = int(payload.get("size", 54))
    uma_linha = bool(payload.get("uma_linha", False))
    position = str(payload.get("position") or "bottom").strip().lower()
    stroke_color = str(payload.get("stroke_color") or "black").strip().lower()
    stroke_size = int(payload.get("stroke_size", 3))
    animation = str(payload.get("animation") or "none").strip().lower()
    colors = {}
    for key, fallback in (("primary_color", "#FFFFFF"), ("highlight_color", "#FFE45C"), ("background_color", "#000000")):
        value = str(payload.get(key) or fallback).strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", value):
            raise ValueError(f"{key} deve estar no formato hexadecimal #RRGGBB.")
        colors[key] = value
    background_alpha = int(payload.get("background_alpha", 50))
    position_y = payload.get("position_y")
    if position_y is not None:
        position_y = float(position_y)
    position_x = payload.get("position_x")
    if position_x is not None:
        position_x = float(position_x)
    if not _STYLE_ID_RE.fullmatch(style_id):
        raise ValueError("style_id inválido; use letras minúsculas, números, _ ou -.")
    if not 1 <= len(name) <= 80:
        raise ValueError("O nome do estilo deve ter entre 1 e 80 caracteres.")
    if style not in {"clean", "bold", "highlight"}:
        raise ValueError("Preset interno inválido.")
    if font not in set(CAPTION_FONTS) | set(list_caption_fonts(perfil_id)) or not 32 <= size <= 160:
        raise ValueError("Fonte ou tamanho de legenda inválido.")
    if position not in CAPTION_POSITIONS:
        raise ValueError(f"Posição de legenda inválida: {position}.")
    if stroke_color not in CAPTION_STROKE_COLORS and not re.fullmatch(r"#[0-9A-Fa-f]{6}", stroke_color):
        raise ValueError(f"Cor de stroke inválida: {stroke_color}.")
    if stroke_size not in CAPTION_STROKE_WIDTHS:
        raise ValueError(f"Espessura de stroke inválida: {stroke_size}.")
    if animation not in _ALLOWED_ANIMATIONS or not 0 <= background_alpha <= 100 or (position_y is not None and not 0 <= position_y <= 100) or (position_x is not None and not 0 <= position_x <= 100):
        raise ValueError("A animação informada ainda não é suportada pelo renderizador.")
    return _base_config(style_id, name, style, font, size, position, stroke_color, stroke_size, animation, **colors, background_alpha=background_alpha, position_y=position_y, position_x=position_x, uma_linha=uma_linha)


def ensure_internal_styles(perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    init_db()
    conn = get_connection()
    try:
        for style_id, config in INTERNAL_CAPTION_STYLES.items():
            conn.execute(
                "INSERT INTO caption_styles (perfil_id, style_id, nome, config_json, protegido) VALUES (?, ?, ?, ?, 1) ON CONFLICT(perfil_id, style_id) DO UPDATE SET nome=excluded.nome, config_json=excluded.config_json, protegido=1",
                (perfil_id, style_id, config["name"], json.dumps(config, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()


def list_caption_styles(perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    ensure_internal_styles(perfil_id)
    conn = get_connection()
    try:
        rows = conn.execute("SELECT style_id, nome, config_json, protegido FROM caption_styles WHERE perfil_id=? ORDER BY protegido DESC, nome", (perfil_id,)).fetchall()
        result = []
        for row in rows:
            config = json.loads(row["config_json"])
            config["protected"] = bool(row["protegido"])
            result.append(config)
        return result
    finally:
        conn.close()


def import_caption_style(payload, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    config = validate_style_config(payload)
    if config["style_id"] in INTERNAL_CAPTION_STYLES:
        raise ValueError("Não é permitido substituir um estilo interno protegido.")
    ensure_internal_styles(perfil_id)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO caption_styles (perfil_id, style_id, nome, config_json, protegido) VALUES (?, ?, ?, ?, 0) ON CONFLICT(perfil_id, style_id) DO UPDATE SET nome=excluded.nome, config_json=excluded.config_json",
            (perfil_id, config["style_id"], config["name"], json.dumps(config, ensure_ascii=False)),
        )
        conn.commit()
        return config
    finally:
        conn.close()


def get_caption_style(style_id, perfil_id=1):
    perfil_id = normalize_profile_id(perfil_id)
    ensure_internal_styles(perfil_id)
    conn = get_connection()
    try:
        row = conn.execute("SELECT config_json FROM caption_styles WHERE perfil_id=? AND style_id=?", (perfil_id, style_id)).fetchone()
        if not row:
            raise ValueError("Estilo de legenda não encontrado.")
        return json.loads(row["config_json"])
    finally:
        conn.close()
