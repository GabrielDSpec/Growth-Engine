# Especificação Corporativa
## Growth Engine

**Versão:** 1.0  
**Data:** 21 de outubro de 2026  
**Classificação:** Documento de apresentação executiva e técnica

## 1. Resumo executivo

O Growth Engine é uma plataforma de inteligência editorial e produção de conteúdo para canais do YouTube. O sistema transforma dados históricos, transcrições, desempenho e contexto externo em decisões editoriais rastreáveis: quais temas merecem atenção, quais trechos podem virar Shorts, como preparar os metadados e como publicar o resultado.

A plataforma combina análise própria do canal, inteligência artificial local, automação de mídia e operação assistida por jobs persistentes. O produto foi concebido para reduzir o trabalho manual entre a descoberta de uma oportunidade e a publicação de um conteúdo curto, preservando evidências e permitindo revisão humana antes de ações irreversíveis.

O núcleo funcional já existe. A próxima etapa para uma oferta corporativa é consolidar isolamento estrutural por tenant, governança de acesso, observabilidade, idempotência de publicação e validação operacional em ambiente controlado.

## 2. Problema de negócio

A produção recorrente de Shorts normalmente exige uma sequência fragmentada de atividades:

- interpretar o histórico do canal;
- identificar temas e formatos que funcionam;
- transcrever vídeos longos;
- localizar momentos relevantes;
- editar e enquadrar o vídeo;
- escrever título e descrição;
- relacionar o Short ao vídeo de origem;
- publicar ou agendar;
- manter rastreabilidade sobre o que já foi utilizado.

Sem uma camada de inteligência e controle, o processo tende a gerar retrabalho, cortes repetidos, decisões baseadas em contexto incorreto, perda de evidência e risco de publicação duplicada.

## 3. Proposta de valor

O Growth Engine entrega uma esteira editorial orientada por evidência:

1. **Conhecer o acervo:** sincronizar vídeos, métricas e classificações.
2. **Entender o canal:** produzir Autópsia, perfil semântico e histórico editorial.
3. **Encontrar oportunidades:** combinar evidência própria com Radar externo, sem misturar as fontes.
4. **Selecionar trechos:** usar transcrição, contexto multimodal, regras temporais e diversidade entre ciclos.
5. **Produzir Shorts:** renderizar, validar e revisar cortes verticais.
6. **Distribuir com controle:** editar metadados, publicar ou agendar mantendo estados persistentes.
7. **Aprender com o processo:** preservar origem, evidência, status, falhas e decisões.

## 4. Escopo funcional

### 4.1 Inteligência do canal

- Sincronização de vídeos e métricas do YouTube.
- Classificação entre vídeos longos e Shorts.
- Autópsia individual e em lote, com observações, trechos, hipóteses e dados ausentes.
- Perfil semântico com temas, pilares e formatos.
- Histórico editorial e análise dos vídeos prioritários.

### 4.2 Descoberta e planejamento

- Radar de notícias, tendências e contexto local/nicho via RSS.
- Oportunidades baseadas na Autópsia do próprio canal.
- Score e briefing editorial em evolução.
- Dossiê editorial versionado, com capítulos, resumo, mapa de calor e momentos.
- Fingerprints para validar a atualidade do cache e da transcrição.

**Regra de governança editorial:** o Radar é uma fonte de descoberta externa; ele não substitui nem contamina a evidência usada para gerar oportunidades do canal.

### 4.3 Transcrição e evidência

- Transcrição por DirectCompute para AMD ou faster-whisper.
- Cache em SRT, JSON e sidecars de processamento.
- Reprocessamento adaptativo quando a cobertura temporal é insuficiente ou dominada por marcadores acústicos.
- Retomada de janelas no faster-whisper.
- Exportação da transcrição em SRT UTF-8.

### 4.4 Curadoria e produção de cortes

- Análise editorial por janelas temporais.
- Preservação de timestamps absolutos e relativos.
- Deduplicação por sobreposição e similaridade.
- Diversidade entre ciclos, evitando repetir intervalos já utilizados.
- Priorização de entrevistas e falas substantivas.
- Validação de títulos e descrições contra o texto real do intervalo.
- Regeneração individual de título ou descrição.
- Renderização 9:16 com FFmpeg.
- Encoder AMD AMF quando disponível e fallback para `libx264`.
- Revisão manual antes da publicação.

### 4.5 Publicação e distribuição

- Seleção individual, por ciclo ou em lote.
- Publicação imediata e agendamento.
- Metadados editáveis por corte.
- Associação entre Short e vídeo longo relacionado.
- Notificações de conclusão e falha.
- Verificação de existência e integridade do MP4 antes de publicar.

### 4.6 Operação e administração

- Central operacional com visão de jobs, progresso e ETA.
- Troca de perfil ativo.
- Upload local por caminho físico.
- Limpeza controlada de caches e artefatos.
- Painel administrativo para manutenção e controle de serviços.
- Backlog e documentação acessíveis na própria Central.

## 5. Fluxo ponta a ponta

```mermaid
flowchart LR
    A[Canal YouTube] --> B[Sincronização]
    B --> C[SQLite e cache]
    C --> D[Transcrição]
    D --> E[Autópsia e perfil semântico]
    E --> F[Dossiê editorial]
    F --> G[Curadoria de cortes]
    G --> H[Revisão humana]
    H --> I[Renderização FFmpeg]
    I --> J[Metadados]
    J --> K[Publicação ou agendamento]
    K --> L[Histórico e notificações]
    R[Radar RSS] --> P[Descoberta externa]
    P -. contexto separado .-> E
```

O fluxo é assíncrono nas etapas longas. Cada execução deve manter `job_id`, perfil, vídeo, etapa, tentativa, progresso, checkpoint, duração e erro.

## 6. Arquitetura da solução

### 6.1 Camadas atuais

- **Interface:** SPA estática em `frontend/index.html`, `frontend/app.js` e CSS próprio.
- **API e orquestração:** servidor HTTP em `core/web_server.py`.
- **Domínio:** módulos de Autópsia, inteligência, perfil, oportunidades, dossiê, cortes e publicação.
- **Persistência:** SQLite com repositories especializados e tabelas operacionais.
- **Execução:** `TaskRunner`, jobs persistentes, checkpoints, notificações e recuperação após reinício.
- **Providers:** YouTube, Ollama/Qwen, Whisper, FFmpeg/FFprobe, RSS e Playwright.
- **Artefatos:** mídia, transcrições, dossiês, Shorts e caches organizados por perfil.

### 6.2 Decisões técnicas relevantes

- IA local reduz dependência de envio de transcrições para serviços externos.
- Cache e fingerprints evitam repetir processamento pesado sem evidência de mudança.
- Contratos JSON, retries e rejeição de placeholders protegem a qualidade das respostas da IA.
- Renderização CPU possui fallback quando o encoder AMD não está disponível.
- O MP4 é validado fisicamente antes de ser considerado pronto.
- Estados operacionais pertencem ao banco, não ao dossiê editorial somente leitura.

### 6.3 Componentes principais

| Componente | Responsabilidade |
|---|---|
| `core/web_server.py` | API HTTP, autenticação de perfil, rotas e orquestração atual |
| `core/database.py` | SQLite, schema, migrações e conexões |
| `core/job_repository.py` | Jobs, estados, checkpoints, duração e retomada |
| `core/task_runner.py` | Execução assíncrona e limite de workers |
| `core/transcriber.py` | Whisper, DirectCompute, SRT, JSON e cache |
| `core/cutter.py` | Seleção, validação editorial e preparação de cortes |
| `core/media_tools.py` | FFmpeg, crop, blur, encoders e validação de saída |
| `core/publisher.py` | Metadados, publicação e agendamento |
| `core/related_video_studio.py` | Automação do vínculo no YouTube Studio |
| `core/radar_sources.py` | Providers e normalização de feeds RSS |
| `frontend/app.js` | Estado da SPA, workflows, polling e renderização segura |

### 6.4 Tecnologias utilizadas

| Camada | Tecnologia | Uso no Growth Engine |
|---|---|---|
| Linguagem principal | Python | Backend, regras de domínio, workers, integração com providers e automações |
| Backend HTTP | `http.server.ThreadingHTTPServer` | Servidor web local e atendimento concorrente das rotas da Central |
| Frontend | HTML5, CSS3 e JavaScript | SPA operacional, navegação, cards, modais, polling e revisão de conteúdo |
| Persistência | SQLite | Dados de perfis, vídeos, análises, cortes, jobs, notificações e tokens cifrados |
| Concorrência SQLite | WAL e foreign keys | Durabilidade, leitura concorrente e integridade referencial |
| Cliente HTTP | `requests` | YouTube, Ollama, endpoints internos e providers HTTP |
| Segurança criptográfica | `cryptography` / Fernet | Proteção de tokens OAuth e segredos persistidos |
| Download de mídia | `yt-dlp` | Download de vídeo e áudio do YouTube, com retries e suporte a cookies |
| Runtime auxiliar | Node.js | Bypass de desafios JavaScript usados por alguns fluxos do `yt-dlp` |
| IA generativa local | Ollama | Servir os modelos locais sem enviar transcrições a um provedor externo |
| Modelo editorial | Qwen `qwen2.5:14b` | Autópsia, perfil semântico, oportunidades, dossiê, títulos, descrições e cortes |
| Transcrição CPU/CUDA | `faster-whisper` / CTranslate2 | Transcrição segmentada, cache e retomada por janelas |
| Transcrição AMD | DirectCompute, `constme.exe` e Whisper | Aceleração local da transcrição em GPU AMD |
| Visão computacional | `opencv-python` | Detecção facial e análise visual auxiliar dos cortes |
| Processamento audiovisual | FFmpeg e FFprobe | Duração, cenas, áudio, crop, blur, composição, codecs e validação de MP4 |
| Encoder acelerado | AMD AMF `h264_amf` | Renderização H.264 por hardware quando disponível |
| Encoder de fallback | `libx264` | Renderização CPU quando AMF ou dispositivo AMD falha |
| Automação web | Playwright | Fluxos do YouTube Studio e associação de vídeos relacionados |
| Feeds externos | RSS e providers HTTP | Radar local, notícias, tendências e fontes de nicho |
| Interface nativa | CustomTkinter | Painel de Controle residente para serviços, jobs e manutenção |
| Utilitários do painel | psutil, pystray e Pillow | Monitoramento de processos, bandeja do Windows e recursos visuais |
| Empacotamento | PyInstaller | Distribuição do Painel de Controle como executável Windows |
| Testes | `unittest`, mocks e contratos de frontend | Verificação de domínio, IA, mídia, persistência, OAuth e XSS |

### 6.5 Ambiente de execução

- **Sistema operacional principal:** Windows.
- **Backend:** interpretador Python do ambiente virtual `.venv` do projeto.
- **Aceleração de IA:** GPU AMD Radeon compatível com o caminho DirectCompute configurado; `faster-whisper` permanece como alternativa CPU/CUDA conforme o hardware disponível.
- **Mídia:** FFmpeg e FFprobe instalados e acessíveis pelo processo do Growth Engine.
- **IA local:** servidor Ollama em `127.0.0.1:11434`, com o modelo Qwen configurado.
- **Navegador automatizado:** perfil Chrome persistente fora do workspace para os fluxos Playwright.
- **Armazenamento:** SQLite, caches de modelos, transcrições e artefatos de mídia em diretórios configurados por perfil.

As versões de Python, Node.js, FFmpeg, modelos, drivers AMD e dependências Python devem ser fixadas em um manifesto de implantação antes de uma distribuição corporativa. O código atual identifica as dependências por configuração e disponibilidade local, mas ainda não fornece uma matriz formal de compatibilidade versionada.

## 7. Modelo de dados e isolamento

O sistema persiste, entre outros, os seguintes domínios:

- perfis e canais;
- vídeos históricos;
- transcrições e análises;
- classificações semânticas;
- oportunidades;
- dossiês editoriais;
- cortes e artefatos;
- jobs e checkpoints;
- notificações;
- tokens OAuth e preferências.

O isolamento atual é aplicado por `perfil_id`, header `X-Profile-Id`, OAuth associado ao perfil e diretórios de mídia separados.

### Limitação corporativa atual

O isolamento ainda é predominantemente lógico. Algumas constraints históricas usam `video_id` global, há tabelas singleton e permanecem diretórios legados globais. Para operação multi-tenant real, é necessário:

- adotar identidade composta por tenant/perfil e vídeo;
- revisar `PRIMARY KEY`, `UNIQUE` e `ON CONFLICT`;
- migrar tabelas singleton para escopo de tenant;
- validar todas as consultas contra acesso cruzado;
- testar concorrência entre perfis;
- padronizar os diretórios de artefatos.

## 8. Integrações e dependências

| Integração | Uso | Dependência operacional |
|---|---|---|
| YouTube Data API | vídeos, métricas, canais e publicação | OAuth, quotas e credenciais válidas |
| YouTube Analytics | dados analíticos | autorização e disponibilidade da API |
| YouTube Studio/Playwright | vídeo relacionado e fluxos não cobertos pela API | sessão Chrome e seletores sujeitos a mudanças |
| yt-dlp | download de mídia/áudio | cookies, rede e mudanças do YouTube |
| Ollama/Qwen | análise, editorial, títulos e descrições | modelo local, VRAM/RAM e tempo de inferência |
| DirectCompute/faster-whisper | transcrição | GPU/CPU, modelos e runtime |
| FFmpeg/FFprobe | duração, análise e renderização | instalação, codecs e encoders |
| RSS/providers | Radar externo | disponibilidade e formato das fontes |
| SQLite | persistência local | backup, migração e política de concorrência |

## 9. Segurança e governança

### Controles existentes

- Tokens OAuth cifrados com Fernet.
- Preservação de refresh token quando o provedor não retorna novo valor.
- CSP e allowlist de Origin.
- Validação de URLs e bloqueio de protocolos inseguros.
- Escopo de perfil em rotas privadas.
- Verificação administrativa para operações de manutenção.
- Renderização DOM-safe e testes contra XSS.
- Separação física de parte dos artefatos por perfil.

### Requisitos para apresentação como produto corporativo

- RBAC com papéis, permissões e escopo por organização/tenant.
- Auditoria de login, alteração, exclusão, publicação e manutenção.
- Gestão formal de segredos e rotação de credenciais.
- Política de retenção, exportação e exclusão de dados.
- Logs estruturados sem tokens, cookies ou dados pessoais indevidos.
- Backup, restauração e teste periódico do SQLite.
- Autenticação forte caso o servidor seja exposto além da máquina local.

## 10. Operação, confiabilidade e observabilidade

### Capacidades disponíveis

- Jobs persistentes e estados terminais.
- Checkpoints incrementais.
- Cancelamento cooperativo.
- Recuperação de tarefas interrompidas.
- Retry limitado para falhas recuperáveis.
- Notificações persistentes.
- Medição de duração de jobs.
- Fallback de encoder e validação de arquivo.

### Lacunas prioritárias

- Métricas consolidadas de fila, latência, throughput e sucesso por provider.
- Health checks de Ollama, Whisper, FFmpeg e YouTube.
- Locks distribuídos ou transacionais entre processos.
- Limites formais de CPU, GPU, memória e armazenamento.
- Idempotência completa para publicação e agendamento.
- Timezone configurável por perfil.
- Redução da dependência de `sleep` e input interativo do scheduler legado.

## 11. Maturidade atual

### Disponível no núcleo

A plataforma já suporta o ciclo principal de análise, transcrição, inteligência editorial, seleção de cortes, renderização, revisão e preparação para publicação. Há uma base relevante de testes de contratos, segurança, persistência, IA, mídia e frontend.

### Em consolidação

- Retomada completa de transcrição DirectCompute.
- Modularização do servidor e do frontend.
- Validação operacional real de cache miss/hit.
- Publicação real após reautorização e testes controlados.
- Hardening de concorrência, observabilidade e validação de FFmpeg.
- Enquadramento facial confiável e legendas estilizadas por corte.

### Planejado

- Multi-tenant estrutural.
- RBAC e auditoria corporativa.
- Escala com workers independentes e banco server-side.
- Relatórios executivos e aprendizado editorial contínuo.
- Distribuição omnichannel.
- Governança de custo, retenção e operação em cloud.

## 12. Riscos e mitigação

| Risco | Impacto | Mitigação recomendada |
|---|---|---|
| Colisão entre perfis/tenants | exposição ou sobrescrita de dados | migração para chaves compostas e testes cross-tenant |
| Falha ou lentidão da IA local | fila parada e resultado inconsistente | watchdog, timeout, retry limitado, health check e fallback explícito |
| Mudança no YouTube Studio | quebra do vínculo automatizado | contratos de seletores, testes periódicos e caminho manual assistido |
| Publicação duplicada | impacto operacional e reputacional | idempotência por corte, destino e estado confirmado |
| Falha de GPU/codec | renderização incompleta | fallback CPU, validação de MP4 e artefatos de diagnóstico |
| Crescimento de mídia/cache | indisponibilidade de disco | quotas, retenção, limpeza auditada e métricas de armazenamento |
| SQLite sob concorrência | contenção e risco de operação | locks transacionais, backup e avaliação de PostgreSQL |
| Qualidade editorial variável | decisões inadequadas | evidência textual, revisão humana, testes de avaliação e feedback |

## 13. Roadmap recomendado

### Fase 1: Controle e integridade

Multi-tenant estrutural, migrações, RBAC, auditoria, backup e testes de isolamento.

### Fase 2: Publicação confiável

Reautorização, teste controlado de publicação, idempotência, timezone por perfil e retomada de publicação.

### Fase 3: Operação observável

Health checks, métricas, logs estruturados, limites de recursos, alertas e painéis de operação.

### Fase 4: Produção audiovisual avançada

Enquadramento facial por confiança temporal, legendas ASS por estilo, pré-visualização e retry por corte.

### Fase 5: Escala de plataforma

Modularização dos handlers, workers independentes, banco server-side, organizações, permissões e execução cloud opcional.

### Fase 6: Inteligência contínua

DNA editorial, experimentos de título/formato/horário, retenção, conversão, relatórios e distribuição omnichannel.

## 14. Critérios de aceite corporativo

O produto estará pronto para uma implantação corporativa quando:

- nenhum tenant conseguir consultar ou sobrescrever dados de outro;
- ações sensíveis tiverem autorização e trilha de auditoria;
- publicação e agendamento forem idempotentes e retomáveis;
- providers críticos possuírem health check, timeout e métricas;
- backup e restauração forem testados;
- a transcrição, renderização e publicação forem validadas com mídia real;
- a qualidade editorial possuir conjunto de avaliação e revisão amostral;
- custos de IA, armazenamento e processamento forem mensuráveis;
- o roadmap de captions e enquadramento tiver sido validado visualmente;
- documentação operacional permitir recuperação sem conhecimento tácito do desenvolvedor.

## 15. Mensagem para apresentação executiva

> O Growth Engine transforma o acervo de um canal em decisões editoriais rastreáveis e conteúdo pronto para distribuição. Seu diferencial é unir evidência própria, inteligência artificial local, automação audiovisual e controle operacional em uma única esteira. O núcleo já funciona; a agenda corporativa agora é elevar isolamento, governança, observabilidade e escala ao mesmo nível da inteligência editorial.

## Referências internas

- [BACKLOG.md](../BACKLOG.md)
- [Arquitetura modular](arquitetura_modular.md)
- [Documentação de IA](../documentacao_ia.md)
- [Histórico de implementações](../historico_implementacoes.md)
- [Índice do backlog](backlog/index.json)
- [F4 - Dossiê editorial](backlog/features/F4-dossie-editorial.md)
