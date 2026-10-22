# F4 - Dossiê Editorial e Mapa de Calor Semântico

- [x] Steps de curadoria limitados a 180 segundos, com meta de 1 a 2 cortes por janela, acúmulo global proporcional e teste mockado cobrindo timestamps absolutos e relativos nos steps 2, 3 e 4.

## Objetivo

Separar a análise editorial da renderização dos cortes, preservando em um dossiê JSON os momentos candidatos, seus scores e os fingerprints das entradas usadas.

## Fases implementadas

- [x] Fase 1: escrita atômica do dossiê em `media/<perfil_id>/editorial_dossiers/<video_id>_dossier.json`.
- [x] Fase 1: schema versionado, fingerprints de mídia, transcrição, contexto multimodal e parâmetros.
- [x] Fase 2: cache hit com lock por perfil/vídeo, remoção de cortes usados ou sobrepostos e ordenação por `score_viralidade`.
- [x] Fase 2: integração inicial nos fluxos de vídeo baixado e upload local sem alterar o renderizador FFmpeg.
- [x] Fase 3 inicial: `mapa_calor_semantico` com intensidade proporcional por intervalo, ganchos, entidades e sinais multimodais explicáveis.
- [x] Cache miss: chamada única do Diretor de TV recebe a transcrição inteira e o contexto multimodal, retorna `melhores_momentos` com `score_viralidade` e usa timeout elástico de 45 a 300 segundos.
- [x] Cache miss: regra de Contextualização Dupla cruza cada momento com a narrativa geral antes de gerar `titulo_sugerido` e `descricao_sugerida`, evitando metadados genéricos ou clickbait desconectado.
- [x] Cache miss em steps: a transcrição é dividida em blocos de 180 segundos com sobreposição de 15 segundos; cada step recebe resumo global, transcrição e contexto multimodal locais, retorna de 1 a 2 momentos, normaliza timestamps relativos/absolutos e persiste o lote imediatamente por callback no dossiê.
- [x] Fallback editorial humanizado: títulos locais não usam o prefixo `Momento:` e descrições de emergência citam o intervalo temporal e o contexto disponível, sem templates dramáticos.
- [x] Fonte da verdade operacional: após a geração, a colheita não altera o JSON nem consulta flags `usado`; exclusão, renderização e publicação são determinadas pelos registros de `cortes_gerados`.
- [x] Invalidação defensiva: quando existe mídia, o cache é ignorado se a fonte não existe ou a assinatura SHA-256 mudou; sem mídia, a transcrição segmentada persistida é a fonte válida do editorial.
- [x] Integridade do cache: um dossiê é cache hit quando sua estrutura, fonte, transcrição e fingerprints são válidos; `melhores_momentos` pode ser uma lista vazia quando a IA não encontra momentos editoriais. Fallback local nunca entra no JSON.
- [x] Aprovação direta pós-falha do worker: candidatos editoriais brutos são aceitos após normalização dos timestamps, sem validação legada ou bloqueio por sobreposição com cortes anteriores; a versão do algoritmo invalida dossiês antigos.
- [x] Persistência dos momentos editoriais: o mapper tolera timestamps `inicio_segundos`/`fim_segundos` e prioriza o `resumo_conteudo` produzido pela IA, evitando exibir a transcrição bruta como resumo e perder momentos válidos.
- [x] Separação temporal do editorial: vídeos longos usam blocos de 180 segundos com overlap de 15 segundos, acumulando momentos distintos ao longo da linha do tempo e exibindo a descrição editorial persistida.
- [x] Índice editorial global: o dossiê consolida o vídeo inteiro em `resumo_global` e `capitulos` temporais, sem descrever cada corte; a etapa posterior de cortes consulta esse contexto para analisar o trecho, gerar título e descrição e comparar com o conteúdo geral.
- [x] Contexto multimodal por step: o prompt filtra gatilhos por `start_time`, `inicio`, `timestamp` ou intervalo `[MM:SS - MM:SS]` dentro da janela editorial atual; fallback local é persistido como `needs_review_fallback`, nunca como sucesso editorial.
- [x] Single pass e profiling: a descoberta editorial não possui mais rodadas legadas; cada step solicita rigorosamente 1-3 momentos independentes, e o servidor registra tempos de download, transcrição, análise multimodal e inferência Ollama.
- [x] Cancelamento por perfil: a GUI preserva o perfil associado ao job e envia o `X-Profile-Id` correto ao cancelar, evitando erro após a troca de perfil ativo.
- [x] Regra de ouro: o dossiê é o mapa de inteligência do vídeo, com resumo, timestamps e `melhores_momentos` exclusivamente da IA; fallback local atua somente na renderização/revisão.
- [x] Contexto global obrigatório: o resumo estruturado é derivado da transcrição e persiste mesmo quando a curadoria da IA não encontra momentos.
- [x] Persistência de metadados: o fluxo usa `titulo_sugerido` e `descricao_sugerida` editoriais antes do fallback de transcrição e grava ambos ao criar o corte.
- [x] Controle operacional do dossiê: a Central mostra se o vídeo possui editorial e oferece exclusão isolada do JSON para forçar nova geração sem remover transcrição, mídia ou cortes.
- [x] Status do dossiê somente leitura: o indicador visual não é botão; a faixa mantém espaçamento entre ações, posiciona a exclusão como penúltima e o status como último item.
- [x] Leitura e geração manual: `Ler editorial` abre popup com resumo e momentos do JSON; na ausência do dossiê, `Gerar editorial` inicia o job editorial existente.
- [x] JSON Repair e auditoria: o parser extrai o objeto JSON de respostas com Markdown/texto residual, normaliza `melhores_momentos`, `cortes`, `momentos`, `candidatos` e `suggestions`, e registra `parse_error_raw` no diagnóstico quando não há payload aproveitável.
- [x] Prompt Vaca Roxa: o template define a persona de Diretor de TV e especialista viral, exige `resumo_conteudo` e `melhores_momentos` com rigorosos 1-3 itens, usa `inicio_segundos`/`fim_segundos` e orienta títulos completos e `descricao_publicacao` justificando a singularidade do trecho.
- [x] Blindagem do prompt contra espelhamento: o template proíbe chaves de transcrição, inclui exemplo few-shot do JSON editorial e isola a entrada entre `INÍCIO DO MATERIAL PARA ANÁLISE` e `FIM DO MATERIAL`.
- [x] Blindagem ofensiva final: a instrução usa `DIÁLOGOS BRUTOS`/`MATERIAL BASE`, elimina a palavra-gatilho dos prompts, fixa o molde JSON literal no final e envia `format=json` ao Ollama.
- [x] Contrato Single Pass corrigido: 1 a 3 momentos editoriais válidos encerram a geração com sucesso, sem meta mínima de 9 nem mensagens de rodada.
- [x] Parser resiliente contra respostas sujas: remove `<think>...</think>`, aceita cercas Markdown ao extrair o objeto JSON e mantém diagnóstico de resposta inválida.
- [x] Parser à prova de chaves criativas: identifica listas de candidatos por estrutura, não por nome de chave, e grava `RAW:` no erro quando nenhuma lista válida existe.
- [x] Recuperação do schema do índice: JSON válido sem `capitulos`, inclusive mapas de timestamps copiados da transcrição, dispara uma segunda chamada corretiva; capítulos só são aceitos após validação dos intervalos.
- [x] Schema nativo do índice: a chamada editorial usa o JSON Schema do Ollama com `resumo_conteudo`, `capitulos`, títulos e timestamps numéricos obrigatórios; o worker cancelável recebe o mesmo schema.
- [x] Exportação de transcrição: a Central de cortes baixa os segmentos persistidos como SRT UTF-8, preservando intervalos e texto sem expor caminhos internos.
- [x] Capítulos como sumário: o editorial global cobre a linha do tempo do vídeo com títulos no formato assunto + detalhe, sem lista de momentos ou metadados promocionais; a análise de cortes ocorre depois dentro desses intervalos.
- [x] Cobertura integral e detalhada da transcrição: o índice editorial usa contexto Ollama de 32768 tokens no fluxo direto, retry e worker, exige pelo menos seis capítulos e aumenta essa quantidade proporcionalmente em vídeos longos.
- [x] Marcação estrutural em duas passagens: o Ollama identifica bolhas de assunto por janela e depois consolida capítulos; timestamps são ajustados exclusivamente para limites dos segmentos, evitando saltos temporais inventados.
- [x] Continuidade do índice: capítulos são encadeados sem lacunas e uma faixa musical final longa recebe um capítulo específico de encerramento da gravação, sem deslocar timestamps para fora dos segmentos.
- [x] Metadados de corte protegidos: placeholders copiados do prompt são rejeitados antes da deduplicação, o prompt usa somente instruções sem exemplos prontos e o limite interno comporta até doze candidatos distintos.
- [x] Persistência protegida contra timestamps nulos: candidatos com `inicio_segundos`/`fim_segundos` nulos tentam os aliases normalizados e intervalos ainda inválidos são descartados antes da persistência.
- [x] Proteção uniforme nos ramos de corte: a validação de intervalo também cobre candidatos de revisão/fallback, antes de criar registros em `cortes_gerados`.
- [x] Limite físico de mídia: a geração usa a duração real do arquivo e ajusta segmentos que excedem o fim do MP4/MKV, evitando cortes fora da mídia.
- [x] Resultado persistido recuperado na Central: após polling ou recarregamento, a UI lê `resultado_json.cortes` quando o worker não expõe `suggestions` em memória.
- [x] Qualificação de cortes por duração, conteúdo e diversidade: vídeos de 510 segundos exigem pelo menos três candidatos e o máximo é doze; cortes musicais podem participar, mas uma rodada nunca pode conter somente música e eles ficam limitados a um terço da seleção; candidatos editoriais são validados pelos limites reais dos segmentos e resultados abaixo da meta ficam em `needs_review_fallback` com diagnóstico por bloco.
- [x] Normalização resiliente da curadoria: candidatos IA abaixo da duração mínima são expandidos ao redor do intervalo; candidatos válidos acima do teto não são descartados, e emoção, gritos de gol, ambiente e música de evento permanecem elegíveis sem serem classificados como ruído musical.
- [x] Meta baseada em material: a exigência mínima é limitada à quantidade de steps editoriais de 180s com segmentos reais, sem transformar duração vazia em obrigação de nove cortes.
- [x] Renderização com candidatos parciais: qualquer conjunto não vazio de candidatos IA válidos encerra a curadoria como `completed` e libera o worker para renderizar, mesmo quando a meta proporcional não é alcançada; a regressão do job `PQ85Kc7Y6xk` usa cinco candidatos mockados e não chama Ollama nem FFmpeg.
- [x] Steps com material não verbal: toda janela de 180s que possui segmentos transcritos é enviada ao Ollama, inclusive quando os segmentos são música, gritos, ambiente ou frases curtas; somente janelas sem segmentos são omitidas.
- [x] Separação de candidatos no step: o prompt exige pelo menos 30s de distância entre momentos diferentes, e a normalização desloca expansões curtas para intervalos livres da própria janela antes da deduplicação.
- [x] Recuperação de fala sobreposta: quando a transcrição é dominada por marcadores acústicos, o worker reprocessa o áudio com `faster-whisper large-v3` e só aceita a nova saída quando ela recupera fala útil; música e gritos permanecem como contexto, não como evidência textual principal.
- [x] Entrevistas de lideranças preservadas: o prompt editorial v3 trata presidentes, vice-presidentes, representantes e convidados como material prioritário, evitando que uma apresentação seja descartada antes da resposta substantiva.
- [x] Títulos ancorados no trecho: a validação final compara o título com a transcrição efetivamente selecionada; quando não há evidência local, usa uma manchete derivada do conteúdo do próprio intervalo, sem depender de frame ou thumbnail.
- [x] Regeneração individual de metadados: o modal do corte permite gerar novamente título ou descrição separadamente; o endpoint força nova análise usando a transcrição do intervalo e atualiza somente o campo solicitado.
- [x] Estado visual por corte durante jobs: legenda, renderização, postagem/agendamento e regeneração de título/descrição substituem o card afetado por etapa, progresso e ETA; jobs em lote carregam os IDs dos cortes e o polling atualiza somente esses cards, sem recriar previews não envolvidos. A recuperação de jobs preserva timestamps/checkpoint para ETA, e o render recebe somente segmentos de legenda que cruzam o intervalo do corte.
- [x] Preview legendado após conclusão: o player do card alterna para a saída `captions=1` quando `legenda_status` está concluído, em vez de continuar exibindo o MP4 original.
- [x] Áudio inesperado ao abrir corte corrigido: o preview ampliado aguarda interação do usuário e pausa players anteriores antes de trocar de corte.
- [x] Preview auxiliar de legendas silenciado: a mídia visual da configuração inicia sem áudio, com silêncio forçado na propriedade do elemento e volume zero.
- [x] Seleção individual e geração em massa de legendas: o controle do card usa `Selecionar`; o ciclo oferece `Gerar legendas` a partir de dois cortes selecionados, com configuração compartilhada e jobs acompanhados individualmente.
- [x] Integridade da saída legendada: o arquivo gerado recebe sufixo único por job e é comparado ao MP4 sem legendas; saídas idênticas falham e não são persistidas como concluídas.
- [x] ETA de captions corrigido: jobs de legenda não extrapolam o progresso inicial de 10% sem telemetria contínua do FFmpeg; a interface mostra ETA calculando até receber uma estimativa real.
- [x] ETA estimado persistente: o job calcula uma previsão pela duração do corte, salva o valor no checkpoint e a UI desconta o tempo decorrido, identificando o valor como `ETA estimado`.
- [x] Legendas sobre o MP4 renderizado: quando disponível, o worker usa o arquivo final do corte como fonte, desloca segmentos e palavras para timestamps relativos e evita decodificar o vídeo original longo novamente; cortes de 89 segundos passam a ter previsão aproximada de 2m15s.
- [x] Preview em tamanho real: controle de expandir sobreposto ao player abre o MP4 em popup vertical ampliado, mantendo controles de reprodução e suporte à versão legendada.
- [x] Escala ASS estabilizada: `PlayResX` e `PlayResY` definidos como `1080x1920` para manter o tamanho configurado da legenda consistente no vídeo final.
- [x] Refazer legendas atualiza o preview: o player recebe uma versão baseada no novo caminho de saída e a rota de mídia envia headers `no-cache`, evitando exibir o MP4 anterior.
- [x] Controle de preview compacto: expansão em ícone sobreposto no canto inferior direito, alinhado aos controles nativos do player.
- [x] Tela cheia nativa: o controle usa a API fullscreen do player HTML5 e mantém o popup como fallback quando necessário.
- [x] Alinhamento do ícone fullscreen: controle fixo na barra inferior, ao lado do menu nativo do player.
- [x] Proporção vertical no fullscreen: o preview usa o contêiner como elemento fullscreen e preserva `9:16` em telas horizontais.
- [x] Personalização de cores: menu padrão e diálogo de geração expõem cores HEX para texto, destaque/karaokê, stroke e fundo, além da opacidade do fundo; o backend converte os valores para o formato ASS.
- [x] Validação de stroke detalhada: compatibilidade com `black`, `white`, `coral` e HEX, com mensagens específicas para posição, cor e espessura inválidas.
- [x] Legendas sem corte lateral: o renderizador calcula limite de caracteres conforme o tamanho da fonte, quebra karaoke por palavra e usa margens horizontais seguras no ASS.
- [x] Preview de ajuste sobre o corte: o menu usa a mídia real do corte como fundo, atualiza tamanho/cores/stroke ao vivo e envia as coordenadas X/Y exatas do arraste ao ASS.
- [x] Centralização horizontal independente: os editores de legenda oferecem “Centralizar horizontalmente”, levando X para 50% e preservando Y.
- [x] Leitura da transcrição no ajuste de legenda: o modal permite abrir os segmentos do próprio corte com timestamps relativos para conferir palavras bugadas antes da geração.
- [x] Edição persistida da transcrição no corte: o leitor permite corrigir cada segmento e salvar antes da geração; a legenda usa esse texto corrigido sem alterar a transcrição global do vídeo.
- [x] Contraste e diagnóstico do leitor: os campos editáveis seguem o tema do modal, e a ausência de segmentos informa se falta transcrição temporizada ou se é necessário enviar SRT.
- [x] Picker de relacionados: “Nenhum vídeo relacionado” aparece como primeiro item selecionável e a Biblioteca pode limpar uma relação existente sem iniciar aplicação no YouTube Studio.
- [x] Integridade da publicação legendada: o publisher prioriza `legenda_caminho` quando `legenda_status` é concluído, sem fallback silencioso para o corte original; arquivo ausente interrompe o envio.
- [x] Janela inicial do agendamento: no modo recomendado, o usuário informa data e hora de início e o planejador ignora candidatos anteriores, mantendo o ranking de melhores horários por corte.
- [x] Relacionamento com estreia agendada: o picker aceita vídeos `programado` e `agendado`; o ID é mantido para aplicação pelo YouTube Studio após a publicação do corte.
- [x] Acompanhamento da postagem: o progresso geral não é ocultado quando o job possui cortes-alvo, e o estado inicial inclui `cut_ids` para a restauração do polling.
- [x] Reenvio após publicação sem legenda: a verificação de idempotência compara o arquivo efetivo de publicação, permitindo corrigir uploads antigos do original quando a versão legendada foi gerada depois.
- [x] Deduplicação confiável no ciclo: candidatos com título ou descrição iguais são conferidos contra a existência real no YouTube antes de serem tratados como já publicados.
- [x] Manutenção da fila: o executável `GrowthEnginePainel` oferece “Limpar Jobs Finalizados”, removendo apenas estados finais do perfil atual sem interromper jobs em execução.
- [x] Abertura resiliente do Studio: a etapa de vídeo relacionado reconhece a página genérica de erro, repete a navegação até três vezes e captura HTML/screenshot se o editor continuar indisponível.
- [x] Retry manual: Shorts com relação falha exibem um comando na Biblioteca que reenvia os mesmos IDs ao Studio sem duplicar o upload.
- [x] Interface de legendas: o diálogo foi reorganizado em preview, controles rápidos e acordeão de ajustes avançados para reduzir ruído visual.
- [x] Edição precisa de legendas: tamanho e opacidade possuem campos numéricos editáveis, sincronizados com seus controles deslizantes.
- [x] Cache da interface: o identificador do `app.js` foi atualizado para garantir que o diálogo novo seja carregado após a atualização.
- [x] Descrição de capítulos: o schema editorial, o dossiê persistido e o leitor da interface exibem uma descrição factual por capítulo.
- [x] Pipeline editorial pós-transcrição: a conclusão da transcrição enfileira automaticamente o editorial; após a leitura estrutural, a IA propõe correções conservadoras e o editorial final é regenerado quando há alterações.
- [x] Histórico de revisão: transcrição original, corrigida e motivos/confianças das alterações ficam persistidos e a API usa a corrigida nos cortes posteriores.
- [x] Revisão humana: o painel exibe cada correção em comparação com o original e salva decisões individuais antes de regenerar o editorial.
- [x] Validação acústica das correções: cada sugestão contextual é conferida por uma janela Whisper do áudio real; divergências ficam pendentes de revisão e preservam texto reconhecido e similaridade.
- [x] Compatibilidade de descrições: o schema editorial exige `descricao` nos capítulos; dossiês antigos sem esse campo devem ser invalidados e regenerados.
- [x] Limite máximo de cortes: a validação final rejeita intervalos acima da duração máxima configurada, evitando que candidatos de mais de 60 segundos sejam persistidos ou renderizados.
- [x] Revisão transcricional com evidência: o modal permite ouvir o intervalo real do áudio e editar manualmente a sugestão antes de salvar a decisão.
- [x] Timestamp visível na revisão: cada cartão de correção exibe os horários de início e fim logo abaixo do player do segmento.
- [x] Regeneração pós-revisão: o endpoint invalida o dossiê anterior e enfileira automaticamente o editorial final, com polling visual do job.
- [x] Substituição de palavras por ciclo: o cabeçalho do ciclo permite trocar uma palavra ou expressão em todos os títulos e descrições do job, somente em palavras completas e sem afetar outros ciclos.
- [x] Tamanho contínuo e centralização: slider de 32 a 96px atualiza a prévia em tempo real, e o comando de centralização reposiciona a legenda no centro do frame.
- [x] Escala fiel da prévia: tamanho da fonte, stroke e sombras usam a proporção da composição ASS 1080x1920, mantendo o preview em 9:16 e recalculando ao redimensionar.
- [x] Posição manual fiel no render: coordenadas arrastadas usam `\\an5\\pos(x,y)`, mantendo a mesma âncora central usada pelo preview visual.
- [x] Legenda grande em uma linha: controles aceitam até 160px e o modo “Uma linha” preserva o texto sem `\\N` no ASS, inclusive no karaoke.
- [x] Uma linha sem corte: preview e render calculam uma fonte efetiva menor quando necessário, mantendo todas as palavras dentro da largura segura.
- [x] Cores com visual e atalhos: campos exibem a cor atual e círculos rápidos para preto, branco, coral, amarelo e azul, atualizando o mesmo valor usado no preview e no ASS.
- [x] Semântica de cores do karaoke esclarecida: “Cor base” representa palavras não ativas em branco e “Cor destaque” representa a palavra ativa em amarelo, com mapeamento ASS alinhado.
- [x] Prévia de uma linha corrigida: a fonte é recalculada pela largura efetivamente desenhada do texto, evitando divergência e corte nas bordas.
- [x] Linha única pós-layout: o preview recalcula após o modal montar o layout e aplica margem segura adicional, alinhada à redução conservadora do ASS.
- [x] Integridade do resultado atual: quando a geração de cortes executa, seus candidatos não são substituídos por momentos antigos do dossiê; títulos semelhantes em intervalos distintos permanecem válidos e o fallback escolhe janelas distribuídas no início, meio e encerramento do vídeo.
- [x] Diagnóstico legível na Central: resultados por bloco sem o campo `aceitos` não são apresentados como zero aprovações; a interface os identifica como candidatos encontrados e reserva a contagem de aceitos para o resumo agregado.
- [x] Curadoria sem fallback: somente candidatos validados pela IA entram na renderização; abaixo do mínimo, timeout, erro ou provider desativado produzem `failed` com rejeição explícita e zero cortes persistidos.
- [x] Contrato de testes da curadoria: respostas editoriais vazias e provider desativado são verificados como falha sem candidatos locais; o retry corretivo de schema também é esperado no contrato.
- [x] Contrato JSON por step: cada janela usa schema nativo para exigir objetos editoriais e recebe uma única correção quando a Qwen devolve listas de strings; a validação temporal preserva candidatos IA válidos mesmo sem pontuação final nos segmentos Whisper.
- [x] Entrada local sem transferência: a Central permite informar o caminho completo de um MP4/MKV; o backend processa o caminho diretamente no worker escopado pelo perfil e mantém o limite de 8 GB apenas para multipart HTTP.
- [x] O worker local persiste o estado `failed` e a mensagem de erro quando falha depois de iniciar, mantendo a fila e o histórico consistentes.
- [x] A validação editorial normaliza timestamps em segundos e em formatos `MM:SS`/`HH:MM:SS`; respostas abaixo do mínimo não permanecem válidas no cache do dossiê.
- [x] O dossiê persiste momentos editoriais e a colheita ignora intervalos já usados; estruturas vazias sem capítulos nem momentos são invalidadas para nova geração.
- [x] Candidatos de blocos sobrepostos são deduplicados somente depois da conversão para intervalos absolutos, preservando candidatos estruturais por índices de segmentos.
- [x] A meta proporcional considera a duração unificada dos segmentos falados/elegíveis e ignora blocos exclusivamente musicais, evitando exigir nove cortes de um vídeo cuja maior parte é música.
- [x] Diversidade editorial: candidatos musicais são classificados e podem gerar cortes, mas a seleção exige ao menos um trecho com fala e limita música-only a um terço dos cortes finais.
- [x] Marcadores musicais descritivos: a duração elegível também exclui rótulos como `[MÚSICA DE FUNDO]` e `[SOM DO MÚSICA TOCANDO]`, sem impedir que um candidato musical validado participe da seleção diversificada.
- [x] Meta editorial refinada: blocos de análise continuam com 180 segundos, mas a meta de cortes usa aproximadamente 60 segundos de conteúdo elegível por corte e solicita essa quantidade explicitamente à IA.
- [x] Transcrição adaptativa por cobertura: os caminhos YouTube e arquivo local medem a cobertura temporal; áudio longo abaixo de 75% dispara segunda passagem sem VAD ou fallback faster-whisper após DirectCompute, e o cache JSON versionado impede reutilização de transcrição parcial antiga.
- [x] Checkpoints operacionais iniciais: jobs persistem etapa, cursor, total, tentativa e payload de checkpoint; o processamento local atualiza o contrato durante transcrição, editorial e renderização, preparando retomada por unidade.
- [x] Contrato uniforme de steps: os workers persistem `step_name`, `step_index` e `step_total`; transcrição também mapeia `segments_processed`/`segments_total` para os contadores gerais do job. O faster-whisper retoma janelas concluídas pelo sidecar parcial; DirectCompute ainda requer suporte validado a offset.
- [x] Retomada editorial por janela: o dossiê parcial registra `running`, `steps_total` e `steps_completed`; após reinício, steps editoriais concluídos são reutilizados e somente janelas ausentes ou falhas voltam ao Ollama. O `tarefas_jobs.checkpoint_json` acompanha o cursor em tempo real.
- [x] Retomada editorial no worker de cortes: `checkpoint_json` faz merge incremental do payload `editorial_partial`, o ciclo seguinte reutiliza steps concluídos e a renderização não duplica intervalos com MP4 válido.
- [x] Retry editorial operacional: respostas insuficientes ou erros recuperáveis podem repetir a curadoria; timeout do provedor permanece falha terminal para preservar o watchdog e o diagnóstico de indisponibilidade.
- [x] Retomada após reinício: o servidor reencaminha jobs internos interrompidos usando vídeo, perfil, etapa e checkpoint persistidos; uploads/publicações externas não são repetidos sem contrato de idempotência.
- [x] Renderização retomável por corte: o job de cortes selecionados valida status e MP4 existente antes do FFmpeg, preserva itens concluídos e renderiza somente os cortes ainda não disponíveis.
- [x] Publicação retomável por corte: fluxos imediato e agendado verificam `videos_historico` por perfil, Short e MP4 de origem antes de chamar a API, preservando o ID externo já publicado ou programado.

## Plano de enquadramento e legendas por corte

- [ ] Fase 1, enquadramento: substituir a decisão binária de “detectou rosto/não detectou” por uma classificação temporal com três estados: uma face estável, múltiplas faces e plano amplo/sem face.
- [ ] Fase 2, foco facial: quando houver uma única face com confiança e estabilidade suficientes nas amostras, calcular o centro suavizado e manter o rosto dentro da janela 9:16, com margem para não cortar testa ou queixo.
- [ ] Fase 3, composição ampla: quando houver várias faces, detecção instável ou nenhum rosto confiável, manter a fonte horizontal centralizada sobre fundo preenchido e desfocado; registrar no diagnóstico qual regra foi escolhida.
- [x] Fase 4, cues: selecionar os segmentos Whisper que intersectam o intervalo do corte, converter timestamps para zero relativo, remover marcadores acústicos/HTML e quebrar linhas por largura visual, sem alterar a transcrição original.
- [x] Fase 5, estilos: converter cues para ASS e oferecer presets `clean`, `bold` e `highlight`, com fonte, tamanho, posição, cor e espessura de stroke configuráveis e validados no backend; galeria JSON por perfil, presets protegidos, importação validada, preview/render unificados e snapshot imutável por corte implementados. Faster-Whisper preserva timestamps por palavra para karaoke ASS, com fallback para transcrições legadas; fontes TTF/OTF/TTC são armazenadas por perfil e entregues ao libass por `fontsdir`.
- [x] Fase 6, geração individual: painel de opcionais com padrões de estilo/fonte/tamanho/posição, botão `Gerar legendas` em cada card com configuração individual, job assíncrono, nova saída do corte, download separado e preservação do MP4 original.
- [x] Fase 6, UX de configuração: o bloco de legendas dos opcionais é expansível e fechado por padrão; controles, preview, galeria JSON e importação de fontes ficam no conteúdo aberto.
- [ ] Fase 7, persistência e retry: salvar versão do renderer, repetir somente a etapa pendente e invalidar a saída quando a transcrição ou o estilo mudar. O `style_id` e o JSON efetivamente usado já são persistidos como snapshot por corte.
- [ ] Fase 8, testes: a parte de legendas cobre timestamps relativos, clipping, marcadores acústicos, caracteres especiais, presets e regressão da renderização sem legenda; permanecem os testes de enquadramento facial e validação visual FFmpeg.

## Transição

No cache miss, o Diretor de TV processa blocos sequenciais e o mapper materializa cada lote no dossiê antes de aguardar o próximo. No cache hit, o Ollama é ignorado e os melhores momentos são colhidos diretamente do JSON, mas seu estado operacional vem exclusivamente de `cortes_gerados`. O antigo enriquecimento em lotes foi aposentado; a curadoria aponta somente para o processamento por steps.

## Escopo aprovado para as Fases 4 a 8

- [ ] Fase 4: validar operacionalmente cache miss, cache hit, schema e conteúdo do JSON em execução real; esta validação será feita manualmente antes da continuidade do desenvolvimento.
- [ ] Fase 6: o dossiê JSON é somente leitura durante a colheita e funciona como cardápio de candidatos. Os estados definitivos `usado`, `renderizado` e `publicado` devem ser gravados e consultados exclusivamente em `cortes_gerados`; a colheita não deve reescrever flags booleanas no JSON.
- [ ] Fase 6: revisar o lock por perfil/vídeo para garantir exclusão mútua entre processos do sistema operacional, usando file lock ou lock transacional no SQLite, evitando geração simultânea do mesmo vídeo.
- [x] Fase 7: o publisher usa `titulo` e `descricao_publicacao` persistidos pelo dossiê sem regeneração de IA, limita o título enviado ao YouTube a 100 caracteres com truncamento em fronteira de palavra e `...`, e grava no SQLite exatamente os metadados enviados após upload bem-sucedido; a IA fica restrita ao fallback de metadados ausentes.
- [ ] Fase 8: manter auditoria e testes de concorrência compatíveis com a separação entre o cardápio editorial (JSON) e o estado operacional (SQLite).