# Arquitetura modular do Growth Engine

## Objetivo

A plataforma deve permitir adicionar fontes, análises, contas e fluxos de produção sem transformar o servidor ou o frontend em pontos obrigatórios de alteração. Cada módulo deve ter uma responsabilidade clara, dependências explícitas e uma interface pequena.

## Camadas

```text
frontend/
  telas, estado visual e chamadas HTTP

core/web_server.py
  transporte HTTP, autenticação de origem, roteamento e serialização

core/*_service.py
  regras de negócio e orquestração de cada domínio

core/*_providers.py
  YouTube, Ollama, RSS, Whisper e outros serviços externos

core/*_repository.py
  leitura e escrita no SQLite

core/schemas.py
  validação de entradas e saídas externas

core/tasks.py
  estado persistente, progresso, locks e execução assíncrona

tests/
  contratos e testes de comportamento por domínio
```

## Regras obrigatórias

- O servidor não deve implementar regra editorial, SQL de domínio ou parsing de fornecedor.
- Um provedor externo pode falhar sem derrubar o serviço que o utiliza.
- Dados externos devem ser validados antes de entrar no banco ou na interface.
- Funções de negócio devem receber dados e retornar resultados; efeitos colaterais devem ficar em providers e repositories.
- Estado de tarefas deve ser persistido quando a operação puder durar mais que uma requisição.
- Fontes do Radar devem ser adicionadas em um registry/provider, sem alterar a triagem editorial.
- O frontend deve consumir contratos HTTP e não conhecer SQL, modelos de IA ou detalhes de RSS.
- Toda nova feature deve incluir pelo menos um teste de contrato e documentação do fluxo.
- Operações que usam Whisper, FFmpeg ou modelos locais devem declarar o grupo de recurso e passar pelo executor pesado; não podem criar threads diretos.
- O lock de hardware usa `video:<video_id>` e é compartilhado entre transcrição e cortes do mesmo vídeo.

## Estado atual

- Domínios já separados: OAuth, sincronização, transcrição, Autópsia, inteligência de conteúdo, perfil semântico, Radar, Oportunidades, cortes e notificações.
- `core/web_server.py` ainda concentra rotas, estados em memória e orquestração das tarefas.
- `core/database.py` ainda é um gateway compartilhado; consultas de domínio devem migrar gradualmente para repositories.
- `frontend/app.js` ainda concentra renderização, estado e transporte HTTP.
- O transporte/parsing das fontes RSS foi separado de `core/radar.py` em `core/radar_sources.py`.
- A execução limitada e o lock por nome foram separados de `core/web_server.py` em `core/task_runner.py`.
- A persistência de notificações foi separada em `core/notification_repository.py`; `core/notifications.py` permanece como serviço de domínio.
- A persistência da fila de análise foi separada em `core/content_analysis_repository.py`; `core/content_intelligence.py` permanece como orquestrador de Whisper e Qwen.
- A persistência do perfil semântico foi separada em `core/content_profile_repository.py`; `core/content_profile.py` permanece como regra de classificação e agregação.
- A persistência e seleção editorial das oportunidades foi separada em `core/opportunities_repository.py`; `core/opportunities.py` permanece como score, briefing e geração pela Qwen.
- Jobs individuais de transcrição e cortes são persistidos em `tarefas_jobs`; jobs `queued`/`running` são marcados como `interrupted` durante a inicialização seguinte.

## Plano de migração

1. Separar providers RSS do serviço Radar.
2. Consolidar execução e locks em `core/task_runner.py`, mantendo compatibilidade com os endpoints atuais.
3. Criar repositories para notificações, análises, perfil e Radar.
4. Separar handlers HTTP por domínio sem mudar as URLs públicas.
5. Extrair clientes de frontend por domínio e manter renderizadores independentes.
6. Ampliar testes de contratos, falhas de provider, persistência e progresso.

## Critério de aceitação

Uma mudança em um fornecedor externo, como adicionar TecMundo ou trocar o endpoint do YouTube, deve alterar somente o provider correspondente e seus testes. Uma mudança na regra editorial deve alterar o service, sem exigir mudanças no transporte HTTP ou no banco bruto.
