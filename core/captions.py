"""Geração de legendas ASS a partir de segmentos de transcrição."""

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable

from core.caption_fonts import list_caption_fonts


_ACOUSTIC_MARKER_RE = re.compile(r"\[(?:m[uú]sica|gritos?|aplausos?|risos?|sons?|ru[ií]dos?)[^\]]*\]", re.IGNORECASE)


@dataclass(frozen=True)
class CaptionStyle:
    fontname: str
    fontsize: int
    primary_colour: str
    outline_colour: str
    back_colour: str
    bold: int
    outline: int
    shadow: int
    alignment: int
    margin_v: int


CAPTION_STYLES = {
    "clean": CaptionStyle("Arial", 54, "&H00FFFFFF", "&H00000000", "&H80000000", 0, 3, 1, 2, 110),
    "bold": CaptionStyle("Arial", 60, "&H00FFFFFF", "&H00000000", "&H80000000", 1, 4, 1, 2, 120),
    "highlight": CaptionStyle("Arial", 56, "&H0000FFFF", "&H00000000", "&H80000000", 1, 3, 1, 2, 110),
}

CAPTION_FONTS = ("Arial", "Montserrat", "Poppins", "Bebas Neue", "DejaVu Sans")
CAPTION_POSITIONS = {"top": 8, "center": 5, "bottom": 2}
CAPTION_STROKE_COLORS = {
    "black": ("&H00000000", "#000000"),
    "white": ("&H00FFFFFF", "#FFFFFF"),
    "coral": ("&H005B4BFF", "#FF4B5B"),
}
CAPTION_STROKE_WIDTHS = (0, 1, 2, 3, 4, 6, 8)


def _cor_ass(valor: str, padrao: str = "#FFFFFF") -> str:
    nomes = {nome: hex_color for nome, (_, hex_color) in CAPTION_STROKE_COLORS.items()}
    cor = nomes.get(str(valor or "").strip().lower(), str(valor or padrao).strip())
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", cor):
        raise ValueError("A cor da legenda deve estar no formato hexadecimal #RRGGBB.")
    vermelho, verde, azul = (int(cor[indice:indice + 2], 16) for indice in (1, 3, 5))
    return f"&H00{azul:02X}{verde:02X}{vermelho:02X}"


def _cor_hex(valor: str, padrao: str = "#FFFFFF") -> str:
    nomes = {nome: hex_color for nome, (_, hex_color) in CAPTION_STROKE_COLORS.items()}
    cor = nomes.get(str(valor or "").strip().lower(), str(valor or padrao).strip()).upper()
    if not re.fullmatch(r"#[0-9A-F]{6}", cor):
        raise ValueError("A cor da legenda deve estar no formato hexadecimal #RRGGBB.")
    return cor


def _fundo_ass(cor: str, opacidade: int) -> str:
    alpha = round((100 - opacidade) * 255 / 100)
    return _cor_ass(cor)[0:2] + f"{alpha:02X}" + _cor_ass(cor)[4:]


def _numero(segmento: dict[str, Any], *chaves: str) -> float | None:
    for chave in chaves:
        valor = segmento.get(chave)
        if valor is None:
            continue
        try:
            return float(valor)
        except (TypeError, ValueError):
            return None
    return None


def _texto_limpo(texto: Any) -> str:
    valor = re.sub(r"\s+", " ", str(texto or "")).strip()
    valor = re.sub(r"<[^>]*>", "", valor)
    valor = _ACOUSTIC_MARKER_RE.sub("", valor)
    return re.sub(r"\s+", " ", valor).strip()


def _quebrar_texto(texto: str, limite: int = 42) -> list[str]:
    palavras = texto.split()
    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        candidato = f"{atual} {palavra}".strip()
        if atual and len(candidato) > limite:
            linhas.append(atual)
            atual = palavra
        else:
            atual = candidato
    if atual:
        linhas.append(atual)
    if len(linhas) <= 2:
        return linhas
    return [" ".join(linhas[: len(linhas) // 2]), " ".join(linhas[len(linhas) // 2 :])]


def _palavras_segmento(segmento: dict[str, Any], inicio_base: float, fim_base: float, texto_fallback: str = "") -> list[dict[str, Any]]:
    palavras = segmento.get("palavras") or segmento.get("words") or []
    resultado = []
    for palavra in palavras:
        inicio = _numero(palavra, "inicio", "start")
        fim = _numero(palavra, "fim", "end")
        texto = _texto_limpo(palavra.get("texto", palavra.get("word", ""))) if isinstance(palavra, dict) else ""
        if inicio is None or fim is None or fim <= inicio or not texto or fim <= inicio_base or inicio >= fim_base:
            continue
        resultado.append({
            "inicio": round(max(0.0, inicio - inicio_base), 3),
            "fim": round(min(fim_base - inicio_base, fim - inicio_base), 3),
            "texto": texto,
        })
    if resultado or not texto_fallback:
        return resultado
    inicio = _numero(segmento, "inicio", "start")
    fim = _numero(segmento, "fim", "end")
    palavras_fallback = texto_fallback.split()
    if inicio is None or fim is None or fim <= inicio or not palavras_fallback:
        return []
    duracao = (fim - inicio) / len(palavras_fallback)
    for indice, palavra in enumerate(palavras_fallback):
        palavra_inicio = inicio + indice * duracao
        palavra_fim = fim if indice == len(palavras_fallback) - 1 else palavra_inicio + duracao
        if palavra_fim <= inicio_base or palavra_inicio >= fim_base:
            continue
        resultado.append({
            "inicio": round(max(0.0, palavra_inicio - inicio_base), 3),
            "fim": round(min(fim_base - inicio_base, palavra_fim - inicio_base), 3),
            "texto": palavra,
        })
    return resultado


def gerar_cues_relativos(
    segmentos: Iterable[dict[str, Any]],
    inicio_corte: float,
    fim_corte: float,
    limite_linha: int = 42,
    incluir_palavras: bool = False,
) -> list[dict[str, Any]]:
    """Converte segmentos absolutos em cues relativos ao início do corte."""
    inicio_base = float(inicio_corte)
    fim_base = float(fim_corte)
    if fim_base <= inicio_base:
        raise ValueError("O fim do corte deve ser maior que o início.")

    cues: list[dict[str, Any]] = []
    for segmento in segmentos or []:
        inicio = _numero(segmento, "inicio", "start")
        fim = _numero(segmento, "fim", "end")
        texto = _texto_limpo(segmento.get("texto", segmento.get("text", "")))
        if inicio is None or fim is None or fim <= inicio or not texto:
            continue
        if fim <= inicio_base or inicio >= fim_base:
            continue
        inicio_relativo = max(0.0, inicio - inicio_base)
        fim_relativo = min(fim_base - inicio_base, fim - inicio_base)
        if fim_relativo <= inicio_relativo:
            continue
        linhas = _quebrar_texto(texto, limite_linha)
        cue = {
            "inicio": round(inicio_relativo, 3),
            "fim": round(fim_relativo, 3),
            "texto": "\\N".join(linhas),
        }
        palavras = _palavras_segmento(segmento, inicio_base, fim_base, texto) if incluir_palavras else []
        if incluir_palavras and palavras:
            cue["palavras"] = palavras
        cues.append(cue)
    return cues


def _timestamp_ass(segundos: float) -> str:
    centesimos_total = max(0, round(float(segundos) * 100))
    horas, resto = divmod(centesimos_total, 360000)
    minutos, resto = divmod(resto, 6000)
    segundos_inteiros, centesimos = divmod(resto, 100)
    return f"{horas}:{minutos:02d}:{segundos_inteiros:02d}.{centesimos:02d}"


def _texto_ass_seguro(texto: str) -> str:
    return str(texto).replace("\\", "/").replace("{", "(").replace("}", ")").replace("\r", "").replace("\n", "\\N")


def _limite_linha_ass(tamanho: int) -> int:
    return max(18, min(42, int(960 / (int(tamanho) * 0.52))))


def _texto_ass_karaoke(cue: dict[str, Any], limite_linha: int, uma_linha: bool = False) -> str:
    palavras = cue.get("palavras") or []
    if not palavras:
        return _texto_ass_seguro(cue.get("texto", cue.get("text", "")))
    partes = []
    caracteres_linha = 0
    for palavra in palavras:
        duracao = max(1, round((float(palavra["fim"]) - float(palavra["inicio"])) * 100))
        texto_palavra = _texto_ass_seguro(palavra['texto'])
        separador = " " if caracteres_linha else ""
        if not uma_linha and caracteres_linha and caracteres_linha + len(texto_palavra) + 1 > limite_linha:
            separador = "\\N"
        partes.append(f"{separador}{{\\k{duracao}}}{texto_palavra}")
        caracteres_linha = len(texto_palavra) if separador == "\\N" else caracteres_linha + len(texto_palavra) + (1 if caracteres_linha else 0)
    return "".join(partes)


def gerar_ass(
    cues: Iterable[dict[str, Any]],
    estilo: str = "clean",
    titulo: str = "Growth Engine",
    fonte: str | None = None,
    tamanho: int | None = None,
    posicao: str | None = None,
    stroke_cor: str | None = None,
    stroke_tamanho: int | None = None,
    cor_texto: str | None = None,
    cor_destaque: str | None = None,
    cor_fundo: str | None = None,
    opacidade_fundo: int | None = None,
    posicao_y: float | None = None,
    posicao_x: float | None = None,
    animacao: str | None = None,
    fontes_permitidas: Iterable[str] | None = None,
    uma_linha: bool = False,
) -> str:
    """Gera um script ASS UTF-8 pronto para o filtro subtitles/ass do FFmpeg."""
    try:
        style = CAPTION_STYLES[estilo]
    except KeyError as error:
        raise ValueError(f"Estilo de legenda desconhecido: {estilo}") from error
    permitidas = set(CAPTION_FONTS) | set(fontes_permitidas or [])
    if fonte is not None and fonte not in permitidas:
        raise ValueError(f"Fonte de legenda não permitida: {fonte}")
    if tamanho is not None and not 32 <= int(tamanho) <= 160:
        raise ValueError("O tamanho da legenda deve estar entre 32 e 160.")
    if posicao is not None and posicao not in CAPTION_POSITIONS:
        raise ValueError(f"Posição de legenda desconhecida: {posicao}")
    if stroke_cor is not None and stroke_cor not in CAPTION_STROKE_COLORS and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(stroke_cor)):
        raise ValueError(f"Cor de stroke desconhecida: {stroke_cor}")
    if stroke_tamanho is not None and int(stroke_tamanho) not in CAPTION_STROKE_WIDTHS:
        raise ValueError(f"Espessura de stroke inválida: {stroke_tamanho}")
    texto_ass = _cor_ass(cor_texto) if cor_texto else style.primary_colour
    destaque_ass = _cor_ass(cor_destaque or "#FFE45C")
    fundo_opacidade = 50 if opacidade_fundo is None else int(opacidade_fundo)
    if not 0 <= fundo_opacidade <= 100:
        raise ValueError("A opacidade do fundo deve estar entre 0 e 100.")
    if posicao_y is not None and not 0 <= float(posicao_y) <= 100:
        raise ValueError("A posição vertical da legenda deve estar entre 0 e 100.")
    if posicao_x is not None and not 0 <= float(posicao_x) <= 100:
        raise ValueError("A posição horizontal da legenda deve estar entre 0 e 100.")
    fundo_ass = _fundo_ass(cor_fundo or "#000000", fundo_opacidade)
    style = replace(
        style,
        fontname=fonte or style.fontname,
        fontsize=int(tamanho) if tamanho is not None else style.fontsize,
        alignment=CAPTION_POSITIONS[posicao] if posicao else style.alignment,
        outline=int(stroke_tamanho) if stroke_tamanho is not None else style.outline,
        primary_colour=texto_ass,
        outline_colour=_cor_ass(stroke_cor) if stroke_cor else style.outline_colour,
        back_colour=fundo_ass,
    )
    limite_linha = _limite_linha_ass(style.fontsize)

    eventos = []
    for cue in cues or []:
        inicio = _numero(cue, "inicio", "start")
        fim = _numero(cue, "fim", "end")
        texto_fonte = str(cue.get("texto", cue.get("text", "")))
        if animacao == "karaoke" and not texto_fonte:
            texto_fonte = " ".join(str(palavra.get("texto", palavra.get("text", ""))) for palavra in cue.get("palavras", cue.get("words", [])))
        if animacao == "karaoke":
            texto = _texto_ass_karaoke(cue, limite_linha, uma_linha)
        else:
            texto_original = texto_fonte
            linhas = [texto_original] if uma_linha else _quebrar_texto(texto_original, limite_linha)
            texto = "\\N".join(_texto_ass_seguro(linha) for linha in linhas)
        if inicio is None or fim is None or fim <= inicio or not texto:
            continue
        tamanho_linha = style.fontsize
        if uma_linha:
            tamanho_linha = max(18, min(style.fontsize, int(960 / max(1, len(texto_fonte) * 0.62))))
        tamanho_override = f"\\fs{tamanho_linha}" if uma_linha and tamanho_linha != style.fontsize else ""
        if posicao_x is not None or posicao_y is not None:
            x = round(float(posicao_x if posicao_x is not None else 50) * 10.8)
            posicao_vertical = {"top": 22, "center": 50, "bottom": 78}
            y = round(float(posicao_y if posicao_y is not None else posicao_vertical.get(posicao or "bottom", 78)) * 19.2)
            posicao_override = f"{{{tamanho_override}\\q2\\an5\\pos({x},{y})}}" if uma_linha else f"{{\\an5\\pos({x},{y})}}"
        else:
            posicao_override = f"{{{tamanho_override}\\q2}}" if uma_linha else ""
        eventos.append(f"Dialogue: 0,{_timestamp_ass(inicio)},{_timestamp_ass(fim)},Default,,0,0,0,,{posicao_override}{texto}")

    nome_script = re.sub(r"[^A-Za-z0-9 _.-]", "", str(titulo or "Growth Engine"))[:80] or "Growth Engine"
    return "\n".join(
        [
            "[Script Info]",
            f"Title: {nome_script}",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: None",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{style.fontname},{style.fontsize},{destaque_ass if animacao == 'karaoke' else style.primary_colour},{texto_ass if animacao == 'karaoke' else destaque_ass},{style.outline_colour},{style.back_colour},{style.bold},0,0,0,100,100,0,0,1,{style.outline},{style.shadow},{style.alignment},60,60,{style.margin_v},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *eventos,
            "",
        ]
    )
