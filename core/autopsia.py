import os
import json
import urllib.request
from core.database import DB_PATH, get_connection, init_db
from core.transcriber import transcrever_video_youtube

def _consultar_qwen(prompt, timeout=180, formato=None, model="qwen2.5:14b"):
    payload = {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}}
    if formato:
        payload["format"] = formato
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")).get("response", "")

def _analisar_video_individual(video):
    descricao = video.get("descricao") or "[descrição não sincronizada]"
    transcricao = video.get("transcricao") or "[transcrição indisponível]"
    views = int(video.get("views") or 0)
    likes = int(video.get("likes") or 0)
    taxa_likes = round((likes / views) * 100, 4) if views else None
    prompt = f"""
Você é um analista forense de conteúdo. Analise SOMENTE o registro abaixo.
Não invente fatos, contexto, falas ou causas. Separe observações de hipóteses.
Se um campo estiver ausente, escreva "evidência insuficiente".
Não trate visualizações ou likes como prova de causalidade.

REGISTRO REAL:
ID: {video['video_id']}
FORMATO: {video['tipo']}
TÍTULO: {video.get('titulo') or ''}
DESCRIÇÃO: {descricao}
DATA DE PUBLICAÇÃO: {video.get('data_publicacao') or '[ausente]'}
VISUALIZAÇÕES: {views}
LIKES: {likes}
TAXA DE LIKES SOBRE VIEWS: {taxa_likes if taxa_likes is not None else '[indisponível]'}%
TRANSCRIÇÃO LITERAL DISPONÍVEL: {transcricao}

Retorne JSON válido com exatamente estas chaves:
{{
  "id": "{video['video_id']}",
  "observacoes_comprovadas": ["..."],
  "trechos_literais_relevantes": ["..."],
  "hipoteses": ["..."],
  "dados_ausentes": ["..."]
}}
"""
    try:
        resposta = _consultar_qwen(prompt, formato="json")
        analise = json.loads(resposta)
        analise["id"] = video["video_id"]
        return analise
    except Exception as e:
        return {"id": video["video_id"], "erro": str(e)}

def rodar_autopsia_top15():
    """Analisa separadamente os 15 melhores longos e os 15 melhores Shorts."""
    init_db()
    conn = get_connection()
    try:
        videos = {}
        for tipo in ("video", "short"):
            rows = conn.execute("""
                SELECT video_id, titulo, descricao, data_publicacao, tipo, views, likes, transcricao
                FROM videos_historico
                WHERE tipo = ?
                ORDER BY CAST(views AS INTEGER) DESC
                LIMIT 15
            """, (tipo,)).fetchall()
            videos[tipo] = [dict(row) for row in rows]
    finally:
        conn.close()

    if not videos["video"] and not videos["short"]:
        print("📭 Nenhum vídeo sincronizado para analisar.")
        return

    relatorios = {}
    for tipo, itens in videos.items():
        relatorios[tipo] = []
        print(f"🧠 Analisando {len(itens)} {tipo}(s) individualmente...")
        for indice, video in enumerate(itens, 1):
            if not video.get("transcricao"):
                video["transcricao"] = transcrever_video_youtube(video["video_id"])
            print(f"  [{indice}/{len(itens)}] {video['titulo']}")
            relatorios[tipo].append(_analisar_video_individual(video))

    prompt = f"""
Você é um estrategista de conteúdo. Consolide os relatórios individuais abaixo.
Use somente as observações fornecidas. Não invente dados e não transforme hipótese em fato.
Compare LONGOS e SHORTS separadamente, considerando título, descrição, transcrição literal,
visualizações, likes, taxa de likes e data de publicação. A data serve para contexto temporal,
mas não prova que uma estratégia causou desempenho.

RELATÓRIOS INDIVIDUAIS DE VÍDEOS LONGOS:
{json.dumps(relatorios['video'], ensure_ascii=False, indent=2)}

RELATÓRIOS INDIVIDUAIS DE SHORTS:
{json.dumps(relatorios['short'], ensure_ascii=False, indent=2)}

Entregue Markdown pt-BR com:
1. Padrões observáveis dos 15 longos.
2. Padrões observáveis dos 15 Shorts.
3. Diferenças entre os formatos.
4. Relação possível com data de publicação, explicitando limites da evidência.
5. Três hipóteses testáveis para próximos conteúdos.
6. Dados ausentes que impedem conclusões (por exemplo, retenção por segundo).
"""
    try:
        resposta = _consultar_qwen(prompt, timeout=240)
        print("\n" + "=" * 70)
        print("📊 AUTÓPSIA DOS TOP 15 LONGOS E TOP 15 SHORTS")
        print("=" * 70)
        print(resposta)
        print("=" * 70)
    except Exception as e:
        print(f"⚠️ Erro ao consolidar autópsia: {e}")

def listar_ranking(limite=15):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    rows = cursor.execute("""
        SELECT video_id, titulo, tipo, views, status, data_publicacao 
        FROM videos_historico 
        ORDER BY CAST(views AS INTEGER) DESC 
        LIMIT ?
    """, (limite,)).fetchall()
    conn.close()
    
    print(f"\n🏆 TOP {limite} VÍDEOS MAIS VISTOS DO CANAL:")
    print("-" * 75)
    for r in rows:
        print(f"👁️ {r['views']:>6} views | [{r['tipo'].upper()}] {r['titulo'][:50]}... (ID: {r['video_id']})")
    print("-" * 75)

def rodar_autopsia_com_qwen():
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    all_videos = cursor.execute("SELECT video_id, titulo, tipo, views FROM videos_historico ORDER BY CAST(views AS INTEGER) DESC").fetchall()
    conn.close()
    
    if not all_videos:
        print("📭 Nenhum vídeo no banco para auditar.")
        return

    videos = [dict(r) for r in all_videos]
    top_cut = max(1, int(len(videos) * 0.2))
    top_perf = videos[:top_cut]
    bottom_perf = videos[-top_cut:] if len(videos) > 1 else videos

    top_str = json.dumps(top_perf, ensure_ascii=False, indent=2)
    bottom_str = json.dumps(bottom_perf, ensure_ascii=False, indent=2)

    prompt = f"""
    Você é o Head de Growth e Estratégia de Conteúdo do canal '@aquelecaradebigode'.
    Analise somente os dados reais fornecidos abaixo. Não invente fatos, falas, causas ou contexto.
    Se os dados não permitirem uma conclusão, escreva explicitamente "evidência insuficiente".
    Não trate correlação de views com causalidade comprovada.
    Analise o desempenho histórico real sincronizado do YouTube (Top vs Bottom em visualizações de {len(videos)} vídeos analisados):

    TOP PERFORMERS (Ouro - Mais visualizados):
    {top_str}

    LOW PERFORMERS (Lixo/Sub-indexados - Menos visualizados):
    {bottom_str}

    Responda em formato executivo Markdown pt-BR:
    1. 🏆 PADRÃO VENCEDOR: O que os títulos/temas do Top têm em comum? (curiosidade, tom, estrutura)
    2. 📉 FALHA ESTRUTURAL: Por que os Bottoms falharam? (título fraco, tema genérico, desalinhamento)
    3. 🎯 PLAYBOOK PRÓXIMO LOTE: 3 recomendações acionáveis de 1 linha para o que produzir agora.
    """

    print("🧠 Consultando Qwen2.5:14b para autópsia profunda dos 58 itens...")
    
    payload = {
        "model": "qwen2.5:14b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1}
    }
    
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            resposta_ai = data.get("response", "Sem resposta da IA.")
            print("\n" + "="*60)
            print("📊 RELATÓRIO DE AUTÓPSIA (QWEN 2.5:14B)")
            print("="*60)
            print(resposta_ai)
            print("="*60)
    except Exception as e:
        print(f"⚠️ Erro ao comunicar com Ollama: {e}")

def auditar_amostra_empirica(limite_top=3, limite_bottom=3):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    tops = cursor.execute("SELECT video_id, titulo, tipo, views, likes, transcricao FROM videos_historico WHERE views > 0 ORDER BY CAST(views AS INTEGER) DESC LIMIT ?", (limite_top,)).fetchall()
    bots = cursor.execute("SELECT video_id, titulo, tipo, views, likes, transcricao FROM videos_historico WHERE views > 0 ORDER BY CAST(views AS INTEGER) ASC LIMIT ?", (limite_bottom,)).fetchall()
    conn.close()

    dataset = {"top_performers": [], "low_performers": []}

    print("🔍 Coletando/garantindo transcrições reais para auditoria empírica...")
    for row in tops:
        d = dict(row)
        if not d['transcricao']:
            d['transcricao'] = transcrever_video_youtube(d['video_id'])
        dataset["top_performers"].append(d)

    for row in bots:
        d = dict(row)
        if not d['transcricao']:
            d['transcricao'] = transcrever_video_youtube(d['video_id'])
        dataset["low_performers"].append(d)

    prompt = f"""
    Você é um cientista de dados de retenção e analista forense de conteúdo do canal @aquelecaradebigode.
    Proibido alucinar. Baseie-se APENAS nos dados e transcrições reais fornecidos abaixo.
    Não invente trechos, timestamps, intenções ou eventos que não estejam no material.
    O dataset não contém retenção por segundo. Portanto, não afirme retenção, abandono ou o conteúdo dos primeiros 3 segundos.
    Quando uma conclusão não puder ser comprovada, escreva "evidência insuficiente".
    Taxa de engajamento = likes / views (quando aplicável).

    DADOS REAIS (TOP PERFORMERS):
    {json.dumps(dataset['top_performers'], ensure_ascii=False, indent=2)}

    DADOS REAIS (LOW PERFORMERS):
    {json.dumps(dataset['low_performers'], ensure_ascii=False, indent=2)}

    Gere um relatório forense objetivo em Markdown (pt-BR):
    1. 🔬 EVIDÊNCIA OBSERVÁVEL (TOP): Cite literalmente trechos presentes nas transcrições e compare-os com títulos e métricas, sem afirmar causalidade.
    2. 🩸 DIFERENÇAS OBSERVÁVEIS (LOW): Compare títulos, métricas e linguagem realmente presente nas transcrições; não diagnostique retenção sem dados de retenção.
    3. 📐 HIPÓTESES TESTÁVEIS: Liste até 3 hipóteses claramente identificadas como hipóteses, cada uma acompanhada do dado que seria necessário para confirmá-la.
    """

    print("🧠 Rodando autópsia forense empírica com Qwen2.5:14b...")
    payload = {
        "model": "qwen2.5:14b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1}
    }
    
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print("\n" + "="*70)
            print("forense_report = RELATÓRIO FORENSE EMPÍRICO (SEM ALUCINAÇÃO)")
            print("="*70)
            print(data.get("response", ""))
            print("="*70)
    except Exception as e:
        print(f"⚠️ Erro ao consultar Ollama: {e}")