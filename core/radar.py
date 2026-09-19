import json
import threading
import time

from core.autopsia import _consultar_qwen
from core.radar_sources import buscar_itens_rss

_RADAR_CACHE = {}
_RADAR_CACHE_LOCK = threading.Lock()
_RADAR_CACHE_TTL = 900
from core.database import get_connection, init_db


def salvar_localizacao(bairro="", cidade="", estado=""):
    init_db()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO preferencias_usuario (id, bairro, cidade, estado, atualizado_em)
            VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET bairro=excluded.bairro, cidade=excluded.cidade,
            estado=excluded.estado, atualizado_em=CURRENT_TIMESTAMP
        """, (bairro.strip(), cidade.strip(), estado.strip()))
        conn.commit()
    finally:
        conn.close()


def obter_localizacao():
    init_db()
    conn = get_connection()
    try:
        row = conn.execute("SELECT bairro, cidade, estado FROM preferencias_usuario WHERE id=1").fetchone()
        return dict(row) if row else {"bairro": "", "cidade": "", "estado": ""}
    finally:
        conn.close()


def _temas_do_canal(limit=50):
    conn = get_connection()
    try:
        analyses = conn.execute("""
            SELECT a.resultado_json FROM analises_conteudo a
            WHERE a.status='concluida' AND a.resultado_json IS NOT NULL
            ORDER BY a.atualizado_em DESC LIMIT 50
        """).fetchall()
        profile = conn.execute("SELECT perfil_json FROM perfis_conteudo WHERE id=1").fetchone()
    finally:
        conn.close()
    topics = []
    if profile:
        try:
            profile_data = json.loads(profile["perfil_json"])
            topics.extend(profile_data.get("temas_nucleares", []))
            topics.extend(profile_data.get("pilares_editoriais", []))
        except json.JSONDecodeError:
            pass
    for row in analyses:
        try:
            data = json.loads(row["resultado_json"])
            topics.extend(data.get("temas", []))
            topics.extend(data.get("pilares", []))
        except (TypeError, ValueError):
            pass
    unique = []
    for topic in topics:
        clean_topic = str(topic).strip()
        if clean_topic and clean_topic.lower() not in {item.lower() for item in unique}:
            unique.append(clean_topic)
    return unique[:5]


NEWS_RELEVANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevante": {"type": "boolean"},
        "score": {"type": "number", "minimum": 0, "maximum": 100},
        "motivo": {"type": "string"},
    },
    "required": ["relevante", "score", "motivo"],
}
def _filtrar_relevancia(items, topics):
    if not items or not topics:
        return []
    filtered = []
    for item in items:
        title_lower = item.get("titulo", "").lower()
        blocked_phrases = ("inscrições", "inscricoes", "resultado preliminar", "homologadas", "edital", "lista de notícias", "lista de noticias", "notícias que movimentaram", "noticias que movimentaram")
        if any(phrase in title_lower for phrase in blocked_phrases):
            continue
        profile_context = ""
        try:
            conn = get_connection()
            row = conn.execute("SELECT perfil_json FROM perfis_conteudo WHERE id=1").fetchone()
            conn.close()
            if row:
                profile = json.loads(row["perfil_json"])
                profile_context = json.dumps({"formatos": profile.get("formatos", []), "pilares": profile.get("pilares_editoriais", [])}, ensure_ascii=False)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        prompt = f"""
Você é um editor de pauta. Decida se esta notícia tem relação concreta com a proposta editorial da conta.
    Não aceite apenas uma palavra em comum. A notícia precisa gerar uma pauta gravável, uma experiência,
    uma análise ou uma continuação coerente com os formatos e pilares da conta.
    Descarte obrigatoriamente: inscrições, resultados administrativos, editais, comunicados institucionais,
    listas genéricas de notícias, celebridades sem conexão, eventos sem ângulo gravável e literatura/arte
    sem relação com a experiência ou formato do canal.
Retorne somente JSON com relevante (boolean), score (0-100) e motivo curto.

TEMAS DA CONTA: {json.dumps(topics, ensure_ascii=False)}
    FORMATOS E PILARES DA CONTA: {profile_context}
TÍTULO: {item.get('titulo')}
FONTE: {item.get('fonte')}
CATEGORIA DA BUSCA: {item.get('categoria')}
"""
        try:
            result = json.loads(_consultar_qwen(prompt, timeout=45, formato=NEWS_RELEVANCE_SCHEMA, model="qwen2.5-coder:14b"))
            if result.get("relevante") and float(result.get("score", 0)) >= 55:
                item["relevancia_score"] = round(float(result["score"]))
                item["motivo"] = result.get("motivo", item.get("motivo", ""))
                filtered.append(item)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return filtered


def buscar_radar(force=False):
    local = obter_localizacao()
    location = ", ".join(part for part in (local["bairro"], local["cidade"], local["estado"]) if part)
    topics = _temas_do_canal()
    cache_key = (location, tuple(topics))
    with _RADAR_CACHE_LOCK:
        cached = _RADAR_CACHE.get(cache_key)
        if not force and cached and time.monotonic() - cached["created_at"] < _RADAR_CACHE_TTL:
            return cached["payload"]
    local_opportunities = []
    niche_opportunities = []
    local_queries = [(f"eventos {location}", "eventos próximos"), (f"notícias {location}", "notícias locais")] if location else []
    niche_queries = []
    for topic in topics[:5]:
        niche_queries.extend(((f"notícias {topic}", topic), (f"{topic} eventos novidades", topic)))
    for query_index, (query, label) in enumerate(local_queries + niche_queries):
        try:
            category = label
            is_niche = (query, label) in niche_queries
            semantic_score = max(45, 100 - query_index * 8) if is_niche else 70
            items = buscar_itens_rss(
                query,
                category,
                limit=6,
                semantic_score=semantic_score,
                include_primary=not is_niche,
                topic=label if is_niche else None,
            )
            (local_opportunities if (query, label) in local_queries else niche_opportunities).extend(items)
        except Exception as error:
            target = local_opportunities if (query, label) in local_queries else niche_opportunities
            target.append({"categoria": "fonte_indisponivel", "titulo": query, "erro": str(error)})
    filtered_local = _filtrar_relevancia(local_opportunities, topics)
    filtered_niche = _filtrar_relevancia(niche_opportunities, topics)
    local_unique = {item.get("link"): item for item in filtered_local if item.get("link")}
    niche_unique = {}
    topic_counts = {}
    for item in filtered_niche:
        topic = item.get("categoria", "")
        if topic_counts.get(topic, 0) >= 3:
            continue
        link = item.get("link")
        if link and link not in niche_unique:
            niche_unique[link] = item
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
    payload = {
        "localizacao_configurada": bool(location),
        "localizacao": local,
        "temas_do_canal": topics,
        "oportunidades_locais": list(local_unique.values()),
        "oportunidades_nicho": list(niche_unique.values()),
        "oportunidades": list(local_unique.values()) + list(niche_unique.values()),
        "mensagem": "Configure a localização para ativar o radar local; o radar de nicho já pode operar." if not location else "Radar local e de nicho ativos.",
    }
    with _RADAR_CACHE_LOCK:
        _RADAR_CACHE[cache_key] = {"created_at": time.monotonic(), "payload": payload}
    return payload