import os
import json
import hashlib
from datetime import datetime
from core.config import LOG_PATH, CACHE_METADADOS_PATH

def registrar_log(mensagem):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{timestamp}] {mensagem}\n"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha)
    except Exception as e:
        print(f"⚠️ Falha ao escrever no log: {e}")

def carregar_cache_metadados():
    if os.path.exists(CACHE_METADADOS_PATH):
        try:
            with open(CACHE_METADADOS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def salvar_cache_metadados(cache_data):
    try:
        with open(CACHE_METADADOS_PATH, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Erro ao salvar cache de metadados: {e}")

def calcular_hash_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()