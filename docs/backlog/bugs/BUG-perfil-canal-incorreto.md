# BUG - Canal incorreto após troca de perfil

**Status:** resolvido
**Progresso:** 100%

## Sintoma

Após alternar o perfil, a interface podia manter identidade, vídeos ou fontes do contexto anterior.

## Causa

A troca recarregava apenas o dashboard; fontes de cortes e identidade Google permaneciam em memória.

## Correção

A troca limpa o estado local e recarrega dashboard, fontes, agenda e notificações. A identidade Google é selecionada por `perfil_id`, e o sync consulta a credencial do mesmo perfil.

## Validação

Compilação, 28 testes e consulta do vínculo perfil/canal no SQLite.
