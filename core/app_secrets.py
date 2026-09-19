import base64
import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = PROJECT_ROOT / "config.secrets"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect(data):
    if os.name != "nt":
        raise RuntimeError("A proteção DPAPI deste projeto exige Windows.")
    source = ctypes.create_string_buffer(data)
    input_blob = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    output_blob = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def _unprotect(data):
    if os.name != "nt":
        raise RuntimeError("A proteção DPAPI deste projeto exige Windows.")
    source = ctypes.create_string_buffer(data)
    input_blob = _Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    output_blob = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def salvar_segredos(segredos):
    payload = json.dumps(segredos, ensure_ascii=False).encode("utf-8")
    SECRETS_PATH.write_text(base64.b64encode(_protect(payload)).decode("ascii"), encoding="ascii")
    try:
        os.chmod(SECRETS_PATH, 0o600)
    except OSError:
        pass


def carregar_segredos():
    if not SECRETS_PATH.exists():
        return {}
    encrypted = base64.b64decode(SECRETS_PATH.read_text(encoding="ascii"))
    return json.loads(_unprotect(encrypted).decode("utf-8"))


def carregar_segredos_no_ambiente():
    for nome, valor in carregar_segredos().items():
        if valor:
            os.environ.setdefault(nome, str(valor))