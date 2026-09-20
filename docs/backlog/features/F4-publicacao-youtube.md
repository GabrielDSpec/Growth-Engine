# F4 - Publicacao e agendamento real no YouTube

## Objetivo

Enviar cortes renderizados para o canal correto, com metadados editoriais e horario de publicacao, sem confundir a avaliacao humana com a publicacao automatica.

## Implementado

- `core/publisher.py` valida a existencia do MP4 e o escopo OAuth `youtube.upload`.
- Titulo, descricao e tags sao gerados a partir do contexto do corte e limitados ao contrato do YouTube.
- O upload usa `videos.insert` da YouTube Data API com `privacyStatus=private` e `publishAt`.
- O agendamento pode receber data e hora escolhidas pelo usuario ou gerar slots automaticamente.
- Slots automaticos consideram recomendacao da Qwen por corte, historico de views/likes e horarios de pico.
- Dois cortes nao recebem o mesmo instante no mesmo lote.
- A selecao explicita continua obrigatoria: candidato renderizado nao e publicado automaticamente.

## Bloqueio atual

O perfil Google conectado anteriormente possui permissao de leitura, mas nao o escopo `https://www.googleapis.com/auth/youtube.upload`. E necessario reautorizar o perfil para liberar a publicacao real. O sistema retorna uma mensagem explicita de reautorizacao e nao simula sucesso.

## Aceite

- Um corte sem MP4 falha sem chamar a API externa.
- Um perfil sem `youtube.upload` falha com instrução de reautorizacao.
- Um upload bem-sucedido retorna o ID do video externo e os metadados usados.
- O usuario consegue revisar e selecionar antes de agendar.
- O agendamento automatico gera datas futuras e horarios distintos.

## Proxima validacao

Reautorizar um perfil de teste com permissao de upload, publicar um corte renderizado como privado e conferir no YouTube o ID, titulo, descricao, tags e horario programado.

**Status:** bloqueado por credencial externa
**Progresso:** 85%
**Prioridade:** critica
**Area:** producao
