# Backlog do Growth Engine

Backlog funcional e técnico do Growth Engine, organizado para trabalho Ágil. A fonte de contexto é `documentacao_ia.md`, `historico_implementacoes.md`, `docs/arquitetura_modular.md` e o estado atual do código.

> **Painel estruturado:** abra `http://127.0.0.1:4174/backlog.html` para acompanhar percentuais, filtros e itens por épico, feature, bug, defeito e decisão. A fonte operacional de status é [`docs/backlog/index.json`](docs/backlog/index.json); este arquivo preserva o histórico amplo e aponta para a documentação detalhada por tema.

## Contexto do produto

- Objetivo: transformar vídeos do YouTube em evidência editorial, oportunidades de pauta, cortes para Shorts e publicações agendadas.
- Stack: Python, SQLite, YouTube Data API/OAuth, yt-dlp, faster-whisper, Ollama/Qwen, RSS e Playwright.
- Estado conhecido: cache com 312 vídeos, sendo 219 Shorts, 87 vídeos longos e 6 sem classificação; a Autópsia inicial dos Top 15 foi concluída.
- Regra de produto: Oportunidades usa apenas a Autópsia do canal; Radar é descoberta externa e não alimenta pautas automaticamente.
- Critério de prioridade: primeiro desbloquear inteligência editorial confiável, depois automatizar produção e publicação; segurança, persistência e observabilidade acompanham cada entrega.

## Épicos

### E1. Inteligência editorial baseada em evidência

- [ ] Consolidar o perfil semântico por conta com temas, pilares, formatos, ganchos, contextos, hipóteses e dados ausentes.
- [ ] Gerar Score de oportunidade de 0 a 100 com critérios visíveis: atualidade, relevância, potencial local, facilidade de gravação, potencial de Short e força da evidência.
- [ ] Gerar briefing gravável para cada oportunidade: promessa, título provisório, abertura, estrutura, perguntas, tomadas, local e versões longo/Short.
- [ ] Criar o DNA do canal, comparando temas de alto alcance com temas de alto engajamento, duração, likes e padrões de títulos.
- [ ] Criar painel que diferencie fato observado, hipótese, recomendação e dado ainda necessário.

### E2. Pipeline de produção e cortes

- [ ] Iniciar a pipeline de cortes dinâmicos de vídeos longos para Shorts usando transcrição, trechos literais, gancho, clareza, autonomia e score de corte.
- [ ] Gerar cortes compatíveis com FFmpeg e preparar exportação para DaVinci Resolve/Premiere sem depender de edição manual para cada vídeo.
- [ ] Persistir origem, evidência, versão e estado de cada corte para permitir revisão, retry e auditoria.
- [ ] Criar endpoint e interface de 'Upload Local' para enviar vídeos crus (.mp4), executar transcrição e cortes antes da publicação no YouTube.
- [ ] Criar botão 'Forçar Download/Recorte' para baixar vídeos sob demanda via `yt-dlp` e gerar novos cortes ignorando o cache existente.
- [ ] **Transcrição local acelerada e observável:** executar `large-v3` na AMD Radeon RX 9060 XT usando backend compatível, como Vulkan/whisper.cpp ou HIP/ROCm, tornar modelo e compute type configuráveis e exibir etapa real, tempo decorrido, velocidade, ETA e segmentos processados; proposta em [`docs/backlog/features/F3-transcricao-gpu.md`](docs/backlog/features/F3-transcricao-gpu.md).
- [ ] **Transcrição concluída não aparece nos cortes:** incluir uploads locais nas fontes, distinguir texto sem segmentos de transcrição pronta para cortes e carregar automaticamente a transcrição do primeiro vídeo; registro em [`docs/backlog/bugs/BUG-transcricao-nao-atualiza-cortes.md`](docs/backlog/bugs/BUG-transcricao-nao-atualiza-cortes.md).
- [x] **Curadoria humana de cortes:** candidatos renderizados aparecem em cards com player, título, score, duração, download, exclusão, seleção e agendamento; candidatos abaixo do limiar continuam disponíveis para aprovação humana.
- [x] **Análise de conteúdo observável:** o job exibe progresso por rodada da IA, quantidade de candidatos recebidos e válidos, separando aprovação automática de revisão humana.
- [x] **Fallback de cortes:** quando a resposta do Qwen não atende ao contrato, o pipeline cria janelas contíguas ancoradas na transcrição dentro da faixa escolhida para evitar a tela vazia.
- [x] **Revisão visual dos cortes:** a Central exibe todos os candidatos em grade, expande cada item individualmente e reproduz MP4 com streaming parcial compatível com HTML5.
- [x] **Score editorial observável:** candidatos sem subnotas do Qwen recebem pontuação calculada por sinais da transcrição; scores antigos zerados são recalculados na API.

### E3. Automação de agendamento e publicação

- [ ] Transformar o fluxo Playwright do YouTube Studio em uma tarefa persistente, retomável e observável.
- [ ] Validar slots, fuso horário, arquivo, metadados, privacidade e confirmação final antes de mover o Short para `arquivados/`.
- [ ] Implementar estratégia de publicação baseada em dados reais do canal, sem sobrescrever o histórico de agendamentos.

### E4. Radar de oportunidades externas

- [ ] Consolidar fontes RSS por provider, com timeout, retry, deduplicação, limite por fonte e diagnóstico de falhas.
- [ ] Cruzar temas do perfil semântico com notícias e eventos locais/nicho, mantendo links verificáveis e janela de sete dias.
- [ ] Evoluir o mapa de pautas por localização, tema, data, distância aproximada, urgência e potencial de gravação.

### E5. Plataforma modular e sustentável

- [ ] Extrair handlers HTTP por domínio sem alterar as URLs públicas.
- [ ] Completar a migração de consultas de domínio do gateway compartilhado para repositories.
- [ ] Separar clientes e renderizadores do frontend por domínio, mantendo os contratos HTTP como fronteira.
- [ ] Ampliar contratos para providers externos, persistência, progresso, falhas e retomada.

### E6. Preparação para Cloud/Docker

- [ ] Criar imagem Docker reproduzível com Python, FFmpeg/FFprobe, dependências do Whisper e configuração explícita do Ollama.
- [ ] Separar configuração, segredos, dados SQLite, cache de modelos, perfil do navegador e diretórios de mídia em volumes/variáveis de ambiente.
- [ ] Definir modo de execução local e modo servidor, incluindo healthcheck, logs, migrações e política de backup do SQLite.
- [ ] Documentar limites de CPU, RAM, armazenamento e GPU/CPU para Whisper, Qwen, RSS e Playwright.

### E7. Aprendizado editorial contínuo

- [ ] Criar Laboratório de testes para variações de título, gancho, formato e horário.
- [ ] Criar Detector de vídeos esquecidos: alto engajamento com pouco alcance e muitas views com baixa interação.
- [ ] Criar Memória de decisões para registrar por que uma pauta foi aprovada, rejeitada, adiada ou transformada.

### E8. Multi-Tenant e Operação Modo Agência (Escala B2B) [concluído nas Fases 1-3]

- [ ] Refatorar o banco de dados (`SQLite`/futuro `PostgreSQL`) para isolamento de dados por `channel_id`, permitindo o gerenciamento de múltiplos canais simultâneos.
- [ ] Criar painel de alternância rápida de contas (Switch Context) no frontend, sem necessidade de relogar no OAuth.
- [ ] Desenvolver gerador de relatórios executivos em PDF/HTML: compilar a "Autópsia do Mês" para envio automático aos clientes da agência.
- [ ] Implementar controle de acesso (RBAC) com níveis de permissão: Administrador (acesso técnico) e Analista/Cliente (apenas visualização de pautas e aprovação de Shorts).

### E8 - Fases 1-3 concluídas

- [x] Migração transacional inicial com backup, tabela `perfis`, Perfil Padrão legado e `perfil_id` nas tabelas principais.
- [x] Repositories de oportunidades, cortes, análises, perfil semântico, notificações e jobs filtram por `perfil_id`.
- [x] TaskRunner aceita chaves tenant-aware, como `perfil:<id>:...`.
- [x] Migrar as consultas SQL diretas críticas e adaptar a sessão/API ao perfil ativo.
- [x] Fase 2: sessão, OAuth por perfil, seletor visual, troca de contexto e sincronização sob demanda.
- [x] Fase 3: armazenamento de mídia por perfil, upload local multipart, jobs tenant-aware e pipeline Whisper/Qwen/FFmpeg escopado.

### Relatório da Fase 3 - Modo Híbrido / Upload Local por Perfil

- **Armazenamento:** arquivos brutos, downloads forçados e Shorts resultantes usam `media/<perfil_id>/uploads/`, `media/<perfil_id>/downloads/` e `media/<perfil_id>/shorts/`.
- **Contrato HTTP:** `POST /api/uploads/local` exige `X-Profile-Id`; o servidor valida o perfil ativo antes de criar o arquivo e o job.
- **Pipeline:** o `perfil_id` atravessa o `TaskRunner`, Whisper, Qwen, FFmpeg, `tarefas_jobs` e `cortes_gerados`; a chave do upload é `perfil:<perfil_id>:upload:<job_id>`.
- **Frontend:** o Upload Local envia explicitamente `X-Profile-Id` usando o perfil ativo do chip Google; a renderização continua DOM-safe.
- **Validação:** `node --check frontend/app.js`, `py_compile`, 28 testes automatizados e smoke test HTTP multipart com arquivo/job isolados no perfil `915380`.

PDF executivo e RBAC permanecem itens de evolução da operação de agência, fora do escopo operacional concluído nesta sequência.

### E9. Autópsia de Comunidade (Social Listening)

- [ ] Integrar o endpoint de `CommentThreads` da YouTube Data API para extrair os comentários dos vídeos analisados.
- [ ] Criar pipeline na Qwen para classificar sentimentos, agrupar críticas recorrentes e identificar dúvidas frequentes da audiência.
- [ ] Injetar os dados da comunidade na geração do `Score de Oportunidade`, priorizando pautas que respondem diretamente a perguntas reais dos inscritos.
- [ ] Monitorar a aba de comunidade (Community Posts) para medir o engajamento em testes de variações de título.

### E10. Esteira de Distribuição Omnichannel

- [ ] Expandir o motor de conteúdo para, além de Shorts, gerar formatos em texto baseados na transcrição do Whisper.
- [ ] Criar prompt otimizado na Qwen para converter roteiros em *Threads* (X/Twitter), *Carrosséis* (Instagram/LinkedIn) e *Artigos* (Blog/Newsletter).
- [ ] Adaptar a tabela `oportunidades_conteudo` para rastrear em quais plataformas aquele conhecimento já foi distribuído.

### E11. Monitoramento Competitivo (Stealth Radar)

- [ ] Adicionar funcionalidade no painel para cadastrar URLs de até 3 canais concorrentes diretos.
- [ ] Executar o `yt-dlp` em modo silencioso para mapear a frequência de postagem e os picos de visualização dos concorrentes.
- [ ] Gerar alertas no *Centro de Notificações* sempre que um concorrente postar um vídeo com taxa de *likes/views* significativamente acima da média do nicho, sugerindo pautas de resposta.

## Dívida Técnica & Bugs

### Segurança e isolamento

- [ ] Remover o `innerHTML` residual do frontend ou garantir renderização exclusivamente por DOM seguro; hoje há interpolação em vários renderizadores e apenas alguns valores passam por `escapeHtml`.
- [ ] Confirmar que nenhum perfil Chrome permanece no workspace e remover referências legadas a `perfil_chrome_youtube`; o caminho oficial é `%LOCALAPPDATA%\GrowthEngine\ChromeProfile`.
- [ ] Rever CSP, validação de Origin, URLs do YouTube e entradas de localização com testes de regressão de segurança.
- [ ] Auditar logs para garantir que tokens OAuth, Client Secret, cookies e dados pessoais nunca sejam gravados.

### Concorrência, recursos e robustez

- [x] Substituir os `threading.Thread` diretos das rotas de transcrição e cortes pelo `TaskRunner`, com limite global, lock por vídeo e estado persistente.
- [x] Definir limite inicial de um worker pesado global para Whisper/FFmpeg, com lock compartilhado por vídeo; RSS e tarefas HTTP continuam fora dessa fila.
- [ ] Validar presença, versão e código de saída de FFmpeg/FFprobe antes de iniciar cortes ou transcrição.
- [ ] Garantir cancelamento, timeout, retry com limite e recuperação após reinício para todas as tarefas longas.
- [ ] Substituir `sleep` fixos e seletores frágeis do Playwright por esperas condicionais e testes contra mudanças de interface.

### Dados e qualidade da IA

- [ ] Registrar a causa individual das classificações semânticas inválidas; cinco dos 15 vídeos-base ficaram sem classificação válida na última rodada.
- [ ] Corrigir o rebuild do perfil semântico para que falhas parciais sejam reportadas, reprocessadas e não sejam tratadas como evidência.
- [ ] Garantir que views e likes ausentes não sejam confundidos com zero e que tipos/durações sejam normalizados na entrada.
- [ ] Testar respostas inválidas, incompletas ou fora do schema da Qwen em todos os prompts públicos.
- [ ] Criar retenção e limpeza para transcrições, mídia temporária, cache e logs sem apagar evidência necessária à Autópsia.

### Arquitetura e operação

- [ ] Reduzir a concentração de estado global, SQL e orquestração em `core/web_server.py`.
- [ ] Adicionar migrations/versionamento do SQLite e rotina de backup antes de alterações de schema.
- [ ] Adicionar métricas e notificações para duração, throughput, erro, retry e último sucesso de cada provider.
- [ ] Documentar setup, recuperação, comandos de verificação, contratos de API e procedimento de retomada após queda.

## Quadro Kanban (Sprint Atual)

### To Do

- [x] **Reconstrução confiável do perfil semântico:** prompt JSON estrito, parser estrutural, retry de até 3 tentativas por vídeo e persistência da causa final da falha. Aceite: respostas fora do contrato são rejeitadas e o perfil só usa classificações válidas.
- [x] **Oportunidades dos Top 15:** executar o fluxo de sugestões e confirmar que nenhuma notícia do Radar é usada como fonte editorial. Aceite: cada pauta exibe evidência, score, contexto e origem na Autópsia.
- [ ] **Contrato RSS:** manter Bing News e TecMundo no provider correto, criar testes de payload, timeout e feed indisponível. Aceite: fontes de nicho e locais continuam separadas sem derrubar o Radar.
- [x] **Pipeline de cortes:** backend seguro, integração visual DOM-safe, persistência individual, validação FFmpeg/FFprobe, timeout, estados e link seguro para MP4 concluídos.
- [ ] **Agendamento Playwright:** transformar a execução atual em tarefa controlada, com confirmação, retry, retomada e histórico persistente.
- [ ] **Mínimo de 9 cortes válidos:** retry finito, persistência da transcrição, estado `needs_review` e diagnóstico visual implementados; faltam motivos individuais por regra e retry acionável; proposta em [`docs/backlog/features/F4-cortes-minimo-9.md`](docs/backlog/features/F4-cortes-minimo-9.md).
- [ ] **Curadoria manual de candidatos:** candidatos de `needs_review` são persistidos por vídeo/rodada, exibidos com score e podem ser selecionados para renderização; faltam payload bruto completo, rejeições individuais e histórico de rodadas; proposta em [`docs/backlog/features/F4-curadoria-manual-candidatos.md`](docs/backlog/features/F4-curadoria-manual-candidatos.md).
- [ ] **Score e briefing:** implementar os critérios documentados e expor a justificativa de cada decisão, sem nota opaca da IA.
- [x] **Frontend seguro:** substituir os pontos restantes de `innerHTML` por criação segura de elementos ou restringir rigorosamente os dados interpolados com testes XSS.
- [ ] **Testes de integração:** cobrir endpoints de perfil, análise, Radar, oportunidades, localização e tarefas após o primeiro ciclo de contratos.

### In Progress

- [x] **Perfil semântico por classificação individual:** classificação granular com schema estrito, validação, retry limitado e registro das falhas por vídeo.
- [ ] **Fila de análise de conteúdo:** a Autópsia dos vídeos longos usa Whisper/Qwen, cache e progresso persistente; é necessário acompanhar a retomada, o total de pendências e o resultado final após reinício.
- [ ] **Modularização do backend:** repositories de notificações, análises e perfil, providers RSS e `TaskRunner` já existem; faltam handlers HTTP por domínio e remoção progressiva da orquestração concentrada.
- [ ] **Hardening operacional:** CSP, Origin, URLs YouTube, perfil Chrome externo e contratos básicos já foram adicionados; faltam XSS residual, limites de threads e validação de FFmpeg.
- [x] **Concorrência de hardware:** transcrição e cortes usam um worker pesado global, lock por `video_id`, jobs persistentes e recuperação como `interrupted` após reinício.

### Done

- [x] **OAuth Google/YouTube:** credenciais protegidas por DPAPI, tokens cifrados com Fernet, PKCE corrigido, callback local validado e perfil do canal persistido.
- [x] **Sincronização do YouTube:** uso da API quando há OAuth, playlist de uploads, lotes de até 50 vídeos, cache incremental, preservação de likes existentes e classificação por duração.
- [x] **Cache e Autópsia:** fila `analises_conteudo`, reaproveitamento de transcrições/análises, seleção dos Top 15 longos e Shorts, observações/trechos/hipóteses/dados ausentes em JSON.
- [x] **Perfil Chrome:** movido para `%LOCALAPPDATA%\GrowthEngine\ChromeProfile`, fora do workspace e do controle de versão.
- [x] **Radar:** separado entre local e nicho, com localização explícita, Google News/Bing/Yahoo/Reddit, Flipboard e TecMundo no nicho, G1/UOL no local, triagem Qwen, score e cache TTL.
- [x] **Integração RSS solicitada:** Bing News e feed oficial do TecMundo já estão implementados em `core/radar_sources.py`, com contrato que diferencia fontes locais e de nicho.
- [x] **Oportunidades:** API persistente, score inicial e briefing determinístico; decisão de produto registrada para usar exclusivamente os dados da Autópsia dos Top 15.
- [x] **Perfil semântico granular:** schema corrigido para `tema_abstrato`, `pilar` e `formato`; agregação ponderada por views/likes e verificação pós-persistência implementadas.
- [x] **Persistência de tarefas:** tabela `tarefas_processamento`, progresso, erro, horários, retomada e lock por nome; `TaskRunner` com limite de workers criado.
- [x] **Arquitetura inicial:** repositories de notificações, análises e perfil, provider RSS e executor de tarefas extraídos dos módulos originais.
- [x] **Painel:** progresso com ETA, recuperação de tarefa ativa, tema claro/escuro, última sincronização real, avatar do backend e notificações persistentes.
- [x] **Contratos automatizados:** testes para URLs YouTube, schema semântico, rótulos, score de cortes, fontes RSS, locks, repositories e formato do status.
- [x] **Proteções iniciais:** CSP, validação de Origin em POSTs, validação de URLs YouTube e remoção do handler inline de erro do avatar.

### Registro: reconstrução semântica fora do contrato

- **Sintoma:** a Qwen podia retornar texto, Markdown, JSON incompleto ou categorias inválidas durante a classificação de tema, pilar e formato.
- **Investigação:** `core/content_profile.py` já executava `json.loads`, mas aceitava validação parcial e não tentava novamente; o prompt não proibia explicitamente campos extras e texto externo.
- **Causa:** contrato de saída insuficientemente estrito e ausência de retry por vídeo.
- **Solução:** prompt JSON estrito, parser que exige exatamente três chaves, validação de tipos/rótulos/formato e até três tentativas por vídeo.
- **Validação:** 15 testes passaram, incluindo resposta inválida seguida de válida e três respostas inválidas; nenhuma resposta inválida é classificada.
- **Estado:** resolvido no código; rebuild real da Qwen fica para execução operacional controlada.

## Definição de pronto do sprint

- [ ] A tarefa tem critério de aceite verificável e fonte de dados identificada.
- [ ] O estado é persistido quando a execução ultrapassa uma requisição.
- [ ] Falhas de provider ou da Qwen aparecem no status e não viram evidência silenciosa.
- [ ] Existe pelo menos um teste de contrato ou comportamento para a mudança.
- [ ] `py_compile`, `node --check`, testes automatizados e endpoint afetado foram executados e registrados no histórico.
- [ ] Documentação, riscos e instruções de retomada foram atualizados.

## Protocolo obrigatório para bugs relatados

Todo bug ou defeito relatado deve seguir este fluxo antes de ser considerado encerrado:

1. **Registrar no backlog:** descrever o sintoma, a tela/rota afetada, data e impacto.
2. **Investigar:** localizar o caminho do código, reproduzir o comportamento e registrar a causa provável ou confirmada.
3. **Planejar a solução:** definir a menor correção segura, impactos e possíveis riscos.
4. **Implementar:** alterar somente os módulos necessários e atualizar a entrada do backlog.
5. **Validar:** executar teste focado, testes de regressão, diagnóstico e verificação do endpoint ou fluxo afetado.
6. **Encerrar:** registrar causa, solução, arquivos alterados, validações, estado final e pendências residuais.

Nenhum bug deve ser considerado resolvido apenas porque o código foi alterado; a causa e a validação precisam estar documentadas.

### Registro: Radar exibindo tela vazia

- **Sintoma:** a interface mostrava localização não configurada e nenhum item, embora o backend tivesse localização e notícias de nicho.
- **Investigação:** `/api/radar` respondia corretamente; a tela estava usando um estado antigo/fallback silencioso quando a requisição falhava ou permanecia em cache.
- **Causa:** ausência de atualização forçada e fallback visual que mascarava erros da API como ausência de oportunidades.
- **Solução:** `/api/radar?force=1`, `cache: 'no-store'`, botão `Atualizar Radar` e toast explícito em falha.
- **Validação:** endpoint HTTP 200, localização configurada, 2 itens de nicho retornados, frontend atualizado e 12 testes passando.
- **Estado:** resolvido; Radar local pode permanecer vazio quando nenhum item passa pela triagem editorial.

### Registro: Dashboard carregando tela vazia (resolvido)

- **Sintoma:** o shell carregava, mas `#app-view` permanecia vazio após a limpeza física do frontend.
- **Investigação:** endpoints HTTP e `node --check` estavam normais; Edge headless capturou `renderAutopsy is not defined` durante o dispatcher de inicialização.
- **Causa:** a limpeza removeu renderizadores ainda referenciados pelo dispatcher (`renderAutopsy`, `renderSuggestions`, `renderSettings` e `renderSimple`).
- **Solução:** restaurados renderizadores DOM-safe para essas rotas e mantida a remoção física de `innerHTML`.
- **Validação:** Dashboard renderizado em Edge headless, `node --check` OK, zero `innerHTML` e suíte XSS verde.
- **Estado:** resolvido.

### Registro: Seletor de perfil separado do chip Google (resolvido)

- **Sintoma:** o seletor multi-tenant apareceu como um campo independente no topbar, separado do avatar e nome do canal Google.
- **Causa:** `mountProfileSelector()` inseria um `<select>` diretamente em `.topbar-actions`.
- **Solução:** o seletor passou a reutilizar `.user-chip`, mantendo avatar, nome e seta; as opções aparecem em dropdown DOM-safe.
- **Validação:** Edge headless confirmou `.user-chip` com `data-action=profile-toggle`, nome/avatar Google e `profile-menu`; nenhum `profile-selector` separado é criado.
- **Estado:** resolvido.

### Registro: Novo perfil pede nome manual e OAuth falha

- **Sintoma:** ao adicionar perfil, a interface pede um nome manual; após o OAuth, aparece `Falha ao conectar o YouTube. Consulte o log local.`
- **Investigação:** em andamento; verificar callback OAuth, criação tardia do perfil pelo nome do canal e SQL de persistência das credenciais.
- **Estado:** aberto.

### Registro: Novo perfil pede nome manual e OAuth falha (resolvido)

- **Causa:** o callback criava o perfil pelo título do canal, mas salvava as credenciais usando o `perfil_id` ainda nulo do estado OAuth.
- **Solução:** o callback agora usa o `perfil_id` efetivamente criado; o frontend vai direto ao Google sem pedir nome manual.
- **Validação:** `node --check`, `py_compile` e 28 testes passaram; criação/remoção de perfil continuam válidas.
- **Estado:** resolvido.

### Registro: OAuth Google continua retornando falha genérica (resolvido)

- **Causa confirmada:** o callback criava o perfil novo, mas passava o `perfil_id` ainda nulo ao salvar `perfis_google`, causando falha de persistência.
- **Solução:** usar a variável `perfil_id` efetiva após criação e gravar traceback completo em `erros.log`.
- **Validação:** SQL de persistência testado em transação revertida, `py_compile`, `node --check` e 28 testes passaram.
- **Estado:** resolvido no código; é necessário reiniciar o servidor e repetir o OAuth.

### Registro: OAuth rejeita escopo openid devolvido pelo Google (resolvido)

- **Sintoma:** callback retornava falha genérica e logava `Scope has changed`.
- **Causa:** o Google incluía `openid` na resposta, mas o cliente não declarava esse escopo em `SCOPES_READ_ONLY`.
- **Solução:** `openid` adicionado aos escopos OAuth declarados.
- **Validação:** módulo recompilado e fluxo pronto para nova autorização após reinício.
- **Estado:** resolvido no código.

### Registro: OAuth Google continua retornando falha genérica

- **Sintoma:** o callback continua exibindo `Falha ao conectar o YouTube. Consulte o log local.`.
- **Investigação:** reabrir auditoria do schema `perfis_google`, associação `perfil_id` e persistência do callback; a mensagem atual não expõe a exceção real ao diagnóstico.
- **Estado:** aberto.

### Registro: Dashboard carregando tela vazia (resolvido)

- **Sintoma:** após as refatorações de DOM seguro, o shell do painel carregava, mas o conteúdo de `#app-view` permanecia vazio.
- **Investigação:** endpoints principais respondiam HTTP 200 e `app.js` passava no `node --check`; Edge headless capturou `renderAutopsy is not defined` durante `render()`.
- **Causa:** a limpeza removeu renderizadores ainda referenciados pelo dispatcher.
- **Solução:** renderizadores DOM-safe foram restaurados para Autópsia, Sugestões, Configurações e módulos simples.
- **Validação:** Dashboard renderizado em Edge headless, `node --check` OK, zero `innerHTML` e suíte XSS verde.
- **Estado:** resolvido.
