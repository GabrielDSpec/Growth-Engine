# F4 - Diretorios de midia por perfil

## Objetivo

Manter uploads, downloads, transcricoes e Shorts isolados por `perfil_id`.

## Estado

- [x] Workers de corte resolvem a origem por `videos_historico` e `perfil_id`.
- [x] Saidas de cortes usam `media/<perfil_id>/shorts`.
- [x] Renderer de Shorts aplica crop 9:16 em 1080x1920, smart crop facial amostrado e padding configuravel por `SHORTS_PADDING_INICIO`/`SHORTS_PADDING_FIM`.
- [x] Dependencias do renderer instaladas no `.venv`: `opencv-python`, `requests`, `tqdm`, `yt-dlp` e `faster-whisper`.
- [ ] Validar renderizacao real com video de cada proporcao e conferir enquadramento, audio e metadados finais.
- [x] Cache SRT usa `media/<perfil_id>/transcripts`.
- [ ] Migrar e auditar todas as rotinas legadas que ainda usam diretorios globais.
