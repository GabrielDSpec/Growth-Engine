import json

from core.autopsia import _consultar_qwen
from core.content_profile_repository import save_classifications, save_profile, select_profile, select_profile_videos


PROFILE_PROMPT = """
Voce e um estrategista de conteudo. Construa um perfil semantico do canal usando somente os dados reais abaixo.
Nao faca contagem de palavras nem trate hashtags como assunto principal. Entenda o conteudo, a intencao,
os cenarios, o publico, os conflitos e os formatos. Separe evidencia observada de hipotese.

Retorne JSON valido com exatamente estas chaves:
{{
  "resumo": "resumo fiel do canal em ate 5 frases",
  "temas_nucleares": ["assuntos semanticos do canal"],
  "formatos": ["formatos recorrentes"],
  "publico_provavel": ["publicos inferidos com cautela"],
  "pilares_editoriais": ["pilares de conteudo"],
  "padroes_de_titulos": ["padroes observaveis"],
  "conflitos_e_ganchos": ["conflitos e ganchos recorrentes"],
  "cenarios_e_contextos": ["lugares e contextos relevantes"],
  "hipoteses": ["hipoteses que ainda exigem dados"],
  "dados_ausentes": ["limitacoes da base"]
}}

Nao retorne uma chave "videos". Os itens de temas_nucleares e pilares_editoriais devem ser rotulos abstratos curtos,
com 2 a 6 palavras, sem nomes de videos, IDs, numeros de views ou frases explicativas.

DADOS DO CANAL:
{dados}
"""

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "resumo": {"type": "string"},
        "temas_nucleares": {"type": "array", "items": {"type": "string", "maxLength": 60}},
        "formatos": {"type": "array", "items": {"type": "string"}},
        "publico_provavel": {"type": "array", "items": {"type": "string"}},
        "pilares_editoriais": {"type": "array", "items": {"type": "string", "maxLength": 60}},
        "padroes_de_titulos": {"type": "array", "items": {"type": "string"}},
        "conflitos_e_ganchos": {"type": "array", "items": {"type": "string"}},
        "cenarios_e_contextos": {"type": "array", "items": {"type": "string"}},
        "hipoteses": {"type": "array", "items": {"type": "string"}},
        "dados_ausentes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "resumo", "temas_nucleares", "formatos", "publico_provavel",
        "pilares_editoriais", "padroes_de_titulos", "conflitos_e_ganchos",
        "cenarios_e_contextos", "hipoteses", "dados_ausentes",
    ],
}

REPAIR_PROMPT = """
Converta o material abaixo em um perfil semântico de canal.
Retorne SOMENTE JSON válido conforme o schema recebido.
Temas e pilares devem ser rótulos abstratos curtos, de 2 a 6 palavras.
Não use títulos, cidades, nomes próprios, IDs, números ou frases explicativas como categorias.
Não retorne a chave videos.

MATERIAL:
{dados}
"""

THEME_PROMPT = """
Analise os resumos forenses de um canal e abstraia o conteúdo em categorias semânticas.
Retorne SOMENTE um JSON com três listas:
temas_nucleares, pilares_editoriais, formatos.
Cada item de temas_nucleares e pilares_editoriais deve ter de 2 a 6 palavras,
ser uma categoria abstrata, não conter cidade, nome próprio, título, ID, número ou explicação.
Não retorne vídeos, frases completas ou exemplos.

RESUMOS FORENSES:
{dados}
"""

THEME_SCHEMA = {
    "type": "object",
    "properties": {
        "temas_nucleares": {"type": "array", "items": {"type": "string"}},
        "pilares_editoriais": {"type": "array", "items": {"type": "string"}},
        "formatos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["temas_nucleares", "pilares_editoriais", "formatos"],
}

VIDEO_THEME_PROMPT = """
Classifique semanticamente este conteúdo de canal.
Retorne SOMENTE um objeto JSON válido, sem Markdown, sem comentários, sem explicações e sem texto antes ou depois.
O objeto deve conter EXATAMENTE as chaves tema_abstrato, pilar e formato; não inclua nenhuma chave adicional.
Categorias de formato de referência: vlog, tutorial, review, storytelling, documentário, gameplay, música, entrevista, experimento.
Todos os valores devem ser strings não vazias. Tema e pilar devem ter de 2 a 6 palavras, sem cidades, nomes, títulos, IDs, números ou frases.
Não copie palavras do título; generalize o assunto e a intenção do conteúdo.

CONTEÚDO:
{dados}
"""

VIDEO_THEME_SCHEMA = {
    "type": "object",
    "properties": {
        "tema_abstrato": {"type": "string"},
        "pilar": {"type": "string"},
        "formato": {"type": "string"},
    },
    "required": ["tema_abstrato", "pilar", "formato"],
}

MAX_CLASSIFICATION_ATTEMPTS = 3
VALID_FORMATS = {"vlog", "tutorial", "review", "storytelling", "documentário", "documentario", "gameplay", "música", "musica", "entrevista", "experimento"}


def _validar_perfil(perfil):
    if not isinstance(perfil, dict):
        return False
    required_lists = ("temas_nucleares", "pilares_editoriais", "formatos", "padroes_de_titulos")
    compact_fields = ("temas_nucleares", "pilares_editoriais")
    valid_lists = all(isinstance(perfil.get(key), list) and perfil.get(key) for key in required_lists)
    compact_labels = all(
        isinstance(label, str)
        and 1 < len(label.split()) <= 8
        and len(label) <= 60
        and not any(character.isdigit() for character in label)
        for field in compact_fields for label in perfil.get(field, [])
    )
    return valid_lists and compact_labels and "videos" not in perfil


def _resumo_para_modelo(dados):
    return [
        {
            "titulo": item.get("titulo", ""),
            "views": item.get("views", 0),
            "likes": item.get("likes", 0),
            "analise": item.get("analise", {}),
        }
        for item in dados
    ]


def _rotulo_valido(value):
    return isinstance(value, str) and 1 < len(value.split()) <= 8 and len(value) <= 60 and not any(character.isdigit() for character in value)


def _parse_classification_response(response):
    try:
        candidate = json.loads(response)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("resposta não é JSON válido") from error
    if not isinstance(candidate, dict):
        raise ValueError("resposta JSON não é um objeto")
    expected_keys = {"tema_abstrato", "pilar", "formato"}
    if set(candidate) != expected_keys:
        raise ValueError("resposta deve conter exatamente tema_abstrato, pilar e formato")
    if not all(isinstance(candidate[key], str) and candidate[key].strip() for key in expected_keys):
        raise ValueError("tema_abstrato, pilar e formato devem ser strings não vazias")
    if not _rotulo_valido(candidate["tema_abstrato"]):
        raise ValueError("tema_abstrato inválido")
    if not _rotulo_valido(candidate["pilar"]):
        raise ValueError("pilar inválido")
    if candidate["formato"].strip().lower() not in VALID_FORMATS:
        raise ValueError("formato inválido")
    return {
        "tema_abstrato": candidate["tema_abstrato"].strip(),
        "pilar": candidate["pilar"].strip(),
        "formato": candidate["formato"].strip(),
    }


def _classificar_videos(dados, progress_callback=None):
    classificados = []
    falhas = []
    for index, item in enumerate(dados, 1):
        material = json.dumps(_resumo_para_modelo([item])[0], ensure_ascii=False)
        errors = []
        for tentativa in range(1, MAX_CLASSIFICATION_ATTEMPTS + 1):
            try:
                prompt = VIDEO_THEME_PROMPT.format(dados=material)
                if tentativa > 1:
                    prompt += "\nA resposta anterior falhou. Corrija o contrato e retorne somente o objeto JSON exigido."
                resposta = _consultar_qwen(
                    prompt,
                    timeout=90,
                    formato=VIDEO_THEME_SCHEMA,
                    model="qwen2.5-coder:14b",
                )
                candidate = _parse_classification_response(resposta)
                classified = {**candidate, "video_id": item["video_id"], "peso": int(item.get("views") or 0) + int(item.get("likes") or 0) * 20}
                classificados.append(classified)
                break
            except (OSError, ValueError, TypeError) as error:
                errors.append(f"tentativa {tentativa}: {error}")
        else:
            falhas.append((item["video_id"], f"{MAX_CLASSIFICATION_ATTEMPTS} tentativas esgotadas; " + "; ".join(errors)))
        if progress_callback:
            progress_callback(index, len(dados), f"Perfil semântico: vídeo {index}/{len(dados)}")
    if not classificados:
        raise ValueError("Nenhum vídeo recebeu classificação semântica válida.")
    return classificados, falhas


def preparar_dados_perfil(limite=15, perfil_id=1):
    dados = select_profile_videos(limite, perfil_id)
    if not dados:
        raise ValueError("Nenhum video longo disponivel para perfilar")
    return dados


def consolidar_perfil_canal(limite=15, progress_callback=None, perfil_id=1):
    dados = preparar_dados_perfil(limite, perfil_id)
    if progress_callback:
        progress_callback(1, 3, "Dados do canal preparados")
    classified, failures = _classificar_videos(dados, progress_callback=progress_callback)
    grouped = save_classifications(classified, failures, perfil_id)
    perfil = {
        "resumo": "Perfil semântico agregado por classificação individual dos vídeos analisados.",
        "temas_nucleares": [row["tema_abstrato"] for row in grouped["temas"]],
        "pilares_editoriais": [row["pilar"] for row in grouped["pilares"]],
        "formatos": [row["formato"] for row in grouped["formatos"]],
        "publico_provavel": [], "padroes_de_titulos": ["padrões semânticos observados"], "conflitos_e_ganchos": [],
        "cenarios_e_contextos": [], "hipoteses": [], "dados_ausentes": [],
    }
    if progress_callback:
        progress_callback(2, 3, "Perfil semântico gerado pela Qwen")
    save_profile(perfil, len(dados), perfil_id)
    if progress_callback:
        progress_callback(3, 3, "Perfil semântico salvo")
    return perfil


def obter_perfil_canal(perfil_id=1):
    result = select_profile(perfil_id)
    return result if result and _validar_perfil(result) else None