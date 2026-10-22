# Backlog do Growth Engine

Backlog funcional e técnico do Growth Engine, organizado para trabalho Ágil. A fonte de contexto é `documentacao_ia.md`, `historico_implementacoes.md`, `docs/arquitetura_modular.md` e o estado atual do código.

## Contexto do produto

- Objetivo: transformar vídeos do YouTube em evidência editorial, oportunidades de pauta, cortes para Shorts e publicações agendadas.
- Stack: Python, SQLite, YouTube Data API/OAuth, yt-dlp, faster-whisper, Ollama/Qwen, RSS e Playwright.
- Estado conhecido: cache com 312 vídeos, sendo 219 Shorts, 87 vídeos longos e 6 sem classificação; a Autópsia inicial dos Top 15 foi concluída.
- Regra de produto: Oportunidades usa apenas a Autópsia do canal; Radar é descoberta externa e não alimenta pautas automaticamente.
- Critério de prioridade: primeiro desbloquear inteligência editorial confiável, depois automatizar produção e publicação; segurança, persistência e observabilidade acompanham cada entrega.

## Entregas recentes

- [x] Especificação corporativa: consolidada a proposta de valor, capacidades, arquitetura, integrações, maturidade, riscos, critérios de aceite e roadmap do Growth Engine para apresentação executiva.
- [x] Stack tecnológica documentada: Python, SPA HTML/CSS/JavaScript, SQLite/WAL, Ollama/Qwen, Whisper/DirectCompute, FFmpeg, yt-dlp, Playwright, RSS e painel Windows foram relacionados às suas responsabilidades e dependências de implantação.
- [x] README de portfólio: o repositório privado apresenta objetivo, fluxo, arquitetura, stack, maturidade, segurança, execução local e links para a documentação corporativa.
- [x] Especificação corporativa em inglês: tradução técnica completa adicionada ao repositório e vinculada ao README para apresentação internacional.
- [x] README em inglês: versão equivalente da vitrine técnica adicionada com links cruzados para a documentação corporativa e o README em português.
- [x] Notificações: limpar lidas remove os itens em tempo real do painel, atualiza o contador e mantém a exclusão persistida.
- [x] Notificações: botão `Ler todas` marca todas as notificações não lidas do perfil ativo em uma única operação e atualiza o contador do painel.
- [x] Biblioteca: análise manual individual com fila, progresso, ETA e notificações de conclusão ou falha.
- [x] Autópsia selecionável: seleção explícita, análise individual e em lote limitado aos cards visíveis, progresso fracionado, ETA em tempo real e geração de ideias com `qwen2.5:14b`.
- [x] Robustez da geração de ideias: prompt compacto com evidências da Autópsia, timeout configurável por `OPPORTUNITY_AI_TIMEOUT` e status persistente de falha.
- [x] Publicação em lote: timeout do Playwright no vídeo relacionado não aborta mais o restante da fila de Shorts.
- [x] Vídeo relacionado: o seletor aceita somente vídeos já publicados, excluindo itens programados ou agendados.
- [x] Atualização do seletor de vídeo relacionado: o botão bloqueia ações concorrentes, aguarda o fim da sincronização e recarrega a lista sem reutilizar dados antigos.
- [x] Ordem dos vídeos relacionados: a lista prioriza data de publicação; instâncias duplicadas do servidor foram encerradas para evitar respostas inconsistentes.
- [x] Atualização por perfil dos vídeos relacionados: o botão envia o `X-Profile-Id` ativo também para iniciar e consultar a sincronização, e o status informa as quantidades reais encontradas por tipo.
- [x] Bootstrap após reinício: corrigido erro de sintaxe no polling de sincronização que impedia o `app.js` de executar e deixava a Central vazia em “Carregando perfil...”.
- [x] Retomada automática: jobs já encerrados não são reclassificados como retomáveis após reinício; a recuperação preserva `concluido_em` e a fila ignora registros stale.
- [x] Estado da Central de cortes durante polling: a atualização preserva scroll, grupos de vídeo, ciclos e descrições expandidos, evitando que menus fechem enquanto a tela acompanha um job.
- [x] Vídeo relacionado no perfil correto: o vídeo `PQ85Kc7Y6xk` foi confirmado como pertencente ao perfil 1 (Aquele Cara de Bigode); a associação indevida ao perfil Ipiranga foi desfeita.
- [x] Ordem dos relacionados por recência: vídeos sem data do YouTube usam atualização persistida como fallback; `PQ85Kc7Y6xk` recebeu a data oficial de 2026-10-16 e aparece primeiro.
- [x] Metadados editoriais: títulos sem evidência ou genéricos como "A gente" são rejeitados antes da publicação, recebem fallback baseado no conteúdo do corte e o enriquecimento orienta Open Loop/conflito ancorado no tema do vídeo pai.
- [x] Fallback editorial de títulos: fillers iniciais são removidos, o texto é limitado a até oito palavras com reticências quando necessário e recebe o prefixo "Momento:".
- [x] Integridade de agendamento: rotas individuais e em lote recusam cortes cujo MP4 não existe ou está vazio no disco.
- [x] Publicação sem vídeo relacionado: o menu oferece “Nenhum vídeo relacionado”, persiste `sem_relacao` sem `NULL` e diferencia falha de geração de falha de publicação; quando o YouTube aceita o upload antes de uma falha local, o ID externo aparece na notificação.
- [x] Auto-cura de cortes: a listagem valida arquivos concluídos e converte registros sem MP4 válido para `falhou`, preservando-os para exclusão ou reprocessamento.
- [x] Unificação da renderização CPU: `core/cutter.py` e `core/media_tools.py` usam `montar_comando_render()` com seek preciso (`-ss` pós-input), `-t` relativo, `-avoid_negative_ts make_zero`, `libx264/faster/CRF 20`, bicubic, `yuv420p` explícito e AAC 160k.
- [x] Seleção de encoder com segurança: `SHORTS_ENCODER=auto` prioriza `h264_amf` quando anunciado pelo FFmpeg e repete uma vez com `libx264` somente em falhas reconhecíveis de AMF/device; render real na Radeon e benchmark permanecem pendentes.
- [x] Mensagem de revisão humana: a Central de cortes conta somente MP4s concluídos como renderizados e informa explicitamente quando a IA falha sem produzir candidatos locais.
- [x] Modo Force Generate: removida a repescagem por offsets e o bypass final; a seleção usa apenas janelas naturais com sobreposição máxima de 40%, aceitando menos cortes quando o material se esgota.
- [x] Painel de Controle executável: `painel_controle.py` oferece dashboard de serviços/hardware, fila de jobs, cancelamento, kill switches e manutenção assíncrona com CustomTkinter.
- [x] Empacotamento do Painel de Controle: temas JSON do CustomTkinter são incluídos explicitamente no build PyInstaller para evitar falha de inicialização do executável.
- [x] Quantidade graciosa por ciclo: a cota de 9 não é obrigatória; após o filtro temporal e semântico, o ciclo conclui com 1, 2 ou mais cortes distintos quando esse for o material disponível.
- [x] Diversidade de conteúdo nos cortes: música pode gerar corte, mas a seleção exige ao menos um trecho com fala e limita cortes exclusivamente musicais a um terço do resultado.
- [x] Detecção de marcadores musicais descritivos: classificadores reconhecem variações como `[MÚSICA DE FUNDO]` e `[SOM DO MÚSICA TOCANDO]`, evitando que a duração musical infle a meta de cortes.
- [x] Meta editorial proporcional refinada: a janela de análise permanece em 180 segundos, mas a quantidade-alvo considera aproximadamente 60 segundos de conteúdo elegível por corte, permitindo vários cortes dentro de uma única faixa contínua de fala.
- [x] Transcrição adaptativa por cobertura: faster-whisper e DirectCompute reprocessam áudio longo quando a transcrição cobre menos de 75% da duração, escolhendo a passagem com maior cobertura; caches anteriores à política são invalidados por versão.
- [x] Contrato inicial de checkpoints: `tarefas_jobs` persiste etapa, item atual, total, tentativa e `checkpoint_json`; o worker de mídia local atualiza esses dados durante transcrição, editorial e renderização.
- [x] Contrato explícito de steps: transcrição, editorial e renderização persistem `step_name`, `step_index` e `step_total` no checkpoint; contadores emitidos por segmentos também alimentam `item_atual` e `total_itens` sem alterar o schema SQLite.
- [x] Watchdog de finalização AMD: quando o DirectCompute já alcançou o fim estimado/real do áudio, o fechamento do SRT tem timeout configurável (`WHISPER_DIRECTCOMPUTE_FINALIZATION_TIMEOUT`, padrão de 300s) e encerra o processo com erro explícito em vez de prender a fila por horas.
- [x] Recuperação AMD após reinício: o startup encerra `constme.exe` órfão antes de retomar jobs interrompidos, evitando que uma transcrição antiga mantenha a fila ou a GPU ocupada.
- [x] Saída SRT DirectCompute alinhada: removido `--no-timestamps` da chamada AMD e fixado o diretório temporário como `cwd`, garantindo que o SRT produzido seja o mesmo arquivo monitorado pelo worker.
- [x] Falso estado de finalização AMD corrigido: a estimativa de duração não dispara mais “Finalizando transcrição AMD e fechando SRT”; o watchdog só começa quando o timestamp real do SRT alcança o fim do áudio.
- [x] Paralelismo DirectCompute ajustável: a chamada AMD usa 8 threads por padrão (`WHISPER_DIRECTCOMPUTE_THREADS`) em vez do padrão interno de 4, e registra a configuração no checkpoint.
- [x] Editorial sem mídia original: vídeos com transcrição segmentada persistida podem gerar dossiê mesmo quando `arquivo_origem` está ausente, sem inventar caminho físico e com cache validado pela transcrição.
- [x] Steps editoriais proporcionais: janelas de até 180s calculam metas dinâmicas por duração, acumulam candidatos válidos de todos os steps e não limitam a colheita global a três cortes.
- [x] Preservação de cortes entre steps: timestamps absolutos são mantidos, timestamps relativos recebem o deslocamento da janela e ambos fazem snap aos limites Whisper; cada janela pede 1 a 2 cortes e a prova mockada de 600s confirma candidatos nos steps 2, 3 e 4 sem chamar o Ollama real.
- [x] Retomada editorial por janela: o dossiê parcial marca `running`, persiste steps concluídos e, após reinício, o mapper reprocessa somente steps ausentes ou falhos; o job operacional recebe o cursor a cada janela.
- [x] Contratos de curadoria sincronizados: testes não aceitam mais candidatos locais quando a resposta editorial está vazia ou o Ollama está desativado; o retry corretivo de schema permanece coberto.
- [x] Retomada por janela no faster-whisper: janelas concluídas são salvas em sidecar parcial com escrita atômica e puladas após reinício; overlap é deduplicado antes do cache final. O offset retomável do DirectCompute AMD permanece pendente.
- [x] Retomada automática de jobs internos: após reinicialização, tarefas interrompidas de upload local, transcrição, editorial e cortes retornam à fila com seus checkpoints; publicação externa permanece fora da retomada até possuir idempotência própria.
- [x] Estado de jobs após reinício: a API permite descartar retomadas `interrupted`, e a Central limpa jobs terminais da memória da SPA e do `localStorage`, evitando exibir Editorial na fila após o servidor liberar o job.
- [x] Renderização idempotente por corte: lotes selecionados pulam cortes concluídos com MP4 válido e reprocessam somente itens pendentes, interrompidos ou falhos.
- [x] Checkpoint incremental de jobs: atualizações posteriores fazem merge no `checkpoint_json`, preservando o payload editorial parcial e permitindo retomada após progresso de renderização.
- [x] Worker de cortes retomável: o fluxo principal carrega `editorial_partial`, persiste cada step editorial e evita recriar ou re-renderizar candidatos cujo intervalo já possui MP4 válido.
- [x] Retry editorial recuperável: o worker usa duas tentativas para respostas inválidas ou insuficientes, mantendo timeout do provedor como falha terminal observável.
- [x] Publicação idempotente por corte: publicação imediata e agendada consultam Shorts já registrados pelo MP4 de origem e não repetem upload após reinício ou retry.
- [x] Progresso de renderização por corte: jobs atualizam estágio, índice, total e mensagem durante cada execução FFmpeg, evitando que a interface permaneça exibindo a etapa de IA enquanto os vídeos são codificados.
- [x] ETA e tempo decorrido dinâmicos: a estimativa é recalculada com base no tempo médio dos cortes concluídos e o relógio total do job continua avançando durante o FFmpeg, em vez de permanecer congelado na etapa de IA.
- [x] Métrica histórica de duração de jobs: `tarefas_jobs.duracao_segundos` é preenchida no encerramento e migrada para jobs antigos, permitindo analisar médias por tipo, status e etapa.
- [x] Resumo editorial obrigatório: a descrição prévia só aceita resumo gerado pela IA ou revisão manual; texto transcrito nunca é usado como fallback.
- [x] Fallback editorial definitivo: quando a IA não retorna descrição válida, o MP4 é preservado e o sistema monta descrição com título, trecho de até 20 palavras da transcrição e hashtags `#shorts #podcast #cortes`.
- [x] Curadoria híbrida de cortes: respostas parciais do Ollama preservam todos os candidatos locais, distinguindo itens enriquecidos e brutos para revisão manual; o enriquecimento usa lotes de até cinco candidatos para reduzir sobrecarga de contexto.
- [x] Timeout elástico do Ollama: análise de cortes usa `120 + (duracao_em_segundos * 1.5)`, limitado entre 120 e 1200 segundos e configurável por ambiente; o caminho legado também usa o teto de 1200 segundos para não abortar inferências longas.
- [x] Cache de modelo Ollama entre lotes: o payload de geração mantém o modelo aquecido por `15m` com `keep_alive`, reduzindo recargas de VRAM durante a curadoria editorial.
- [x] Memoização do pipeline pesado: segmentos Whisper são reutilizados por cache JSON/SRT e detecções FFmpeg de cena/áudio são reutilizadas por cache sidecar validado por arquivo e parâmetros.
- [x] Resumo semântico resiliente ao cache hit: a duração é recuperada de `videos_historico` ou derivada dos segmentos, e o Ollama usa timeout elástico com modelo aquecido por `15m`.
- [x] Verdade visual do fallback: candidatos locais são reportados somente após a deduplicação global; quando todos colidem com cortes existentes, o job informa descarte por sobreposição e retorna zero candidatos.
- [x] Dossiê Editorial Fases 1/2 e 3: `editorial_mapper.py` persiste dossiês versionados com fingerprints, gera mapa de calor semântico por intervalo e, em cache hit, colhe momentos inéditos ranqueados por `score_viralidade` sem chamar o Ollama; o cache miss usa uma única chamada do Diretor de TV com transcrição completa, contexto multimodal, Contextualização Dupla para título/descrição e timeout de até 1200s; integração aplicada aos fluxos de vídeo baixado e upload local.
- [x] Dossiê Editorial em steps: o cache miss divide a transcrição em blocos de até 10 minutos com overlap de 20 segundos, mantém resumo global e contexto multimodal local, salva cada lote bem-sucedido imediatamente no JSON e continua após falha isolada; fallback local remove `Momento:` dos títulos e usa descrição factual com timestamps.
- [x] Dossiê Editorial Fonte da Verdade: enriquecimento legado removido; após a geração, o JSON é somente leitura, flags operacionais são consultadas em `cortes_gerados` e o cache é invalidado por mídia ausente, transcrição vazia ou SHA-256 divergente.
- [x] Integridade do Dossiê Editorial: cache hit valida estrutura, fonte, transcrição e fingerprints; `melhores_momentos` pode ser vazio quando a IA não encontra a vaca roxa, enquanto fallback local permanece fora do JSON e atua somente na renderização/revisão.
- [x] Hotfix de aprovação editorial: o resultado bruto da IA é encaminhado diretamente com `inicio_segundos`/`fim_segundos` normalizados; a deduplicação contra cortes antigos não pode transformar candidato editorial aceito em `editorial_unavailable`; dossiês anteriores são invalidados por versão do algoritmo.
- [x] Recuperação de curadoria curta: intervalos IA menores que a duração mínima são expandidos ao redor do trecho e candidatos longos válidos, incluindo emoção, gritos de gol, ambiente e música de evento, não são rejeitados pelo teto de duração; a seleção ignora a classificação de ruído para candidatos IA.
- [x] Meta editorial por material: a quantidade mínima é limitada aos steps de 180s que realmente contêm material, em vez de usar a duração total vazia do vídeo.
- [x] Renderização não bloqueada por cota: qualquer conjunto não vazio de candidatos IA válidos conclui a curadoria e segue para renderização, mesmo abaixo da meta proporcional; o job real `PQ85Kc7Y6xk` tem regressão mockada sem Ollama ou FFmpeg reais.
- [x] Steps editoriais preservados: nenhuma janela com segmentos transcritos é descartada antes do Ollama por conter somente música, gritos, ambiente ou frases curtas; janelas vazias continuam sem step.
- [x] Distância entre candidatos do step: o prompt exige momentos diferentes com pelo menos 30 segundos entre cortes, e a expansão de candidatos curtos procura slots livres dentro da janela para evitar colisões artificiais.
- [x] Recuperação de fala sobreposta: saídas Whisper/DirectCompute dominadas por marcadores como `[MÚSICA DE FUNDO]` ou `[GRITOS DE GOL]` acionam uma segunda passagem com `faster-whisper large-v3`, evitando que ambiente substitua entrevistas e falas editoriais.
- [x] Entrevistas de lideranças preservadas: o prompt editorial v3 prioriza entrevistas com presidentes, vice-presidentes, representantes e convidados, mantendo a apresentação e a resposta substantiva como material de corte.
- [x] Títulos ancorados no trecho: antes de persistir o corte, o título é validado contra a transcrição do intervalo selecionado; títulos sem evidência local são substituídos por uma manchete derivada do próprio conteúdo.
- [x] Regeneração individual de metadados: o editor de cada corte oferece ações separadas para gerar novamente título ou descrição com a transcrição real do intervalo, preservando o outro campo e persistindo o resultado antes da publicação.
- [x] Correção de persistência editorial: candidatos retornados somente com `inicio_segundos`/`fim_segundos` agora entram em `melhores_momentos`, e o dossiê usa `resumo_conteudo` da IA em vez da transcrição bruta como resumo principal.
- [x] Editorial por blocos: vídeos longos são divididos em janelas de 180 segundos com sobreposição de 15 segundos para separar introdução, desenvolvimento e fechamento; a leitura exibe `descricao_publicacao` dos momentos.
- [x] Arquitetura editorial em duas fases: o dossiê é um índice global de capítulos e resumo consolidado; a geração de cortes consulta esse índice e só então cria título e descrição específicos para cada trecho.
- [x] Sincronia multimodal por step: cada prompt editorial recebe somente os gatilhos cujos timestamps pertencem à janela de 10 minutos; fallback local usa `needs_review_fallback` e não pode ser persistido como `completed`.
- [x] Otimização de geração: removido o loop legado de rodadas/retries; o Ollama faz uma única passagem pelos steps, cada step pede rigorosamente 1-3 momentos, e o job registra duração de download, transcrição, multimodal e inferência.
- [x] Cancelamento pela GUI: o job mantém seu `perfil_id` e a requisição de cancelamento usa esse perfil, mesmo após troca do perfil ativo.
- [x] Regra arquitetural do Dossiê: somente momentos editoriais retornados pela IA entram em `melhores_momentos`; fallback matemático nunca é injetado no mapa de inteligência.
- [x] Contexto global obrigatório: o dossiê materializa um resumo estruturado da transcrição mesmo quando `melhores_momentos` fica vazio.
- [x] Metadados editoriais no corte: `titulo_sugerido` e `descricao_sugerida` da IA são normalizados e persistidos no próprio `create_cut`, sem depender de uma segunda chamada individual para cada corte.
- [x] Controle do Dossiê Editorial na Central: cada vídeo informa se possui editorial e permite apagar somente o JSON do dossiê, preservando transcrição, mídia e cortes.
- [x] Estado do Dossiê na Central: o indicador de disponibilidade é somente leitura, fica no fim da faixa de ações e a exclusão permanece como ação separada imediatamente antes dele, com espaçamento consistente.
- [x] Leitura do Dossiê na Central: vídeos com editorial exibem `Ler editorial` em popup com resumo e momentos; vídeos sem editorial exibem `Gerar editorial` usando o job editorial existente.
- [x] JSON Repair do Ollama: respostas editoriais aceitam Markdown/texto ao redor, chaves sinonimas e persistem `parse_error_raw` quando a resposta é inválida ou vazia.
- [x] Prompt Vaca Roxa: o Diretor de TV recebe missão editorial explícita, retorna somente `resumo_conteudo` e `melhores_momentos` com 1 a 3 itens, timestamps em segundos, títulos completos e justificativa de retenção.
- [x] Blindagem semântica do prompt: restrição negativa impede devolver `transcrição`/`tempo`/`texto`, exemplo few-shot fixa o schema editorial e o material é delimitado por tags sem chaves JSON.
- [x] Engenharia de Prompt Ofensiva: prompts usam `DIÁLOGOS BRUTOS`/`MATERIAL BASE` sem a palavra-gatilho e a chamada HTTP força `format=json` no Ollama.
- [x] Contrato editorial Single Pass: qualquer retorno válido de 1 a 3 cortes é sucesso; removida a meta legada de 9 e as mensagens de rodada/aprovação associadas.
- [x] Parser editorial resiliente: remove blocos `<think>`, extrai o objeto JSON mesmo com Markdown e preserva evidência bruta em erros de parsing.
- [x] Parser editorial flexível: aceita a primeira lista de dicionários sob qualquer chave JSON e anexa o objeto bruto aos erros sem candidatos.
- [x] Recuperação do índice editorial: quando o Ollama devolve JSON estruturalmente válido, mas no formato de mapa de transcrição e sem `capitulos`, uma segunda chamada corretiva exige o schema global antes de declarar `empty_editorial_index`.
- [x] Schema nativo do índice editorial: a API do Ollama recebe `required`, `capitulos` e os tipos de timestamp diretamente no campo `format`; o mesmo contrato é encaminhado ao worker cancelável.
- [x] Exportação de transcrição: a Central de cortes oferece download da transcrição persistida em SRT UTF-8, com timestamps, nome de arquivo seguro e escopo pelo perfil ativo.
- [x] Capítulos como sumário global: o dossiê apresenta a linha do tempo inteira em capítulos informativos no formato assunto + detalhe; momentos, ganchos e cortes ficam restritos à etapa posterior de análise de trechos.
- [x] Contexto completo e granularidade do editorial: a geração do índice usa `num_ctx=32768` no Ollama, inclusive no retry e no worker cancelável, e exige quantidade de capítulos proporcional à duração, evitando truncar a transcrição ou comprimir vídeos longos em poucos capítulos.
- [x] Editorial estrutural em duas passagens: janelas da transcrição geram bolhas de assunto com limites reais; uma segunda leitura consolida apenas bolhas adjacentes em capítulos, normalizando início e fim para boundaries dos segmentos.
- [x] Continuidade e encerramento editorial: o pós-processamento elimina lacunas entre capítulos e separa uma faixa musical final longa em continuação do show e encerramento da gravação, sempre usando limites reais da transcrição.
- [x] Blindagem dos cortes contra placeholders: respostas que copiam `Gancho viral` ou `Porque é uma Vaca Roxa...` são rejeitadas antes da deduplicação; o prompt não contém mais exemplos de título/descrição e o buffer de candidatos permite até doze cortes.
- [x] Robustez de timestamps dos candidatos: valores `null` em `inicio_segundos`/`fim_segundos` usam aliases válidos quando disponíveis e intervalos inválidos são descartados antes do INSERT em `cortes_gerados`.
- [x] Validação aplicada aos dois ramos de renderização: candidatos de revisão/fallback e candidatos concluídos passam pela mesma proteção antes da persistência.
- [x] Duração de análise limitada ao arquivo físico: quando a transcrição ultrapassa o MP4/MKV, segmentos e timestamps são recortados na duração real antes da geração.
- [x] Política de qualidade dos cortes: o mínimo passa a ser proporcional à duração (510s exige 3 e o teto permanece 6), candidatos compostos somente por `[MÚSICA TOCANDO]` são rejeitados, e resultados abaixo da meta entram em `needs_review_fallback` com diagnósticos editoriais preservados.
- [x] Correção do corte único persistido: o job não substitui candidatos recém-gerados por um dossiê antigo com um único item; a deduplicação só remove sobreposição temporal e o fallback distribui janelas pelo vídeo longo, incluindo o encerramento.
- [x] Diagnóstico da Central sem contagem falsa: blocos que informam apenas `candidatos` aparecem como candidatos encontrados; a UI só exibe cortes aceitos quando o diagnóstico realmente fornece `aceitos`.
- [x] Contrato definitivo de curadoria: insuficiência, timeout, erro de resposta ou Ollama desativado encerram o job como `failed`, sem fallback de transcrição, sem títulos improvisados, sem descrições vazias e sem renderização para revisão.
- [x] Processamento sem upload de arquivos locais: a Central aceita o caminho completo de um arquivo MP4/MKV via `/api/uploads/local-path`, reutiliza o worker por perfil e não aplica o limite de 8 GB porque nenhum byte é transferido pelo navegador.
- [x] Falhas do processamento local sincronizadas no repositório persistente de jobs, evitando que uma exceção após o início deixe o job histórico preso em `running`.
- [x] Curadoria local aceita timestamps editoriais numéricos ou formatados (`MM:SS`/`HH:MM:SS`), exige tipos numéricos no schema Ollama e invalida dossiês persistidos abaixo do mínimo para permitir nova geração.
- [x] Candidatos editoriais são persistidos no dossiê, deduplicados após a validação dos intervalos absolutos e filtrados contra cortes existentes; dossiês sem capítulos e sem momentos não são reutilizados pelo cache.
- [x] A meta mínima de cortes usa a duração de conteúdo editorial elegível, não a duração física de blocos compostos apenas por música/ruído; blocos exclusivamente musicais não são enviados ao Ollama.
- [x] Cancelamentos e exceções do job principal de cortes atualizam também o repositório persistente, e a contagem exibida no frontend é capturada antes do reload das fontes.
- [x] Robustez dos steps editoriais: o Ollama recebe schema JSON para objetos de candidatos e uma correção única quando retorna strings em `melhores_momentos`; candidatos IA com timestamps válidos não são descartados apenas por falta de pontuação formal do Whisper.
- [x] Resultado persistido recuperado no frontend: jobs concluídos usam `resultado_json.cortes` quando `suggestions` não está disponível na memória do worker, evitando a contagem falsa de zero cortes.
- [x] Correção da Central de cortes: “Limpar cache da transcrição” usa endpoint não destrutivo, preserva vídeo/fonte/cortes e invalida somente transcrição, caches derivados e dossiê editorial.
- [x] Download de áudio YouTube: `yt-dlp` usa timeout/retries resilientes, runtime Node e cookies opcionais para reduzir falhas 403; a mensagem diferencia bloqueio que exige sessão.
- [ ] Dossiê Editorial Fases 4 a 8: validação operacional real de cache miss/hit fica pendente; o JSON será somente leitura na colheita, com `usado`/`renderizado`/`publicado` controlados exclusivamente por `cortes_gerados`; o lock deverá ser robusto entre processos.
- [x] Dossiê Editorial Fase 7: publicação usa `titulo` e `descricao_publicacao` persistidos sem regeneração de IA, aplica truncamento inteligente de título em até 100 caracteres e grava no SQLite exatamente os metadados enviados após upload bem-sucedido; a IA permanece apenas como fallback para metadados ausentes.
- [x] Diagnóstico visual do Studio: timeout na busca relacionada salva `youtube_studio_error.png` e `youtube_studio_error.html` na raiz e tenta `get_by_placeholder("Pesquise")` e `get_by_role("textbox")` antes de falhar.
- [x] Deduplicação rígida de cortes: o filtro temporal de 40% vale contra o banco e candidatos atuais, e títulos exatos ou muito similares são descartados antes da lista final.
- [x] Regeração após exclusão: cortes com status `excluido`, `falhou` ou `cancelado` não bloqueiam novas janelas; somente intervalos ativos participam da deduplicação entre ciclos.
- [x] Smart crop para planos abertos: detector facial amostra cinco posições do trecho, aceita faces menores e prioriza a maior detecção; sem rosto, o fallback vertical usa o quarto superior da sobra do crop.
- [ ] Enquadramento editorial por confiança facial: classificar cada trecho como uma face estável, múltiplas faces ou plano amplo; uma única face estável deve receber crop 9:16 acompanhando o rosto, enquanto múltiplas faces ou ausência de face usam composição horizontal com fundo desfocado.
- [x] Legendas automáticas por corte: cues relativos dos segmentos Whisper, timestamps por palavra com karaoke ASS e fallback para cues segmentados, galeria JSON por perfil com presets protegidos, fontes TTF/OTF/TTC isoladas por perfil via `fontsdir`, painel de opcionais recolhido por padrão com preview integrado, validação de allowlists, preview e render usando a mesma configuração, snapshot imutável por corte, job assíncrono, saída MP4 separada, acesso para download e persistência de status/erro; versionamento formal do renderer e invalidação por mudança de transcrição/estilo permanecem pendentes.
- [x] Cards de cortes em processamento: enquanto legenda, renderização, postagem/agendamento ou regeneração de título/descrição está ativa, o card afetado substitui preview e ações por etapa, barra de progresso, percentual e ETA; jobs em lote marcam somente os cortes envolvidos e o polling atualiza apenas esses cards. Jobs restaurados preservam timestamps/checkpoint para recalcular ETA, e legendas filtram explicitamente os segmentos dentro do intervalo do corte.
- [x] Preview pós-legenda: após a conclusão do job, o `<video>` do card usa a rota `captions=1`, alinhando a prévia ao arquivo legendado já usado pelo download.
- [x] Centralização horizontal independente: o editor de legendas oferece um comando que leva a legenda para X=50% sem alterar a posição vertical escolhida.
- [x] Leitura da transcrição no ajuste de legenda: o modal permite abrir os segmentos do próprio corte com timestamps relativos para conferir e corrigir palavras antes da geração.
- [x] Edição persistida da transcrição no corte: o leitor permite corrigir cada segmento e salvar antes da geração; a correção fica isolada no corte e preserva os timestamps originais.
- [x] Contraste do leitor de transcrição: campos editáveis usam o tema escuro do modal e estados sem segmentos explicam quando é necessário transcrever novamente ou enviar SRT.
- [x] Opção sem vídeo relacionado como item selecionável no topo do picker, com confirmação pelo mesmo fluxo dos vídeos e remoção suportada na Biblioteca.
- [x] Publicação de cortes legendados: quando a legenda está concluída, o upload usa obrigatoriamente o MP4 legendado e bloqueia se o arquivo não existir; o histórico registra o caminho enviado.
- [x] Agendamento inteligente a partir de data/hora: o usuário define o início e a IA escolhe os melhores horários posteriores individualmente para os cortes.
- [x] Relacionamento com vídeos agendados: vídeos em estado `programado` ou `agendado` aparecem no picker de relacionados, mantendo privados e excluídos fora da seleção.
- [x] Progresso de postagem dos cortes: a barra geral permanece visível para jobs individuais e em massa, e os IDs dos cortes são persistidos para restaurar o acompanhamento após recarregar.
- [x] Idempotência da publicação legendada: um upload anterior do original não bloqueia o reenvio quando existe uma versão legendada concluída diferente.
- [x] Deduplicação por ciclo: antes de publicar, o sistema procura Shorts com o mesmo título ou descrição e confirma no YouTube se o ID ainda existe; registros locais falsos não bloqueiam o envio.
- [x] Limpeza da fila no executável `GrowthEnginePainel`: botão de manutenção remove jobs concluídos, falhos, cancelados ou rejeitados e preserva jobs ativos.
- [x] Robustez do vídeo relacionado: o fluxo do Studio detecta a tela genérica “Ops! Algo deu errado”, tenta recarregar até três vezes e salva diagnóstico na falha definitiva.
- [x] Retry manual de vídeo relacionado: a Biblioteca mostra “Tentar relação novamente” quando a aplicação falha e reenvia a relação sem republicar o Short.
- [x] Menu de legendas minimalista: preview vem antes dos controles, ajustes essenciais ficam visíveis e fonte/contorno/cores ficam em “Ajustes avançados”.
- [x] Campos numéricos de legendas: tamanho em pixels e opacidade do fundo em porcentagem podem ser digitados e permanecem sincronizados com os sliders.
- [x] Atualização do asset da interface de legendas: versão do `app.js` incrementada para evitar que o navegador mantenha o menu antigo em cache.
- [x] Substituição de palavras por ciclo: a Central permite trocar uma palavra ou expressão simultaneamente em títulos e descrições de todos os cortes de um `job_id`, com escopo isolado e confirmação.
- [x] Áudio inesperado ao abrir corte corrigido: o preview ampliado não inicia mais automaticamente e vídeos anteriores são pausados antes de abrir outro corte.
- [x] Preview auxiliar de legendas silenciado: o vídeo usado como fundo visual inicia somente com `muted`, `defaultMuted` e volume zero, sem áudio ao abrir a Central.
- [x] Seleção e legendas em massa: o botão individual passou de `Postar` para `Selecionar`; ciclos exibem `Gerar legendas` somente com pelo menos dois cortes selecionados, reutilizando o modal de estilo e acompanhando cada job no card correspondente.
- [x] Validação da saída legendada: cada job usa um nome de arquivo único e falha explicitamente quando o MP4 produzido é idêntico ao corte sem legendas, evitando marcar saída stale como concluída.
- [x] ETA de legendas sem projeção falsa: como o renderizador ainda não publica progresso contínuo durante o FFmpeg, jobs `caption_render` exibem ETA calculando em vez de extrapolar os 10% iniciais para dezenas de minutos.
- [x] ETA estimado de legendas restaurado: jobs persistem uma estimativa baseada na duração do corte e a interface exibe contagem regressiva rotulada como `ETA estimado`, sem confundir a previsão com progresso real do FFmpeg.
- [x] Renderização de legendas otimizada: quando o MP4 do corte já existe, o ASS é aplicado diretamente sobre esse arquivo com timestamps relativos, evitando reabrir e decodificar o vídeo original inteiro; a estimativa cai de aproximadamente 5,3x para 1,5x a duração do corte.
- [x] Visualização do corte em tamanho real: o controle de expandir fica sobreposto ao preview de cada card renderizado e abre um popup com player vertical ampliado e controles próprios.
- [x] Escala de legendas corrigida: os scripts ASS passam a declarar referência `1080x1920`, evitando que o libass infira uma escala excessiva e gere legendas enormes.
- [x] Regeneração de legendas refletida no preview: a URL do vídeo usa a versão do novo arquivo e a rota MP4 desabilita cache, garantindo que escolhas alteradas carreguem o MP4 legendado recém-gerado.
- [x] Controle de tamanho real refinado: o botão textual foi substituído por um ícone de expandir sobreposto no canto inferior direito do player, junto ao menu nativo de três pontos.
- [x] Fullscreen nativo do preview: o ícone chama `requestFullscreen()` no próprio elemento de vídeo, com popup como fallback; o contêiner deixou de ser esticado pela coluna de ações.
- [x] Alinhamento do controle fullscreen: ícone fixado na faixa inferior do player, imediatamente à esquerda do menu nativo de três pontos.
- [x] Fullscreen vertical corrigido: o contêiner do preview entra em tela cheia e mantém o vídeo centralizado em `9:16`, com fundo preto nas laterais.
- [x] Cores de legendas configuráveis: os menus de opcionais e de geração de legendas permitem definir texto, destaque/karaokê, contorno, fundo e opacidade; as escolhas são persistidas no estilo e aplicadas ao ASS/MP4.
- [x] Validação de stroke corrigida: nomes legados e cores HEX são aceitos, e erros de posição, cor ou espessura são reportados separadamente.
- [x] Overflow horizontal de legendas corrigido: linhas comuns e karaoke respeitam largura segura proporcional ao tamanho da fonte, com margens ASS ampliadas e quebra automática antes de cortar nas bordas.
- [x] Preview interativo de legendas: menus de ajuste usam a imagem/vídeo real do corte, refletem tamanho e cores em tempo real e enviam as coordenadas X/Y exatas do arraste ao renderizador.
- [x] Tamanho contínuo e centralização no preview: slider de 32 a 96px com valor visível e comando para centralizar a legenda no frame.
- [x] Escala fiel da prévia: fonte, stroke e sombras são proporcionais à largura 1080 do render ASS, com frame responsivo 9:16 e atualização ao redimensionar.
- [x] Posição manual fiel no render: coordenadas arrastadas usam âncora ASS central (`\\an5`) junto de `\\pos`, igualando o ponto de referência do preview.
- [x] Legenda grande em uma linha: tamanho ampliado até 160px e opção “Uma linha” no preview e no render, inclusive para karaoke, sem quebra automática.
- [x] Uma linha sem corte: quando o texto excede a largura segura, preview e ASS reduzem automaticamente a fonte daquela legenda até caber inteira na tela.
- [x] Cores com visual e atalhos: campos de cor exibem a amostra atual e oferecem círculos rápidos para cores principais, sincronizados com HEX, preview e render.
- [x] Semântica de cores do karaoke esclarecida: “Cor base” é branca para palavras não ativas e “Cor destaque” é amarela para a palavra ativa, com mapeamento corrigido no ASS.
- [x] Prévia de uma linha corrigida: o ajuste usa a largura renderizada real do texto para evitar corte visual nas bordas.
- [x] Linha única pós-layout: o encaixe é recalculado depois que o modal assume suas dimensões reais e usa margem interna conservadora para evitar cortes.
- [x] Fallback profissional sem rosto: planos sem coordenadas faciais usam vídeo ajustado ao centro sobre fundo preenchido e desfocado via `filter_complex`, com saída `[outv]` mapeada para AMF/CPU.
- [x] Filtro de fallback otimizado: o vídeo é dividido uma vez, o fundo é desfocado em resolução reduzida e ampliado antes do overlay, reduzindo o custo de renderização sem mudar o enquadramento.
- [x] Painel residente na bandeja: minimizar ou fechar a janela oculta o GUI da barra de tarefas, com restauração e saída pelo ícone do Growth Engine.
- [x] Identidade do perfil padrão: o perfil legado `1` é exibido como `Aquele Cara de Bigode`, mantendo o Pod Ipiranga separado no perfil `915361`.
- [x] Publicação protegida contra restart: o painel não reinicia o servidor enquanto há job `cut_publish` ativo; o vínculo no Studio usa fallback de seletores para variações do campo de busca.
- [x] Busca relacionada resiliente: a automação também reconhece diálogos de seleção alternativos, diálogos ARIA, campo visível genérico e botão de pesquisa recolhido do YouTube Studio.
- [x] Isolamento do pipeline de transcrição: áudio temporário do YouTube usa diretório exclusivo por execução e o estado operacional do Whisper é thread-local para evitar colisões entre jobs.
- [x] Resiliência do download de transcrição: retries de extração e fragmentos com backoff para HTTP 403 transitório do YouTube.
- [x] Identidade YouTube no download forçado: o ID da URL é preservado em `tarefas_jobs`, `videos_historico` e no nome do cache SRT; o `job_id` permanece somente como identidade da tarefa.
- [x] Robustez do ciclo de download: a sincronização tenta `yt-dlp` quando o OAuth retorna `invalid_grant`, e o download forçado aceita saída MP4, MKV ou WebM antes da transcrição/renderização.
- [x] Exclusão controlada na Central de cortes: remove vídeo, transcrição, cortes, jobs terminados e caches/artefatos associados somente dentro do perfil selecionado.
- [x] Painel Admin inicial: perfil principal com `is_admin`, guard para manutenção, limpeza de temporários/caches órfãos, reset de jobs, VACUUM, reinício do servidor e controles confirmados na UI.
- [x] Torre de Controle: o GUI inicia o servidor web ao abrir, confirma a porta `4174` antes de reportar sucesso e oferece botões individuais para ligar/desligar/reiniciar o Servidor Web e ligar/desligar Ollama; no executável frozen, o launcher usa a `.venv` ou `python` do `PATH` em vez de relançar o próprio GUI.
- [x] Postagem imediata de cortes: o seletor de vídeo relacionado envia explicitamente o perfil ativo e deixa de falhar com `400` por ausência de `X-Profile-Id`.
- [x] OAuth YouTube: publicação e aplicação de vídeo relacionado agora solicitam `youtube`, `youtube.force-ssl` e `youtube.upload`, com ação de renovação de permissões no menu do perfil.
- [x] Central de cortes: corrigida a deduplicação visual que descartava cortes persistidos com intervalos temporais sobrepostos, fazendo 15 cortes aparecerem como apenas 1.
- [x] Torre de Controle: o executável usa instância única no Windows para impedir múltiplas janelas ao clicar no GUI repetidamente; o processo pai/filho do PyInstaller continua sendo tratado como bootstrap normal.
- [x] Integridade física dos cortes: o renderer rejeita saídas ausentes/vazias, a listagem converte concluídos sem MP4 válido para `falhou` e o agendamento recusa arquivos removidos do disco.
- [x] Renovação OAuth offline: autorizações solicitam `access_type=offline` e `prompt=consent`, refresh tokens são preservados quando o Google não retorna um novo valor e os clientes YouTube usam access token, refresh token e credenciais do cliente para renovação automática.
- [x] Acesso OAuth no painel nativo: o `GrowthEnginePainel.exe` oferece o botão `Renovar permissões YouTube`, abre o fluxo do perfil configurado e foi reconstruído após a inclusão do controle.
- [x] Relação Short-vídeo longo: o seletor exclui Shorts e a própria origem, rejeita autoassociação no endpoint da Biblioteca e sincroniza `aplicado`/`falhou` em `videos_historico` e `cortes_gerados`.
- [x] Robustez de encoding na geração: stdout/stderr do cutter são configurados como UTF-8 com substituição segura para que emojis dos logs não causem falha `charmap` no Windows.
- [x] Contexto multimodal para cortes: FFmpeg detecta mudanças de cena e picos de energia de áudio uma vez por job, associa tags semânticas aos segmentos e entrega o roteiro anotado à curadoria Ollama; indisponibilidade do FFmpeg recua para a transcrição existente.

## Épicos

### E1. Inteligência editorial baseada em evidência

- [ ] Consolidar o perfil semântico por conta com temas, pilares, formatos, ganchos, contextos, hipóteses e dados ausentes.
- [ ] Gerar Score de oportunidade de 0 a 100 com critérios visíveis: atualidade, relevância, potencial local, facilidade de gravação, potencial de Short e força da evidência.
- [ ] Gerar briefing gravável para cada oportunidade: promessa, título provisório, abertura, estrutura, perguntas, tomadas, local e versões longo/Short.
- [ ] Criar o DNA do canal, comparando temas de alto alcance com temas de alto engajamento, duração, likes e padrões de títulos.
- [ ] Criar painel que diferencie fato observado, hipótese, recomendação e dado ainda necessário.

### E2. Pipeline de produção e cortes

- [x] Pipeline de cortes dinâmicos: transcrição, trechos literais, gancho, clareza, autonomia, score, persistência, renderização FFmpeg unificada e curadoria visual estão integrados; a garantia editorial de nove cortes permanece em validação.
- [ ] Gerar cortes compatíveis com FFmpeg e preparar exportação para DaVinci Resolve/Premiere sem depender de edição manual para cada vídeo.
- [ ] Persistir origem, evidência, versão e estado de cada corte para permitir revisão, retry e auditoria.

### E3. Automação de agendamento e publicação

- [ ] Transformar o fluxo Playwright do YouTube Studio em uma tarefa persistente, retomável e observável.
- [ ] Validar slots, fuso horário, arquivo, metadados, privacidade e confirmação final antes de mover o Short para `arquivados/`.
- [ ] Implementar estratégia de publicação baseada em dados reais do canal, sem sobrescrever o histórico de agendamentos.
- [x] Agendamento comportamental: ranquear horários premium por nicho/contexto e avançar para o dia seguinte somente após esgotar os horários futuros disponíveis do nicho.

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

- [x] Remover o `innerHTML` residual do frontend: os arquivos em `frontend/` não possuem mais ocorrências; contratos XSS cobrem links e renderizadores críticos.
- [ ] Confirmar que nenhum perfil Chrome permanece no workspace e remover referências legadas a `perfil_chrome_youtube`; o caminho oficial é `%LOCALAPPDATA%\GrowthEngine\ChromeProfile`.
- [ ] Rever CSP, validação de Origin, URLs do YouTube e entradas de localização com testes de regressão de segurança.
- [ ] Auditar logs para garantir que tokens OAuth, Client Secret, cookies e dados pessoais nunca sejam gravados.

### Concorrência, recursos e robustez

- [ ] Substituir os `threading.Thread` diretos das rotas de transcrição e cortes pelo `TaskRunner`, com limite global, lock por vídeo e estado persistente.
- [ ] Definir limites de threads para Whisper, yt-dlp, RSS e tarefas HTTP, evitando saturação de CPU/RAM e tarefas duplicadas.
- [ ] Validar presença, versão e código de saída de FFmpeg/FFprobe antes de iniciar cortes ou transcrição.
- [x] Diagnóstico de transcrição: falhas de download, arquivo ausente, Whisper e transcrição vazia persistem a exceção real no job.
- [x] Garantir cancelamento, timeout, retry com limite e recuperação após reinício para todas as tarefas longas; a geração de cortes usa watchdog isolado para o Ollama e fallback local no primeiro timeout.
- [ ] Substituir `sleep` fixos e seletores frágeis do Playwright por esperas condicionais e testes contra mudanças de interface.
- [ ] Migrar o scheduler legado para o publisher persistente ou marcá-lo explicitamente como deprecated; corrigir a movimentação para `arquivados/` quando o Playwright falhar.

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
- [x] **Robustez da geração local de cortes:** transcrição + janelas locais + FFmpeg são o caminho principal; Ollama fica opt-in, com watchdog de 30s, contexto/saída limitados e cancelamento forçado. Referência: `docs/backlog/bugs/BUG-ollama-trava-geracao-cortes.md`.
- [ ] **Agendamento Playwright:** transformar a execução atual em tarefa controlada, com confirmação, retry, retomada e histórico persistente.
- [ ] **Fuso horário por perfil:** substituir o offset fixo `-03:00` por timezone configurável e persistido no perfil antes de publicar/agendar.
- [ ] **Score e briefing:** implementar os critérios documentados e expor a justificativa de cada decisão, sem nota opaca da IA.
- [ ] **Frontend seguro:** substituir os pontos restantes de `innerHTML` por criação segura de elementos ou restringir rigorosamente os dados interpolados com testes XSS.
- [ ] **Testes de integração:** cobrir endpoints de perfil, análise, Radar, oportunidades, localização e tarefas após o primeiro ciclo de contratos.

### In Progress

- [ ] **Autópsia analítica selecionável:** seleção, filtros, ações individuais e em lote, progresso/ETA e geração baseada nos Top 15 estão implementados; falta executar uma geração completa após reinício e registrar a duração real. Referência: `docs/backlog/features/F5-autopsia-analise-selecionavel.md`.
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
- [x] **Diversidade entre ciclos:** a Central mantém a deduplicação por título/sobreposição e o gerador, inclusive no fallback após timeout do Ollama, recebe os intervalos já usados para procurar trechos novos em cada ciclo.
- [x] **Isolamento stateless do Ollama:** cada lote editorial monta prompt e payload HTTP novos, envia `context: []` e não reaproveita histórico de respostas entre lotes ou jobs.
- [x] **Fallback local sem contaminação temática:** títulos locais usam somente as primeiras palavras significativas da evidência do trecho; regras hardcoded de doação, motel, caminhada e outros temas foram removidas.
- [x] **Integridade semântica dos cortes:** validação rejeita cortes no meio de frases e expande segmentos Whisper até uma fronteira de encerramento; testes de regressão cobrem ambos os casos.
- [x] **Montagem de retenção:** cortes podem repetir o destaque no começo e retornar ao contexto até o momento original, com fallback contínuo para cortes antigos ou sem marcação válida.
- [x] **Título contextual e publicação em massa:** a Qwen confere o título original contra a transcrição para corrigir ortografia e entidades com evidência; a Central oferece seleção total por ciclo, `Postar selecionados`, `Agendar selecionados` e `Agendar ciclo`.
- [x] **Metadados editáveis de publicação:** `Editar título` permite ajustar o título e a descrição enviada ao YouTube por corte; marcadores Markdown como `###` são removidos antes da persistência e o estado da Central é sincronizado.
- [x] **Fila de postagem imediata:** `Postar selecionados` envia os cortes renderizados um por vez, com job, progresso e histórico persistidos.
- [ ] **Decisão de produto sobre ciclos:** definir se `Ciclo 1` é apenas uma sessão técnica ou se terá significado editorial, filtros e automações próprios.

## Definição de pronto do sprint

- [ ] A tarefa tem critério de aceite verificável e fonte de dados identificada.
- [ ] O estado é persistido quando a execução ultrapassa uma requisição.
- [ ] Falhas de provider ou da Qwen aparecem no status e não viram evidência silenciosa.
- [ ] Existe pelo menos um teste de contrato ou comportamento para a mudança.
- [ ] `py_compile`, `node --check`, testes automatizados e endpoint afetado foram executados e registrados no histórico.
- [ ] Documentação, riscos e instruções de retomada foram atualizados.
