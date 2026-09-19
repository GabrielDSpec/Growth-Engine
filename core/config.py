import os

DIRETORIO_PROJETO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PASTA_LONGOS = os.path.join(DIRETORIO_PROJETO, "pracortar")
PASTA_SHORTS = os.path.join(DIRETORIO_PROJETO, "shorts")
PASTA_ARQUIVO = os.path.join(DIRETORIO_PROJETO, "arquivados")
MEDIA_ROOT = os.path.join(DIRETORIO_PROJETO, "media")
CACHE_METADADOS_PATH = os.path.join(DIRETORIO_PROJETO, "cache_metadados.json")
LOG_PATH = os.path.join(DIRETORIO_PROJETO, "erros.log")
MAX_UPLOAD_BYTES = int(os.getenv("GROWTH_ENGINE_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024 * 1024)))
UPLOAD_CHUNK_BYTES = 1024 * 1024
HORARIOS_PICO = ["11:00", "17:30", "20:00"]

for p in [PASTA_LONGOS, PASTA_SHORTS, PASTA_ARQUIVO]:
    os.makedirs(p, exist_ok=True)


def obter_pastas_midia(perfil_id):
    try:
        perfil_id = int(perfil_id)
    except (TypeError, ValueError) as error:
        raise ValueError("perfil_id inválido para mídia") from error
    if perfil_id < 1:
        raise ValueError("perfil_id inválido para mídia")
    raiz = os.path.join(MEDIA_ROOT, str(perfil_id))
    pastas = {
        "root": raiz,
        "uploads": os.path.join(raiz, "uploads"),
        "shorts": os.path.join(raiz, "shorts"),
        "downloads": os.path.join(raiz, "downloads"),
        "transcripts": os.path.join(raiz, "transcripts"),
    }
    for pasta in pastas.values():
        os.makedirs(pasta, exist_ok=True)
    return pastas