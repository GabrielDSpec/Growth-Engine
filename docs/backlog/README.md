# Backlog estruturado

Esta pasta organiza o trabalho por tipo e mantém um manifesto único em `index.json`.

## Versionamento

O backlog faz parte do repositório Git e é publicado junto com o código. Cada alteração de produto deve atualizar o item correspondente em `index.json`, o documento Markdown da feature/bug e, quando necessário, o `BACKLOG.md` de contexto amplo. O commit cria o histórico auditável entre implementação, testes e decisão de produto.

## Estrutura

- `epicos/`: objetivos amplos e critérios de conclusão.
- `features/`: funcionalidades entregáveis.
- `bugs/`: comportamento incorreto reproduzível.
- `defeitos/`: dívida técnica, riscos e falhas de qualidade.
- `decisoes/`: decisões arquiteturais e de produto.
- `index.json`: fonte consumida pelo dashboard visual.

## Dashboard

Abra `http://127.0.0.1:4174/backlog.html` com o servidor local ativo. O dashboard consulta `/api/backlog`, recalcula percentuais por tipo e atualiza a cada 10 segundos.

## Regra de progresso

Cada item possui `progress` entre 0 e 100. O progresso de um grupo é a média dos itens do grupo. Status `done` deve ter 100; `blocked` mantém o percentual real e registra a causa em `notes`.

Ao criar ou alterar um item, atualize `index.json` e o documento correspondente na pasta temática. O dashboard deve continuar sendo derivado do manifesto, nunca de texto Markdown.
