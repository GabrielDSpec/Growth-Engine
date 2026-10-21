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

Após a revisão, o usuário seleciona os cortes pelo botão com ícone de círculo/check. Ao existir seleção, uma barra contextual mostra `Renderizar selecionados`, `Postar selecionados`, `Agendar selecionados` e `Excluir selecionados`. `Postar selecionados` publica imediatamente em fila sequencial; `Agendar selecionados` abre o modal para usar recomendação futura ou informar data e horário. Ambas as ações exigem cortes renderizados. Cada ciclo também possui `Selecionar todos` e `Agendar ciclo`, e a exclusão em lote pede uma confirmação única.

A descrição de publicação do Short é gerada e salva antes da revisão, com base na transcrição real do trecho. O card exibe essa descrição em um bloco expansível; o conteúdo não é a fala literal do corte, não recebe fatos inventados e inclui palavras-chave e hashtags relacionadas quando geradas pela IA. Cortes antigos sem descrição são preparados automaticamente ao abrir a fonte.

Na Visão geral, `Cortes em revisão` é uma métrica real por perfil, calculada a partir dos cortes ativos no SQLite. A tela atualiza esse indicador e os demais dados do dashboard automaticamente a cada 30 segundos enquanto permanece aberta.

Jobs pesados compartilham um lock por perfil e vídeo. O cancelamento passa por `cancelling` até o worker liberar o lock. Chamadas ao Ollama rodam em processo isolado com watchdog; timeout ou cancelamento encerra o processo-filho e aciona fallback/limpeza, sem exigir reinicialização manual do servidor.

Na Central, a seção se chama `Cortes gerados`. O vídeo original agrupa os ciclos, e cada ciclo aparece como um acordeão `Ciclo N`, recolhido até o usuário clicar para ver seus cortes. A seleção individual é um botão curto `Postar`/`Selecionado`, com ícone vazio/check e estado verde; a troca não fecha o ciclo. As ações em lote ficam na mesma faixa das ações do ciclo (`Selecionar todos`, `Agendar ciclo` e `Excluir ciclo`). `Selecionar todos` atualiza a seleção sem reconstruir a tela nem fechar o acordeão. Um corte que já possui MP4 não exibe novamente a ação `Renderizar`.
