# OAuth expirado e container de download

## Sintoma

A sincronização retornava zero itens quando o refresh token Google estava expirado ou revogado. O download forçado também procurava somente arquivos `.mp4`, embora o `yt-dlp` pudesse produzir `.mkv` ou `.webm`.

## Correção

Quando a API do YouTube falha, a sincronização tenta a descoberta pública com `yt-dlp`. O download forçado passa a aceitar `.mp4`, `.mkv` e `.webm`; o arquivo é então encaminhado ao FFmpeg pelo caminho real.

## Limite conhecido

O fallback público não atualiza métricas oficiais do canal. Para isso, o perfil Google precisa ser reautorizado.

## Validação

- `python -m py_compile core/sync_channel.py core/web_server.py`
- Sincronização do perfil 1 encontrou 61 vídeos após `invalid_grant`.
- O ciclo do vídeo `wg_FsCzCUfo` foi enfileirado pelo servidor após a correção.

## Correção relacionada: 403 transitório na transcrição

O download de áudio da transcrição agora usa retries de extração e fragmentos, backoff HTTP e retomada de downloads parciais. Isso evita que um bloqueio transitório do YouTube encerre o job antes do Whisper iniciar.