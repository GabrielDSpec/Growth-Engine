# F4 - Curadoria manual e cache de candidatos de cortes

## Atualização

- Candidatos estruturalmente válidos agora são renderizados mesmo quando a rodada termina em `needs_review`.
- A Central exibe player, score, intervalo, título, evidência, download e ações de exclusão/agendamento antes da seleção humana.
- A seleção continua separada da aceitação automática: renderizar previamente não marca o candidato como escolhido.
- Quando a IA não produz uma resposta aproveitável, o pipeline cria candidatos de revisão usando janelas contíguas reais da transcrição.
- O job informa rodada, candidatos recebidos e válidos em tempo real, separando aprovação automática de revisão humana.
- Os candidatos aparecem em uma grade compacta; cada item expande individualmente para assistir, selecionar, baixar, excluir ou agendar.
- A rota de mídia suporta `Range`/`206 Partial Content`, permitindo reprodução e avanço no player HTML5.
- Scores zerados de candidatos antigos são recalculados na API com sinais observáveis da transcrição.
- A Central organiza os cortes em menus por vídeo original e, dentro dele, por ciclo de análise identificado pelo job da sessão.
- O título solicitado à IA é uma manchete de YouTube específica, completa e engajante, baseada literalmente no conteúdo do corte.
- A prévia do vídeo usa proporção vertical 9:16, com título acima, arquivo fonte abaixo e score numérico colorido sobre o canto superior esquerdo.
- A revisão abre em modal com fundo escurecido e blur; as ações Editar e Excluir ficam ao lado do player. Renderizar só aparece enquanto o MP4 ainda não existe; depois disso o card oferece Baixar MP4 e Agendar postagem.
- A interface permite excluir um ciclo inteiro, marcando seus cortes como excluídos e removendo os MP4s gerados.
- A validação semântica rejeita limites no meio de frases e amplia segmentos Whisper até o encerramento da frase, dentro da duração máxima.
- O contrato da Qwen sinaliza a oportunidade editorial `gancho_contexto_retorno`, sem inventar falas ou timestamps.
- A montagem composta é persistida em `montagem_json` e o FFmpeg concatena gancho, contexto e destaque; cortes legados usam o intervalo contínuo.
- A Qwen recebe o título original do vídeo, confere coerência com a transcrição e pode corrigir ortografia, nomes e entidades somente quando há evidência no contexto.
- O ciclo oferece `Selecionar todos` e `Agendar ciclo`; a Central também oferece `Agendar selecionados` com uma única data e horário.
- A hierarquia visual mostra `Cortes gerados` por vídeo e ciclos como `Ciclo 1`, `Ciclo 2` etc.; cada ciclo é um acordeão recolhido por padrão e expande somente os cortes daquele ciclo.
- A seleção individual usa um botão curto e alternável: ícone de círculo + `Postar` quando livre e círculo com check verde + `Selecionado` quando ativo, com tooltip e estado `aria-pressed`; a troca atualiza apenas o botão e mantém o ciclo aberto.
- Quando existe seleção, a Central exibe uma barra contextual com a quantidade escolhida e as ações `Renderizar selecionados`, `Postar selecionados`, `Agendar selecionados` e `Excluir selecionados`.
- `Postar selecionados` usa os melhores slots futuros automaticamente; `Agendar selecionados` permite informar data e horário; ambas as ações exigem MP4 renderizado. A exclusão em lote pede uma única confirmação e respeita o perfil atual.

**Status:** em implementacao
**Progresso:** 95%
**Prioridade:** critica
**Area:** producao

## Objetivo

Quando a analise nao atingir nove cortes recomendados, o sistema deve preservar o maximo de candidatos reais encontrados e permitir que o usuario escolha quais serao renderizados. Nenhum candidato pode inventar fala, timestamp ou evidencia.

## Escopo

- Persistir candidatos estruturalmente validos, mesmo quando o score editorial ficar abaixo do limiar recomendado.
- Persistir cada candidato com perfil, video original, titulo do video, job, rodada, score total e subnotas.
- Persistir payload bruto e diagnostico de cada rodada para auditoria e analise futura.
- Exibir candidatos ordenados por score, com alerta para notas baixas ou dados incompletos.
- Permitir selecao individual ou em lote.
- Renderizar candidatos estruturais para revisão humana e reservar a seleção explícita para postagem/agendamento.
- Manter candidatos e rodadas consultaveis sem executar novamente a Qwen.

## Estados

`candidato`, `selecionado`, `renderizando`, `concluido`, `rejeitado`, `falhou` e `cancelado`.

## Identidade da rodada

Cada rodada deve manter `perfil_id`, `video_id`, `video_titulo`, `job_id`, `numero_rodada`, `nome_rodada`, `modelo`, `prompt_versao` e `transcricao_hash`. O nome exibido deve ser estavel e legivel, por exemplo `2026-09-19_video-curadoria-01`.

## Aceite

- Candidatos validos estruturalmente com score abaixo de 70 aparecem na tela para revisao.
- A tela mostra score total, subnotas, intervalo, titulo, gancho e rodada.
- Nenhum candidato e agendado sem selecao explicita; candidatos em `needs_review` podem ser renderizados previamente para avaliacao humana.
- A selecao respeita `perfil_id` e nao permite escolher candidato de outro tenant.
- Uma falha de FFmpeg altera apenas o candidato afetado e preserva os demais.
- Uma analise anterior pode ser consultada pelo video original e pelo nome da rodada.
- O servidor ativo nao precisa ser reiniciado durante a gravacao de um video; a nova versao entra no proximo ciclo.

## Estado atual

- [x] Candidatos estruturalmente validos abaixo do score recomendado sao preservados.
- [x] Candidatos de `needs_review` sao persistidos com video original e rodada.
- [x] API de selecao e job de renderizacao sob aprovacao implementados.
- [x] Interface exibe player, score, ciclo, download, exclusao e agendamento.
- [x] Fallback cria candidatos reais quando a IA retorna estrutura inválida ou vazia.
- [x] Progresso em tempo real informa rodada, candidatos recebidos e candidatos válidos.
- [x] Grade expansível e streaming parcial permitem assistir cada candidato antes da aprovação.
- [x] Score observável substitui o zero quando a IA não fornece subnotas.
- [x] Sessões repetidas do mesmo vídeo ficam separadas por ciclo no histórico visual.
- [x] Card vertical exibe prévia 9:16, título editorial, arquivo fonte e score sem badge vermelho.
- [x] Modal de edição usa o MP4 renderizado como player 9:16 e mantém o fundo desfocado.
- [x] Ciclos podem ser excluídos com rótulo amigável de ciclo/rodada e limpeza do arquivo gerado.
- [x] Fronteiras de cortes preservam frases completas, incluindo expansão de segmentos Whisper truncados.
- [ ] Persistir payload bruto completo de cada resposta da Qwen.
- [ ] Persistir motivo individual para cada rejeicao estrutural.
- [ ] Exibir historico completo de rodadas por video.
- [x] Montar fisicamente cortes não contínuos no formato gancho, contexto e retorno ao destaque com FFmpeg.
- [x] Conferir título original contra transcrição antes de gerar/refinar títulos editoriais.
- [x] Agendar cortes renderizados em massa por seleção geral ou por ciclo.
- [x] Ciclos usam acordeão intuitivo: o cabeçalho mostra somente `Ciclo N` e os cortes aparecem ao expandir.
- [x] Seleção individual usa ícone com estado visual e acessível, sem checkbox textual ocupando o card.
- [x] Ações dos selecionados aparecem na mesma faixa de `Selecionar todos`, `Agendar ciclo` e `Excluir ciclo`.
- [x] `Selecionar todos` atualiza os botões e a contagem sem reconstruir a tela nem fechar o ciclo aberto.
- [x] Cards já renderizados não exibem a ação redundante `Renderizar`; cards sem MP4 continuam oferecendo a ação.