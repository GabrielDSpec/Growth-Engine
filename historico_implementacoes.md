# Growth Engine - Historico de Implementacoes

Documento de transferencia para continuidade do projeto e uso por outros agentes de IA.

## Estado atual

- Servidor local: `http://127.0.0.1:4174`.
- Inicializacao recomendada: `iniciar_growth_engine.bat`.
- Segredos: `config.secrets`, protegido por DPAPI do Windows e ignorado pelo Git.
- Perfil Google/YouTube conectado: canal `Gabriel Diaz - Aquele Cara de Bigode`.
- Cache atual: 312 registros de videos.
- Classificacao atual: 219 Shorts, 87 videos longos e 6 nao classificados.
- Taxa media de likes confirmada pela API: aproximadamente 2,58%.
- Autopsia em andamento: primeira rodada dos 15 videos longos mais vistos.
- Ultimo estado observado: 6/15 concluidos, 6/87 no cache. O sexto video e longo e a transcricao Whisper esta avancando internamente; o contador externo so avanca quando cada video termina por completo.

## O que foi implementado

### Inicializacao e segredos

- Criado `iniciar_servidor.py` para iniciar o painel e abrir o navegador.
- Criado `iniciar_growth_engine.bat` para executar por duplo clique.
- Criado `configurar_segredos.py` com janela Tkinter para permitir colar Client ID e Client Secret.
- Criado `core/secrets.py` usando DPAPI do Windows.
- Segredos carregados apenas em memoria antes do OAuth.
- Chave Fernet de tokens validada e regenerada quando estava invalida.
- `config.secrets` adicionado ao `.gitignore`.

### OAuth Google/YouTube

- Corrigido carregamento das credenciais protegidas.
- Permitido HTTP somente para callback local `127.0.0.1`.
- Corrigido fluxo PKCE: `code_verifier` preservado entre inicio e callback.
- Tokens OAuth cifrados no SQLite com Fernet.
- Conexao validada com retorno HTTP 302 e callback concluido.
- Perfil salvo com nome do canal e avatar.
- Escopo de e-mail Google adicionado para futuras reautorizacoes.

### Sincronizacao e cache

- Sincronizacao passou a usar YouTube Data API quando ha perfil OAuth.
- Playlist de uploads usada no lugar da varredura lenta separada de Shorts.
- Estatisticas buscadas em lotes de ate 50 videos.
- Likes indisponiveis nao sobrescrevem likes existentes com zero.
- Cache incremental: sincronizacoes posteriores consultam paginas recentes e IDs pendentes.
- Timeout e tentativas limitadas no fallback yt-dlp.
- Durasoes persistidas em `duracao_segundos`.
- Regra operacional: ate 180 segundos = Short; acima = Longo.
- Registros sem duracao verificavel sao `indefinido`, nao entram como Longos.

### Painel e experiencia

- Indicador de ultima sincronizacao deixou de ser fixo e usa `last_sync_at` do SQLite.
- Fila de trabalho mostra progresso, itens processados, percentual e ETA.
- Painel recupera uma sincronizacao ja ativa ao ser recarregado.
- Cache HTTP desabilitado para arquivos locais.
- Tema claro/escuro com preferencia salva no navegador.
- Fonte trocada para Plus Jakarta Sans.
- Textos auxiliares, descricoes e insights ampliados.
- Contraste reforcado no tema escuro.
- Insights da visao geral usam videos e metricas reais.
- Avatar servido pelo backend local em `/api/profiles/google/avatar`, com fallback para inicial.
- Nome da conta/canal no topo deixou de ser fixo.

### Fila de inteligencia de conteudo

- Criada tabela `analises_conteudo` com status por video.
- Criado `core/content_intelligence.py`.
- Transcricoes existentes sao reutilizadas.
- Analises concluidas nao sao repetidas.
- Primeira rodada processa os 15 Longos mais vistos.
- Resultados salvam observacoes, trechos literais, hipoteses e dados ausentes em JSON.
- Botao `Rodar autopsia` conectado a endpoint real.

### Radar local

- Criado `core/radar.py`.
- Criada tabela `preferencias_usuario`.
- Endpoints preparados:
  - `GET /api/radar/location`
  - `POST /api/radar/location`
  - `GET /api/radar`
- Radar consulta Google News RSS por eventos, noticias e temas extraidos dos titulos do canal.
- Resultados incluem titulo, fonte, data, link, categoria, motivo e indicacao de verificacao.
- Cada resultado agora inclui `mapa_url` com busca contextual no Google Maps e campo reservado para coordenadas, sem inventar endereços.
- O Radar foi separado em oportunidades locais e oportunidades de nicho; notícias de nicho podem ser consultadas sem localização configurada.
- O Radar de nicho passou a combinar até 50 títulos do canal e análises de conteúdo concluídas, em vez de depender apenas de poucos títulos do ranking.
- Criado o desenho do perfil semântico `perfis_conteudo`: resumo do canal, temas nucleares, formatos, público provável, pilares, padrões de títulos, ganchos, contextos, hipóteses e dados ausentes.
- Radar refinado: múltiplas consultas por tema, triagem editorial individual pela Qwen, descarte de notícias administrativas/genéricas, janela de 7 dias, limite de 3 itens por tema e score de relevância.
- Localização formatada na interface como `Bairro - Cidade - UF`, com capitalização Unicode correta.
- Títulos de notícias passaram a ter versão curta para exibição, preservando o título original no tooltip.
- Sem localizacao, o sistema nao tenta inferir a posicao.
- Onboarding implementado no frontend: primeiro uso apos conta conectada solicita bairro, cidade e estado.
- Configuracoes permitem alterar a localizacao posteriormente.

## Pontos importantes para continuidade

1. Nao reiniciar o servidor enquanto a Autopsia estiver processando; isso interrompe a tarefa em memoria.
2. O status externo e por video completo. Um video longo pode ficar muitos minutos em `6/15` enquanto o Whisper transcreve.
3. Para verificar atividade durante a transcricao, olhar o terminal do servidor: aparecem segmentos Whisper com timestamps crescentes.
4. Depois que a rodada 15/15 terminar, reiniciar o servidor para ativar as ultimas rotas do Radar e do onboarding.
5. O e-mail Google so sera preenchido apos nova autorizacao, pois o escopo `userinfo.email` foi adicionado depois da primeira conexao.
6. O proximo desenvolvimento de alto valor e consolidar as 15 analises em ideias de videos, titulos, angulos e cortes priorizados.
7. Depois, configurar a localizacao do usuario e testar `GET /api/radar` com fontes reais.
8. Eventos e noticias devem sempre mostrar fonte e link; nunca publicar oportunidade externa sem verificacao.

## Backlog priorizado adicionado

- Score de oportunidade para pautas.
- Gerador de briefing para transformar oportunidade em plano de gravação.
- DNA do canal com temas, formatos, durações e engajamento.
- Painel separando fatos, hipóteses, recomendações e dados ausentes.
- Laboratório de testes A/B de títulos e ganchos.
- Mapa de pautas por localização, tema, data e urgência.
- Detector de vídeos esquecidos ou mal embalados.
- Memória de decisões editoriais.
- API persistente de oportunidades em `core/opportunities.py`.
- `POST /api/opportunities` calcula score e retorna briefing inicial.
- `GET /api/opportunities` lista pautas salvas.
- `GET /api/opportunities/{id}/briefing` retorna briefing estruturado.
- Decisão registrada: Oportunidades é separada do Radar e usa somente a Autópsia dos Top 15 como fonte editorial.
- O Radar continua restrito a descoberta externa de notícias/eventos e não deve preencher Oportunidades automaticamente.
- Criada tabela `tarefas_processamento` e módulo `core/tasks.py` para persistir status, progresso, erro e horários das tarefas.
- A Autópsia passa a salvar progresso persistente em uma próxima inicialização, permitindo retomada e diagnóstico após reinício.

Ordem escolhida: consolidar Autópsia, implementar Score de oportunidade, implementar briefing, integrar ao Radar e depois criar testes e memória editorial.

## Comandos de verificacao

```powershell
Invoke-RestMethod http://127.0.0.1:4174/api/content-analysis/status
Invoke-RestMethod http://127.0.0.1:4174/api/dashboard
Invoke-RestMethod http://127.0.0.1:4174/api/profiles/google/status
```

Para salvar localizacao via PowerShell:

```powershell
$body = @{ bairro = 'Centro'; cidade = 'Sao Paulo'; estado = 'SP' } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:4174/api/radar/location -Method Post -Body $body -ContentType 'application/json'
```

## Regra para futuras alteracoes

Toda implementacao relevante deve atualizar este arquivo com:

- data e objetivo;
- arquivos tocados;
- comportamento novo;
- validacao executada;
- pendencias e riscos.

## Entrega de 19/09/2026 - Curadoria, ciclos e integridade semântica

- A Central de cortes passou a agrupar sessões por vídeo e ciclo com rótulos amigáveis de ciclo/rodada, sem expor o ID do job na interface.
- A revisão usa um modal com fundo escurecido e blur; o próprio MP4 renderizado é o player vertical 9:16.
- Foram adicionadas ações laterais de Editar, Renderizar e Excluir, além da exclusão de ciclo completo com remoção dos MP4s gerados.
- O prompt da Qwen exige início e fim em frases completas e sinaliza a estrutura editorial opcional `gancho_contexto_retorno`.
- A validação expande segmentos Whisper até uma fronteira de frase quando possível e rejeita candidatos que terminam no meio da fala.
- Testes de regressão cobrem truncamento e expansão de frases; a suíte completa passou com 38 testes.
- Pendência explícita: o renderer ainda trabalha com intervalo contínuo e não monta fisicamente a sequência gancho, contexto e retorno ao destaque.

## Continuação de 19/09/2026 - Montagem de retenção no FFmpeg

- Candidatos `gancho_contexto_retorno` agora localizam o gancho e o destaque nos segmentos Whisper e geram três intervalos ordenados: gancho, contexto e destaque.
- A montagem é persistida em `cortes_gerados.montagem_json`, com migração automática para bancos existentes.
- O renderer cria partes temporárias, aplica o encode configurado e concatena os arquivos com FFmpeg; cortes antigos continuam no caminho contínuo.
- Teste de contrato adicionado para validar a ordem dos intervalos compostos.
- A pendência de montagem não contínua foi concluída; permanecem payload bruto da Qwen e motivo individual de rejeição estrutural.

## Handoff de 19/09/2026 - Renderer de Shorts

- Objetivo: corrigir o corte horizontal, manter o rosto no quadro vertical e evitar cortes abruptos de palavras.
- Arquivo principal: `core/cutter.py`.
- Nova função: `renderizar_corte_shorts(video_origem, inicio, fim, caminho_saida)`.
- O filtro FFmpeg calcula `crop=W:H:X:Y,scale=1080:1920:flags=lanczos`; `X:Y` vem do centro médio do maior rosto detectado em nove amostras OpenCV. Sem detecção, o fallback é o centro da imagem.
- O intervalo usa padding padrão de `0.3s` no início e `0.5s` no fim, limitado pela duração do FFprobe. As variáveis `SHORTS_PADDING_INICIO` e `SHORTS_PADDING_FIM` permitem configuração.
- O comando usa `libx264`, `crf 20`, `yuv420p`, AAC `192k`, `-map 0:a?` e `+faststart`; o áudio é mantido quando existe.
- `cortar_com_ffmpeg` grava em `media/<perfil_id>/shorts`; `executar_cortes` agora aceita `perfil_id=1`.
- Dependências instaladas no `.venv`: `opencv-python`, `requests`, `tqdm`, `yt-dlp` e `faster-whisper`.
- Comando reproduzível: `\.venv\Scripts\python.exe -m pip install opencv-python requests tqdm yt-dlp faster-whisper`.
- FFmpeg/FFprobe foram encontrados como executáveis locais na raiz do projeto; `core.cutter` importou corretamente após a instalação.
- Validação concluída: compilação sintática de `core/cutter.py` e import do renderer. Smoke test real de mídia ainda pendente.
- Risco conhecido: o ambiente não expõe FFmpeg no `PATH`, mas `core.media_tools.localizar_ferramentas()` resolve `ffmpeg.exe` e `ffprobe.exe` locais.

## Validacao de 18/09/2026

- Corrigido `VIDEO_THEME_SCHEMA` em `core/content_profile.py`: a chave obrigatoria passou de `tema` para `tema_abstrato`, alinhando o schema com o formato retornado e consumido pelo classificador.
- Adicionada verificacao pos-commit das classificacoes granulares; o perfil nao deve ser salvo como concluido se os IDs classificados nao persistirem no SQLite.
- Corrigido o fallback do avatar em `frontend/app.js`: removido handler inline `onerror` e substituido por elemento DOM com listener de erro.
- Servidor reiniciado e validado em `http://127.0.0.1:4174`; reconstrução granular concluida com 10 classificacoes persistidas para 15 videos base.
- Agregacoes SQLite confirmadas por tema e pilar; perfil atualizado em `13:57:01`.
- Validacoes executadas: `py_compile`, `node --check`, endpoints de status/reconstrucao e consulta direta das tabelas `classificacoes_conteudo` e `perfis_conteudo`.
- Risco restante: 5 dos 15 videos nao receberam classificacao valida nesta rodada; a tarefa conclui com os itens validos, e a causa individual ainda nao e registrada no banco.
- A fila de analise de conteudo foi ampliada para todos os videos longos pendentes; execucao iniciada pelo endpoint e acompanhada pelo status do painel.
- A pasta `perfil_chrome_youtube` foi movida para `%LOCALAPPDATA%\GrowthEngine\ChromeProfile`; `Local State` e `Default` confirmados no destino.
- Criado `tests/test_core_contracts.py` com contratos para URLs YouTube, schema semantico, rotulos e score de cortes.
- Criada `falhas_classificacao_conteudo` para registrar por video respostas semanticas invalidas ou erros da Qwen.
- Adicionados indices SQLite para fila de analises, ranking por tipo/views e agregacoes por tema/pilar.
- O status inicial da fila agora informa o total de pendencias antes do primeiro Whisper, evitando a exibicao enganosa de `0/0`.
- A rodada iniciada antes do reinicio ainda esta processando o primeiro video longo; apos sua conclusao, o servidor deve ser reiniciado para carregar a fila sem limite e as novas migracoes.
- Criado `docs/arquitetura_modular.md` com camadas, regras de dependência, critérios de aceitação e plano de migração modular.
- Criado `core/radar_sources.py`; `core/radar.py` ficou responsável pela regra editorial, cache e composição local/nicho.
- Criado `core/task_runner.py`; `core/web_server.py` deixou de possuir a implementação direta do executor e do lock de tarefas.
- Adicionado teste de contrato para impedir duas tarefas com o mesmo nome em paralelo.
- Criado `core/notification_repository.py`; o serviço de notificações deixou de conter SQL direto.
- Adicionado teste de contrato para o formato retornado pelo repository de notificações.
- Criado `core/content_analysis_repository.py`; a orquestração de análise não contém mais SQL direto da fila.
- Criado `core/content_profile_repository.py`; a consolidação semântica não contém mais SQL direto de vídeos, classificações ou perfis.
- Criado `core/opportunities_repository.py`; score, briefing e geração de sugestões foram separados da persistência SQL.
- Implementada a Sprint de estabilidade de hardware: `threading.Thread` direto foi removido das rotas de transcrição/cortes, substituído por `TaskRunner(max_workers=1)` com lock compartilhado `video:<id>`.
- Criada a tabela `tarefas_jobs` e `core/job_repository.py` para persistir estado, progresso, erro e resultado dos jobs; tarefas interrompidas são recuperadas como `interrupted` no boot.
- Smoke test pós-reinício: endpoints principais HTTP 200, job inexistente HTTP 404, tabela de jobs presente e zero jobs `queued/running` presos.
- Bug do Radar registrado e resolvido: a tela podia mascarar falha/cache como ausência de dados. Foi adicionado refresh forçado, `no-store`, botão de atualização e aviso explícito de erro; validação confirmou 2 itens de nicho no endpoint.
- Processo definido: bugs relatados devem ser registrados no `BACKLOG.md` com sintoma, investigação, causa, solução, validação e estado final.
- Reconstrução semântica endurecida: `VIDEO_THEME_PROMPT` exige JSON estrito, `_parse_classification_response` valida exatamente `tema_abstrato`, `pilar` e `formato`, e `_classificar_videos` tenta novamente até três vezes por vídeo.
- Respostas inválidas não entram em `classificacoes_conteudo`; após esgotar as tentativas, a causa acumulada é registrada em `falhas_classificacao_conteudo`.
- Validação executada: 15 testes, `py_compile` dos módulos afetados e `node --check`.
- Fases 1 e 2 do frontend seguro iniciadas: criados `createElement`, `setText`, `setSafeLink` e `clearElement`; notificações e busca foram migradas para DOM seguro, preservando classes e ações existentes.
- Validação das Fases 1/2: `node --check`, diagnósticos sem erros e CSS dos componentes preservado; Radar, Dashboard e demais renderizadores continuam pendentes para a próxima fase.
- Fases 3/4 executadas: Radar, Oportunidades, Dashboard, Ranking e Publicação passaram a construir seus nós com DOM seguro; links do Radar usam `setSafeLink` com allowlist `http/https`.
- Validação das Fases 3/4: `node --check`, diagnósticos sem erros, endpoints de Radar/Dashboard/Ranking/Oportunidades/Publicação em HTTP 200.
- Resíduo conhecido: definições legadas sobrescritas de alguns renderizadores ainda contêm `innerHTML` no arquivo, mas não são chamadas pelo dispatcher atual; devem ser removidas na limpeza final antes das Fases 5/6.
- Fases 5/6 executadas: renderizador ativo de Cortes usa `textContent`/DOM para transcrições Whisper, sugestões da Qwen e progresso; `replaceView` usa `clearElement`/`appendChild` para substituir a raiz sem `appView.innerHTML`.
- Etapa A de Oportunidades dos Top 15 executada: schema/repository passaram a persistir `evidencia_json`, `origem_tipo`, `origem_video_ids` e `origem_resumo`; geração validada exclusivamente contra os vídeos da Autópsia.
- Contrato da Qwen para oportunidades agora exige JSON estrito, 3-5 sugestões, `video_ids`, trechos, observações, hipóteses, views e likes; IDs fora dos Top 15 são rejeitados antes do banco.
- Teste real da Etapa A: primeira resposta inválida foi rejeitada por `relevancia` fora da escala; segunda execução gerou 3 pautas, persistiu origem `autopsia_top15` e zero oportunidades com origem Radar.
- Validação Etapa A: 20 testes passaram, `py_compile` passou e auditoria SQLite confirmou as novas colunas, 3 oportunidades ancoradas e `RADAR_ORIGIN=0`.
- Etapa B de Oportunidades concluída: briefing passou a consumir `evidencia_json`, gerar promessa, abertura, estrutura e versão Short ancoradas nos trechos; listagem resolve IDs para nomes dos vídeos-base.
- Frontend de Oportunidades atualizado com resumo de evidência nos cards e painel DOM-safe de briefing completo, preservando a separação estrita do Radar.
- Validação Etapa B: 21 testes passaram, `node --check`/`py_compile` passaram, `/api/opportunities` e `/api/opportunities/{id}/briefing` responderam HTTP 200 com evidência e `origem_tipo=autopsia_top15`.
- Fase 7 executada: criado `tests/test_frontend_xss.py` cobrindo bloqueio de protocolos perigosos em links, cards do Radar, textos de transcrição/sugestões e Oportunidades.
- Validação final desta etapa: 19 testes passaram, `node --check` passou e diagnósticos do frontend não reportaram erros.
- Risco residual documentado: o arquivo ainda contém definições legadas não executadas com `innerHTML`; a limpeza física dessas definições deve ocorrer antes de considerar o frontend seguro totalmente concluído.
- Limpeza física final concluída: definições legadas removidas de `frontend/app.js`, atualização do ícone de tema migrada para DOM e busca por `innerHTML` retornou zero ocorrências.
- `BACKLOG.md` atualizado: **Frontend seguro** marcado como concluído.
- Backend da Pipeline de cortes implementado: tabela `cortes_gerados`, `core/cuts_repository.py`, `core/media_tools.py` com FFmpeg/FFprobe, timeout, returncode e validação do arquivo final; `_run_cut_job` persiste e atualiza cada corte individualmente.
- Testes unitários com mocks cobrem executável ausente, returncode diferente de zero, timeout, arquivo de origem ausente e remoção de saída parcial. Resultado: 26 testes passaram.
- Etapa pausada antes da integração visual e do teste com arquivo real, conforme aprovação da Sprint.
- E8 Fase 2 inicial implementada: API passou a exigir `X-Profile-Id` nas rotas de domínio, catálogo público `/api/profiles` foi adicionado, OAuth carrega `perfil_id` no estado e salva credenciais associadas ao perfil.
- Frontend passou a manter `activeProfileId`, enviar o header automaticamente, exibir seletor DOM-safe de perfil e recarregar o dashboard ao trocar; o boot não dispara polling passivo de sincronização/análise.
- Smoke test Fase 2: sem header em `/api/dashboard` retorna HTTP 400; com `X-Profile-Id: 1` retorna HTTP 200; catálogo de perfis HTTP 200; avatar por `?perfil_id=1` HTTP 200; suíte completa com 28 testes passou.
- Pendência: repositories e serviços ainda precisam receber o perfil ativo em todos os caminhos de rota; esta etapa estabeleceu a fronteira de sessão e o comportamento sob demanda sem avançar para Upload Local.
- E8 Fase 1 iniciada: migração `migrate_multitenant.py` executada com backup transacional `canal_inteligencia.backup-20260918-151643.db`, tabela `perfis`, Perfil Padrão e colunas `perfil_id` nas tabelas principais.
- Repositories de oportunidades, cortes, análises, perfil, notificações e jobs passaram a aceitar/filtar `perfil_id`; serviços de inteligência também propagam o argumento.
- Testes de isolamento entre Perfil A e Perfil B e chaves tenant-aware do TaskRunner adicionados; suíte completa passou com 28 testes.
- Pendência explícita: consultas SQL diretas em módulos antigos e rotas ainda usam o Perfil Padrão até a Fase 2 de sessão/API; nenhuma rota foi alterada nesta etapa.
- Backlog E2 ampliado com tarefas futuras de Upload Local (.mp4) e Forçar Download/Recorte via `yt-dlp`, sem implementação nesta etapa.
- Etapa 1 da Pipeline de cortes validada: `cortes_gerados`, `cuts_repository.py`, `media_tools.py`, integração do `_run_cut_job` com persistência individual e testes de timeout/returncode/saída parcial.
- Ferramentas reais confirmadas no projeto: `ffmpeg.exe` e `ffprobe.exe`; suíte completa passou com 26 testes. Integração visual e render real permanecem pendentes.
- Integração visual da Pipeline de cortes concluída: `/api/cuts` expõe cortes persistidos, `/api/cuts/file?id=` serve somente MP4 concluído, e a aba DOM-safe exibe título, gancho/promessa, score, status colorido e link seguro.
- Validação visual/HTTP: `/api/cuts`, `/api/cut-sources` e `/api/dashboard` responderam HTTP 200; `node --check` passou, `innerHTML` permaneceu ausente e a suíte completa passou com 26 testes.

## Pausa de 18/09/2026

Estado no encerramento:

- Servidor local funcionando em `http://127.0.0.1:4174`.
- Autópsia: ociosa; rodada inicial dos Top 15 concluída e salva no cache.
- Radar: separado entre local e nicho, com janela de 7 dias, triagem editorial e limite de 3 por tema.
- Oportunidades: separada do Radar; deve usar exclusivamente a Autópsia dos Top 15.
- Perfil semântico: ainda é o principal ponto pendente. A Qwen retornou estruturas inválidas em chamadas monolíticas.
- Nova solução implementada: classificação semântica individual por vídeo usando saída pequena (`tema`, `pilar`, `formato`) e agregação ponderada por views/likes.
- Segurança: CSP, validação de Origin em POSTs, validação de URLs YouTube e exclusão do perfil Chrome adicionadas.
- Performance: Radar com cache TTL de 15 minutos.
- Notificações persistentes e busca global implementadas.

### Primeiro passo ao retomar

1. Abrir Oportunidades e clicar em `Gerar sugestões dos Top 15`.
2. Confirmar que as sugestões são derivadas da Autópsia, sem Radar.
3. Reconstruir o perfil semântico usando a classificação individual por vídeo.
4. Corrigir XSS residual do frontend e mover `perfil_chrome_youtube` para fora do workspace.
5. Limitar threads, validar FFmpeg e adicionar testes automatizados.
