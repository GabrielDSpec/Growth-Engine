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

TRANSCRIÇÃO / CONTEXTO DO CORTE:
{contexto}

Analise internamente se o corte é uma Vaca Roxa. Se for, gere o JSON puro abaixo (sem markdown fora):
{{
  "vaca_roxa": true,
  "indice_remarkabilidade": "alta/media",
  "pilar": "NOME_DO_PILAR",
  "titulo": "...",
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