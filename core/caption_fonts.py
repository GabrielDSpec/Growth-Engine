"""Fontes externas de legenda isoladas por perfil."""

import os
import re
from pathlib import Path

from core.config import obter_pastas_midia

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
_FONT_NAME_RE = re.compile(r"[^A-Za-z0-9 _-]+")


def caption_fonts_dir(perfil_id=1):
    path = Path(obter_pastas_midia(perfil_id)["transcripts"]) / "caption-fonts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _font_name(path):
    return _FONT_NAME_RE.sub("", Path(path).stem).strip(" .-")[:80]


def list_caption_fonts(perfil_id=1):
    directory = caption_fonts_dir(perfil_id)
    return sorted({name for path in directory.iterdir() if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS if (name := _font_name(path))})


def store_caption_font(source_path, original_name, perfil_id=1):
    extension = Path(original_name or "").suffix.lower()
    if extension not in FONT_EXTENSIONS:
        raise ValueError("A fonte deve estar em formato TTF, OTF ou TTC.")
    name = _font_name(original_name)
    if not name:
        raise ValueError("Nome de fonte inválido.")
    target = caption_fonts_dir(perfil_id) / f"{name}{extension}"
    with open(source_path, "rb") as source, open(target, "wb") as destination:
        while chunk := source.read(1024 * 1024):
            destination.write(chunk)
    return {"name": name, "filename": target.name}
