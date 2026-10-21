"""Remove caches locais de transcricao de um perfil.

Por seguranca, o script apenas lista os arquivos por padrao. Use --confirm
para apagar os arquivos .srt e .json encontrados.
"""

import argparse
from pathlib import Path

from core.config import obter_pastas_midia


def main():
    parser = argparse.ArgumentParser(description="Limpa o cache SRT/JSON de transcricoes")
    parser.add_argument("--perfil-id", type=int, required=True)
    parser.add_argument("--youtube-id", help="Limpa somente caches que contenham este ID")
    parser.add_argument("--confirm", action="store_true", help="Apaga os arquivos encontrados")
    args = parser.parse_args()

    transcript_dir = Path(obter_pastas_midia(args.perfil_id)["transcripts"])
    files = sorted(path for path in transcript_dir.iterdir() if path.is_file() and path.suffix.lower() in {".srt", ".json"})
    if args.youtube_id:
        files = [path for path in files if f"v={args.youtube_id}_" in path.name]

    action = "apagando" if args.confirm else "encontrados"
    print(f"Cache de transcricao {action}: {len(files)} arquivo(s) em {transcript_dir}")
    for path in files:
        if args.confirm:
            path.unlink()
            print(f"APAGADO {path.name}")
        else:
            print(path.name)

    if not args.confirm:
        print("Simulacao concluida. Use --confirm para apagar os arquivos listados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
