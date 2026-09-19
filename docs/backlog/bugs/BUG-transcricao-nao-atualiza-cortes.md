# BUG - Transcricao concluida nao aparece na Central de cortes

**Status:** em implementacao
**Prioridade:** alta
**Area:** producao

## Sintoma

Depois de uma transcricao concluida, a Central de cortes continua exibindo que nao existem segmentos salvos e nao oferece a geracao de sugestoes.

## Causa confirmada

- A lista de fontes filtrava somente `status='publicado_externo'`, excluindo registros `upload_local`.
- `has_transcription` era verdadeiro quando havia apenas texto, embora o pipeline de cortes precise de `transcricao_segmentos`.
- `loadCutSources()` selecionava o primeiro video, mas nao chamava `selectCutSource()` para carregar `/api/transcription`.

## Correcao

- Incluir fontes `upload_local` na Central de cortes.
- Expor separadamente `has_transcription` e `has_segments`.
- Carregar a transcricao segmentada ao selecionar automaticamente a primeira fonte.
- Manter a mensagem de transcricao quando houver texto sem segmentos e orientar a resegmentacao.
- O fluxo de upload local tambem persiste candidatos estruturais quando a Qwen retorna `needs_review`, alinhando-o ao fluxo de cortes externos.

## Resultado do video de teste

- Video: `A lutadora de Muay Thai que virou Miss! (Bastidores)`.
- Upload local: `a310d20abd444a4bb069a3a6cfdd13d3`.
- Final: `failed` em `2026-09-19 13:30:22`, com `A Qwen não aprovou cortes válidos.`.
- Persistencia: nenhuma transcricao, segmento ou candidato foi salvo nessa execucao antiga.
- O codigo atual foi corrigido, mas o servidor que executou o video nao foi reiniciado durante o processamento; a confirmacao ao vivo depende do proximo ciclo.

## Backend de transcricao validado

- `constme.exe` lista a `AMD Radeon RX 9060 XT` como adaptador 0.
- Smoke test com `diagnostic_audio.wav` carregou 1259 tensores e aproximadamente 2,95 GB de VRAM.
- O transcriber integrado retornou segmentos SRT usando `backend=directcompute`.
- O job `1ab62cf0a0de4e1081235092b6182e03`, iniciado antes da ativacao da GPU, foi interrompido em 11% durante o reinicio e nao deixou transcricao persistida.

## Retomada autorizada

- Em 2026-09-19, o reinicio do servidor foi autorizado depois da conclusao do job antigo.
- Proximo teste: iniciar o servidor com o codigo corrigido, enviar novamente o arquivo local e confirmar fontes, segmentos, `needs_review` e candidatos persistidos.

## Aceite

- Upload local concluido aparece como fonte de corte.
- A fonte selecionada com segmentos mostra evidencias sem exigir troca manual no seletor.
- Texto sem segmentos nao e tratado como pronto para gerar cortes.
- O status do job concluido e o estado visual da Central permanecem consistentes apos novo carregamento.
- O servidor ativo nao e reiniciado durante o video de teste; a correcao entra no proximo ciclo.