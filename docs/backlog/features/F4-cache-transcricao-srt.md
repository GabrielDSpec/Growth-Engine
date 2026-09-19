# F4 - Cache persistente de transcricao e SRT

## Objetivo

Reutilizar a transcricao segmentada quando o mesmo arquivo for usado novamente para gerar cortes.

## Estado

- [x] Chave baseada em SHA-256 do arquivo e isolamento por perfil.
- [x] SRT persistido em `media/<perfil_id>/transcripts/<sha256>.srt`.
- [x] Cache consultado antes de iniciar Whisper/DirectCompute.
- [x] Segmentos persistidos no banco para a interface e para novas sugestoes.
- [ ] Versionar formalmente modelo/backend no metadata do cache.