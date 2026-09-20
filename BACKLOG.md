# Backlog do Growth Engine

Backlog funcional e técnico do Growth Engine, organizado para trabalho Ágil. A fonte de contexto é `documentacao_ia.md`, `historico_implementacoes.md`, `docs/arquitetura_modular.md` e o estado atual do código.

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

### E8. Multi-Tenant e Operação Modo Agência (Escala B2B)

- [ ] Refatorar o banco de dados (`SQLite`/futuro `PostgreSQL`) para isolamento de dados por `channel_id`, permitindo o gerenciamento de múltiplos canais simultâneos.
- [ ] Criar painel de alternância rápida de contas (Switch Context) no frontend, sem necessidade de relogar no OAuth.
- [ ] Desenvolver gerador de relatórios executivos em PDF/HTML: compilar a "Autópsia do Mês" para envio automático aos clientes da agência.
- [ ] Implementar controle de acesso (RBAC) com níveis de permissão: Administrador (acesso técnico) e Analista/Cliente (apenas visualização de pautas e aprovação de Shorts).

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

- [ ] Substituir os `threading.Thread` diretos das rotas de transcrição e cortes pelo `TaskRunner`, com limite global, lock por vídeo e estado persistente.
- [ ] Definir limites de threads para Whisper, yt-dlp, RSS e tarefas HTTP, evitando saturação de CPU/RAM e tarefas duplicadas.
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

- [ ] **Reconstrução confiável do perfil semântico:** refatorar/validar o prompt JSON granular, executar retry apenas nos vídeos sem classificação e persistir a causa de cada falha. Aceite: todos os itens têm estado explícito e o perfil só usa classificações válidas.
- [ ] **Oportunidades dos Top 15:** executar o fluxo de sugestões e confirmar que nenhuma notícia do Radar é usada como fonte editorial. Aceite: cada pauta exibe evidência, score, contexto e origem na Autópsia.
- [ ] **Contrato RSS:** manter Bing News e TecMundo no provider correto, criar testes de payload, timeout e feed indisponível. Aceite: fontes de nicho e locais continuam separadas sem derrubar o Radar.
- [ ] **Pipeline de cortes:** conectar a Autópsia aos trechos priorizados, validar FFmpeg e salvar score/origem/estado de cada corte.
- [ ] **Agendamento Playwright:** transformar a execução atual em tarefa controlada, com confirmação, retry, retomada e histórico persistente.
- [ ] **Score e briefing:** implementar os critérios documentados e expor a justificativa de cada decisão, sem nota opaca da IA.
- [ ] **Frontend seguro:** substituir os pontos restantes de `innerHTML` por criação segura de elementos ou restringir rigorosamente os dados interpolados com testes XSS.
- [ ] **Testes de integração:** cobrir endpoints de perfil, análise, Radar, oportunidades, localização e tarefas após o primeiro ciclo de contratos.

### In Progress

- [ ] **Perfil semântico por classificação individual:** a solução monolítica foi substituída por classificações pequenas (`tema_abstrato`, `pilar`, `formato`), mas o rebuild ainda precisa ser concluído e validado com os itens inválidos registrados.
- [ ] **Fila de análise de conteúdo:** a Autópsia dos vídeos longos usa Whisper/Qwen, cache e progresso persistente; é necessário acompanhar a retomada, o total de pendências e o resultado final após reinício.
- [ ] **Modularização do backend:** repositories de notificações, análises e perfil, providers RSS e `TaskRunner` já existem; faltam handlers HTTP por domínio e remoção progressiva da orquestração concentrada.
- [ ] **Hardening operacional:** CSP, Origin, URLs YouTube, perfil Chrome externo e contratos básicos já foram adicionados; faltam XSS residual, limites de threads e validação de FFmpeg.
- [x] **Montagem editorial de gancho:** a Qwen sinaliza `gancho_contexto_retorno`; os intervalos são persistidos e montados no FFmpeg na sequência gancho, contexto e retorno ao destaque.

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
- [x] **Curadoria visual de cortes:** revisão em modal com blur, player do MP4 renderizado em 9:16, ações laterais, agrupamento amigável por ciclo/rodada e exclusão de ciclo com limpeza dos arquivos.
- [x] **Integridade semântica dos cortes:** validação rejeita cortes no meio de frases e expande segmentos Whisper até uma fronteira de encerramento; testes de regressão cobrem ambos os casos.
- [x] **Montagem de retenção:** cortes podem repetir o destaque no começo e retornar ao contexto até o momento original, com fallback contínuo para cortes antigos ou sem marcação válida.
- [x] **Título contextual e publicação em massa:** a Qwen confere o título original contra a transcrição para corrigir ortografia e entidades com evidência; a Central oferece seleção total por ciclo, `Agendar selecionados` e `Agendar ciclo`.

## Definição de pronto do sprint

- [ ] A tarefa tem critério de aceite verificável e fonte de dados identificada.
- [ ] O estado é persistido quando a execução ultrapassa uma requisição.
- [ ] Falhas de provider ou da Qwen aparecem no status e não viram evidência silenciosa.
- [ ] Existe pelo menos um teste de contrato ou comportamento para a mudança.
- [ ] `py_compile`, `node --check`, testes automatizados e endpoint afetado foram executados e registrados no histórico.
- [ ] Documentação, riscos e instruções de retomada foram atualizados.
