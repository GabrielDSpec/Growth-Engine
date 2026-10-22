import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import cv2
import requests
from difflib import SequenceMatcher
from tqdm import tqdm
from core.media_tools import MediaToolError, _executar_render_com_fallback, _run, localizar_ferramentas, montar_comando_render, obter_duracao
from core.config import DIRETORIO_PROJETO, PASTA_LONGOS, PASTA_SHORTS, PASTA_ARQUIVO, obter_pastas_midia
from core.utils import registrar_log, carregar_cache_metadados, salvar_cache_metadados, calcular_hash_arquivo
from core.transcriber import transcrever_arquivo_local_segmentos, validar_correcoes_no_audio

MIN_CORTES_PADRAO = 1
MAX_CORTES_SOLICITADOS = 12
OLLAMA_MAX_SECONDS = int(os.getenv("GROWTH_ENGINE_OLLAMA_TIMEOUT_SECONDS", "1200"))
OLLAMA_TIMEOUT_BASE_SECONDS = float(os.getenv("GROWTH_ENGINE_OLLAMA_TIMEOUT_BASE_SECONDS", "120"))
OLLAMA_TIMEOUT_FACTOR = float(os.getenv("GROWTH_ENGINE_OLLAMA_TIMEOUT_FACTOR", "1.5"))
OLLAMA_TIMEOUT_MIN_SECONDS = float(os.getenv("GROWTH_ENGINE_OLLAMA_TIMEOUT_MIN_SECONDS", "120"))
OLLAMA_TIMEOUT_MAX_SECONDS = float(os.getenv("GROWTH_ENGINE_OLLAMA_TIMEOUT_MAX_SECONDS", "1200"))
OLLAMA_MODEL = os.getenv("GROWTH_ENGINE_CUT_MODEL", "qwen2.5:14b")
OLLAMA_CUTS_ENABLED = os.getenv("GROWTH_ENGINE_ENABLE_OLLAMA_CUTS", "1").lower() in {"1", "true", "yes"}
EDITORIAL_STEP_SECONDS = 180
EDITORIAL_TARGET_SECONDS = 60
EDITORIAL_STEP_OVERLAP_SECONDS = 15
EDITORIAL_MIN_CANDIDATE_GAP_SECONDS = 30


class EditorialResponseParseError(ValueError):
    """Resposta do Ollama sem JSON editorial aproveitável, com evidência bruta."""


class EditorialCandidates(list):
    def __init__(self, values=(), diagnostics=None):
        super().__init__(values)
        self.diagnostics = diagnostics or []
        self.resumo_conteudo = ""
        self.steps_total = None
        self.steps_completed = None


class EditorialIndex(list):
    def __init__(self, values=(), diagnostics=None):
        super().__init__(values)
        self.diagnostics = diagnostics or []
        self.resumo_conteudo = ""

def _metas_editoriais_do_step(duracao_step):
    duracao = max(0.0, float(duracao_step or 0))
    minimo = 1 if duracao > 0 else 0
    maximo = min(2, max(minimo, round(duracao / 90)))
    return minimo, maximo


def _limite_editorial_global(duracao_total_seg):
    duracao = max(0.0, float(duracao_total_seg or 0))
    limite = 0
    inicio = 0.0
    while inicio < duracao:
        fim = min(duracao, inicio + EDITORIAL_STEP_SECONDS)
        _, maximo = _metas_editoriais_do_step(fim - inicio)
        limite += maximo
        inicio = fim
    return max(1, limite)
    return min(MAX_CORTES_SOLICITADOS, max(1, limite, int((duracao + EDITORIAL_STEP_SECONDS - 1) // EDITORIAL_STEP_SECONDS)))


def _configurar_saida_utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


_configurar_saida_utf8()


def _montar_prompt(transcricao_texto, duracao_total_seg, segmentos, tentativa, cortes_atuais, rejeicoes, duracao_minima=10, duracao_maxima=90, titulo_original="", intervalos_usados=None, contexto_multimodal=""):
    feedback = ""
    if rejeicoes:
        feedback = "\nCorrija estes problemas observados nas validações anteriores:\n- " + "\n- ".join(rejeicoes[-12:])
    usados = ", ".join(f"{inicio:.3f}-{fim:.3f}s" for inicio, fim in (intervalos_usados or [])) or "nenhum"
    roteiro_multimodal = transcricao_texto
    if contexto_multimodal:
        roteiro_multimodal += f"\n\nContexto multimodal associado aos timestamps:\n{contexto_multimodal}"
    return f"""Você é Curador Sênior de Atenção e Diretor de Cortes (Teoria da Vaca Roxa).
    Analise exclusivamente o texto abaixo. Não invente falas, eventos, contexto ou timestamps.
    Gere candidatos suficientes para que, após a validação, existam pelo menos {MIN_CORTES_PADRAO} cortes independentes.
    Nesta passagem, retorne entre {MIN_CORTES_PADRAO} e {_limite_editorial_global(duracao_total_seg)} candidatos quando houver material.
    Nunca invente falas, timestamps ou segmentos apenas para atingir a quantidade.
    Os cortes já aceitos nesta execução: {len(cortes_atuais)}. A curadoria editorial ocorre em uma passagem única.
    Intervalos já usados nesta execução: {usados}. Não reutilize nem sobreponha esses intervalos em pelo menos 50% da duração.
    Escolha somente segmentos existentes nos DIÁLOGOS BRUTOS numerados. Retorne segmento_inicio e segmento_fim
    como índices inteiros inclusivos copiados exatamente da numeração; não invente índices nem timestamps.
    O trecho deve ser uma sequência contínua de segmentos e a diferença entre o primeiro início e o último fim
    precisa ficar entre {duracao_minima} e {duracao_maxima} segundos. Nunca selecione apenas um segmento curto
    para depois tentar completar a duração com texto inventado.
    Os limites precisam preservar frases completas: comece no início de uma ideia, não no meio de uma frase,
    e termine somente depois de uma frase concluída (pontuação final ou encerramento inequívoco da fala).
    Nunca corte palavra, oração ou contexto no meio. Se o Whisper dividiu uma frase em vários segmentos,
    inclua todos os segmentos necessários para fechá-la, respeitando a duração máxima.
    Para cada corte, crie um título editorial em pt-BR com 35 a 55 caracteres, pronto para ser usado no YouTube Shorts.
    O título NÃO DEVE resumir o vídeo nem ser factual. Ele deve abrir um 'Loop de Curiosidade' (Open Loop) ou apresentar um contraste absurdo. É PERMITIDO usar reticências (...), frases sem verbo de impacto, ou citações parciais se soarem mais chocantes. Pense como um Youtuber nativo focado em retenção: crie tensão, ameaça ou desafio, não um artigo de jornal.
        Aprove um corte somente se ele tiver uma única ideia, conflito ou contraste claro, começo autossuficiente,
        desenvolvimento e conclusão. O início deve conter o gancho, sem saudação ou contexto dependente de outro vídeo.
        Quando um destaque forte aparecer mais tarde no trecho, você pode sinalizar a montagem
        "gancho_contexto_retorno": use uma frase literal do destaque como gancho inicial, depois o contexto,
        e retorne ao momento do destaque. Isso é uma oportunidade editorial, não uma licença para inventar
        texto ou timestamps; todos os elementos precisam existir no MATERIAL BASE.
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
        PRIORIDADE MULTIMODAL: as tags [🎬 CORTE DE CÂMERA] e [🔊 PICO DE ÁUDIO] indicam dinamismo visual ou auditivo.
        Priorize ganchos cujo início ou janela contenha essas tags, especialmente quando coincidirem com uma ideia
        autossuficiente. As tags são contexto de roteiro, não falas: nunca as inclua no título, na descrição ou no texto inventado.
    Título original do vídeo: {titulo_original or "não informado"}
    Antes de propor cortes, confira o título original contra o MATERIAL BASE. Identifique erros ortográficos,
    nomes próprios, entidades ou afirmações do título que não correspondam ao contexto. Corrija somente o que
    puder ser confirmado pelo MATERIAL BASE e mantenha o sentido factual. Para cada corte, o título editorial deve
    ser coerente com o vídeo original e não pode contradizer seu tema.
    Analise os DIÁLOGOS BRUTOS segmentados ({duracao_total_seg:.1f}s):
    {roteiro_multimodal or transcricao_texto}
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
    Retorne pelo menos {MIN_CORTES_PADRAO} cortes quando existirem trechos que atendam às regras e nunca exceda {_limite_editorial_global(duracao_total_seg)}.
    {feedback}
    """


def _texto_bruto_ollama(resposta):
    payload_resposta = resposta if isinstance(resposta, dict) else resposta.json()
    return str(payload_resposta.get("response", "") or "").strip()


def _reparar_json_ollama(texto):
    texto_bruto = str(texto or "")
    texto_limpo = re.sub(r"<think>.*?</think>", "", texto_bruto, flags=re.DOTALL | re.IGNORECASE).strip()
    trecho = re.search(r"\{.*\}", texto_limpo, flags=re.DOTALL)
    evidencia = texto_bruto[:2000]
    if not trecho:
        raise EditorialResponseParseError(f"parse_error_raw: {evidencia!r}")
    try:
        return json.loads(trecho.group(0))
    except (json.JSONDecodeError, TypeError) as error:
        raise EditorialResponseParseError(f"{type(error).__name__}; parse_error_raw: {evidencia!r}") from error


def _extrair_candidatos(resposta):
    texto_bruto = _texto_bruto_ollama(resposta)
    texto_limpo = re.sub(r"<think>.*?</think>", "", texto_bruto, flags=re.DOTALL | re.IGNORECASE).strip()
    trecho_json = re.search(r"\{.*\}", texto_limpo, flags=re.DOTALL)
    texto_json = trecho_json.group(0) if trecho_json else texto_bruto
    payload = _reparar_json_ollama(texto_bruto)
    resumo_conteudo = payload.get("resumo_conteudo", "") if isinstance(payload, dict) else ""
    if isinstance(payload, dict):
        candidatos = next(
            (valor for valor in payload.values() if isinstance(valor, list) and any(isinstance(item, dict) for item in valor)),
            [],
        )
        if candidatos:
            payload = candidatos
        else:
            payload = []
    if not isinstance(payload, list) or not payload:
        raise EditorialResponseParseError(f"empty_editorial_response; sem candidatos válidos. RAW: {texto_json}")
    placeholders = (
        "gancho viral",
        "gancho viral completo",
        "gancho viral completo e específico",
        "porque é uma vaca roxa",
        "por que é uma vaca roxa",
        "sua síntese do bloco aqui",
        "por que este trecho é uma vaca roxa",
    )
    candidatos_validos = [
        candidato for candidato in payload
        if isinstance(candidato, dict)
        and not _candidato_placeholder(candidato, placeholders)
    ]
    if not candidatos_validos:
        raise EditorialResponseParseError(f"placeholder_editorial_response; candidatos eram exemplos do prompt. RAW: {texto_json}")
    candidatos = EditorialCandidates(candidatos_validos)
    candidatos.resumo_conteudo = str(resumo_conteudo or "").strip()
    return candidatos


def _candidato_placeholder(candidato, placeholders=None):
    placeholders = placeholders or (
        "gancho viral",
        "gancho viral completo",
        "gancho viral completo e específico",
        "porque é uma vaca roxa",
        "por que é uma vaca roxa",
        "sua síntese do bloco aqui",
        "por que este trecho é uma vaca roxa",
    )
    return any(
        any(placeholder in _texto_normalizado(str(candidato.get(campo) or "")) for placeholder in placeholders)
        for campo in ("titulo", "titulo_sugerido", "descricao_publicacao", "descricao_sugerida")
    )


def _formatar_tempo_corte(segundos):
    total_segundos = max(0, int(round(float(segundos))))
    minutos, segundos_restantes = divmod(total_segundos, 60)
    horas, minutos = divmod(minutos, 60)
    if horas:
        return f"{horas:02d}:{minutos:02d}:{segundos_restantes:02d}"
    return f"{minutos:02d}:{segundos_restantes:02d}"


def _calcular_timeout_ollama(duracao_em_segundos):
    try:
        duracao = max(0.0, float(duracao_em_segundos or 0))
    except (TypeError, ValueError):
        duracao = 0.0
    timeout = OLLAMA_TIMEOUT_BASE_SECONDS + duracao * OLLAMA_TIMEOUT_FACTOR
    return max(OLLAMA_TIMEOUT_MIN_SECONDS, min(OLLAMA_TIMEOUT_MAX_SECONDS, timeout))
class GenerationCancelled(RuntimeError):
    pass


def _gerar_resposta_ollama_http(prompt, timeout=OLLAMA_MAX_SECONDS, num_predict=1400, num_ctx=2048, json_schema=None):
    partes = []
    iniciou = time.monotonic()
    resposta = None
    request_timeout = max(0.5, float(timeout))
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": True,
            "context": [],
            "options": {"temperature": 0.2, "num_ctx": num_ctx, "num_predict": num_predict},
            "keep_alive": "15m",
            "format": json_schema or "json",
        }
        resposta = requests.post("http://localhost:11434/api/generate", json=payload, stream=True, timeout=(min(5.0, request_timeout), request_timeout))
        if resposta.status_code != 200:
            return {"status_code": resposta.status_code, "response": ""}
        if not hasattr(resposta, "iter_lines"):
            payload = resposta.json()
            resposta_bruta = payload.get("response", "")
            return {"status_code": 200, "response": resposta_bruta}
        for linha in resposta.iter_lines(decode_unicode=True):
            if time.monotonic() - iniciou > timeout:
                raise requests.Timeout(f"Ollama excedeu o limite de {timeout}s.")
            if not linha:
                continue
            evento = json.loads(linha)
            partes.append(evento.get("response", ""))
            if evento.get("done"):
                break
        resposta_bruta = "".join(partes)
        return {"status_code": 200, "response": resposta_bruta}
    finally:
        if resposta is not None and hasattr(resposta, "close"):
            resposta.close()


def _gerar_resposta_ollama(prompt, cancel_callback=None, timeout=OLLAMA_MAX_SECONDS, json_schema=None, num_ctx=2048):
    if cancel_callback is None:
        return _gerar_resposta_ollama_http(prompt, timeout=timeout, json_schema=json_schema, num_ctx=num_ctx)
    if cancel_callback():
        raise GenerationCancelled("Processamento cancelado pelo usuário.")
    processo = subprocess.Popen(
        [sys.executable, "-m", "core.ollama_worker"],
        cwd=DIRETORIO_PROJETO,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    try:
        processo.stdin.write(json.dumps({"prompt": prompt, "timeout": timeout, "json_schema": json_schema, "num_ctx": num_ctx}, ensure_ascii=False) + "\n")
        processo.stdin.close()
    except Exception:
        processo.kill()
        processo.wait(timeout=2)
        raise requests.RequestException("Não foi possível iniciar o worker do Ollama.")
    iniciou = time.monotonic()
    try:
        while True:
            if cancel_callback():
                processo.kill()
                processo.wait(timeout=2)
                raise GenerationCancelled("Processamento cancelado pelo usuário.")
            if processo.poll() is not None:
                resposta = processo.stdout.read().strip()
                if not resposta:
                    raise requests.RequestException("O worker do Ollama encerrou sem resposta.")
                payload = json.loads(resposta)
                if payload.get("ok"):
                    return payload["result"]
                if payload.get("error_type") == "timeout":
                    raise requests.Timeout(payload.get("error") or "Ollama excedeu o limite de tempo.")
                raise requests.RequestException(payload.get("error") or "Falha no worker do Ollama.")
            if time.monotonic() - iniciou > timeout:
                processo.kill()
                processo.wait(timeout=2)
                raise requests.Timeout(f"Ollama excedeu o limite de {timeout}s.")
            time.sleep(0.25)
    finally:
        if processo.poll() is None:
            processo.kill()
        processo.wait(timeout=2)
        if processo.stdout:
            processo.stdout.close()


def _intervalo_corte(corte):
    return (round(float(corte["inicio"]), 3), round(float(corte["fim"]), 3))


def _chave_titulo_corte(corte):
    return re.sub(r"[^a-z0-9]+", " ", _texto_normalizado(str(corte.get("titulo") or ""))).strip()


def _cortes_repetidos(primeiro, segundo):
    inicio_a, fim_a = _intervalo_corte(primeiro)
    inicio_b, fim_b = _intervalo_corte(segundo)
    intersecao = max(0.0, min(fim_a, fim_b) - max(inicio_a, inicio_b))
    menor_duracao = min(fim_a - inicio_a, fim_b - inicio_b)
    return bool(menor_duracao > 0 and intersecao / menor_duracao > 0.4)


def _titulos_repetidos(primeiro, segundo):
    titulo_a = _chave_titulo_corte(primeiro)
    titulo_b = _chave_titulo_corte(segundo)
    if not titulo_a or not titulo_b:
        return False
    return titulo_a == titulo_b or SequenceMatcher(None, titulo_a, titulo_b).ratio() >= 0.85


def _deduplicar_cortes(cortes, intervalos_bloqueados=None):
    resultado = []
    intervalos = set()
    bloqueados = intervalos_bloqueados or []
    for corte in cortes:
        intervalo = _intervalo_corte(corte)
        if (
            intervalo in intervalos
            or any(_cortes_repetidos(corte, existente) for existente in bloqueados)
            or any(_cortes_repetidos(corte, existente) for existente in resultado)
        ):
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


def _expandir_intervalo_candidato(inicio, fim, duracao_total_seg, duracao_minima, limite_inicio=0.0, limite_fim=None, intervalos_ocupados=None):
    """Adiciona contexto ao redor de um timestamp editorial curto."""
    limite_inicio = max(0.0, float(limite_inicio))
    limite_fim = min(float(duracao_total_seg), float(limite_fim if limite_fim is not None else duracao_total_seg))
    inicio = max(limite_inicio, float(inicio))
    fim = min(limite_fim, float(fim))
    alvo = min(limite_fim - limite_inicio, max(0.0, float(duracao_minima)))
    if fim - inicio >= alvo:
        return inicio, fim
    inicio_desejado = min(max(limite_inicio, inicio - (alvo - (fim - inicio)) / 2), limite_fim - alvo)
    ocupados = sorted(intervalos_ocupados or [], key=lambda intervalo: intervalo[0])

    def livre(inicio_teste):
        fim_teste = inicio_teste + alvo
        return not any(
            inicio_teste < ocupado_fim + EDITORIAL_MIN_CANDIDATE_GAP_SECONDS
            and fim_teste > ocupado_inicio - EDITORIAL_MIN_CANDIDATE_GAP_SECONDS
            for ocupado_inicio, ocupado_fim in ocupados
        )

    candidatos_inicio = [inicio_desejado, limite_inicio, limite_fim - alvo]
    for ocupado_inicio, ocupado_fim in ocupados:
        candidatos_inicio.extend((ocupado_inicio - EDITORIAL_MIN_CANDIDATE_GAP_SECONDS - alvo, ocupado_fim + EDITORIAL_MIN_CANDIDATE_GAP_SECONDS))
    for inicio_teste in sorted({round(max(limite_inicio, min(limite_fim - alvo, candidato)), 3) for candidato in candidatos_inicio}):
        if livre(inicio_teste):
            return inicio_teste, inicio_teste + alvo

    necessario = alvo - (fim - inicio)
    esquerda = min(inicio - limite_inicio, necessario / 2)
    direita = min(limite_fim - fim, necessario - esquerda)
    return max(limite_inicio, inicio - esquerda), min(limite_fim, fim + direita)


def _candidatos_para_revisao(candidatos, segmentos, duracao_total_seg, duracao_minima=10, duracao_maxima=90):
    if not segmentos:
        return []
    revisao = []
    vistos = set()
    blocos_editoriais = _segmentar_editorial(segmentos, duracao_total_seg)
    intervalos_por_step = {}
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
            # Timestamps editoriais válidos não devem ser descartados só porque o Whisper
            # não marcou pontuação suficiente para reconstruir uma fronteira de frase.
            intervalo_frase = (0, len(selecionados) - 1, selecionados)
        _, _, selecionados = intervalo_frase
        inicio_indice = selecionados[0]["indice"]
        fim_indice = selecionados[-1]["indice"]
        inicio = selecionados[0]["inicio"]
        fim = selecionados[-1]["fim"]
        try:
            step = int(candidato.get("step"))
        except (TypeError, ValueError):
            step = next(
                (
                    indice + 1
                    for indice, (_, _, bloco) in enumerate(blocos_editoriais)
                    if any(item["indice"] in {segmento["indice"] for segmento in selecionados} for item in bloco)
                ),
                0,
            )
        if 1 <= step <= len(blocos_editoriais):
            limite_inicio, limite_fim, _ = blocos_editoriais[step - 1]
        else:
            limite_inicio, limite_fim = 0.0, float(duracao_total_seg)
        inicio, fim = _expandir_intervalo_candidato(
            inicio,
            fim,
            duracao_total_seg,
            duracao_minima,
            limite_inicio=limite_inicio,
            limite_fim=limite_fim,
            intervalos_ocupados=intervalos_por_step.setdefault(step, []),
        )
        selecionados = [
            segmento for segmento in segmentos
            if segmento["fim"] > inicio and segmento["inicio"] < fim
        ]
        if not selecionados:
            continue
        inicio = selecionados[0]["inicio"]
        fim = selecionados[-1]["fim"]
        if not (0 <= inicio < fim <= duracao_total_seg) or not duracao_minima <= fim - inicio <= duracao_maxima:
            continue
        intervalo = (inicio, fim)
        if intervalo in vistos:
            continue
        vistos.add(intervalo)
        intervalos_por_step[step].append(intervalo)
        texto = " ".join(segmento["texto"] for segmento in selecionados)
        titulo = normalizar_titulo_corte(candidato.get("titulo"))
        if not _titulo_tem_evidencia(titulo, texto):
            titulo = _titulo_editorial_local(texto, len(revisao) + 1, inicio, fim)
        descricao = str(candidato.get("descricao_publicacao") or candidato.get("descricao_sugerida") or "").strip()
        if descricao and re.search(r"(?i)\b(?:últim[oa]s?|primeir[oa]s?|final)\s+frames?\b|\bthumbnail\b|\bminiatura\b", descricao):
            descricao = _descricao_editorial_local(texto)
        montagem_intervalos = _montagem_gancho_contexto_retorno(candidato, selecionados)
        pontuacoes = candidato.get("pontuacoes") if isinstance(candidato.get("pontuacoes"), dict) else {}
        score = calcular_score_corte(pontuacoes) if pontuacoes else calcular_score_observavel(texto, selecionados)
        if not pontuacoes:
            pontuacoes = score["pontuacoes"]
            score = score["score"]
        revisao.append({
            "titulo": titulo or f"Trecho para revisão {len(revisao) + 1:02d}",
            "descricao_publicacao": descricao,
            "score_viralidade": candidato.get("score_viralidade"),
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
            "tipo_conteudo": "ia",
        })
    return revisao


def _selecionar_cortes_com_diversidade(candidatos, limite):
    falados = [candidato for candidato in candidatos if candidato.get("tipo_conteudo") != "musical"]
    musicais = [candidato for candidato in candidatos if candidato.get("tipo_conteudo") == "musical"]
    if not falados:
        return _deduplicar_cortes(musicais)[:limite]
    limite_musical = min(len(musicais), max(1, limite // 3))
    selecionados = falados[:limite]
    selecionados.extend(musicais[:limite_musical])
    return _deduplicar_cortes(selecionados)[:limite]


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
        inicio = _segundos_editoriais(candidato.get("inicio_segundos", candidato.get("inicio")))
        fim = _segundos_editoriais(candidato.get("fim_segundos", candidato.get("fim")))
    except (TypeError, ValueError):
        return None
    selecionados = [segmento for segmento in segmentos if segmento["fim"] > inicio and segmento["inicio"] < fim]
    if not selecionados:
        return None
    return selecionados[0]["indice"], selecionados[-1]["indice"], selecionados


def _segundos_editoriais(valor):
    if isinstance(valor, str) and ":" in valor:
        partes = [float(parte.strip()) for parte in valor.strip().split(":")]
        if len(partes) == 2:
            return partes[0] * 60 + partes[1]
        if len(partes) == 3:
            return partes[0] * 3600 + partes[1] * 60 + partes[2]
    return float(valor)


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


def _candidatos_fallback(segmentos, duracao_total_seg, duracao_minima, duracao_maxima, deslocamento=0, duracoes_alvo=None):
    """Gera janelas locais distintas usando somente os segmentos da transcrição."""
    if not segmentos or duracao_minima <= 0 or duracao_maxima < duracao_minima:
        return []
    possiveis = []
    duracoes = sorted({float(duracao) for duracao in (duracoes_alvo or (duracao_minima, min(duracao_maxima, duracao_minima + 10), duracao_maxima)) if duracao_minima <= float(duracao) <= duracao_maxima})
    for inicio_pos in range(len(segmentos)):
        inicio = segmentos[inicio_pos]["inicio"]
        if inicio < deslocamento:
            continue
        for duracao_alvo in duracoes:
            fim_pos = next((indice for indice in range(inicio_pos, len(segmentos)) if segmentos[indice]["fim"] - inicio >= duracao_alvo), None)
            if fim_pos is None:
                continue
            fim = segmentos[fim_pos]["fim"]
            if fim > duracao_total_seg or fim - inicio > duracao_maxima:
                continue
            trecho = segmentos[inicio_pos:fim_pos + 1]
            if _segmentos_sao_ruido_audio(trecho):
                continue
            primeiro_conteudo = next((item for item in trecho if not _titulo_de_ruido_audio(item.get("texto"))), None)
            if not primeiro_conteudo:
                continue
            intervalo = (inicio, fim)
            if intervalo not in {(item["inicio"], item["fim"]) for item in possiveis}:
                texto = " ".join(item["texto"] for item in trecho).strip()
                score_data = calcular_score_observavel(texto, trecho)
                possiveis.append({
                    "titulo": _titulo_editorial_local(texto, fallback_index=len(possiveis) + 1, inicio=inicio, fim=fim),
                    "inicio": inicio,
                    "fim": fim,
                    "segmento_inicio": trecho[0]["indice"],
                    "segmento_fim": trecho[-1]["indice"],
                    "gancho": primeiro_conteudo["texto"],
                    "promessa": texto[:240],
                    "virada": trecho[len(trecho) // 2]["texto"],
                    "conclusao": trecho[-1]["texto"],
                    "descricao_publicacao": "",
                    "score_vaca_roxa": score_data["score"],
                    "pontuacoes": score_data["pontuacoes"],
                    "revisao_humana": True,
                    "fallback_transcricao": True,
                })
    possiveis.sort(key=lambda item: (-item["score_vaca_roxa"], item["inicio"], item["fim"]))
    possiveis.sort(key=lambda item: (-item["score_vaca_roxa"], item["inicio"], item["fim"]))
    return possiveis


def _selecionar_candidatos_locais_com_insistencia(segmentos, duracao_total_seg, duracao_minima, duracao_maxima, intervalos_existentes):
    """Seleciona janelas naturais distintas e distribui-as pela linha do tempo."""
    candidatos_base = _candidatos_fallback(segmentos, duracao_total_seg, duracao_minima, duracao_maxima)
    intervalos_ativos = [
        item for item in intervalos_existentes
        if str(item.get("status") or "").casefold() not in {"excluido", "falhou", "cancelado"}
    ]
    candidatos = _deduplicar_cortes(candidatos_base, intervalos_ativos)
    if not candidatos:
        return []
    quantidade_alvo = _limite_editorial_global(duracao_total_seg)
    escolhidos = []
    for indice in range(quantidade_alvo):
        centro = float(duracao_total_seg or 0) * indice / quantidade_alvo
        candidatos_proximos = sorted(candidatos, key=lambda item: (abs(float(item["inicio"]) - centro), -item["score_vaca_roxa"]))
        candidato = next((item for item in candidatos_proximos if not any(_cortes_repetidos(item, escolhido) for escolhido in escolhidos)), None)
        if candidato:
            escolhidos.append(candidato)
    for candidato in sorted(candidatos, key=lambda item: (-item["score_vaca_roxa"], item["inicio"], item["fim"])):
        if len(escolhidos) >= quantidade_alvo:
            break
        if not any(_cortes_repetidos(candidato, escolhido) for escolhido in escolhidos):
            escolhidos.append(candidato)
    return sorted(escolhidos[:quantidade_alvo], key=lambda item: item["inicio"])


def _segmentar_editorial(segmentos, duracao_total_seg):
    if not segmentos:
        return []
    blocos = []
    inicio = 0.0
    while inicio < duracao_total_seg:
        fim = min(float(duracao_total_seg), inicio + EDITORIAL_STEP_SECONDS)
        bloco = [segmento for segmento in segmentos if segmento["fim"] > inicio and segmento["inicio"] < fim]
        if bloco:
            blocos.append((inicio, fim, bloco))
        if fim >= duracao_total_seg:
            break
        inicio = max(inicio + 1, fim - EDITORIAL_STEP_OVERLAP_SECONDS)
    return blocos


def _contexto_multimodal_do_bloco(contexto_multimodal, inicio, fim):
    linhas = []
    itens = contexto_multimodal if isinstance(contexto_multimodal, list) else str(contexto_multimodal or "").splitlines()
    for item in itens:
        if isinstance(item, dict):
            timestamp = next((item.get(chave) for chave in ("start_time", "startTime", "inicio", "timestamp") if item.get(chave) is not None), None)
            try:
                timestamps = [float(timestamp)]
            except (TypeError, ValueError):
                continue
            linha = json.dumps(item, ensure_ascii=False)
        else:
            linha = str(item)
            intervalos = re.findall(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", linha)
            relogios = re.findall(r"(\d+):(\d{2})(?:\s*[-–]\s*(\d+):(\d{2}))?", linha)
            chaves = re.findall(r"(?:start_time|startTime|inicio|timestamp)\s*[:=]\s*(\d+(?:\.\d+)?)", linha, flags=re.IGNORECASE)
            timestamps = [float(inicio_decimal) for inicio_decimal, _ in intervalos]
            timestamps.extend(int(minuto) * 60 + int(segundo) for minuto, segundo, _, _ in relogios)
            timestamps.extend(float(timestamp) for timestamp in chaves)
        if any(inicio <= timestamp < fim for timestamp in timestamps):
            linhas.append(linha)
    return "\n".join(linhas)


def _resumo_global_editorial(segmentos, titulo_original):
    textos = [str(segmento.get("texto") or "").strip() for segmento in segmentos if segmento.get("texto")]
    if len(textos) <= 16:
        resumo = " ".join(textos)
    else:
        resumo = " ".join(textos[:8] + ["..."] + textos[-8:])
    return f"Vídeo: {titulo_original or 'não informado'}. Evidência global: {resumo[:3500]}"


def _extrair_indice_editorial(resposta, minimo_capitulos=1):
    texto_bruto = _texto_bruto_ollama(resposta)
    payload = _reparar_json_ollama(texto_bruto)
    resumo_conteudo = payload.get("resumo_conteudo", "") if isinstance(payload, dict) else ""
    capitulos = payload.get("capitulos", []) if isinstance(payload, dict) else []
    if not isinstance(capitulos, list):
        capitulos = []
    indice = []
    for item in capitulos:
        if not isinstance(item, dict):
            continue
        try:
            inicio = float(item.get("inicio_segundos", item.get("inicio")))
            fim = float(item.get("fim_segundos", item.get("fim")))
        except (TypeError, ValueError):
            continue
        if fim <= inicio:
            continue
        indice.append({
            "titulo": str(item.get("titulo") or item.get("capitulo") or f"Capítulo {len(indice) + 1}"),
            "descricao": str(item.get("descricao") or item.get("description") or "").strip(),
            "inicio": inicio,
            "fim": fim,
        })
    if len(indice) < minimo_capitulos:
        raise EditorialResponseParseError(
            f"empty_editorial_index; esperados pelo menos {minimo_capitulos} capítulos válidos, encontrados {len(indice)}. RAW: {texto_bruto[:2000]!r}"
        )
    resultado = EditorialIndex(indice)
    resultado.resumo_conteudo = str(resumo_conteudo or "").strip()
    return resultado


def corrigir_transcricao_com_contexto(segmentos, capitulos, titulo_original="", caminho_audio="", cancel_callback=None):
    """Propõe correções de transcrição usando o contexto editorial sem alterar a fonte original."""
    schema = {
        "type": "object",
        "required": ["correcoes"],
        "properties": {"correcoes": {"type": "array", "items": {
            "type": "object",
            "required": ["indice", "texto_corrigido", "motivo", "confianca"],
            "properties": {
                "indice": {"type": "integer"},
                "texto_corrigido": {"type": "string"},
                "motivo": {"type": "string"},
                "confianca": {"type": "number"},
            },
            "additionalProperties": False,
        }}},
        "additionalProperties": False,
    }
    contexto = "\n".join(
        f"- {capitulo.get('inicio', 0):.1f}s-{capitulo.get('fim', 0):.1f}s: {capitulo.get('titulo', '')} | {capitulo.get('descricao', '')}"
        for capitulo in capitulos
    )
    texto = "\n".join(f"[{segmento.get('indice')}] {segmento.get('inicio', 0):.3f}-{segmento.get('fim', 0):.3f}: {segmento.get('texto', '')}" for segmento in segmentos)
    prompt = f"""Você é um revisor conservador de transcrição em português.
Use o editorial apenas para detectar possíveis nomes próprios, termos técnicos ou palavras incompatíveis com o contexto.
Corrija somente erros muito prováveis; não reescreva estilo, não resuma e não invente falas.
Retorne somente correções com confiança >= 0.85. Se não houver correções, retorne uma lista vazia.
Cada índice deve corresponder exatamente ao índice de um segmento fornecido.

VÍDEO: {titulo_original or 'não informado'}
CONTEXTO EDITORIAL:
{contexto[:12000]}

TRANSCRIÇÃO:
{texto[:30000]}
"""
    resposta = _gerar_resposta_ollama(prompt, cancel_callback=cancel_callback, timeout=_calcular_timeout_ollama(max(60, len(segmentos))), json_schema=schema, num_ctx=16384)
    if resposta.get("status_code") != 200:
        raise requests.RequestException(f"Ollama HTTP {resposta.get('status_code')}")
    payload = _reparar_json_ollama(_texto_bruto_ollama(resposta))
    propostas = payload.get("correcoes", []) if isinstance(payload, dict) else []
    try:
        propostas = validar_correcoes_no_audio(caminho_audio, segmentos, propostas, cancel_callback=cancel_callback)
    except Exception:
        propostas = [{**proposta, "audio_verificacao": "erro"} for proposta in propostas]
    por_indice = {int(segmento.get("indice")): segmento for segmento in segmentos if segmento.get("indice") is not None}
    corrigidos = [dict(segmento) for segmento in segmentos]
    aplicadas = []
    for proposta in propostas if isinstance(propostas, list) else []:
        try:
            indice = int(proposta.get("indice"))
            confianca = float(proposta.get("confianca", 0))
        except (TypeError, ValueError):
            continue
        texto_corrigido = str(proposta.get("texto_corrigido") or "").strip()
        if indice not in por_indice or not texto_corrigido or confianca < 0.85:
            continue
        original = por_indice[indice].get("texto", "")
        if texto_corrigido == original:
            continue
        audio_divergente = proposta.get("audio_verificacao") == "divergente"
        registro = {"indice": indice, "inicio": por_indice[indice].get("inicio"), "fim": por_indice[indice].get("fim"), "original": original, "corrigido": texto_corrigido, "motivo": str(proposta.get("motivo") or ""), "confianca": confianca, "audio_verificacao": proposta.get("audio_verificacao", "indisponivel"), "audio_texto": proposta.get("audio_texto", ""), "audio_similaridade": proposta.get("audio_similaridade"), "aceita": not audio_divergente}
        if audio_divergente:
            aplicadas.append(registro)
            continue
        alvo = next(segmento for segmento in corrigidos if int(segmento.get("indice")) == indice)
        alvo["texto"] = texto_corrigido
        aplicadas.append(registro)
    return corrigidos, aplicadas


def _extrair_bolhas_editoriais(resposta):
    payload = _reparar_json_ollama(_texto_bruto_ollama(resposta))
    marcadores = payload.get("marcadores", []) if isinstance(payload, dict) else []
    if not isinstance(marcadores, list):
        marcadores = []
    bolhas = []
    for item in marcadores:
        if not isinstance(item, dict):
            continue
        try:
            inicio = float(item.get("inicio_segundos", item.get("inicio")))
            fim = float(item.get("fim_segundos", item.get("fim")))
        except (TypeError, ValueError):
            continue
        if fim <= inicio or not str(item.get("titulo") or "").strip():
            continue
        bolhas.append({"titulo": str(item["titulo"]).strip(), "inicio": inicio, "fim": fim})
    if not bolhas:
        raise EditorialResponseParseError("empty_editorial_bubbles; sem marcadores estruturais válidos")
    return bolhas


def _ajustar_timestamp_editorial(timestamp, limites):
    if not limites:
        return float(timestamp)
    valor = float(timestamp)
    return min(limites, key=lambda limite: abs(limite - valor))


def _normalizar_indice_editorial(indice, segmentos):
    limites = sorted({float(segmento[chave]) for segmento in segmentos for chave in ("inicio", "fim")})
    if not limites:
        return indice
    normalizado = []
    for item in sorted(indice, key=lambda item: (item["inicio"], item["fim"])):
        inicio = _ajustar_timestamp_editorial(item["inicio"], limites)
        fim = _ajustar_timestamp_editorial(item["fim"], limites)
        if fim > inicio:
            normalizado.append({**item, "inicio": inicio, "fim": fim})
    if normalizado:
        normalizado[0]["inicio"] = limites[0]
        for anterior, atual in zip(normalizado, normalizado[1:]):
            atual["inicio"] = anterior["fim"]
        normalizado[-1]["fim"] = limites[-1]
        ultimo = normalizado[-1]
        ultimo_titulo = ultimo["titulo"].casefold()
        duracao_ultimo = ultimo["fim"] - ultimo["inicio"]
        if duracao_ultimo >= 150 and any(palavra in ultimo_titulo for palavra in ("música", "musica", "intervalo")):
            ponto_encerramento = _ajustar_timestamp_editorial(ultimo["fim"] - 75, limites)
            if ultimo["inicio"] < ponto_encerramento < ultimo["fim"]:
                ultimo["fim"] = ponto_encerramento
                normalizado.append({
                    "titulo": "Encerramento da gravação: trecho final do evento",
                    "inicio": ponto_encerramento,
                    "fim": limites[-1],
                })
    return normalizado


def _gerar_indice_editorial_estrutural(transcricao_texto, duracao_total_seg, segmentos, titulo_original="", cancel_callback=None):
    if not segmentos:
        raise EditorialResponseParseError("empty_editorial_bubbles; transcrição sem segmentos")
    duracao = max(0.0, float(duracao_total_seg or 0))
    minimo_capitulos = max(6, min(24, int((duracao + 179) // 180)))
    maximo_capitulos = max(minimo_capitulos + 4, min(48, int((duracao + 89) // 90)))
    bolhas = []
    resumo_partes = []
    bolha_schema = {
        "type": "object",
        "required": ["marcadores"],
        "properties": {"marcadores": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["titulo", "descricao", "inicio_segundos", "fim_segundos"],
            "properties": {"titulo": {"type": "string"}, "descricao": {"type": "string"}, "inicio_segundos": {"type": "number"}, "fim_segundos": {"type": "number"}},
            "additionalProperties": False,
        }}},
        "additionalProperties": False,
    }
    for numero, (inicio_bloco, fim_bloco, segmentos_bloco) in enumerate(_segmentar_editorial(segmentos, duracao), 1):
        if cancel_callback and cancel_callback():
            raise GenerationCancelled("Geração editorial cancelada")
        texto_bloco = "\n".join(f"[{s['indice']}] {s['inicio']:.3f}-{s['fim']:.3f}: {s['texto']}" for s in segmentos_bloco)
        prompt = f"""Você é um anotador estrutural de vídeo. Analise somente a janela {inicio_bloco:.1f}s-{fim_bloco:.1f}s.
Marque cada mudança de assunto, atividade, local, pessoa ou etapa do evento como uma bolha cronológica.
As bolhas são matéria-prima para um índice posterior, não são cortes, ganchos nem descrições promocionais.
Use obrigatoriamente os limites de início e fim dos segmentos fornecidos. Não invente timestamps.
Retorne somente JSON com marcadores, normalmente 2 a 8 por janela, sem copiar falas:
{{"marcadores":[{{"titulo":"Tema: detalhe específico","inicio_segundos":0.0,"fim_segundos":30.0}}]}}

JANELA {numero}:
{texto_bloco}
"""
        resposta = _gerar_resposta_ollama(prompt, cancel_callback=cancel_callback, timeout=_calcular_timeout_ollama(fim_bloco - inicio_bloco), json_schema=bolha_schema, num_ctx=8192)
        if resposta.get("status_code") != 200:
            raise requests.RequestException(f"Ollama HTTP {resposta.get('status_code')}")
        bolhas.extend(_extrair_bolhas_editoriais(resposta))
    limites = sorted({float(segmento[chave]) for segmento in segmentos for chave in ("inicio", "fim")})
    unicas = {}
    for bolha in bolhas:
        inicio = _ajustar_timestamp_editorial(bolha["inicio"], limites)
        fim = _ajustar_timestamp_editorial(bolha["fim"], limites)
        if fim > inicio:
            unicas[(inicio, fim, bolha["titulo"].casefold())] = {**bolha, "inicio": inicio, "fim": fim}
    bolhas = list(unicas.values())
    if not bolhas:
        raise EditorialResponseParseError("empty_editorial_bubbles; nenhuma bolha após normalização")
    bolhas_texto = "\n".join(f"B{i}: {b['inicio']:.3f}-{b['fim']:.3f} | {b['titulo']}" for i, b in enumerate(sorted(bolhas, key=lambda item: item["inicio"])))
    consolidacao_schema = {
        "type": "object", "required": ["resumo_conteudo", "capitulos"],
        "properties": {"resumo_conteudo": {"type": "string"}, "capitulos": {"type": "array", "minItems": minimo_capitulos, "maxItems": maximo_capitulos, "items": {
            "type": "object", "required": ["titulo", "descricao", "inicio_segundos", "fim_segundos"],
            "properties": {"titulo": {"type": "string"}, "descricao": {"type": "string"}, "inicio_segundos": {"type": "number"}, "fim_segundos": {"type": "number"}},
            "additionalProperties": False,
        }}}, "additionalProperties": False,
    }
    prompt = f"""Você é o editor-chefe consolidando um índice cronológico detalhado.
Agrupe somente bolhas adjacentes quando elas tratarem do mesmo assunto. Preserve todas as mudanças reais.
Gere entre {minimo_capitulos} e {maximo_capitulos} capítulos, cobrindo do início ao fim.
Não elimine capítulos só porque há música; música pode estar dentro do capítulo do show ou ser um capítulo próprio quando mudar a etapa do evento.
Os horários devem ser escolhidos exclusivamente entre os limites das bolhas abaixo. Não invente, arredonde ou desloque timestamps.
Cada título deve seguir "Tema: detalhe específico". Escreva uma descrição factual de uma ou duas frases para cada capítulo, explicando o que acontece naquele intervalo. Não gere cortes, ganchos, scores ou descrições promocionais.
Retorne somente JSON com resumo_conteudo e capitulos.

VÍDEO: {titulo_original or 'não informado'} ({duracao:.1f}s)
BOLHAS ESTRUTURAIS:
{bolhas_texto}
"""
    resposta = _gerar_resposta_ollama(prompt, cancel_callback=cancel_callback, timeout=_calcular_timeout_ollama(duracao), json_schema=consolidacao_schema, num_ctx=16384)
    if resposta.get("status_code") != 200:
        raise requests.RequestException(f"Ollama HTTP {resposta.get('status_code')}")
    indice = _extrair_indice_editorial(resposta, minimo_capitulos=minimo_capitulos)
    indice[:] = _normalizar_indice_editorial(indice, segmentos)
    if len(indice) < minimo_capitulos:
        raise EditorialResponseParseError("empty_editorial_index; capítulos insuficientes após normalização")
    return indice


def _gerar_indice_editorial(transcricao_texto, duracao_total_seg, segmentos, titulo_original="", cancel_callback=None):
    if cancel_callback and cancel_callback():
        raise GenerationCancelled("Geração editorial cancelada")
    try:
        duracao = max(0.0, float(duracao_total_seg or 0))
    except (TypeError, ValueError):
        duracao = 0.0
    minimo_capitulos = max(6, min(24, int((duracao + 179) // 180)))
    maximo_capitulos = max(minimo_capitulos + 4, min(48, int((duracao + 89) // 90)))
    prompt = f"""Você é o editor-chefe responsável por criar o sumário cronológico de um vídeo inteiro.
Leia toda a transcrição abaixo e compreenda o conteúdo geral, a linha narrativa e a ordem dos assuntos.
O resultado é um ÍNDICE DE CAPÍTULOS, como o sumário de um documentário: capítulos nomeiam mudanças
reais de assunto ao longo do vídeo e ajudam outra etapa a localizar trechos. Não é uma lista de cortes,
momentos virais ou descrições promocionais.

Retorne exclusivamente JSON puro neste formato:
{{
  "resumo_conteudo": "Consolidação factual do conteúdo geral em 3 a 5 frases.",
    "capitulos": [
    {{"titulo": "A missão: assunto específico do trecho", "descricao": "Descrição factual do que acontece neste intervalo.", "inicio_segundos": 0.0, "fim_segundos": 60.0}}
  ]
}}

REGRAS:
- Crie um índice cronológico detalhado com pelo menos {minimo_capitulos} e no máximo {maximo_capitulos} capítulos para esta duração. Para vídeos longos, aumente a quantidade proporcionalmente; não comprima uma hora em poucos capítulos.
- Dê títulos editoriais informativos no padrão "Tema: detalhe específico", por exemplo: "Pausa no estacionamento: a marca de 5 mil fotos em dois cartões".
- Comece o primeiro capítulo no início real do vídeo e cubra a linha do tempo até o fim, agrupando música ou silêncio dentro do capítulo adjacente quando não houver mudança de assunto.
- Os capítulos devem cobrir a linha do tempo inteira sem inventar eventos ou timestamps.
- Crie um novo capítulo sempre que houver mudança de local, atividade, pessoa, objetivo, etapa do evento, equipamento, clima, apresentação ou encerramento. Não agrupe várias mudanças em um capítulo genérico.
- Use somente os limites dos segmentos fornecidos.
- O capítulo contém título, descrição factual e intervalo; não escreva descrição de corte, gancho, score, seleção de melhores momentos ou análise promocional.
- Nunca use chaves ou conceitos como `melhores_momentos`, `cortes`, `gancho`, `score`, `descricao_publicacao` ou `Vaca Roxa`.
- Não retorne a transcrição, não copie falas e não crie capítulos artificiais para preencher quantidade.
- Música sem conteúdo pode ser marcada como "Intervalo musical" apenas quando ocupar uma faixa contínua real.
- O resumo deve consolidar o vídeo inteiro e não narrar cada capítulo separadamente.

Título original: {titulo_original or "não informado"}
Duração: {duracao_total_seg:.1f} segundos
TRANSCRIÇÃO COMPLETA:
{transcricao_texto}
"""
    schema_indice_editorial = {
        "type": "object",
        "required": ["resumo_conteudo", "capitulos"],
        "properties": {
            "resumo_conteudo": {"type": "string"},
            "capitulos": {
                "type": "array",
                            "minItems": minimo_capitulos,
                            "maxItems": maximo_capitulos,
                "items": {
                    "type": "object",
                    "required": ["titulo", "descricao", "inicio_segundos", "fim_segundos"],
                    "properties": {
                        "titulo": {"type": "string"},
                        "descricao": {"type": "string"},
                        "inicio_segundos": {"type": "number"},
                        "fim_segundos": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }
    timeout = _calcular_timeout_ollama(duracao_total_seg)
    resposta = _gerar_resposta_ollama(prompt, cancel_callback=cancel_callback, timeout=timeout, json_schema=schema_indice_editorial, num_ctx=32768)
    if resposta.get("status_code") != 200:
        raise requests.RequestException(f"Ollama HTTP {resposta.get('status_code')}")
    try:
        return _extrair_indice_editorial(resposta, minimo_capitulos=minimo_capitulos)
    except EditorialResponseParseError as primeiro_erro:
        if cancel_callback and cancel_callback():
            raise GenerationCancelled("Geração editorial cancelada")
        prompt_corretivo = f"""A resposta anterior não respeitou o contrato do índice editorial.
Ignore completamente qualquer formato de mapa de transcrição, template, chave com placeholders ou lista de falas.
Leia novamente o material abaixo e retorne somente um objeto JSON válido com estas chaves exatas:
{{
  "resumo_conteudo": "Resumo factual do vídeo inteiro em 3 a 5 frases.",
  "capitulos": [
    {{"titulo": "Nome do capítulo", "descricao": "Descrição factual do intervalo.", "inicio_segundos": 0.0, "fim_segundos": 60.0}}
  ]
}}
Os capítulos devem usar apenas limites presentes na transcrição, cobrir o vídeo inteiro e conter pelo menos {minimo_capitulos} itens. Para vídeos longos, seja proporcionalmente detalhista.
Não retorne transcrição, falas, mapas, placeholders, markdown ou qualquer chave adicional.

Título original: {titulo_original or "não informado"}
Duração: {duracao_total_seg:.1f} segundos
TRANSCRIÇÃO COMPLETA:
{transcricao_texto}
"""
        resposta_corrigida = _gerar_resposta_ollama(prompt_corretivo, cancel_callback=cancel_callback, timeout=timeout, json_schema=schema_indice_editorial, num_ctx=32768)
        if resposta_corrigida.get("status_code") != 200:
            raise requests.RequestException(f"Ollama HTTP {resposta_corrigida.get('status_code')}")
        try:
            return _extrair_indice_editorial(resposta_corrigida, minimo_capitulos=minimo_capitulos)
        except EditorialResponseParseError as segundo_erro:
            raise EditorialResponseParseError(
                f"editorial_index_retry_failed; primeira tentativa: {primeiro_erro}; segunda tentativa: {segundo_erro}"
            ) from segundo_erro


def _gerar_dossie_editorial_unico(transcricao_texto, duracao_total_seg, segmentos, duracao_minima, duracao_maxima, titulo_original="", cancel_callback=None, contexto_multimodal="", contexto_editorial="", intervalos_usados=None, partial_callback=None, quantidade_minima=1, resume_analysis=None):
    usados = ", ".join(f"{inicio:.3f}-{fim:.3f}s" for inicio, fim in (intervalos_usados or [])) or "nenhum"
    resumo_global = _resumo_global_editorial(segmentos, titulo_original)
    blocos = _segmentar_editorial(segmentos, duracao_total_seg)
    candidatos_totais = []
    diagnosticos = []
    ultimo_erro_parse = None
    resume_diagnostics = {
        int(item["step"]): item
        for item in (resume_analysis or {}).get("diagnostico", [])
        if isinstance(item, dict) and str(item.get("status") or "").casefold() == "completed" and item.get("step") is not None
    }
    resume_candidates = [
        item for item in (resume_analysis or {}).get("candidatos", [])
        if isinstance(item, dict) and item.get("step") is not None
    ]
    for numero, (inicio_bloco, fim_bloco, segmentos_bloco) in enumerate(blocos, 1):
        if cancel_callback and cancel_callback():
            raise GenerationCancelled("Geração editorial cancelada")
        if numero in resume_diagnostics:
            candidatos_totais.extend(item for item in resume_candidates if int(item["step"]) == numero)
            diagnosticos.append(resume_diagnostics[numero])
            continue
        texto_bloco = "\n".join(f"[{s['indice']}] {s['inicio']:.3f}-{s['fim']:.3f}: {s['texto']}" for s in segmentos_bloco)
        minimo_step, maximo_step = _metas_editoriais_do_step(fim_bloco - inicio_bloco)
        multimodal_started_at = time.time()
        contexto_bloco = _contexto_multimodal_do_bloco(contexto_multimodal, inicio_bloco, fim_bloco)
        registrar_log(f"PROFILE multimodal step={numero} segundos={time.time() - multimodal_started_at:.2f}")
        prompt = f"""Você é um Diretor de TV e Especialista em Conteúdo Viral (Shorts/TikTok).
Sua missão é ler os DIÁLOGOS BRUTOS deste bloco de vídeo e garimpar a "Vaca Roxa": momentos
extraordinários, contra-intuitivos, de alto valor ou emoção que geram retenção absoluta na audiência,
aplicando Contextualização Dupla entre o resumo global e a evidência deste bloco.

MISSÃO EDITORIAL:
- Analise somente este bloco e identifique a ideia principal específica dele.
- Gere um resumo inteligente de 2 a 3 linhas em `resumo_conteudo`.
- Esta janela possui {int(fim_bloco - inicio_bloco)}s. Extraia obrigatoriamente entre {minimo_step} e {maximo_step} cortes distintos nesta janela; quando o bloco tiver
    introdução, desenvolvimento e fechamento relevantes, retorne pelo menos 2 momentos distintos.
- É ESTRITAMENTE PROIBIDO retornar os DIÁLOGOS BRUTOS, reescrever os diálogos ou criar chaves como
    "tempo" ou "texto" no JSON. Sua única função é analisar e extrair cortes editoriais proporcionais à duração desta janela
    e formatar no esquema exato abaixo.
            - Uma Vaca Roxa precisa ser única, inesperada, emocional, útil ou contra-intuitiva; não escolha
    falas genéricas, introduções, saudações, anúncios, autopromoção ou trechos sem payoff.
            - Entrevistas com presidentes, vice-presidentes, representantes, convidados ou lideranças da comunidade
                são material editorial prioritário: preserve a apresentação do entrevistado e selecione também a resposta
                substantiva quando ela existir nesta janela. Não descarte a entrevista por começar com uma apresentação.
- Nunca invente falas, fatos, contexto ou timestamps. Use apenas evidência literal deste bloco.
- Use o ÍNDICE EDITORIAL GLOBAL abaixo para entender em que parte do vídeo este bloco se encaixa,
    mas faça a seleção e a descrição do corte somente com a evidência temporal deste bloco.
    - Cada corte deve ter entre {duracao_minima} e {duracao_maxima} segundos, evitar os intervalos já usados
    - Os cortes escolhidos dentro desta janela DEVEM abordar momentos diferentes e ter pelo menos 30 segundos de distância entre si. NUNCA retorne intervalos sobrepostos ou colados no mesmo minuto.
    ({usados}) e começar/terminar em frases completas.

REGRAS DOS METADADOS:
- `titulo` deve ser um gancho viral completo, específico e natural em pt-BR.
- Não use o prefixo "Momento:", não quebre frases no meio e não termine em conectivos como "e", "mas",
    "porque", "que" ou "quando".
- `descricao_publicacao` deve explicar brevemente o conteúdo e justificar por que o trecho é uma Vaca Roxa,
    sem inventar informações e sem copiar o MATERIAL BASE inteiro.
- `inicio_segundos` e `fim_segundos` devem ser números decimais absolutos dentro deste bloco, copiados dos
    limites dos segmentos fornecidos.

FORMATO DE RETORNO OBRIGATÓRIO:
Retorne EXCLUSIVAMENTE um JSON puro, sem Markdown, sem comentários e sem texto antes ou depois.
O objeto deve conter EXATAMENTE as chaves `resumo_conteudo` e `melhores_momentos`.
Cada item de `melhores_momentos` deve conter `titulo`, `descricao_publicacao`, `inicio_segundos` e `fim_segundos`.
Os valores devem ser escritos especificamente com base no material deste bloco. Nunca copie exemplos desta instrução.
O array `melhores_momentos` deve conter rigorosamente de {minimo_step} a {maximo_step} itens. Nunca retorne zero itens quando
existir qualquer momento que satisfaça as regras.

Título original: {titulo_original or "não informado"}
Resumo global de apoio:
{resumo_global}

INÍCIO DO MATERIAL PARA ANÁLISE ({inicio_bloco:.1f}s-{fim_bloco:.1f}s)
{texto_bloco}
FIM DO MATERIAL

CONTEXTO MULTIMODAL DESTE BLOCO:
{contexto_bloco or "nenhum gatilho multimodal detectado"}

ÍNDICE EDITORIAL GLOBAL DO VÍDEO:
{contexto_editorial or "não disponível"}

RESPONDA ESTRITAMENTE NESTE FORMATO JSON, SEM ADICIONAR NENHUMA OUTRA CHAVE:
Retorne um objeto com `resumo_conteudo` e `melhores_momentos`; substitua todos os valores por conteúdo factual específico deste bloco.
"""
        inferencia_started_at = time.time()
        try:
            candidato_schema = {
                "type": "object",
                "required": ["resumo_conteudo", "melhores_momentos"],
                "properties": {
                    "resumo_conteudo": {"type": "string"},
                    "melhores_momentos": {
                        "type": "array",
                        "minItems": minimo_step,
                        "maxItems": maximo_step,
                        "items": {
                            "type": "object",
                            "required": ["titulo", "descricao_publicacao", "inicio_segundos", "fim_segundos"],
                            "properties": {
                                "titulo": {"type": "string"},
                                "descricao_publicacao": {"type": "string"},
                                "inicio_segundos": {"type": "number"},
                                "fim_segundos": {"type": "number"},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                            "additionalProperties": False,
            }
            timeout_bloco = _calcular_timeout_ollama(fim_bloco - inicio_bloco)
            resposta = _gerar_resposta_ollama(prompt, cancel_callback=cancel_callback, timeout=timeout_bloco, json_schema=candidato_schema, num_ctx=16384)
            if resposta.get("status_code") != 200:
                raise requests.RequestException(f"Ollama HTTP {resposta.get('status_code')}")
            try:
                candidatos_extraidos = _extrair_candidatos(resposta)
            except EditorialResponseParseError as primeiro_erro:
                resposta_corrigida = _gerar_resposta_ollama(
                    f"A resposta anterior não respeitou o schema: {primeiro_erro}. Retorne novamente somente JSON com resumo_conteudo e uma lista de {minimo_step} a {maximo_step} objetos em melhores_momentos. Cada objeto deve ter titulo, descricao_publicacao, inicio_segundos e fim_segundos. Não retorne strings na lista.\n\n{prompt}",
                    cancel_callback=cancel_callback,
                    timeout=timeout_bloco,
                    json_schema=candidato_schema,
                    num_ctx=16384,
                )
                if resposta_corrigida.get("status_code") != 200:
                    raise requests.RequestException(f"Ollama HTTP {resposta_corrigida.get('status_code')}")
                candidatos_extraidos = _extrair_candidatos(resposta_corrigida)
            resumo_conteudo = candidatos_extraidos.resumo_conteudo
            candidatos = [_normalizar_candidato_bloco(candidato, inicio_bloco, fim_bloco, segmentos_bloco) for candidato in candidatos_extraidos[:maximo_step]]
            for candidato in candidatos:
                candidato["step"] = numero
                if "score_vaca_roxa" not in candidato and "score_viralidade" in candidato:
                    candidato["score_vaca_roxa"] = candidato["score_viralidade"]
            candidatos_totais.extend(candidatos)
            diagnosticos.append({"step": numero, "inicio": inicio_bloco, "fim": fim_bloco, "candidatos": len(candidatos), "status": "completed"})
            if partial_callback:
                candidatos_persistiveis = [{**corte, "inicio": corte.get("inicio_segundos") if corte.get("inicio_segundos") is not None else corte.get("inicio"), "fim": corte.get("fim_segundos") if corte.get("fim_segundos") is not None else corte.get("fim")} for corte in candidatos_totais]
                partial_callback({"status": "running", "steps_total": len(blocos), "steps_completed": sum(item.get("status") == "completed" for item in diagnosticos), "cortes": candidatos_persistiveis, "candidatos": candidatos_persistiveis, "resumo_conteudo": resumo_conteudo, "diagnostico": list(diagnosticos), "rejeicoes": []})
        except GenerationCancelled:
            raise
        except (json.JSONDecodeError, requests.RequestException, TypeError, AttributeError, ValueError) as error:
            if isinstance(error, EditorialResponseParseError):
                ultimo_erro_parse = error
            diagnosticos.append({"step": numero, "inicio": inicio_bloco, "fim": fim_bloco, "candidatos": 0, "status": "failed", "erro": str(error)})
        finally:
            registrar_log(f"PROFILE inferencia_ollama step={numero} segundos={time.time() - inferencia_started_at:.2f}")
    if not candidatos_totais and ultimo_erro_parse:
        raise ultimo_erro_parse
    candidatos_finais = EditorialCandidates(candidatos_totais[:_limite_editorial_global(duracao_total_seg)], diagnosticos)
    candidatos_finais.resumo_conteudo = locals().get("resumo_conteudo", "")
    candidatos_finais.steps_total = len(blocos)
    candidatos_finais.steps_completed = sum(item.get("status") == "completed" for item in diagnosticos)
    return candidatos_finais


def _normalizar_candidato_bloco(candidato, inicio_bloco, fim_bloco, segmentos=None):
    """Converte tempos do step e aproxima-os dos limites reais dos segmentos."""
    normalizado = dict(candidato)
    inicio = normalizado.get("inicio_segundos", normalizado.get("inicio"))
    fim = normalizado.get("fim_segundos", normalizado.get("fim"))
    try:
        inicio_num = _segundos_editoriais(inicio)
        fim_num = _segundos_editoriais(fim)
    except (TypeError, ValueError):
        return normalizado
    duracao_bloco = max(0.0, float(fim_bloco) - float(inicio_bloco))
    inicio_bloco = float(inicio_bloco)
    fim_bloco = float(fim_bloco)
    duracao_bloco = max(0.0, fim_bloco - inicio_bloco)
    esta_absoluto = inicio_bloco <= inicio_num < fim_num <= fim_bloco
    esta_relativo = 0 <= inicio_num < fim_num <= duracao_bloco
    if not esta_absoluto and esta_relativo:
        inicio_num += float(inicio_bloco)
        fim_num += float(inicio_bloco)
    inicio_num = min(fim_bloco, max(inicio_bloco, inicio_num))
    fim_num = min(fim_bloco, max(inicio_bloco, fim_num))
    if segmentos:
        segmentos_janela = [
            segmento for segmento in segmentos
            if float(segmento["fim"]) > inicio_bloco and float(segmento["inicio"]) < fim_bloco
        ]
        if segmentos_janela:
            limites_inicio = [float(segmento["inicio"]) for segmento in segmentos_janela]
            limites_fim = [float(segmento["fim"]) for segmento in segmentos_janela]
            inicio_num = min(limites_inicio, key=lambda limite: abs(limite - inicio_num))
            fim_num = min(limites_fim, key=lambda limite: abs(limite - fim_num))
            if fim_num <= inicio_num:
                fim_num = max(limites_fim, key=lambda limite: limite if limite > inicio_num else -1)
    normalizado["inicio"] = inicio_num
    normalizado["fim"] = fim_num
    normalizado["inicio_segundos"] = inicio_num
    normalizado["fim_segundos"] = fim_num
    return normalizado


def gerar_cortes_com_retry(transcricao_texto, duracao_total_seg, segmentos=None,
                           minimo=MIN_CORTES_PADRAO, max_tentativas=1,
                           duracao_minima=10, duracao_maxima=90, progress_callback=None, titulo_original="", cancel_callback=None, cortes_existentes=None, contexto_multimodal="", contexto_editorial="", partial_callback=None, resume_analysis=None):
    duracao_elegivel = _duracao_conteudo_editorial(segmentos) or float(duracao_total_seg or 0)
    limite_global = _limite_editorial_global(duracao_total_seg)
    minimo_calculado = max(int(minimo or 1), max(1, math.ceil(duracao_elegivel / EDITORIAL_STEP_SECONDS)))
    steps_com_material = len(_segmentar_editorial(segmentos or [], duracao_total_seg))
    minimo_exigido = min(minimo_calculado, max(1, steps_com_material))
    intervalos_existentes = []
    for corte in cortes_existentes or []:
        if not isinstance(corte, dict):
            continue
        if str(corte.get("status") or "").casefold() in {"excluido", "falhou", "cancelado"}:
            continue
        try:
            intervalos_existentes.append({
                "inicio": corte.get("inicio", corte.get("inicio_segundos")),
                "fim": corte.get("fim", corte.get("fim_segundos")),
            })
        except (TypeError, ValueError):
            continue
    if OLLAMA_CUTS_ENABLED:
        try:
            if progress_callback:
                progress_callback(1, 1, "editorial", {"candidatos": 0, "candidatos_gerados": 0})
            candidatos_editoriais = _gerar_dossie_editorial_unico(
                transcricao_texto,
                duracao_total_seg,
                segmentos,
                duracao_minima,
                duracao_maxima,
                titulo_original=titulo_original,
                cancel_callback=cancel_callback,
                contexto_multimodal=contexto_multimodal,
                contexto_editorial=contexto_editorial,
                intervalos_usados=[(item["inicio"], item["fim"]) for item in intervalos_existentes],
                partial_callback=partial_callback,
                quantidade_minima=minimo_exigido,
                resume_analysis=resume_analysis,
            )
            resumo_conteudo_editorial = getattr(candidatos_editoriais, "resumo_conteudo", "")
            diagnosticos_editoriais = list(getattr(candidatos_editoriais, "diagnostics", []))
            steps_total = getattr(candidatos_editoriais, "steps_total", None)
            steps_completed = getattr(candidatos_editoriais, "steps_completed", None)
            validos = _candidatos_para_revisao(candidatos_editoriais, segmentos or [], duracao_total_seg, duracao_minima, duracao_maxima)
            candidatos_editoriais = _selecionar_cortes_com_diversidade(_deduplicar_cortes(validos), limite_global)
            if candidatos_editoriais:
                status_job = "completed"
                diagnostico_final = {"tentativa": 1, "candidatos": len(candidatos_editoriais), "aceitos": len(candidatos_editoriais), "status": "editorial_completed", "minimo": minimo_exigido}
                return {"status": status_job, "cortes": candidatos_editoriais[:limite_global], "candidatos": candidatos_editoriais, "editorial_candidatos": candidatos_editoriais, "resumo_conteudo": resumo_conteudo_editorial, "diagnostico": diagnosticos_editoriais + [diagnostico_final], "rejeicoes": [], "minimo": minimo_exigido, "steps_total": steps_total, "steps_completed": steps_completed}
            if max_tentativas > 1:
                if progress_callback:
                    progress_callback(2, max_tentativas, "retry", {"candidatos": len(candidatos_editoriais), "candidatos_gerados": len(candidatos_editoriais)})
                return gerar_cortes_com_retry(
                    transcricao_texto,
                    duracao_total_seg,
                    segmentos,
                    minimo=minimo,
                    max_tentativas=max_tentativas - 1,
                    duracao_minima=duracao_minima,
                    duracao_maxima=duracao_maxima,
                    progress_callback=progress_callback,
                    titulo_original=titulo_original,
                    cancel_callback=cancel_callback,
                    cortes_existentes=cortes_existentes,
                    contexto_multimodal=contexto_multimodal,
                    contexto_editorial=contexto_editorial,
                    partial_callback=partial_callback,
                    resume_analysis=None,
                )
            rejeicao = f"Curadoria editorial insuficiente ({len(candidatos_editoriais)}/{minimo_exigido}); nenhum corte foi renderizado."
            ultimo_diagnostico = diagnosticos_editoriais[-1] if diagnosticos_editoriais else {}
            erro_editorial = ultimo_diagnostico.get("erro", "empty_editorial_response; resposta editorial sem candidatos válidos")
            diagnostico_final = {"tentativa": 1, "candidatos": len(validos), "aceitos": len(validos), "status": "editorial_below_minimum", "erro": erro_editorial, "minimo": minimo_exigido}
            return {"status": "failed", "cortes": [], "candidatos": [], "editorial_candidatos": validos, "diagnostico": diagnosticos_editoriais + [diagnostico_final], "rejeicoes": [rejeicao], "minimo": minimo_exigido, "steps_total": steps_total, "steps_completed": steps_completed}
        except GenerationCancelled:
            raise
        except (json.JSONDecodeError, requests.RequestException, TypeError, AttributeError, ValueError) as error:
            retryable_error = not isinstance(error, requests.Timeout)
            if max_tentativas > 1 and retryable_error:
                if progress_callback:
                    progress_callback(2, max_tentativas, "retry", {"candidatos": 0, "candidatos_gerados": 0, "erro": str(error)})
                return gerar_cortes_com_retry(
                    transcricao_texto,
                    duracao_total_seg,
                    segmentos,
                    minimo=minimo,
                    max_tentativas=max_tentativas - 1,
                    duracao_minima=duracao_minima,
                    duracao_maxima=duracao_maxima,
                    progress_callback=progress_callback,
                    titulo_original=titulo_original,
                    cancel_callback=cancel_callback,
                    cortes_existentes=cortes_existentes,
                    contexto_multimodal=contexto_multimodal,
                    contexto_editorial=contexto_editorial,
                    partial_callback=partial_callback,
                    resume_analysis=None,
                )
            rejeicao = f"Curadoria editorial indisponível: {type(error).__name__}; nenhum corte foi renderizado."
            return {"status": "failed", "cortes": [], "candidatos": [], "editorial_candidatos": [], "diagnostico": [{"tentativa": 1, "candidatos": 0, "aceitos": 0, "status": "editorial_unavailable", "erro": str(error), "minimo": minimo_exigido}], "rejeicoes": [rejeicao], "minimo": minimo_exigido}
    if not OLLAMA_CUTS_ENABLED:
        if progress_callback:
            progress_callback(0, 0, "editorial", {"candidatos": 0, "candidatos_gerados": 0})
        return {
            "status": "failed",
            "cortes": [],
            "candidatos": [],
            "diagnostico": [{"tentativa": 0, "candidatos": 0, "aceitos": 0, "status": "provider_disabled", "minimo": minimo_exigido}],
            "rejeicoes": ["Ollama desativado; nenhum corte foi renderizado."],
            "minimo": minimo_exigido,
        }


def refinar_titulos_com_ia(cortes, titulo_original="", cancel_callback=None):
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
        resposta = _gerar_resposta_ollama(prompt, cancel_callback=cancel_callback)
        if resposta["status_code"] == 200:
            payload = _reparar_json_ollama(resposta.get("response", ""))
            for item in payload.get("titulos", []):
                indice = item.get("indice")
                titulo = normalizar_titulo_corte(item.get("titulo"))
                if isinstance(indice, int) and 0 <= indice < len(cortes) and titulo and not re.match(r"(?i)^(trecho|corte|parte)\b", titulo):
                    cortes[indice]["titulo"] = titulo
    except GenerationCancelled:
        raise
    except (json.JSONDecodeError, requests.RequestException, TypeError, AttributeError):
        pass
    for corte in cortes:
        corte["titulo"] = refinar_titulo_corte(corte.get("titulo"), corte.get("gancho"))
        if _titulo_generico(corte["titulo"]):
            contexto = " ".join(filter(None, (corte.get("gancho"), corte.get("promessa"), corte.get("virada"), corte.get("conclusao"))))
            corte["titulo"] = refinar_titulo_corte(_titulo_editorial_local(contexto), corte.get("gancho"))
    return cortes


def garimpar_vacas_roxas(transcricao_texto, duracao_total_seg, segmentos=None, titulo_original=""):
    return gerar_cortes_com_retry(transcricao_texto, duracao_total_seg, segmentos, titulo_original=titulo_original)["cortes"]


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


def _titulo_tem_evidencia(titulo, texto):
    stopwords = {"a", "as", "ao", "aos", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos", "o", "os", "por", "que", "um", "uma"}
    titulo_tokens = {item for item in _texto_normalizado(titulo).split() if len(item) >= 4 and item not in stopwords}
    texto_tokens = set(_texto_normalizado(texto).split())
    return bool(titulo_tokens and titulo_tokens.intersection(texto_tokens))


def _descricao_editorial_local(corte):
    texto = corte if isinstance(corte, str) else str((corte or {}).get("texto", ""))
    texto = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", " ", texto)).strip()
    frases = [frase.strip() for frase in re.split(r"(?<=[.!?])\s+", texto) if frase.strip()]
    descricao = " ".join(frases[:2]) or texto
    return descricao[:240].rstrip()


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


_RUIDO_AUDIO = re.compile(
    r"^\s*\[(?:(?:[^\]]*\b(?:m[úu]sica|musica)\b[^\]]*)|(?:som|ru[íi]do|ruido|aplausos?|risos?)[^\]]*)\]\s*[.!…]*\s*$",
    re.IGNORECASE,
)
_FALLBACK_INICIO_VAZIO = re.compile(
    r"^\s*(?:(?:ah|eh|é|ent[aã]o|bom|e|mas|a[ií]|olha|tipo|cara|eu|pessoal|gente|galera|a gente)\s*[,;:!?-]?\s*)+",
    re.IGNORECASE,
)
_FALLBACK_EXPRESSAO_VAZIA = re.compile(r"^(?:(?:mais uma vez|de novo)\s*[,;:!?-]?\s*)+", re.IGNORECASE)


def _titulo_de_ruido_audio(titulo):
    return bool(_RUIDO_AUDIO.fullmatch(str(titulo or "")))


def _titulo_generico(titulo):
    normalized = _texto_normalizado(titulo)
    return normalized in {"a gente", "gente", "pessoal", "bom pessoal", "bom galera", "entao"} or len(normalized.split()) < 2


def _segmentos_sao_ruido_audio(segmentos):
    return bool(segmentos) and all(_RUIDO_AUDIO.fullmatch(str(segmento.get("texto", ""))) for segmento in segmentos)


def _candidato_somente_ruido_audio(candidato, segmentos):
    try:
        inicio = float(candidato.get("inicio_segundos") if candidato.get("inicio_segundos") is not None else candidato.get("inicio"))
        fim = float(candidato.get("fim_segundos") if candidato.get("fim_segundos") is not None else candidato.get("fim"))
    except (TypeError, ValueError):
        return False
    trecho = [segmento for segmento in segmentos if segmento["fim"] > inicio and segmento["inicio"] < fim]
    return _segmentos_sao_ruido_audio(trecho)


def _duracao_conteudo_editorial(segmentos):
    intervalos = sorted(
        (float(segmento["inicio"]), float(segmento["fim"]))
        for segmento in segmentos or []
        if not _RUIDO_AUDIO.fullmatch(str(segmento.get("texto", "")))
        and float(segmento.get("fim", 0)) > float(segmento.get("inicio", 0))
    )
    total = 0.0
    inicio_atual = fim_atual = None
    for inicio, fim in intervalos:
        if inicio_atual is None:
            inicio_atual, fim_atual = inicio, fim
        elif inicio <= fim_atual:
            fim_atual = max(fim_atual, fim)
        else:
            total += fim_atual - inicio_atual
            inicio_atual, fim_atual = inicio, fim
    if inicio_atual is not None:
        total += fim_atual - inicio_atual
    return total


def _titulo_editorial_local(texto, fallback_index=None, inicio=None, fim=None):
    try:
        texto = re.sub(r"\s+", " ", str(texto or "")).strip()
        texto = re.sub(r"\[[^\]]*\]", " ", texto)
        texto = _FALLBACK_INICIO_VAZIO.sub("", texto)
        texto = _FALLBACK_EXPRESSAO_VAZIA.sub("", texto)
        frases = [frase.strip() for frase in re.split(r"(?<=[.!?])\s+", texto) if frase.strip()]
        texto = frases[0] if frases else texto
        palavras = re.findall(r"[\wÀ-ÿ]+", texto, flags=re.UNICODE)
        if len(palavras) < 3:
            if inicio is not None and fim is not None:
                return f"Corte do vídeo: [{_formatar_tempo_corte(inicio)} - {_formatar_tempo_corte(fim)}]"
            return f"Corte editorial {fallback_index:02d}" if fallback_index else "Corte do vídeo"

        stopwords = {"a", "as", "ao", "aos", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos", "o", "os", "por", "que", "um", "uma"}
        palavras_titulo = [palavra for palavra in palavras if len(palavra) >= 4 and palavra.casefold() not in stopwords][:8]
        if len(palavras_titulo) < 3:
            palavras_titulo = palavras[:8]
        while palavras_titulo and palavras_titulo[-1].casefold() in {"a", "as", "ao", "aos", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos", "por", "que", "um", "uma"}:
            palavras_titulo.pop()
        frase = " ".join(palavras_titulo)
        frase = frase[:1].upper() + frase[1:]
        if len(frase) > 57:
            frase = frase[:57].rstrip() + "..."
        return frase
    except (AttributeError, TypeError, ValueError):
        if inicio is not None and fim is not None:
            return f"Corte do vídeo: [{_formatar_tempo_corte(inicio)} - {_formatar_tempo_corte(fim)}]"
        return f"Corte editorial {fallback_index:02d}" if fallback_index else "Corte do vídeo"


def validar_cortes(cortes, duracao_total_seg, segmentos=None, score_minimo=70, duracao_minima=10, duracao_maxima=90):
    """Normaliza candidatos da IA sem aplicar curadoria editorial local."""
    if not isinstance(cortes, list):
        return []

    cortes_validos = []
    for corte in cortes:
        if not isinstance(corte, dict):
            continue
        try:
            inicio_raw = corte.get("inicio_segundos") if corte.get("inicio_segundos") is not None else corte.get("inicio")
            fim_raw = corte.get("fim_segundos") if corte.get("fim_segundos") is not None else corte.get("fim")
            if (inicio_raw is None or fim_raw is None) and segmentos:
                inicio_indice = int(corte.get("segmento_inicio"))
                fim_indice = int(corte.get("segmento_fim"))
                selecionados = [segmento for segmento in segmentos if inicio_indice <= segmento["indice"] <= fim_indice]
                if selecionados:
                    inicio_raw = selecionados[0]["inicio"]
                    fim_raw = selecionados[-1]["fim"]
            inicio = _segundos_editoriais(inicio_raw)
            fim = _segundos_editoriais(fim_raw)
        except (TypeError, ValueError):
            continue
        selecionados = []
        if segmentos:
            selecionados = [segmento for segmento in segmentos if segmento["fim"] > inicio and segmento["inicio"] < fim]
            intervalo_frase = _ajustar_limites_para_frases(selecionados, segmentos, duracao_maxima) if selecionados else None
            if not intervalo_frase:
                continue
            _, _, selecionados = intervalo_frase
            inicio = selecionados[0]["inicio"]
            fim = selecionados[-1]["fim"]
        if not 0 <= inicio < fim <= duracao_total_seg or not duracao_minima <= fim - inicio <= duracao_maxima:
            continue
        titulo = str(corte.get("titulo") or corte.get("titulo_sugerido") or "Corte da IA").strip() or "Corte da IA"
        gancho = str(corte.get("gancho") or "Corte selecionado pela IA")
        promessa = str(corte.get("promessa") or corte.get("descricao_publicacao") or "Corte selecionado pela IA")
        virada = str(corte.get("virada") or promessa)
        conclusao = str(corte.get("conclusao") or virada)
        pontuacoes = corte.get("pontuacoes") if isinstance(corte.get("pontuacoes"), dict) else {}
        score = corte.get("score_vaca_roxa", corte.get("score_viralidade", 0))
        if not score and pontuacoes:
            score = calcular_score_corte(pontuacoes)
        try:
            score = float(score or 0)
        except (TypeError, ValueError):
            score = 0
        if 0 <= score <= 10:
            score *= 10
        if score < score_minimo:
            continue
        montagem_intervalos = _montagem_gancho_contexto_retorno(corte, selecionados) if selecionados else corte.get("montagem_intervalos") or []
        cortes_validos.append({
            "titulo": titulo,
            "inicio": inicio,
            "fim": fim,
            "segmento_inicio": selecionados[0]["indice"] if selecionados else corte.get("segmento_inicio"),
            "segmento_fim": selecionados[-1]["indice"] if selecionados else corte.get("segmento_fim"),
            "gancho": gancho,
            "promessa": promessa,
            "virada": virada,
            "conclusao": conclusao,
            "montagem": corte.get("montagem", "continua"),
            "montagem_intervalos": montagem_intervalos,
            "score_vaca_roxa": score,
            "score_viralidade": corte.get("score_viralidade", score),
            "pontuacoes": pontuacoes,
            "descricao_publicacao": corte.get("descricao_publicacao", corte.get("descricao_sugerida", corte.get("descricao", "Sem descrição"))),
            "hashtags": corte.get("hashtags", []),
            "angulo_diferente": corte.get("angulo_diferente", ""),
        })
    return cortes_validos


def normalizar_titulo_corte(titulo, limite=55):
    if not isinstance(titulo, str):
        return ""
    titulo = re.sub(r"^\s*#{1,6}\s*", "", titulo)
    titulo = re.sub(r"\s+#{1,6}\s*$", "", titulo)
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
    """Monta um smart crop 9:16 priorizando a maior face encontrada no trecho."""
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

    deteccoes = []
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path) if os.path.exists(cascade_path) else None
    try:
        amostras = [float(inicio) + (float(fim) - float(inicio)) * fracao for fracao in (0, 0.25, 0.5, 0.75, 1)]
        tamanho_minimo_face = max(12, round(min(w_tot, h_tot) * 0.015))
        for timestamp in amostras:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, round(timestamp * fps)))
            ret, frame = cap.read()
            if not ret or detector is None:
                continue
            cinza = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            rostos = detector.detectMultiScale(
                cinza,
                scaleFactor=1.05,
                minNeighbors=4,
                minSize=(tamanho_minimo_face, tamanho_minimo_face),
            )
            if len(rostos):
                x, y, largura, altura = max(rostos, key=lambda rosto: rosto[2] * rosto[3])
                deteccoes.append((largura * altura, x + largura / 2, y + altura / 2))
    finally:
        cap.release()

    if not deteccoes:
        return (
            "filter_complex:"
            "[0:v]split=2[bgsrc][fgsrc];"
            "[bgsrc]scale=540:960:force_original_aspect_ratio=increase,"
            "crop=540:960,boxblur=10:2,scale=1080:1920[bg];"
            "[fgsrc]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[outv]"
        )

    if deteccoes:
        _, centro_x, centro_y = max(deteccoes, key=lambda deteccao: deteccao[0])

    if eixo == "x":
        x = max(0, min(w_tot - w_corte, round(centro_x - w_corte / 2)))
        y = 0
    else:
        x = 0
        y = max(0, min(h_tot - h_corte, round(centro_y - h_corte / 2)))
    return f"crop={w_corte}:{h_corte}:{x}:{y}"


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
    try:
        _executar_render_com_fallback(
            ffmpeg, video_origem, caminho_saida, inicio_render, fim_render, filtro, 600
        )
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