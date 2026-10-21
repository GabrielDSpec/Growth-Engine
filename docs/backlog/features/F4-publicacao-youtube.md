# F4 - Publicacao e agendamento real no YouTube

## Objetivo

Enviar cortes renderizados para o canal correto, com metadados editoriais e horario de publicacao, sem confundir a avaliacao humana com a publicacao automatica.

## Implementado

- `core/publisher.py` valida a existencia do MP4 e os escopos OAuth `youtube.upload`, `youtube` e `youtube.force-ssl`; as rotas de agendamento e a auto-cura tambem rejeitam arquivos vazios.
- Titulo, descricao e tags sao gerados a partir do contexto do corte e limitados ao contrato do YouTube.
- O upload usa `videos.insert` da YouTube Data API com `privacyStatus=private` e `publishAt`.
- O agendamento pode receber data e hora escolhidas pelo usuario ou gerar slots automaticamente.
- Slots automaticos combinam a recomendacao da Qwen, o contexto do corte, uma matriz comportamental por nicho e historico de views/likes; o ranking preenche todos os horarios futuros disponiveis do dia mais proximo antes de avancar.
- Dois cortes nao recebem o mesmo instante no mesmo lote.
- A selecao explicita continua obrigatoria: candidato renderizado nao e publicado automaticamente.
- `Postar selecionados` inicia uma fila de upload publico imediato, processada sequencialmente e com progresso persistido por job.
- `Agendar selecionados` continua usando `privacyStatus=private` e `publishAt`, com slots manuais ou automaticos.
- Titulo e descricao de cada corte podem ser ajustados antes do upload; a descricao editada e enviada ao YouTube.
- A descricao editorial do Short e gerada e persistida antes de o corte aparecer na Central como pronto para revisao/publicacao. Ela e baseada na transcricao real do trecho, deve ser uma parafrase engajante sem inventar fatos nem copiar a fala, e recebe hashtags relacionadas ao tema.
- Cortes antigos sem `descricao_publicacao` passam por uma preparacao automatica ao abrir a fonte na Central; se a IA nao estiver disponivel, o texto falado nao e salvo como descricao.
- Para cortes originados de vídeos públicos do YouTube, a descrição inclui automaticamente o link `https://www.youtube.com/watch?v=<video_id>` do vídeo original.
- Uploads locais não recebem link de origem, porque não possuem uma URL pública conhecida.
- A postagem e o agendamento permitem selecionar um vídeo relacionado do canal; a escolha é persistida com status `pendente` para aplicação posterior no YouTube Studio.
- O menu do perfil oferece `Renovar permissões YouTube`, iniciando novo consentimento OAuth com `prompt=consent` sem apagar os dados do perfil.
- O fluxo OAuth solicita `access_type=offline` e `prompt=consent`; o callback atualiza o access token e só substitui o refresh token quando o Google devolve um novo valor, preservando o anterior nas reconexões. Publisher e sincronização constroem `Credentials` com access token, refresh token, `token_uri`, client ID e client secret para renovação automática.
- A listagem de cortes repara registros `concluido` cujo MP4 sumiu, alterando-os para `falhou`; as rotas de agendamento recusam arquivos ausentes ou vazios com HTTP 400.

## Bloqueio atual

Perfis conectados antes da ampliação de escopos precisam usar `Renovar permissões YouTube` para conceder `https://www.googleapis.com/auth/youtube`, `https://www.googleapis.com/auth/youtube.force-ssl` e `https://www.googleapis.com/auth/youtube.upload`. O sistema retorna uma mensagem explícita de reautorização e não simula sucesso.

## Aceite

- Um corte sem MP4 ou com arquivo vazio falha sem chamar a API externa.
- Um perfil sem `youtube.upload` falha com instrução de reautorizacao.
- Um upload bem-sucedido retorna o ID do video externo e os metadados usados.
- O usuario consegue revisar e selecionar antes de agendar.
- O usuario consegue postar cortes renderizados imediatamente em fila sequencial.
- O usuario consegue ler a descricao editorial completa em um bloco expansivel antes de publicar.
- Nenhum texto de gancho, promessa ou conclusao e exibido como substituto da descricao do YouTube.
- O agendamento automatico gera datas futuras, ranqueia horarios premium por nicho e so avanca para o dia seguinte quando o limite diario ou a capacidade futura do dia atual foi atingida.
- O upload preserva uma referência clicável ao vídeo original na descrição quando essa origem é um vídeo YouTube válido.

## Limite da API

A YouTube Data API não possui um campo universal no `videos.insert` para criar uma relação nativa "Short derivado de" na lista de conteúdo. A referência por descrição é controlável e auditável; recursos visuais de remix/relacionamento do próprio YouTube dependem das regras e da interface da plataforma.

O seletor de vídeo relacionado já está disponível na postagem, no agendamento e na Biblioteca. A aplicação nativa permanece dependente de automação Playwright no YouTube Studio.

## Proxima validacao

Reautorizar um perfil de teste com permissao de upload, publicar um corte renderizado como privado e conferir no YouTube o ID, titulo, descricao, tags e horario programado.

**Status:** bloqueado por credencial externa
**Progresso:** 90%
**Prioridade:** critica
**Area:** producao
