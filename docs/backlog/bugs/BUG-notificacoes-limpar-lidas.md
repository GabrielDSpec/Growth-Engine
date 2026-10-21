# BUG - Limpar notificacoes lidas

## Sintomas

O menu informava sucesso, mas as notificacoes lidas reapareciam depois de recarregar e o painel podia permanecer visualmente aberto apos o clique.

## Causa

A exclusao era executada no SQLite sem `commit()`. Depois da persistencia ser corrigida, o frontend ainda fechava e reabria o painel no mesmo clique, sem atualizar o contador local.

## Correcao

O repositorio confirma a transacao antes de fechar a conexao. O frontend agora substitui o estado local, atualiza o contador imediatamente e remove o painel sem reabrir a lista antiga.

## Evolucao relacionada

O menu tambem oferece `Ler todas`, com endpoint em lote escopado ao `perfil_id` ativo. Se uma instancia antiga do servidor ainda nao possuir a rota, o frontend usa temporariamente a API individual existente. A operacao atualiza a contagem de nao lidas sem excluir o historico das notificacoes.

**Status:** done
**Progresso:** 100%
**Prioridade:** alta
**Area:** producao
