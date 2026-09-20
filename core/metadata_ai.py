import json
import urllib.request

PROMPT_VACA_ROXA_BIGODE = """
Você é o estrategista sênior de growth do canal @aquelecaradebigode, operando sob a Teoria da Vaca Roxa (Seth Godin).
O mercado está entupido de "vacas comuns" (conteúdo previsível). O corte só vence se for UMA VACA ROXA: algo que faça o espectador fechar o short e pensar "caramba, preciso mostrar isso para alguém" ou gerar um take-double/curiosidade visceral.

ARQUÉTIPOS VALIDADOS DO CANAL:
1. TECH/PERRENGUE: Risco real, erro caro ou descoberta técnica tensa (ex: "Queimei minha nova RX 9060 XT?").
2. MICRO-AVENTURA: Deslocamento / rota incomum com atrito real (ex: "Fui de SP pra Bertioga de trem e Uber").
3. NATUREZA/DESAFIO: Força bruta vs obstáculo hostil (ex: "Drone vs Vento Forte").
4. TURISMO/SAZONAL: Impacto visual bruto em evento/local (ex: "Chuva de Pétalas na ExpoFlora 2025").

CRITÉRIOS DE FILTRAGEM (VACA ROXA):
- O tema é apenas informativo? REJEITE ouforce o ângulo de conflito/descoberta.
- Promessa clara: O espectador entende o ganho/transformação em 1 segundo? [cite: 1]
- Substância: O corte suporta o título sem clickbait mentiroso (mentir é crime/lixo; chamar atenção para algo real é estratégia) [cite: 1].

REGRAS DE OURO PARA O TÍTULO:
- Máximo de 55 caracteres.
- Proibido clichê genérico de IA. Use tensão, conflito ou constatação seca.
- Linguagem de quem fala na roda de amigos, não de release corporativo.
- Preserve nomes próprios, marcas, eventos e números exatamente como aparecem no contexto; não invente grafias.
- Nunca responda "N/A", "NA", "não informado" ou texto vazio.
- A descrição deve ter 1 ou 2 frases diferentes, sem repetir a mesma frase ou expressão em sequência.

TRANSCRIÇÃO / CONTEXTO DO CORTE:
{contexto}

Analise internamente se o corte é uma Vaca Roxa. Se for, gere o JSON puro abaixo (sem markdown fora):
{{
  "vaca_roxa": true,
  "indice_remarkabilidade": "alta/media",
  "pilar": "NOME_DO_PILAR",
  "titulo": "...",
    "descricao": "Descrição curta e fiel ao conteúdo, com contexto suficiente para o YouTube.",
  "angulo_diferente": "ESCREVA AQUI O MOTIVO REAL DESTE CORTE SER REMARKÁVEL",
  "tags": ["tag1", "tag2", "tag3"]
}}
"""

def gerar_metadados_blindados(contexto_corte: str) -> dict:
    prompt = PROMPT_VACA_ROXA_BIGODE.format(contexto=contexto_corte)
    payload = {
        "model": "qwen2.5:14b",
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return json.loads(data.get("response", "{}"))
    except Exception as e:
        print(f"⚠️ Erro ao gerar metadata Vaca Roxa: {e}")
        return {}


PROMPT_HORARIO_CORTE = """
Analise este corte de YouTube Shorts e indique quando o público teria maior propensão a assistir organicamente.
Use apenas o tema, a urgência e o comportamento esperado do público descritos no contexto. Não invente dados de analytics.
Responda somente JSON válido:
{{
  "periodo": "manha|almoco|tarde|noite",
  "dias_preferidos": [0, 1, 2, 3, 4, 5, 6],
  "confianca": 0,
  "justificativa": "..."
}}
Os dias usam 0=segunda-feira e 6=domingo. Escolha no máximo três dias e uma confiança de 0 a 1.
Contexto:
__CONTEXTO_CORTE__
"""


def recomendar_horario_corte(contexto_corte: str) -> dict:
    payload = {
        "model": "qwen2.5:14b",
        "prompt": PROMPT_HORARIO_CORTE.replace("__CONTEXTO_CORTE__", contexto_corte),
        "stream": False,
        "format": "json",
    }
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            result = json.loads(data.get("response", "{}"))
            periodo = result.get("periodo") if result.get("periodo") in {"manha", "almoco", "tarde", "noite"} else "noite"
            dias = [int(dia) for dia in result.get("dias_preferidos", []) if str(dia).isdigit() and 0 <= int(dia) <= 6][:3]
            return {"periodo": periodo, "dias_preferidos": dias, "confianca": max(0, min(1, float(result.get("confianca", 0)))), "justificativa": str(result.get("justificativa", ""))[:500]}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"periodo": "noite", "dias_preferidos": [], "confianca": 0, "justificativa": "Sem recomendação semântica disponível; usando os sinais do canal."}