import json
import sys

from core.cutter import _gerar_resposta_ollama_http


def main():
    linha = sys.stdin.readline()
    if not linha:
        return 1
    try:
        payload = json.loads(linha)
        resultado = _gerar_resposta_ollama_http(
            payload["prompt"],
            timeout=float(payload.get("timeout", 90)),
            json_schema=payload.get("json_schema"),
            num_ctx=int(payload.get("num_ctx", 2048)),
        )
        resposta = {"ok": True, "result": resultado}
    except Exception as error:
        resposta = {"ok": False, "error_type": "timeout" if error.__class__.__name__ == "Timeout" else type(error).__name__, "error": str(error)}
    sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())