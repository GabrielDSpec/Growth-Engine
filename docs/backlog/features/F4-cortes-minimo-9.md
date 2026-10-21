# F4 - Geracao garantida de cortes validos

**Status:** em implementacao
**Progresso:** 65%
**Prioridade:** critica
**Area:** producao

## Contexto

O upload local chega a etapa de transcricao e Qwen, mas o job atual termina como `failed` quando `garimpar_vacas_roxas()` retorna zero cortes aceitos. O codigo atual calcula `estimativa_minima` de 3 e `estimativa_maxima` de 8, enquanto o requisito de produto e gerar no minimo 9 cortes por video elegivel.

O ultimo incidente do perfil `915361` confirmou o problema: o job chegou a analise da Qwen, mas terminou com `A Qwen nao aprovou cortes validos`; nenhum payload bruto, transcricao ou motivo individual de rejeicao foi persistido.

## Requisito de produto

- Um video elegivel deve terminar com pelo menos 9 cortes persistidos e renderizaveis.
- O processamento nao pode tentar indefinidamente.
- Nenhum corte pode inventar fala, timestamp ou evidencia que nao exista na transcricao.
- Toda tentativa deve permanecer isolada por `perfil_id`.

## Limite operacional proposto

Usar um orcamento finito por job:

- no maximo 3 chamadas a Qwen;
- timeout de 90 segundos por chamada;
- no maximo 270 segundos de IA, sem contar transcricao e FFmpeg;
- cada chamada recebe o conjunto de candidatos e os motivos agregados das rejeicoes anteriores;
- se o servidor reiniciar, o job fica `interrupted` e pode ser retomado sem ultrapassar o orcamento persistido.

## Estrategia de geracao

1. **Rodada 1 - selecao ampla:** pedir 12 a 15 candidatos, permitindo cortes de 10 a 90 segundos, sempre ancorados em segmentos reais.
2. **Rodada 2 - correcao orientada:** reenviar somente os candidatos rejeitados com os motivos estruturais, pedindo substituicoes para atingir 9 aceitos.
3. **Rodada 3 - cobertura controlada:** pedir novos cortes em janelas/segmentos ainda nao usados, reduzindo duplicacao e mantendo a evidencia literal.
4. **Selecao final:** deduplicar por intervalo sobreposto e escolher os 9 melhores por score, preservando diversidade de trechos.

## Regras que nunca podem ser relaxadas

- `segmento_inicio` e `segmento_fim` devem existir na transcricao;
- `inicio` e `fim` precisam ser calculados a partir dos segmentos reais;
- inicio menor que fim e intervalo dentro da duracao;
- evidencia textual presente no trecho;
- nenhuma sobreposicao total ou duplicacao do mesmo intervalo;
- arquivo de origem pertencente ao `perfil_id` do job;
- renderizacao deve retornar sucesso e caminho dentro de `media/<perfil_id>/shorts/`.

## Relaxamentos permitidos, em ordem

- aceitar score minimo 60 na rodada 2, desde que as regras de evidencia sejam satisfeitas;
- aceitar cortes de 8 a 90 segundos na rodada 3, se a transcricao nao fornecer nove janelas de 10 segundos;
- permitir titulo e resumo editorial derivados deterministicamente do texto quando a Qwen omitir campos nao essenciais;
- nunca relaxar a origem, os timestamps, a evidencia, o isolamento ou a validade do arquivo.

## Impossibilidade real

“De qualquer maneira” nao pode significar inventar cortes. Se, depois das 3 rodadas, o video nao tiver 9 trechos distintos que atendam as regras invariaveis, o job deve terminar como `needs_review`, nao como `failed` generico. O estado deve informar:

- quantidade de cortes validos;
- quantidade necessaria;
- motivos agregados de rejeicao;
- segmentos sem cobertura;
- transcricao e payloads salvos para revisao.

## Observabilidade e persistencia

Persistir por `job_id` e `perfil_id`:

- transcricao segmentada do upload;
- payload bruto de cada resposta da Qwen;
- rodada, duracao e timeout;
- motivo de rejeicao por candidato;
- candidatos aceitos e descartados;
- estado final `completed`, `needs_review` ou `failed`;
- erro de cada renderizacao individual.

Nenhum log deve conter token OAuth ou segredo.

## Testes de aceite

- resposta vazia na rodada 1 gera rodada 2, sem loop infinito;
- resposta parcialmente invalida e rodada seguinte valida 9 cortes;
- respostas invalidas nas 3 rodadas terminam em `needs_review` com diagnostico;
- 9 cortes sao persistidos somente no `perfil_id` ativo;
- candidato com timestamp inventado e candidato com evidencia ausente sao rejeitados;
- intervalos duplicados sao deduplicados;
- timeout da Qwen consome uma rodada e permite continuar;
- reinicio recupera o job sem reiniciar o orcamento;
- FFmpeg falhando em um corte nao apaga os demais e registra erro individual;
- suite atual de contratos continua verde.

## Dependencias e riscos

- A transcricao local precisa ser persistida antes da chamada a Qwen.
- O schema de jobs precisa guardar rodada/orcamento e diagnostico sem vazar dados entre tenants.
- Nove cortes podem ser editorialmente ruins em videos curtos; `needs_review` protege a qualidade quando a materia-prima nao comporta o requisito.
- O custo de CPU/tempo aumenta com ate tres chamadas da Qwen e ate nove renderizacoes.

## Estado da implementacao

- [x] Saída UTF-8 do cutter: logs com emojis não derrubam a geração em consoles Windows configurados com `charmap`; caracteres não suportados são substituídos apenas na saída.
- [x] Fallback editorial definitivo: ausência, invalidade ou erro no resumo da IA não descarta um MP4 já renderizado; o corte recebe descrição estruturada com título, trecho de até 20 palavras da transcrição e `#shorts #podcast #cortes`.
- [x] Force Generate sem clones: não há mais deslocamentos artificiais nem bypass final; janelas com mais de 40% de sobreposição ou título exato/similar são descartadas contra o banco e o ciclo atual, com degradação graciosa para menos de 9 cortes.
- [x] Estados inativos não bloqueiam regeneração: cortes `excluido`, `falhou` e `cancelado` ficam fora da lista de intervalos usados, permitindo gerar novos cortes após uma rodada descartada.
- [x] Smart crop facial: o enquadramento vertical analisa frames em 0%, 25%, 50%, 75% e 100%, reduz a escala mínima para faces pequenas de planos abertos e usa a maior face detectada; sem detecção, posiciona o crop no terço superior.
- [x] Fallback sem rosto com fundo desfocado: quando não há coordenada facial válida, o render usa `filter_complex` com fundo preenchido e desfocado, vídeo original centralizado e saída `[outv]` mapeada para preservar os encoders AMF/CPU.
- [x] Filtro blur otimizado: a entrada é dividida uma vez, o fundo recebe blur em 540x960 e só depois volta a 1080x1920, evitando aplicar o blur pesado em resolução cheia.
- [x] Contexto multimodal leve: `core/vision_tools.py` analisa `showinfo` e `astats` uma vez por job, associa `[🎬 CORTE DE CÂMERA]` e `[🔊 PICO DE ÁUDIO]` aos segmentos e passa somente tags semânticas ao prompt; scores do detector não são expostos à IA e falhas do FFmpeg usam fallback textual.
- [x] Retry finito de ate tres chamadas da Qwen.
- [x] Meta de nove cortes e deduplicacao por intervalo.
- [x] Estado `needs_review` com diagnostico em `tarefas_jobs.resultado_json`.
- [x] Persistencia da transcricao segmentada no perfil ativo.
- [x] Contratos automatizados para resposta vazia e nove candidatos validos.
- [x] Frontend exibe `needs_review`, quantidade encontrada e rodadas do diagnóstico.
- [ ] Diagnostico individual de cada regra rejeitada.
- [ ] Persistir payload bruto completo de cada rodada.
- [x] Persistir todos os candidatos estruturalmente validos para curadoria manual, incluindo os omitidos pela IA com `status_editorial=bruto`.
- [ ] Renderizar somente candidatos selecionados explicitamente pelo usuario.

## Proxima implementacao recomendada

Extrair a validacao para retornar `accepted` e `rejected_reasons`, persistir a transcricao e o diagnostico por rodada, e implementar a curadoria manual em [`F4-curadoria-manual-candidatos.md`](F4-curadoria-manual-candidatos.md). A resposta editorial parcial agora faz merge por indice ou timestamps: itens retornados recebem `status_editorial=enriquecido` e itens omitidos sao resgatados como `status_editorial=bruto`.
