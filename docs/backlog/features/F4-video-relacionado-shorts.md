# F4 - Video relacionado para Shorts

## Objetivo

Permitir escolher um video ja publicado do canal como referencia relacionada de um Short, durante a postagem/agendamento ou depois, na Biblioteca.

## Implementado

- Catalogo por perfil com titulo, miniatura, tipo e status.
- Modal rolavel com pesquisa, selecao unica, OK e Cancelar.
- Escolha persistida em cortes gerados e em Shorts da Biblioteca.
- A relacao fica com status `pendente` para aplicacao posterior no YouTube Studio.
- A publicacao via Data API permanece intacta enquanto a escolha e registrada.
- Apos o upload, um worker Playwright abre o Studio por perfil e atualiza a relacao para `aplicando`, `aplicado` ou `falhou`.
- A Biblioteca tambem dispara a aplicacao assincrona para Shorts que ja existem.
- Timeouts do Playwright sao tratados como falha auditavel do relacionamento e nao interrompem a fila de publicacao dos demais Shorts.
- Em timeout no campo de busca, a automacao preserva uma captura visual e o HTML atual em `youtube_studio_error.png` e `youtube_studio_error.html`, alem de tentar locators semanticos do Playwright antes de falhar.
- O seletor de vídeo relacionado mostra somente vídeos com status publicado; vídeos programados ou agendados não são candidatos.
- O seletor mostra somente vídeos longos (`tipo='video'`), nunca o próprio Short; o endpoint rejeita IDs iguais e o worker replica o status final nos registros de `videos_historico` e `cortes_gerados`.
- O botão "Atualizar agora" bloqueia cliques concorrentes, acompanha o status da sincronização e recarrega a lista sem reutilizar dados antigos.
- A lista ordena os itens pela data de publicação; servidores duplicados na porta local foram encerrados para evitar respostas de versões diferentes do backend.
- A atualização inicia e consulta a sincronização no perfil ativo, evitando que a lista leia um perfil enquanto o job atualiza outro; o status informa quantos vídeos longos e Shorts foram encontrados.
- O polling mantém sintaxe válida após reinício e não bloqueia mais o bootstrap da Central antes da montagem da Visão geral.
- A retomada automática preserva o encerramento persistido dos jobs e não reenvia registros stale para o `TaskRunner` ao abrir a Central de cortes.
- A Central de cortes restaura a posição do scroll e os elementos `<details>` abertos por vídeo, ciclo e corte após cada atualização de polling.
- A associação de perfil permanece preservada no conflito global de `video_id`; o vídeo `PQ85Kc7Y6xk` foi confirmado no perfil Aquele Cara de Bigode, não no perfil Ipiranga.
- A lista ordena pela data de publicação mais recente; quando a data está vazia, usa a atualização persistida e o ID como desempate. A data oficial de `PQ85Kc7Y6xk` foi recuperada pelo `yt-dlp`.

## Proximo passo

Validar os seletores do Studio com uma sessao autenticada real e ajustar eventuais variacoes de idioma/layout. Falhas de relacionamento permanecem auditaveis sem invalidar o upload ou interromper o lote.

**Status:** in_progress
**Progresso:** 82%
**Prioridade:** critica
**Area:** producao
