import json
import os
import re
import shutil
import subprocess
import cv2
import requests
from tqdm import tqdm
from core.media_tools import MediaToolError, _run, localizar_ferramentas, obter_duracao
from core.config import DIRETORIO_PROJETO, PASTA_LONGOS, PASTA_SHORTS, PASTA_ARQUIVO, obter_pastas_midia
from core.utils import registrar_log, carregar_cache_metadados, salvar_cache_metadados, calcular_hash_arquivo
from core.transcriber import transcrever_arquivo_local_segmentos

MIN_CORTES_PADRAO = 9
MAX_CORTES_SOLICITADOS = 15
MAX_TENTATIVAS_QWEN = 3


def _montar_prompt(transcricao_texto, duracao_total_seg, segmentos, tentativa, cortes_atuais, rejeicoes, duracao_minima=10, duracao_maxima=90, titulo_original=""):
    feedback = ""
    if rejeicoes:
        feedback = "\nCorrija estes problemas observados nas rodadas anteriores:\n- " + "\n- ".join(rejeicoes[-12:])
    return f"""Você é Curador Sênior de Atenção e Diretor de Cortes (Teoria da Vaca Roxa).
    Analise exclusivamente o texto abaixo. Não invente falas, eventos, contexto ou timestamps.
    Gere candidatos suficientes para que, após a validação, existam pelo menos {MIN_CORTES_PADRAO} cortes independentes.
    Nesta rodada, retorne entre {MIN_CORTES_PADRAO} e {MAX_CORTES_SOLICITADOS} candidatos quando houver material.
    Nunca invente falas, timestamps ou segmentos apenas para atingir a quantidade.
    Os cortes já aceitos nesta execução: {len(cortes_atuais)}. Esta é a rodada {tentativa} de {MAX_TENTATIVAS_QWEN}.
    Escolha somente segmentos existentes na transcrição numerada. Retorne segmento_inicio e segmento_fim
    como índices inteiros inclusivos copiados exatamente da numeração; não invente índices nem timestamps.
    O trecho deve ser uma sequência contínua de segmentos e a diferença entre o primeiro início e o último fim
    precisa ficar entre {duracao_minima} e {duracao_maxima} segundos. Nunca selecione apenas um segmento curto
    para depois tentar completar a duração com texto inventado.
    Os limites precisam preservar frases completas: comece no início de uma ideia, não no meio de uma frase,
    e termine somente depois de uma frase concluída (pontuação final ou encerramento inequívoco da fala).
    Nunca corte palavra, oração ou contexto no meio. Se o Whisper dividiu uma frase em vários segmentos,
    inclua todos os segmentos necessários para fechá-la, respeitando a duração máxima.
    Para cada corte, crie um título editorial em pt-BR com 35 a 55 caracteres, pronto para ser usado no YouTube.
    O título deve ser uma manchete natural, específica e engajante: use uma palavra-chave ou entidade realmente
    presente no trecho, deixe claro o conflito, descoberta ou resultado e crie curiosidade honesta. Não copie uma
    frase inteira da transcrição, não use reticências, não entregue um fragmento sem verbo e não comece com
    "Trecho", "Corte" ou "Parte". Não use #shorts, emojis, promessa exagerada ou afirmações ausentes.
        Aprove um corte somente se ele tiver uma única ideia, conflito ou contraste claro, começo autossuficiente,
        desenvolvimento e conclusão. O início deve conter o gancho, sem saudação ou contexto dependente de outro vídeo.
        Quando um destaque forte aparecer mais tarde no trecho, você pode sinalizar a montagem
        "gancho_contexto_retorno": use uma frase literal do destaque como gancho inicial, depois o contexto,
        e retorne ao momento do destaque. Isso é uma oportunidade editorial, não uma licença para inventar
        texto ou timestamps; todos os elementos precisam existir na transcrição.
        Rejeite cortes que sejam apenas introdução, explicação genérica, anúncio, chamada para curso, cupom ou autopromoção.
        Não corte uma frase no meio. Cada corte deve ter entre {duracao_minima} e {duracao_maxima} segundos, conforme a faixa escolhida pelo usuário.
        Dê seis subnotas independentes de 0 a 100. Elas medem potencial editorial observável, não desempenho garantido:
        distintividade (25%): contraste, novidade ou ângulo memorável;
        gancho (20%): força e clareza do início;
        clareza_promessa (15%): benefício compreensível sem contexto externo;
        autossuficiencia (15%): ideia completa no próprio corte;
        compartilhabilidade (15%): motivo concreto para comentar ou enviar a alguém;
        evidencia (10%): título, gancho e conclusão sustentados literalmente pelo trecho.
        Não use retenção, CTR ou alcance como se fossem medidos; esses dados só existem após publicação.
    Título original do vídeo: {titulo_original or "não informado"}
    Antes de propor cortes, confira o título original contra a transcrição. Identifique erros ortográficos,
    nomes próprios, entidades ou afirmações do título que não correspondam ao contexto. Corrija somente o que
    puder ser confirmado pela transcrição e mantenha o sentido factual. Para cada corte, o título editorial deve
    ser coerente com o vídeo original e não pode contradizer seu tema.
    Analise a transcrição segmentada ({duracao_total_seg:.1f}s):
    {transcricao_texto}
        Retorne EXCLUSIVAMENTE um objeto JSON puro, sem markdown, sem comentários e sem texto antes ou depois.
        A chave cortes deve sempre ser uma lista; se houver material, nunca a deixe vazia.
        {{
            "cortes": [{{
            "titulo": "título factual e específico",
            "segmento_inicio": int,
            "segmento_fim": int,
            "gancho": "frase ou ideia literal do início do trecho",
            "montagem": "continua ou gancho_contexto_retorno",
            "gancho_inicio": "frase literal usada como abertura, se houver",
            "destaque": "frase literal do momento de maior destaque",
            "promessa": "o que o espectador entenderá",
            "virada": "contraste ou descoberta presente no trecho",
            "conclusao": "como a ideia se fecha no próprio trecho",
            "autossuficiente": true,
            "promocional": false,
            "pontuacoes": {{
                "distintividade": 0,
                "gancho": 0,
                "clareza_promessa": 0,
                "autossuficiencia": 0,
                "compartilhabilidade": 0,
                "evidencia": 0
            }}
        }}]
    }}
    Retorne pelo menos {MIN_CORTES_PADRAO} cortes quando existirem trechos que atendam às regras e nunca exceda {MAX_CORTES_SOLICITADOS}.
    {feedback}
    """


def _extrair_candidatos(resposta):
    texto = resposta.json().get("response", "").replace("```json", "").replace("```", "").strip()
    payload = json.loads(texto)
    if isinstance(payload, dict):
        payload = payload.get("cortes", payload.get("suggestions", []))
    return payload if isinstance(payload, list) else []


def _intervalo_corte(corte):
    return (round(float(corte["inicio"]), 3), round(float(corte["fim"]), 3))


def _deduplicar_cortes(cortes):
    resultado = []
    intervalos = set()
    for corte in cortes:
        intervalo = _intervalo_corte(corte)
        if intervalo in intervalos:
            continue
        intervalos.add(intervalo)
        resultado.append(corte)
    return resultado


def calcular_score_observavel(texto, segmentos):
    """Pontua evidências editoriais do trecho sem fingir métricas de publicação."""
    palavras = [palavra for palavra in _texto_normalizado(texto).split() if len(palavra) >= 4]
    unicas = len(set(palavras))
    distintividade = min(100, round((unicas / max(len(palavras), 1)) * 130))
    inicio = segmentos[0].get("texto", "") if segmentos else ""
    hook_words = len(_texto_normalizado(inicio).split())
    gancho = min(100, 45 + hook_words * 5 + (20 if "?" in inicio or "!" in inicio else 0))
    clareza = min(100, 45 + (20 if 45 <= len(palavras) <= 230 else 8))
    autonomia = min(100, 45 + (20 if len(segmentos) >= 3 else 8) + (15 if len(palavras) >= 70 else 0))
    marcadores = {"como", "porque", "erro", "verdade", "descobri", "problema", "resultado", "melhor", "pior"}
    compartilhabilidade = min(100, 40 + len(marcadores.intersection(palavras)) * 10)
    evidencia = 90 if texto and segmentos else 0
    pontuacoes = {
        "distintividade": distintividade,
        "gancho": gancho,
        "clareza_promessa": clareza,
        "autossuficiencia": autonomia,
        "compartilhabilidade": compartilhabilidade,
        "evidencia": evidencia,
    }
    return {"score": calcular_score_corte(pontuacoes), "pontuacoes": pontuacoes}


def _candidatos_para_revisao(candidatos, segmentos, duracao_total_seg, duracao_minima=10, duracao_maxima=90):
    if not segmentos:
        return []
    revisao = []
    vistos = set()
    for candidato in candidatos:
        if not isinstance(candidato, dict):
            continue
        intervalo = _selecionar_segmentos_candidato(candidato, segmentos)
        if not intervalo:
            continue
        inicio_indice, fim_indice, selecionados = intervalo
        if not selecionados:
            continue
        intervalo_frase = _ajustar_limites_para_frases(selecionados, segmentos, duracao_maxima)
        if not intervalo_frase:
            continue
        _, _, selecionados = intervalo_frase
        inicio_indice = selecionados[0]["indice"]
        fim_indice = selecionados[-1]["indice"]
        inicio = selecionados[0]["inicio"]
        fim = selecionados[-1]["fim"]
        if not (0 <= inicio < fim <= duracao_total_seg) or not duracao_minima <= fim - inicio <= duracao_maxima:
            continue
        intervalo = (inicio, fim)
        if intervalo in vistos:
            continue
        vistos.add(intervalo)
        texto = " ".join(segmento["texto"] for segmento in selecionados)
        montagem_intervalos = _montagem_gancho_contexto_retorno(candidato, selecionados)
        pontuacoes = candidato.get("pontuacoes") if isinstance(candidato.get("pontuacoes"), dict) else {}
        score = calcular_score_corte(pontuacoes) if pontuacoes else calcular_score_observavel(texto, selecionados)
        if not pontuacoes:
            pontuacoes = score["pontuacoes"]
            score = score["score"]
        revisao.append({
            "titulo": normalizar_titulo_corte(candidato.get("titulo")) or f"Trecho para revisão {len(revisao) + 1:02d}",
            "inicio": inicio,
            "fim": fim,
            "segmento_inicio": inicio_indice,
            "segmento_fim": fim_indice,
            "gancho": str(candidato.get("gancho") or selecionados[0]["texto"])[:240],
            "promessa": str(candidato.get("promessa") or texto)[:240],
            "virada": str(candidato.get("virada") or "Trecho selecionado para avaliação humana")[:240],
            "conclusao": str(candidato.get("conclusao") or selecionados[-1]["texto"])[:240],
            "montagem": candidato.get("montagem", "continua"),
            "montagem_intervalos": montagem_intervalos,
            "score_vaca_roxa": score,
            "pontuacoes": pontuacoes,
            "revisao_humana": True,
        })
    return revisao


def _selecionar_segmentos_candidato(candidato, segmentos):
    """Aceita o contrato preferido por índices e tolera timestamps produzidos pelo modelo."""
    try:
        inicio_indice = int(candidato.get("segmento_inicio"))
        fim_indice = int(candidato.get("segmento_fim"))
        selecionados = [segmento for segmento in segmentos if inicio_indice <= segmento["indice"] <= fim_indice]
        if selecionados:
            return inicio_indice, fim_indice, selecionados
    except (TypeError, ValueError):
        pass
    try:
        inicio = float(candidato.get("inicio"))
        fim = float(candidato.get("fim"))
    except (TypeError, ValueError):
        return None
    selecionados = [segmento for segmento in segmentos if segmento["fim"] > inicio and segmento["inicio"] < fim]
    if not selecionados:
        return None
    return selecionados[0]["indice"], selecionados[-1]["indice"], selecionados


def _termina_frase(texto):
    return bool(re.search(r"[.!?…](?:[\"'»)]*)$", (texto or "").strip()))


def _comeca_continuacao(texto, tem_anterior=True):
    texto = (texto or "").strip()
    if not texto:
        return True
    palavras = texto.lower().split()
    conectores = {"e", "mas", "porque", "que", "quando", "como", "então", "pois", "só", "também"}
    return texto[0].islower() or (tem_anterior and bool(palavras and palavras[0] in conectores))


def _ajustar_limites_para_frases(selecionados, segmentos, duracao_maxima):
    """Expande limites do Whisper até uma fronteira de frase sem exceder a duração."""
    if not selecionados:
        return None
    inicio_pos = segmentos.index(selecionados[0])
    fim_pos = segmentos.index(selecionados[-1])
    while inicio_pos > 0 and _comeca_continuacao(segmentos[inicio_pos]["texto"]):
        inicio_pos -= 1
    while fim_pos < len(segmentos) - 1 and not _termina_frase(segmentos[fim_pos]["texto"]):
        if segmentos[fim_pos + 1]["fim"] - segmentos[inicio_pos]["inicio"] > duracao_maxima:
            return None
        fim_pos += 1
    selecionados = segmentos[inicio_pos:fim_pos + 1]
    if _comeca_continuacao(selecionados[0]["texto"], inicio_pos > 0) or not _termina_frase(selecionados[-1]["texto"]):
        return None
    return inicio_pos, fim_pos, selecionados


def _localizar_texto_em_segmentos(texto, segmentos):
    palavras = _texto_normalizado(texto).split()
    if not palavras:
        return None
    palavras_segmentos = [_texto_normalizado(item.get("texto", "")).split() for item in segmentos]
    for inicio, palavras_item in enumerate(palavras_segmentos):
        janela = []
        for fim in range(inicio, len(segmentos)):
            janela.extend(palavras_segmentos[fim])
            if palavras == janela:
                return inicio, fim
            if len(janela) >= len(palavras):
                break
    return None


def _montagem_gancho_contexto_retorno(candidato, selecionados):
    if candidato.get("montagem") != "gancho_contexto_retorno":
        return []
    destaque = candidato.get("destaque") or candidato.get("virada")
    gancho = candidato.get("gancho_inicio") or candidato.get("gancho") or destaque
    destaque_pos = _localizar_texto_em_segmentos(destaque, selecionados)
    gancho_pos = _localizar_texto_em_segmentos(gancho, selecionados)
    if not destaque_pos or not gancho_pos:
        return []
    destaque_inicio, destaque_fim = destaque_pos
    gancho_inicio, gancho_fim = gancho_pos
    if destaque_inicio <= 0 or gancho_inicio < destaque_inicio:
        return []
    return [
        {"inicio": selecionados[gancho_inicio]["inicio"], "fim": selecionados[gancho_fim]["fim"]},
        {"inicio": selecionados[0]["inicio"], "fim": selecionados[destaque_inicio]["inicio"]},
        {"inicio": selecionados[destaque_inicio]["inicio"], "fim": selecionados[destaque_fim]["fim"]},
    ]


def _candidatos_fallback(segmentos, duracao_total_seg, duracao_minima, duracao_maxima):
    """Cria trechos reais para revisão humana quando a saída da IA não é utilizável."""
    if not segmentos or duracao_minima <= 0 or duracao_maxima < duracao_minima:
        return []
    candidatos = []
    inicio_pos = 0
    while inicio_pos < len(segmentos) and len(candidatos) < MAX_CORTES_SOLICITADOS:
        inicio = segmentos[inicio_pos]["inicio"]
        fim_pos = inicio_pos
        while fim_pos + 1 < len(segmentos) and segmentos[fim_pos]["fim"] - inicio < duracao_minima:
            fim_pos += 1
        fim = segmentos[fim_pos]["fim"]
        if fim - inicio <= duracao_maxima and fim <= duracao_total_seg:
            trecho = segmentos[inicio_pos:fim_pos + 1]
            texto = " ".join(item["texto"] for item in trecho).strip()
            score_data = calcular_score_observavel(texto, trecho)
            candidatos.append({
                "titulo": refinar_titulo_corte("", trecho[0]["texto"], fallback_index=len(candidatos) + 1),
                "inicio": inicio,
                "fim": fim,
                "segmento_inicio": trecho[0]["indice"],
                "segmento_fim": trecho[-1]["indice"],
                "gancho": trecho[0]["texto"],
                "promessa": texto[:240],
                "virada": trecho[len(trecho) // 2]["texto"],
                "conclusao": trecho[-1]["texto"],
                "score_vaca_roxa": score_data["score"],
                "pontuacoes": score_data["pontuacoes"],
                "revisao_humana": True,
                "fallback_transcricao": True,
            })
            inicio_pos = max(fim_pos + 1, inicio_pos + 1)
        else:
            inicio_pos += 1
    return candidatos


def gerar_cortes_com_retry(transcricao_texto, duracao_total_seg, segmentos=None,
                           minimo=MIN_CORTES_PADRAO, max_tentativas=MAX_TENTATIVAS_QWEN,
                           duracao_minima=10, duracao_maxima=90, progress_callback=None, titulo_original=""):
    aceitos = []
    candidatos_gerados = []
    candidatos_brutos = []
    diagnostico = []
    rejeicoes = []
    for tentativa in range(1, max_tentativas + 1):
        if progress_callback:
            progress_callback(tentativa, max_tentativas, "analisando", {"candidatos": len(candidatos_gerados)})
        prompt = _montar_prompt(transcricao_texto, duracao_total_seg, segmentos, tentativa, aceitos, rejeicoes, duracao_minima, duracao_maxima, titulo_original)
        rodada = {"tentativa": tentativa, "candidatos": 0, "aceitos": 0, "status": "ok"}
        try:
            resposta = requests.post("http://localhost:11434/api/generate", json={
                "model": "qwen2.5:14b",
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
                "format": "json",
            }, timeout=90)
            if resposta.status_code != 200:
                rodada.update({"status": "http_error", "http_status": resposta.status_code})
                rejeicoes.append(f"rodada {tentativa}: Ollama HTTP {resposta.status_code}")
            else:
                candidatos = _extrair_candidatos(resposta)
                candidatos_brutos.extend(candidatos)
                validos = validar_cortes(candidatos, duracao_total_seg, segmentos, score_minimo=0, duracao_minima=duracao_minima, duracao_maxima=duracao_maxima)
                novos = [corte for corte in validos if _intervalo_corte(corte) not in {_intervalo_corte(item) for item in candidatos_gerados}]
                for corte in novos:
                    corte["numero_rodada"] = tentativa
                candidatos_gerados = _deduplicar_cortes(candidatos_gerados + novos)
                recomendados = [corte for corte in novos if corte.get("score_vaca_roxa", 0) >= 70]
                aceitos = _deduplicar_cortes(aceitos + recomendados)
                rodada.update({"candidatos": len(candidatos), "validos_estruturais": len(novos), "aceitos": len(recomendados)})
                if progress_callback:
                    progress_callback(tentativa, max_tentativas, "validando", {"candidatos": len(candidatos), "validos": len(novos), "aceitos": len(recomendados)})
                if len(novos) < len(candidatos):
                    rejeicoes.append(f"rodada {tentativa}: {len(candidatos) - len(novos)} candidato(s) invalido(s) ou duplicado(s)")
        except json.JSONDecodeError:
            rodada["status"] = "invalid_json"
            rejeicoes.append(f"rodada {tentativa}: resposta nao era JSON valido")
        except requests.RequestException as error:
            rodada["status"] = "timeout_or_network"
            rejeicoes.append(f"rodada {tentativa}: falha de rede/timeout ({type(error).__name__})")
        except Exception as error:
            rodada["status"] = "error"
            rejeicoes.append(f"rodada {tentativa}: {type(error).__name__}")
        diagnostico.append(rodada)
        if len(aceitos) >= minimo:
            return {"status": "completed", "cortes": aceitos[:max(minimo, MAX_CORTES_SOLICITADOS)], "candidatos": candidatos_gerados, "diagnostico": diagnostico, "rejeicoes": rejeicoes}
    revisao = candidatos_gerados or _candidatos_para_revisao(candidatos_brutos, segmentos, duracao_total_seg, duracao_minima, duracao_maxima)
    if not revisao:
        revisao = _candidatos_fallback(segmentos, duracao_total_seg, duracao_minima, duracao_maxima)
    return {"status": "needs_review", "cortes": aceitos, "candidatos": revisao, "diagnostico": diagnostico, "rejeicoes": rejeicoes, "minimo": minimo}


def refinar_titulos_com_ia(cortes, titulo_original=""):
    """Transforma títulos brutos em manchetes editoriais sem alterar o conteúdo do corte."""
    if not cortes:
        return cortes
    itens = [{
        "indice": indice,
        "titulo_atual": corte.get("titulo", ""),
        "gancho": corte.get("gancho", ""),
        "promessa": corte.get("promessa", ""),
        "virada": corte.get("virada", ""),
        "conclusao": corte.get("conclusao", ""),
    } for indice, corte in enumerate(cortes)]
    prompt = f"""Você é editor de títulos para YouTube Shorts. Reescreva os títulos dos cortes abaixo.
O título original do vídeo é: {titulo_original or "não informado"}.
Use somente fatos presentes nos campos fornecidos e confirme coerência com o título original. Corrija
ortografia, nomes próprios e entidades do título somente quando a transcrição sustentar a correção. Cada título deve ser uma manchete natural em pt-BR,
específica, completa e curiosa, com 35 a 55 caracteres. Use verbo ou conflito claro, não copie uma frase
inteira, não comece por Trecho, Corte ou Parte, não use emojis, #shorts, reticências ou clickbait.
Retorne somente JSON no formato {{\"titulos\":[{{\"indice\":0,\"titulo\":\"...\"}}]}}.
{json.dumps(itens, ensure_ascii=False)}"""
    try:
        resposta = requests.post("http://localhost:11434/api/generate", json={
            "model": "qwen2.5:14b", "prompt": prompt, "stream": False,
            "options": {"temperature": 0.2}, "format": "json",
        }, timeout=90)
        if resposta.status_code == 200:
            payload = json.loads(resposta.json().get("response", "{}"))
            for item in payload.get("titulos", []):
                indice = item.get("indice")
                titulo = normalizar_titulo_corte(item.get("titulo"))
                if isinstance(indice, int) and 0 <= indice < len(cortes) and titulo and not re.match(r"(?i)^(trecho|corte|parte)\b", titulo):
                    cortes[indice]["titulo"] = titulo
    except (json.JSONDecodeError, requests.RequestException, TypeError, AttributeError):
        pass
    for corte in cortes:
        corte["titulo"] = refinar_titulo_corte(corte.get("titulo"), corte.get("gancho"))
    return cortes


def garimpar_vacas_roxas(transcricao_texto, duracao_total_seg, segmentos=None, titulo_original=""):
    return gerar_cortes_com_retry(transcricao_texto, duracao_total_seg, segmentos, titulo_original=titulo_original)["cortes"]


def _garimpar_vacas_roxas_uma_rodada_legacy(transcricao_texto, duracao_total_seg, segmentos=None):
    """Mantido apenas como referencia local para diagnosticos antigos."""
    prompt = _montar_prompt(transcricao_texto, duracao_total_seg, segmentos, 1, [], [])
    try:
        resp = requests.post("http://localhost:11434/api/generate", json={
            "model": "qwen2.5:14b",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
            "format": "json"
        }, timeout=90)
        if resp.status_code == 200:
            payload = _extrair_candidatos(resp)
            cortes = validar_cortes(payload, duracao_total_seg, segmentos)
            print(f"🧠 Qwen retornou {len(payload) if isinstance(payload, list) else 0} candidato(s); {len(cortes)} passou(aram) na validação.")
            return cortes
        print(f"⚠️ Ollama respondeu HTTP {resp.status_code} ao analisar cortes.")
    except json.JSONDecodeError as e:
        print(f"⚠️ Resposta do Qwen não é JSON válido: {e}")
    except Exception as e:
        print(f"⚠️ Erro ao garimpar com IA: {e}")
    return []


def _texto_normalizado(texto):
    return re.sub(r"[^a-z0-9áéíóúâêôãõç ]", " ", (texto or "").lower())


def _evidencia_presente(gancho, texto):
    gancho_normalizado = _texto_normalizado(gancho)
    texto_normalizado = _texto_normalizado(texto)
    if gancho_normalizado in texto_normalizado:
        return True
    palavras = {palavra for palavra in gancho_normalizado.split() if len(palavra) >= 4}
    if not palavras:
        return False
    presentes = sum(1 for palavra in palavras if palavra in texto_normalizado.split())
    return presentes / len(palavras) >= 0.6


def calcular_score_corte(pontuacoes):
    pesos = {
        "distintividade": 25,
        "gancho": 20,
        "clareza_promessa": 15,
        "autossuficiencia": 15,
        "compartilhabilidade": 15,
        "evidencia": 10,
    }
    try:
        valores = {chave: max(0, min(100, float(pontuacoes[chave]))) for chave in pesos}
    except (KeyError, TypeError, ValueError):
        return None
    return round(sum(valores[chave] * peso for chave, peso in pesos.items()) / 100)


def validar_cortes(cortes, duracao_total_seg, segmentos=None, score_minimo=70, duracao_minima=10, duracao_maxima=90):
    if not isinstance(cortes, list):
        return []

    cortes_validos = []
    for corte in cortes:
        if not isinstance(corte, dict):
            continue
        titulo = refinar_titulo_corte(corte.get("titulo"), corte.get("gancho"))
        inicio = corte.get("inicio")
        fim = corte.get("fim")
        segmento_inicio = corte.get("segmento_inicio")
        segmento_fim = corte.get("segmento_fim")
        gancho = corte.get("gancho")
        promessa = corte.get("promessa")
        virada = corte.get("virada")
        conclusao = corte.get("conclusao")
        pontuacoes = corte.get("pontuacoes")
        score = corte.get("score_vaca_roxa")
        if not titulo or len(titulo) < 8:
            continue
        if not all(isinstance(item, str) and item.strip() for item in (gancho, promessa, virada, conclusao)):
            continue
        if corte.get("autossuficiente") is not True or corte.get("promocional") is True:
            continue
        if pontuacoes:
            score = calcular_score_corte(pontuacoes)
        else:
            try:
                score = float(score)
                if 0 <= score <= 10:
                    score *= 10
            except (TypeError, ValueError):
                continue
        if score is None or not 0 <= score <= 100 or score < score_minimo:
            continue
        if segmentos:
            intervalo = _selecionar_segmentos_candidato(corte, segmentos)
            if not intervalo:
                continue
            segmento_inicio, segmento_fim, selecionados = intervalo
            intervalo_frase = _ajustar_limites_para_frases(selecionados, segmentos, duracao_maxima)
            if not intervalo_frase:
                continue
            _, _, selecionados = intervalo_frase
            segmento_inicio = selecionados[0]["indice"]
            segmento_fim = selecionados[-1]["indice"]
            inicio = selecionados[0]["inicio"]
            fim = selecionados[-1]["fim"]
            texto_selecionado = " ".join(s["texto"] for s in selecionados)
            if not _evidencia_presente(gancho, texto_selecionado):
                continue
            montagem_intervalos = _montagem_gancho_contexto_retorno(corte, selecionados)
        else:
            try:
                inicio = float(inicio)
                fim = float(fim)
            except (TypeError, ValueError):
                continue
        if not (0 <= inicio < fim <= duracao_total_seg):
            continue
        if fim - inicio < duracao_minima or fim - inicio > duracao_maxima:
            continue
        cortes_validos.append({
            "titulo": titulo,
            "inicio": inicio,
            "fim": fim,
            "segmento_inicio": segmento_inicio,
            "segmento_fim": segmento_fim,
            "gancho": gancho.strip(),
            "promessa": promessa.strip(),
            "virada": virada.strip(),
            "conclusao": conclusao.strip(),
            "montagem": corte.get("montagem", "continua"),
            "montagem_intervalos": montagem_intervalos,
            "score_vaca_roxa": score,
            "pontuacoes": pontuacoes or {},
        })
    return cortes_validos


def normalizar_titulo_corte(titulo, limite=55):
    if not isinstance(titulo, str):
        return ""
    titulo = re.sub(r"(?i)#shorts\b", "", titulo)
    titulo = re.sub(r"\s+", " ", titulo).strip(" .-\t\r\n")
    if len(titulo) <= limite:
        return titulo

    palavras = titulo.split()
    reduzido = ""
    for palavra in palavras:
        candidato = f"{reduzido} {palavra}".strip()
        if len(candidato) > limite:
            break
        reduzido = candidato
    return reduzido or titulo[:limite].rstrip()


def refinar_titulo_corte(titulo, gancho="", limite=55, fallback_index=None):
    """Garante uma manchete legível quando a IA devolve um fragmento de fala."""
    titulo = normalizar_titulo_corte(titulo, limite)
    if not titulo or re.match(r"(?i)^(trecho|corte|parte)\b", titulo):
        titulo = normalizar_titulo_corte(gancho, limite)
    if not titulo:
        return f"Corte editorial {fallback_index:02d}" if fallback_index else "Corte editorial"
    titulo = titulo[0].upper() + titulo[1:]
    if titulo[-1:] in ",;:-":
        titulo = titulo[:-1].rstrip()
    return titulo

def calcular_corte_com_rosto(caminho_video, inicio, fim):
    """Monta um smart crop 9:16 usando o centro suavizado dos rostos amostrados."""
    cap = cv2.VideoCapture(caminho_video)
    w_tot = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h_tot = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if w_tot <= 0 or h_tot <= 0:
        cap.release()
        raise MediaToolError("Não foi possível obter a resolução do vídeo.")

    proporcao = w_tot / h_tot
    if proporcao >= 9 / 16:
        w_corte, h_corte = round(h_tot * 9 / 16), h_tot
        eixo = "x"
    else:
        w_corte, h_corte = w_tot, min(h_tot, round(w_tot * 16 / 9))
        eixo = "y"

    centros = []
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path) if os.path.exists(cascade_path) else None
    try:
        amostras = [float(inicio) + (float(fim) - float(inicio)) * indice / 8 for indice in range(9)]
        for timestamp in amostras:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, round(timestamp * fps)))
            ret, frame = cap.read()
            if not ret or detector is None:
                continue
            cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            rostos = detector.detectMultiScale(cinza, 1.1, 5, minSize=(30, 30))
            if len(rostos):
                x, y, largura, altura = max(rostos, key=lambda rosto: rosto[2] * rosto[3])
                centros.append((x + largura / 2, y + altura / 2))
    finally:
        cap.release()

    if centros:
        centro_x = sum(centro[0] for centro in centros) / len(centros)
        centro_y = sum(centro[1] for centro in centros) / len(centros)
    else:
        centro_x, centro_y = w_tot / 2, h_tot / 2

    if eixo == "x":
        x = max(0, min(w_tot - w_corte, round(centro_x - w_corte / 2)))
        y = 0
    else:
        x = 0
        y = max(0, min(h_tot - h_corte, round(centro_y - h_corte / 2)))
    return f"crop={w_corte}:{h_corte}:{x}:{y},scale=1080:1920:flags=lanczos"


def renderizar_corte_shorts(video_origem, inicio, fim, caminho_saida):
    """Renderiza um Short vertical com padding temporal e smart crop facial."""
    try:
        inicio = float(inicio)
        fim = float(fim)
    except (TypeError, ValueError) as error:
        raise MediaToolError("Os timestamps do corte precisam ser numéricos.") from error
    if inicio < 0 or fim <= inicio:
        raise MediaToolError("Timestamps do corte são inválidos.")

    duracao = obter_duracao(video_origem)
    try:
        padding_inicio = float(os.getenv("SHORTS_PADDING_INICIO", "0.3"))
        padding_fim = float(os.getenv("SHORTS_PADDING_FIM", "0.5"))
    except ValueError as error:
        raise MediaToolError("O padding dos Shorts precisa ser numérico.") from error
    if padding_inicio < 0 or padding_fim < 0:
        raise MediaToolError("O padding dos Shorts não pode ser negativo.")
    inicio_render = max(0.0, inicio - padding_inicio)
    fim_render = min(duracao, fim + padding_fim)
    if fim_render <= inicio_render:
        raise MediaToolError("O intervalo com padding não possui duração válida.")

    ffmpeg, _ = localizar_ferramentas()
    filtro = calcular_corte_com_rosto(video_origem, inicio_render, fim_render)
    pasta_saida = os.path.dirname(os.path.abspath(caminho_saida))
    os.makedirs(pasta_saida, exist_ok=True)
    comando = [
        ffmpeg, "-y", "-ss", f"{inicio_render:.3f}", "-to", f"{fim_render:.3f}",
        "-i", video_origem, "-vf", filtro, "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", caminho_saida,
    ]
    try:
        _run(comando, 600)
    except Exception:
        if os.path.exists(caminho_saida):
            os.remove(caminho_saida)
        raise
    if not os.path.isfile(caminho_saida) or os.path.getsize(caminho_saida) <= 0:
        raise MediaToolError("FFmpeg não produziu um Short válido.")
    return caminho_saida

def cortar_com_ffmpeg(caminho_original, cortes, perfil_id=1):
    sucesso = True
    pasta_shorts = obter_pastas_midia(perfil_id)["shorts"]
    for corte in tqdm(cortes, desc="✂️ Renderizando cortes no FFmpeg"):
        titulo = normalizar_titulo_corte(corte.get("titulo")) or "corte_sem_titulo"
        t_limpo = "".join(c for c in titulo if c.isalnum() or c in " _-").replace(" ", "_")
        saida = os.path.join(pasta_shorts, f"{t_limpo}.mp4")
        try:
            renderizar_corte_shorts(caminho_original, corte['inicio'], corte['fim'], saida)
        except Exception:
            sucesso = False
            registrar_log(f"Falha ao renderizar corte em {caminho_original}")
    return sucesso

def executar_cortes(dry_run=False, perfil_id=1):
    print("========================================")
    print("✂️ FÁBRICA DE CORTES (ESTÁGIO 1)")
    print("========================================\n")
    videos_longos = [f for f in os.listdir(PASTA_LONGOS) if f.endswith(".mp4")]
    if not videos_longos:
        print("📭 Nenhum vídeo longo em 'pracortar/'")
        return

    for video in videos_longos:
        c_longo = os.path.join(PASTA_LONGOS, video)
        rc = input(f"⚙️ Cortar {video}? (s/n/pula): ").strip().lower()
        if rc == 's':
            segmentos = transcrever_arquivo_local_segmentos(c_longo)
            if not segmentos:
                print(f"⚠️ Nenhum segmento de fala encontrado em '{video}'.")
            else:
                cap = cv2.VideoCapture(c_longo)
                fps = cap.get(cv2.CAP_PROP_FPS)
                frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                dur = (frames / fps) if fps and fps > 0 else 60.0
                cap.release()
                texto_segmentado = "\n".join(
                    f"[{segmento['indice']}] {segmento['inicio']:.3f}-{segmento['fim']:.3f}: {segmento['texto']}"
                    for segmento in segmentos
                )
                cortes = garimpar_vacas_roxas(texto_segmentado, dur, segmentos)
                if not cortes:
                    print(f"⚠️ A IA não aprovou cortes válidos para '{video}'.")
                elif dry_run:
                    print(f"✅ Prévia: {len(cortes)} corte(s) aprovado(s) para '{video}'.")
                    print(json.dumps(cortes, ensure_ascii=False, indent=2))
                else:
                    print(f"✅ {len(cortes)} corte(s) aprovado(s) para renderização.")
                    sucesso = cortar_com_ffmpeg(c_longo, cortes, perfil_id=perfil_id)
                    if not sucesso:
                        print(f"⚠️ Arquivo mantido em 'pracortar/' porque algum corte falhou: '{video}'.")
                        continue
        if not dry_run:
            shutil.move(c_longo, os.path.join(PASTA_ARQUIVO, video))
    print("✅ Processo de corte concluído. Shorts despejados em 'shorts/'")