# Contexto do Projeto: Growth Engine ( Multi-perfil)

> A arquitetura modular, as regras de dependência e o plano de migração estão em [docs/arquitetura_modular.md](docs/arquitetura_modular.md).

## 🎯 Objetivo Principal
Automatizar a extração, transcrição e análise de vídeos do YouTube para realizar uma "Autópsia Forense" de conteúdo. O objetivo é descobrir padrões de retenção e cliques (Estratégia de Growth) usando IA local, além de alimentar uma pipeline de cortes para Shorts e agendamento automático.

## 🛠️ Stack Tecnológico
- **Linguagem:** Python 3
- **Banco de Dados:** SQLite (`videos_historico`) atuando como cache perpétuo.
- **Download:** `yt-dlp` (com bypass de JS usando Node.js instalado).
- **Transcrição:** DirectCompute (`constme.exe`/`Whisper.dll`) usa a AMD Radeon RX 9060 XT para uploads locais; `faster-whisper` permanece disponível como caminho CPU/CUDA configurável.
- **IA Local:** Ollama rodando a família `qwen2.5` (14b para análise, coder para programação).
- **Extensões/Edição:** Integração prevista com DaVinci Resolve e Premiere (descartando Warp Stabilizer problemático em favor de render manual).

## 🏗️ Arquitetura e Módulos Atuais
- `growth_engine.py`: Painel de controle dinâmico (CLI) que extrai o arroba do canal selecionado.
- `core/profiles.py`: Gerenciamento de múltiplos clientes/perfis via JSON.
- `core/sync_channel.py`: Sincroniza metadados (views, likes, IDs) do YouTube para o SQLite.
- `core/transcriber.py`: Fila de transcrição "Sniper". Ignora o lixo e foca no Top 15 (Pareto) usando `ORDER BY CAST(views AS INTEGER) DESC` para corrigir ordenação do banco.
- `core/autopsia.py`: Seleciona os 15 vídeos longos e os 15 Shorts mais vistos, analisa cada item individualmente e consolida padrões usando título, descrição, data, views, likes e transcrição com prompts forenses da Qwen.

## 🚧 Fase Atual e Desafios
1. A base já está sincronizando corretamente e o cache do Whisper evita refazer vídeos que já foram transcritos.
2. Resolvemos o bug de ordenação de views (Strings vs Integers) usando CAST no SQL.
4. A análise de conteúdo exige metadados completos e separa os melhores 15 vídeos longos dos melhores 15 Shorts; conclusões sem retenção por segundo devem ser tratadas como hipóteses.
5. **Próximo gargalo técnico:** Iniciar a pipeline de cortes dinâmicos (Longos para Shorts) cruzando os dados da autópsia empírica com as ferramentas de edição, e em seguida estruturar o módulo de agendamento (Playwright).

## Estado Atual da Plataforma

- A sincronização usa cache incremental: vídeos já completos não são reprocessados sem necessidade.
- A classificação persiste a duração real: até 180 segundos é tratado como Short; acima disso como vídeo longo. Registros sem evidência ficam como `indefinido`.
- A fila `analises_conteudo` separa metadados sincronizados de conteúdo efetivamente analisado. Transcrições e análises concluídas são reutilizadas.
- O perfil Google conectado fornece nome/e-mail quando autorizado e a imagem do canal é usada como avatar. Uma nova autorização pode ser necessária para preencher o e-mail e a imagem de perfis antigos.
- A interface possui tema claro/escuro, atualização de sincronização e progresso com ETA.
- A análise de conteúdo agora processa todos os vídeos longos pendentes quando iniciada; o limite opcional ficou reservado para testes.
- O perfil Chrome foi movido para `%LOCALAPPDATA%\GrowthEngine\ChromeProfile`; nenhum perfil de navegador deve permanecer no workspace.
- O perfil semântico foi reconstruído com 10 classificações válidas persistidas entre 15 vídeos base; itens sem classificação devem ser tratados como pendência, não como evidência.

## Próximas Entregas de Inteligência

1. Processar os vídeos longos pendentes com Whisper e Qwen, salvando observações, trechos literais, hipóteses e dados ausentes.
2. Consolidar padrões reais em ideias de vídeos, títulos, ângulos e cortes priorizados.
3. Adicionar localização configurável por bairro/cidade, sem inferir endereço automaticamente.
4. Criar radar de eventos, notícias e oportunidades locais usando fontes públicas e links verificáveis.
5. Exibir fonte, data, distância aproximada e motivo de relevância em cada oportunidade externa.

## API do Radar

- `GET /api/radar/location`: retorna bairro, cidade e estado configurados.
- `POST /api/radar/location`: salva `{ "bairro": "...", "cidade": "...", "estado": "..." }`.
- `GET /api/radar`: consulta Google News RSS por eventos, notícias e temas do canal.
- Cada resultado inclui título, fonte, data, link, categoria e motivo da relevância.
- Sem localização configurada, o radar não tenta inferir a posição do usuário.
- Os resultados são oportunidades para investigação; a fonte original deve ser verificada antes de gravar ou publicar.
- Cada resultado inclui `mapa_url`, uma busca contextual no Google Maps. Endereço e coordenadas só devem ser tratados como confirmados quando vierem da fonte original ou de geocodificação validada.
- O Radar separa `oportunidades_locais` de `oportunidades_nicho`: o primeiro exige localização; o segundo monitora notícias dos temas do canal sem depender de bairro ou cidade.
- Os temas do Radar de nicho combinam títulos de todo o canal com resultados concluídos em `analises_conteudo`; quanto mais a Autópsia avança, mais representativa fica a busca temática.
- A fonte principal dos temas passará a ser `perfis_conteudo`, um perfil semântico consolidado pela Qwen a partir das transcrições e análises. Palavras isoladas ficam apenas como fallback quando ainda não há perfil consolidado.
- O agrupamento é específico por conta: não existe taxonomia fixa. Os temas vêm de `temas_nucleares`, `pilares_editoriais` e análises concluídas do perfil semântico, priorizadas por views e likes.
- Respostas da Qwen sem essas categorias obrigatórias são rejeitadas e marcadas como falha; o Radar não usa palavras literais como substituto silencioso.
- Cada tema do nicho gera buscas de notícias e de eventos/novidades para aumentar a diversidade de fontes.
- Cada resultado passa por triagem editorial da Qwen contra temas, formatos e pilares da conta.
- A triagem descarta inscrições, resultados administrativos, editais, comunicados institucionais, listas genéricas e notícias sem ângulo gravável.
- O Radar descarta resultados com mais de 7 dias e limita a 3 notícias aprovadas por tema.
- O coletor RSS combina Google News, Bing News, Yahoo News e Reddit; o Radar de nicho também tenta tópicos do Flipboard e o feed oficial do TecMundo; no Radar local consulta os feeds primários do G1 e UOL.
- Cada fonte contribui no máximo com dois itens por consulta antes da deduplicação, evitando que um único agregador ocupe toda a tela.
- Cada notícia aprovada recebe `relevancia_score`, justificativa, fonte, data, link e `mapa_url`.
- A página Radar exibe local e nicho em seções expansíveis; a página Oportunidades usa o Radar quando ainda não há pautas salvas.
- `GET /api/content-profile` retorna o perfil semântico salvo; `POST /api/content-profile/rebuild` reconstrói o perfil com os vídeos e análises disponíveis.
- No primeiro acesso com uma conta Google conectada, a interface solicita bairro, cidade e estado. Esses dados podem ser alterados em Configurações.

## Backlog de Funcionalidades de Inteligência

Prioridade definida enquanto a Autópsia processa os primeiros vídeos longos:

1. **Score de oportunidade**
	- Avaliar cada pauta por relevância para o canal, atualidade, potencial local, facilidade de gravação, potencial de virar Short e força da evidência.
	- Mostrar os critérios e a justificativa do score, evitando uma nota opaca da IA.

2. **Gerador de briefing**
	- Transformar uma oportunidade em pauta gravável.
	- Gerar título provisório, promessa, abertura, estrutura, perguntas, tomadas necessárias, local e versões para vídeo longo e Short.

3. **DNA do canal**
	- Consolidar temas, formatos, durações, taxa de likes e padrões de títulos.
	- Comparar temas de alto alcance com temas de alto engajamento.

4. **Painel de hipóteses**
	- Separar fato observado, hipótese, recomendação e dado necessário para confirmação.
	- Nunca apresentar correlação como causalidade.

5. **Laboratório de testes**
	- Registrar variações de título, gancho, formato e data.
	- Comparar views, likes, retenção e compartilhamentos quando esses dados estiverem disponíveis.

6. **Mapa de pautas**
	- Organizar oportunidades por localização, tema, data, distância aproximada, urgência e potencial de gravação.

7. **Detector de vídeos esquecidos**
	- Encontrar vídeos com alto engajamento e pouco alcance.
	- Encontrar vídeos com muitas views e baixa interação.
	- Sugerir remake, continuação ou nova embalagem.

8. **Memória de decisões**
	- Registrar por que uma ideia foi aprovada, rejeitada, adiada ou transformada em outro formato.

### Ordem de implementação

Após a primeira rodada da Autópsia:

1. Consolidar as análises em padrões reais.
2. Implementar o Score de oportunidade.
3. Implementar o Gerador de briefing.
4. Integrar briefing e oportunidades ao Radar local.
5. Criar o Laboratório de testes.
6. Criar a Memória de decisões.

## API de Oportunidades e Briefings

- `GET /api/opportunities`: lista oportunidades salvas ordenadas por atualização.
- `POST /api/opportunities`: cria uma oportunidade e retorna score de 0 a 100 e briefing inicial.
- `GET /api/opportunities/{id}/briefing`: gera o briefing estruturado de uma oportunidade.
- O score usa critérios de 0 a 10: atualidade, relevância para o canal, potencial local, facilidade de gravação, potencial de Short e evidência.
- Os pesos ficam centralizados em `core/opportunities.py` e podem ser recalibrados depois com dados reais de desempenho.
- O briefing atual é determinístico e baseado somente nos campos fornecidos; Qwen poderá enriquecer a linguagem depois, sem substituir fontes ou evidências.
- Regra de produto: a página Oportunidades não usa o Radar. Ela é alimentada exclusivamente pela Autópsia dos Top 15, transcrições, observações, hipóteses, views e likes do canal.
- O Radar local/nicho é um módulo separado para descoberta externa; seus resultados não entram automaticamente como sugestões editoriais.
- O botão de Oportunidades deve gerar pautas com base no conteúdo que funcionou no canal e salvar score, contexto e briefing.

## Pipeline de cortes e publicação

O fluxo operacional da Central é:

1. Selecionar um vídeo longo por perfil e iniciar a sugestão de cortes.
2. Transcrever localmente, usando o cache persistente quando o arquivo e o backend forem compatíveis.
3. Enviar à Qwen o título original, a transcrição e o contexto editorial. A IA só pode corrigir nomes, entidades ou ortografia quando a própria transcrição fornece evidência.
4. Validar limites em fronteiras semânticas. O sistema rejeita cortes no meio de palavra, frase ou contexto e pode ampliar segmentos Whisper até o encerramento natural.
5. Persistir candidatos por perfil, vídeo, job e ciclo. Candidatos abaixo do score recomendado continuam disponíveis para avaliação humana.
6. Renderizar a prévia em MP4 vertical 9:16. Montagens não contínuas seguem a ordem gancho, contexto e retorno ao destaque; cortes contínuos usam o intervalo original.
7. Revisar no modal da Central, com player, título, score, evidências e ações adequadas ao estado. `Renderizar` só aparece antes de existir MP4; depois o card oferece `Baixar MP4`, `Agendar postagem` e `Excluir`. A seleção para publicação é explícita e usa um ícone que muda para check quando selecionado.
8. Agendar individualmente, por ciclo ou em lote. Sem data e hora informadas, o sistema calcula slots futuros usando recomendação semântica da Qwen, histórico do canal e horários de pico, sem repetir o mesmo instante. A cadência ocupa os três melhores horários configurados do mesmo dia antes de avançar para o dia seguinte, permitindo pelo menos três Shorts por dia quando houver cortes suficientes.
9. Publicar pelo YouTube Data API com título, descrição, tags, privacidade privada e `publishAt`. O MP4 precisa existir e o perfil Google precisa ter o escopo `youtube.upload`. Quando o corte veio de um vídeo público do YouTube, a descrição inclui `Vídeo original: https://www.youtube.com/watch?v=...`; uploads locais não recebem URL inventada.

### Contratos HTTP principais

- `POST /api/cuts/suggest`: cria job de geração para um `video_id`.
- `GET /api/jobs/{job_id}`: consulta progresso, rodada, diagnóstico e estado terminal.
- `POST /api/jobs/{job_id}/cancel`: solicita cancelamento cooperativo.
- `POST /api/cuts/select`: seleciona cortes por IDs, sempre no perfil atual.
- `POST /api/cuts/render-selected`: renderiza os cortes selecionados em 9:16; depois de renderizados, a Central não repete a ação `Renderizar` no card.
- `POST /api/cuts/schedule`: agenda cortes selecionados, por ciclo ou individualmente.
- `GET /api/cuts/file/{cut_id}`: entrega MP4 com suporte a `Range` para reprodução e avanço.

### Cancelamento e locks

Transcrição e geração de cortes do mesmo vídeo compartilham a chave `video:<perfil_id>:<video_id>` no `TaskRunner`, que possui um worker pesado por vez. Ao cancelar, a API marca o job como `cancelling` e sinaliza o evento; o worker encerra de forma cooperativa e só então persiste `cancelled` e libera a chave. Enquanto o lock existir, uma nova geração é recusada, evitando duas operações pesadas no mesmo vídeo ou a reutilização prematura do lock.

`iniciar_servidor.py` verifica jobs `queued`/`running` no SQLite antes de abrir a Central. Em terminal não interativo, ele não reinicia automaticamente para não interromper tarefas; em terminal interativo, a confirmação literal `CONTINUAR` é exigida.

### Publicação do YouTube

O OAuth de leitura não é suficiente para publicar. É necessário desconectar/reautorizar o perfil com `https://www.googleapis.com/auth/youtube.upload`. Sem esse escopo, a Central retorna uma mensagem de reautorização em vez de tentar um upload parcial.

### Execução e validação local

```powershell
python iniciar_servidor.py
python -m py_compile core/web_server.py core/task_runner.py
node --check frontend/app.js
python -m unittest discover -s tests -p "test_*.py"
```

Se o servidor não iniciar e informar tarefas ativas, aguarde o cancelamento concluir. Para uma reinicialização deliberada em terminal interativo, confirme com `CONTINUAR`; nunca remova manualmente a chave do `TaskRunner` enquanto a thread antiga ainda estiver executando.

## Estado conhecido em 2026-09-20

- Curadoria visual, edição, exclusão, seleção em lote, renderização vertical e montagem composta estão implementadas.
- Cancelamento agora possui estado intermediário `cancelling` para evitar a corrida entre a resposta HTTP e a liberação do lock.
- A publicação real está implementada no código, mas depende de reautorização Google com `youtube.upload` no perfil conectado.
- O YouTube não oferece, pela API de upload, um campo universal para declarar um Short como filho de outro vídeo na lista de conteúdo. O vínculo confiável é o link do vídeo original na descrição; uma associação visual nativa pode depender de recursos do próprio YouTube e não é controlável pelo upload.
- Metadados inválidos como `N/A` são rejeitados antes do upload; descrições repetidas são deduplicadas e entidades só são corrigidas quando comprovadas no título original.
- A validação automatizada disponível no ambiente passou com 40 testes; a execução completa com Qwen, FFmpeg e upload externo ainda depende dos serviços locais e credenciais.