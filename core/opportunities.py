import json

from core.autopsia import _consultar_qwen
from core.opportunities_repository import insert_opportunity, select_opportunities, select_opportunity, select_top15_analyzed_videos, select_video_names


SCORE_WEIGHTS = {
    "atualidade": 0.20,
    "relevancia_canal": 0.25,
    "potencial_local": 0.15,
    "facilidade_gravacao": 0.15,
    "potencial_short": 0.10,
    "evidencia": 0.15,
}


def _clamp(value):
    return max(0.0, min(float(value or 0), 10.0))


def calcular_score(oportunidade):
    score = sum(_clamp(oportunidade.get(field)) * weight for field, weight in SCORE_WEIGHTS.items())
    return round(score * 10, 1)


def _briefing(row, score, perfil_id=1):
    tema = row["tema"] or "tema a definir"
    contexto = row["contexto"] or "Contexto ainda não informado."
    try:
        evidence = json.loads(row.get("evidencia_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        evidence = {}
    video_ids = evidence.get("video_ids") or json.loads(row.get("origem_video_ids") or "[]")
    evidence["video_ids"] = video_ids
    evidence["video_names"] = evidence.get("video_names") or select_video_names(video_ids, perfil_id)
    evidence.setdefault("views", 0)
    evidence.setdefault("likes", 0)
    evidence.setdefault("trechos", [])
    return {
        "titulo_provisorio": row["titulo"],
        "promessa": f"Mostrar o padrão de {tema} observado nos vídeos-base, usando os trechos e sinais de desempenho como evidência.",
        "abertura": f"O que os vídeos-base revelam sobre {tema} e como transformar esse padrão em uma nova pauta?",
        "estrutura": [
            "Apresentar o padrão observado nos vídeos-base.",
            "Reproduzir o conflito ou mecanismo sustentado pelos trechos literais.",
            "Fechar com uma variação original e uma hipótese testável.",
        ],
        "perguntas": ["O que aconteceu?", "Por que isso importa para este canal?", "O que o público pode observar ou fazer?"],
        "tomadas_necessarias": ["referência visual do padrão", "demonstração da nova variação", "fala do criador com conclusão"],
        "versao_short": f"Abrir com o conflito observado em {len(evidence.get('trechos', []))} trecho(s) e testar a nova variação em até 60 segundos.",
        "contexto": contexto,
        "score": score,
        "evidencia": evidence,
        "origem_tipo": row.get("origem_tipo", "autopsia_top15"),
    }


def criar_oportunidade(payload):
    fields = {field: _clamp(payload.get(field)) for field in SCORE_WEIGHTS}
    required = str(payload.get("titulo", "")).strip()
    if not required:
        raise ValueError("titulo é obrigatório")
    score = calcular_score({**payload, **fields})
    opportunity_id = insert_opportunity({"titulo": required, **payload, **fields})
    return {"id": opportunity_id, "score": score, "briefing": gerar_briefing(opportunity_id)}


def listar_oportunidades(limit=30, perfil_id=1):
    result = []
    for item in select_opportunities(limit, perfil_id):
        try:
            evidence = json.loads(item.get("evidencia_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            evidence = {}
        video_ids = evidence.get("video_ids") or json.loads(item.get("origem_video_ids") or "[]")
        evidence["video_ids"] = video_ids
        evidence["video_names"] = evidence.get("video_names") or select_video_names(video_ids, perfil_id)
        item["evidence"] = evidence
        item["score"] = calcular_score(item)
        result.append(item)
    return result


def gerar_briefing(opportunity_id, perfil_id=1):
    row = select_opportunity(opportunity_id, perfil_id)
    if not row:
        raise ValueError("oportunidade não encontrada")
    return _briefing(row, calcular_score(row), perfil_id)


SUGGESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "sugestoes": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "object", "additionalProperties": False, "properties": {
            "titulo": {"type": "string"}, "tema": {"type": "string"},
            "contexto": {"type": "string"}, "relevancia": {"type": "number", "minimum": 0, "maximum": 10},
            "evidencia": {"type": "object", "additionalProperties": False, "properties": {
                "video_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "trechos": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "observacoes": {"type": "array", "items": {"type": "string"}},
                "hipoteses": {"type": "array", "items": {"type": "string"}},
                "views": {"type": "number", "minimum": 0},
                "likes": {"type": "number", "minimum": 0},
            }, "required": ["video_ids", "trechos", "observacoes", "hipoteses", "views", "likes"]},
        }, "required": ["titulo", "tema", "contexto", "relevancia", "evidencia"]}},
    },
    "required": ["sugestoes"], "additionalProperties": False,
}


def _validar_sugestoes(payload, source_rows):
    if not isinstance(payload, dict) or set(payload) != {"sugestoes"}:
        raise ValueError("Resposta de oportunidades fora do contrato JSON.")
    if not isinstance(payload["sugestoes"], list) or not 3 <= len(payload["sugestoes"]) <= 5:
        raise ValueError("A resposta deve conter entre 3 e 5 sugestões.")
    source_ids = {row["video_id"] for row in source_rows}
    validated = []
    for suggestion in payload["sugestoes"]:
        if not isinstance(suggestion, dict) or set(suggestion) != {"titulo", "tema", "contexto", "relevancia", "evidencia"}:
            raise ValueError("Sugestão sem contrato exato de campos.")
        evidence = suggestion["evidencia"]
        if not isinstance(evidence, dict) or set(evidence) != {"video_ids", "trechos", "observacoes", "hipoteses", "views", "likes"}:
            raise ValueError("Evidência sem contrato exato de campos.")
        if not all(isinstance(suggestion[field], str) and suggestion[field].strip() for field in ("titulo", "tema", "contexto")):
            raise ValueError("Título, tema e contexto são obrigatórios.")
        if not isinstance(suggestion["relevancia"], (int, float)) or not 0 <= suggestion["relevancia"] <= 10:
            raise ValueError("Relevância deve estar entre 0 e 10.")
        if not isinstance(evidence["video_ids"], list) or not evidence["video_ids"] or not set(evidence["video_ids"]).issubset(source_ids):
            raise ValueError("A evidência referencia vídeo fora dos Top 15 fornecidos.")
        if not isinstance(evidence["trechos"], list) or not evidence["trechos"] or not all(isinstance(item, str) and item.strip() for item in evidence["trechos"]):
            raise ValueError("A evidência deve conter trechos literais não vazios.")
        if not all(isinstance(evidence[field], list) and all(isinstance(item, str) for item in evidence[field]) for field in ("observacoes", "hipoteses")):
            raise ValueError("Observações e hipóteses devem ser listas de texto.")
        if not all(isinstance(evidence[field], (int, float)) and evidence[field] >= 0 for field in ("views", "likes")):
            raise ValueError("Views e likes da evidência devem ser numéricos.")
        validated.append(suggestion)
    return validated


def gerar_sugestoes_top15(perfil_id=1):
    rows = select_top15_analyzed_videos(perfil_id)
    if not rows:
        raise ValueError("Finalize a Autópsia dos Top 15 antes de gerar sugestões.")
    material = json.dumps(rows, ensure_ascii=False)
    prompt = f"""
Gere de 3 a 5 sugestões de próximos vídeos baseadas SOMENTE nas análises reais dos Top 15 vídeos longos abaixo.
NÃO use notícias, Radar, localização, RSS ou palavras isoladas. Cada sugestão deve citar somente video_ids
presentes nos dados e incluir trechos literais e observações derivados da Autópsia. `relevancia` deve ser
um número entre 0 e 10, nunca percentual ou escala 0-100. Retorne SOMENTE JSON válido, sem Markdown,
texto externo ou campos adicionais, conforme o schema. A origem de todas as pautas é autopsia_top15.
DADOS: {material}
"""
    response = _consultar_qwen(prompt, timeout=240, formato=SUGGESTION_SCHEMA, model="qwen2.5-coder:14b")
    try:
        payload = json.loads(response)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("Qwen retornou oportunidades que não são JSON válido.") from error
    validated = _validar_sugestoes(payload, rows)
    created = []
    for suggestion in validated:
        evidence = suggestion["evidencia"]
        evidence["video_names"] = {
            row["video_id"]: row["titulo"]
            for row in rows
            if row["video_id"] in evidence["video_ids"]
        }
        source_summary = f"Autópsia dos Top 15; vídeos-base: {', '.join(evidence['video_ids'])}; views={evidence['views']}; likes={evidence['likes']}"
        created.append(criar_oportunidade({
            "titulo": suggestion.get("titulo", "").strip(),
            "tema": suggestion.get("tema", ""),
            "contexto": suggestion.get("contexto", ""),
            "fonte": "Autópsia dos Top 15",
            "origem_tipo": "autopsia_top15",
            "origem_video_ids": evidence["video_ids"],
            "origem_resumo": source_summary,
            "evidencia_json": evidence,
            "relevancia_canal": float(suggestion.get("relevancia", 0)) / 10,
            "evidencia": 8,
            "facilidade_gravacao": 6,
            "potencial_short": 7,
        }))
    return created