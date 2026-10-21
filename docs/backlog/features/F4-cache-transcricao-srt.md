# F4 - Cache persistente de transcricao e SRT

## Objetivo

Reutilizar a transcricao segmentada quando o mesmo arquivo for usado novamente para gerar cortes.

## Estado

- [x] Chave baseada em SHA-256 do arquivo e isolamento por perfil.
- [x] SRT persistido em `media/<perfil_id>/transcripts/<sha256>.srt`.
- [x] Cache consultado antes de iniciar Whisper/DirectCompute.
- [x] Segmentos também são persistidos em JSON ao lado do SRT, com leitura prioritária e validação estrutural antes de iniciar qualquer backend de áudio.
- [x] Detecções multimodais de cena e áudio usam caches JSON sidecar por arquivo, invalidados quando o arquivo ou os parâmetros mudam.
- [x] Resumo semântico após cache hit recupera a duração persistida ou calcula o maior fim dos segmentos antes de dimensionar o timeout do Ollama.
- [x] Segmentos persistidos no banco para a interface e para novas sugestoes.
- [x] Limpeza de cache pela Central de cortes remove apenas transcrição, SRT/JSON e dossiê derivado; vídeo, fonte e cortes permanecem na lista para retranscrição.
- [x] O job de transcrição persiste o step `transcription`, o índice de segmentos processados e a cobertura temporal no `checkpoint_json`; o faster-whisper retoma por janelas salvas em sidecar parcial, enquanto o offset retomável do DirectCompute AMD permanece pendente.
- [x] Finalização DirectCompute protegida por watchdog: se o processo não fechar o SRT após atingir o fim estimado/real, o job falha com diagnóstico explícito e libera a fila.
- [x] Exclusão destrutiva de vídeo permanece separada na API administrativa `DELETE /api/videos/{video_id}`.
- [x] Download YouTube resiliente usa timeout de socket, retries ampliados, runtime JavaScript Node, User-Agent de navegador e cookies opcionais por `GROWTH_ENGINE_YOUTUBE_COOKIES` ou `GROWTH_ENGINE_YOUTUBE_COOKIES_FROM_BROWSER` para bloqueios 403 que exigem sessão.
- [ ] Versionar formalmente modelo/backend no metadata do cache.