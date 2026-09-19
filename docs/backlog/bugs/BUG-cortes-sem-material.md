# BUG - Cortes antigos exibidos sem material-fonte

**Status:** resolvido
**Progresso:** 100%

## Sintoma

A Central de cortes mostrava registros persistidos mesmo quando não havia material correspondente no contexto atual.

## Correção

A tela limpa o estado ao carregar e filtra cortes pelos IDs presentes em `/api/cut-sources`. Upload local também registra o material no perfil antes do processamento.
