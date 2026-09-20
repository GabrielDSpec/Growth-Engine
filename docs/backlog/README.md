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

As sessões de geração de cortes são agrupadas por vídeo original e ciclo de análise; o ciclo é identificado pelo job persistido da sessão para que execuções repetidas não se misturem.

A curadoria exige fronteiras de frases completas. A Qwen pode sinalizar uma oportunidade de montagem `gancho_contexto_retorno`, que o renderer persiste e monta em FFmpeg na ordem gancho, contexto e retorno ao destaque.

Após a revisão, o usuário seleciona os cortes pelos checkboxes. O botão `Agendar selecionados` aparece no painel geral; cada ciclo também possui `Selecionar todos` e `Agendar ciclo`. O agendamento em massa exige que todos os cortes estejam renderizados. A data e a hora podem ser escolhidas no modal; quando omitidas, os três slots configurados do melhor dia são ocupados antes de avançar, com recomendação semântica por tema e horários distintos.

Jobs pesados compartilham um lock por perfil e vídeo. O cancelamento passa por `cancelling` até a thread liberar o lock; não se deve iniciar uma nova geração nem remover o lock manualmente durante esse intervalo.

Na Central, a seção se chama `Cortes gerados`. O vídeo original agrupa os ciclos, e cada ciclo aparece como um acordeão `Ciclo N`, recolhido até o usuário clicar para ver seus cortes. A seleção individual é um botão curto `Postar`/`Selecionado`, com ícone vazio/check e estado verde; a troca não fecha o ciclo. Um corte que já possui MP4 não exibe novamente a ação `Renderizar`.
