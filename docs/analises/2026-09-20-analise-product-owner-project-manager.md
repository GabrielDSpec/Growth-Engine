# Analise de produto e projeto - 2026-09-20

## Papel da analise

Revisao de Product Owner e Project Manager do Growth Engine, cruzando a experiencia da Central, os contratos HTTP, a persistencia SQLite, o publisher YouTube e o backlog. O objetivo e separar o que ja e intuitivo do que ainda exige interpretacao ou pode induzir uma operacao errada.

## O que esta intuitivo

- A separacao entre visao geral, producao, publicacao, Radar e configuracoes.
- O fluxo de cortes: escolher fonte, transcrever, definir duracao, gerar, revisar e renderizar.
- A revisao humana com player vertical, score, titulo, selecao, download, exclusao e agendamento.
- A organizacao por video e ciclos, com acordeoes que preservam a caixa aberta durante a selecao.
- A selecao explicita com `Postar`/`Selecionado`, estado verde e contagem de selecionados.
- Acoes destrutivas com confirmacao e acoes em lote agrupadas na mesma faixa do ciclo.
- Agendamento com recomendacao automatica ou data e horario manuais.
- Progresso de tarefas com etapa, rodada, candidatos, velocidade e ETA.
- A separacao conceitual entre Radar externo e Oportunidades baseadas na Autopsia.

## O que nao esta intuitivo ou ainda esta incompleto

### Alta prioridade

1. `Postar` significava agendamento automatico, embora o texto sugerisse envio imediato. A decisao de produto passa a ser: `Postar selecionados` publica imediatamente, um por vez, e `Agendar selecionados` continua usando slots futuros.
2. O usuario podia selecionar cortes sem MP4 e descobrir o bloqueio apenas no envio. A interface deve informar a necessidade de renderizacao antes da postagem/agendamento.
3. O botao `Editar` abria apenas uma visualizacao duplicada. Ele passa a se chamar `Editar titulo` e permite alterar titulo e descricao de publicacao.
4. O significado de `Ciclo 1` ainda nao esta decidido. Por enquanto, ele deve ser tratado como agrupamento visual de uma sessao/rodada persistida; nao deve ganhar semantica editorial adicional antes de uma decisao do produto.
5. A publicacao depende de `youtube.upload`, mas faltava um caminho claro de reautorizacao do perfil atual.

### Media prioridade

- `Biblioteca` e navegavel, mas ainda e um placeholder.
- `Cortes em revisao` e o badge `06` da navegacao nao sao contagens derivadas da base.
- O estado `cancelling` precisa continuar visivel ate o worker liberar o lock.
- A localizacao e o perfil semantico do Radar precisam ser isolados por perfil.
- O publisher usa offset fixo `-03:00`; o fuso do perfil deve controlar a publicacao.
- O workspace lateral parece um seletor, enquanto o seletor funcional esta no chip do cabecalho.
- Falhas de sincronizacao, analise e publicacao aparecem principalmente como toast e nao como historico persistente de acao.

## Decisoes desta entrega

- Titulo e descricao de publicacao sao metadados editaveis por corte e persistidos no tenant atual.
- A descricao do card representa a descricao que sera enviada ao YouTube, com fallback editorial quando ainda nao foi definida.
- `Postar selecionados` inicia uma fila de postagem imediata; a fila valida MP4, usa upload publico e processa os cortes sequencialmente.
- `Agendar selecionados` permanece separado e usa o fluxo de agendamento existente.
- O job de postagem imediata persiste progresso, resultado, erro e historico do Short publicado.

## Riscos e proximos passos

- Validar com OAuth real que o upload publico funciona no perfil autorizado com `youtube.upload`.
- Definir se postagem imediata deve ter uma segunda confirmacao para evitar publicacao acidental.
- Definir o significado de `Ciclo 1` antes de expor filtros, nomes editoriais ou automacoes baseadas nele.
- Implementar reconexao do perfil atual, contagens reais, Biblioteca e isolamento do Radar.
- Adicionar testes de integracao para a fila sequencial, falha no item N, cancelamento e recuperacao apos reinicio.

## Referencias

- `frontend/app.js`: curadoria, metadados, selecao e fila de postagem.
- `core/cuts_repository.py`: persistencia de titulo e descricao.
- `core/publisher.py`: upload publico e agendado.
- `core/web_server.py`: contratos HTTP e jobs.
- `docs/backlog/index.json`: manifesto operacional do backlog.
