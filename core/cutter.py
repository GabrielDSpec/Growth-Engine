import json
import os
import re
import shutil
import subprocess
import cv2
import requests
from tqdm import tqdm
from core.media_tools import renderizar_corte
from core.config import DIRETORIO_PROJETO, PASTA_LONGOS, PASTA_SHORTS, PASTA_ARQUIVO
from core.utils import registrar_log, carregar_cache_metadados, salvar_cache_metadados, calcular_hash_arquivo
from core.transcriber import transcrever_arquivo_local_segmentos

MIN_CORTES_PADRAO = 9
MAX_CORTES_SOLICITADOS = 15
MAX_TENTATIVAS_QWEN = 3


def _montar_prompt(transcricao_texto, duracao_total_seg, segmentos, tentativa, cortes_atuais, rejeicoes, duracao_minima=10, duracao_maxima=90):
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
    como índices inclusivos; não invente timestamps. O código calculará os tempos reais.
    Para cada corte, crie um título em pt-BR com no máximo 55 caracteres.
    O título deve usar uma palavra-chave ou entidade realmente presente no trecho, deixar claro o conflito,
    descoberta ou resultado, e despertar curiosidade sem clickbait. Não use #shorts, emojis ou afirmações ausentes.
        Aprove um corte somente se ele tiver uma única ideia, conflito ou contraste claro, começo autossuficiente,
        desenvolvimento e conclusão. O início deve conter o gancho, sem saudação ou contexto dependente de outro vídeo.
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
    Analise a transcrição segmentada ({duracao_total_seg:.1f}s):
    {transcricao_texto}
        Retorne EXCLUSIVAMENTE um objeto JSON puro, sem markdown:
        {{
            "cortes": [{{
            "titulo": "título factual e específico",
            "segmento_inicio": int,
            "segmento_fim": int,
            "gancho": "frase ou ideia literal do início do trecho",
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


def _candidatos_para_revisao(candidatos, segmentos, duracao_total_seg, duracao_minima=10, duracao_maxima=90):
    if not segmentos:
        return []
    revisao = []
    vistos = set()
    for candidato in candidatos:
        if not isinstance(candidato, dict):
            continue
        try:
            inicio_indice = int(candidato.get("segmento_inicio"))
            fim_indice = int(candidato.get("segmento_fim"))
            selecionados = [segmento for segmento in segmentos if inicio_indice <= segmento["indice"] <= fim_indice]
        except (TypeError, ValueError):
            continue
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
        texto = " ".join(segmento["texto"] for segmento in selecionados)
        pontuacoes = candidato.get("pontuacoes") if isinstance(candidato.get("pontuacoes"), dict) else {}
        score = calcular_score_corte(pontuacoes) if pontuacoes else 0
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
            "score_vaca_roxa": score,
            "pontuacoes": pontuacoes,
            "revisao_humana": True,
        })
    return revisao


def gerar_cortes_com_retry(transcricao_texto, duracao_total_seg, segmentos=None,
                           minimo=MIN_CORTES_PADRAO, max_tentativas=MAX_TENTATIVAS_QWEN,
                           duracao_minima=10, duracao_maxima=90):
    aceitos = []
    candidatos_gerados = []
    candidatos_brutos = []
    diagnostico = []
    rejeicoes = []
    for tentativa in range(1, max_tentativas + 1):
        prompt = _montar_prompt(transcricao_texto, duracao_total_seg, segmentos, tentativa, aceitos, rejeicoes, duracao_minima, duracao_maxima)
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
    return {"status": "needs_review", "cortes": aceitos, "candidatos": revisao, "diagnostico": diagnostico, "rejeicoes": rejeicoes, "minimo": minimo}


def garimpar_vacas_roxas(transcricao_texto, duracao_total_seg, segmentos=None):
    return gerar_cortes_com_retry(transcricao_texto, duracao_total_seg, segmentos)["cortes"]


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
        titulo = normalizar_titulo_corte(corte.get("titulo"))
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
            try:
                segmento_inicio = int(segmento_inicio)
                segmento_fim = int(segmento_fim)
                selecionados = [s for s in segmentos if segmento_inicio <= s["indice"] <= segmento_fim]
            except (TypeError, ValueError):
                continue
            if not selecionados or segmento_inicio > segmento_fim:
                continue
            inicio = selecionados[0]["inicio"]
            fim = selecionados[-1]["fim"]
            texto_selecionado = " ".join(s["texto"] for s in selecionados)
            if _texto_normalizado(gancho) not in _texto_normalizado(texto_selecionado):
                continue
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

def calcular_corte_com_rosto(caminho_video, inicio, fim):
    cap = cv2.VideoCapture(caminho_video)
    w_tot, h_tot = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cap.release()
    if h_tot <= 0 or w_tot <= 0: return "crop=ih*(9/16):ih"
    w_corte = h_tot * (9/16)
    try:
        cap = cv2.VideoCapture(caminho_video)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((inicio + ((fim - inicio)/2)) * fps))
        ret, frame = cap.read()
        cap.release()
        if ret:
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            if os.path.exists(cascade_path):
                rostos = cv2.CascadeClassifier(cascade_path).detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(30,30))
                if len(rostos) > 0:
                    cx = rostos[0][0] + (rostos[0][2]/2)
                    return f"crop={w_corte}:{h_tot}:{max(0, min(w_tot - w_corte, cx - (w_corte/2)))}:0"
    except: pass
    return f"crop={w_corte}:{h_tot}:{(w_tot - w_corte)/2}:0"

def cortar_com_ffmpeg(caminho_original, cortes):
    sucesso = True
    for corte in tqdm(cortes, desc="✂️ Renderizando cortes no FFmpeg"):
        titulo = normalizar_titulo_corte(corte.get("titulo")) or "corte_sem_titulo"
        t_limpo = "".join(c for c in titulo if c.isalnum() or c in " _-").replace(" ", "_")
        saida = os.path.join(PASTA_SHORTS, f"{t_limpo}.mp4")
        try:
            renderizar_corte(caminho_original, saida, corte['inicio'], corte['fim'], calcular_corte_com_rosto(caminho_original, corte['inicio'], corte['fim']))
        except Exception:
            sucesso = False
            registrar_log(f"Falha ao renderizar corte em {caminho_original}")
    return sucesso

def executar_cortes(dry_run=False):
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
                    sucesso = cortar_com_ffmpeg(c_longo, cortes)
                    if not sucesso:
                        print(f"⚠️ Arquivo mantido em 'pracortar/' porque algum corte falhou: '{video}'.")
                        continue
        if not dry_run:
            shutil.move(c_longo, os.path.join(PASTA_ARQUIVO, video))
    print("✅ Processo de corte concluído. Shorts despejados em 'shorts/'")