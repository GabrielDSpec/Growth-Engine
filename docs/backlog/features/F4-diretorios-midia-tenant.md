# F4 - Diretorios de midia por perfil

## Objetivo

Manter uploads, downloads, transcricoes e Shorts isolados por `perfil_id`.

## Estado

- [x] Workers de corte resolvem a origem por `videos_historico` e `perfil_id`.
- [x] Saidas de cortes usam `media/<perfil_id>/shorts`.
- [x] Cache SRT usa `media/<perfil_id>/transcripts`.
- [ ] Migrar e auditar todas as rotinas legadas que ainda usam diretorios globais.
