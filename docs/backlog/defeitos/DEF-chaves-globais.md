# DEF - Constraints globais de video_id

**Status:** em andamento
**Progresso:** 45%

As tabelas antigas ainda possuem `UNIQUE` ou `PRIMARY KEY` global em `video_id`. O código já filtra joins e leituras por `perfil_id`, mas a migração definitiva precisa reconstruir as tabelas com chaves compostas, backup WAL e validação de duplicidades entre canais.
