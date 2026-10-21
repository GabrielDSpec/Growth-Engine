# BUG - Ollama trava a geração de cortes

**Status:** em implementação
**Progresso:** 95%
**Prioridade:** crítica

## Sintoma

A Central permanecia em `IA processando resposta`, normalmente na rodada 3/3, sem concluir nem liberar o cancelamento. Uma requisição mínima ao Ollama também excedia o timeout, confirmando bloqueio no provider/modelo.

## Causa

A chamada HTTP do Ollama ocupava o worker da geração. O heartbeat continuava atualizando o status, mas o cancelamento só era observado depois que a chamada retornava.

## Correção

- Cada chamada ao Ollama roda em um worker Python independente criado por `subprocess.Popen`.
- O processo pai aplica watchdog total por chamada, com timeout elástico `120 + (duracao_em_segundos * 1.5)`, limitado entre 120 e 1200 segundos e configurável por `GROWTH_ENGINE_OLLAMA_TIMEOUT_*`; encerra o filho com `kill()` se houver timeout ou cancelamento. O objetivo é não interromper a inferência normal do modelo 14B por um teto curto.
- A requisição usa contexto máximo de 2048 tokens, saída máxima de 1400 tokens e `keep_alive="15m"` para manter o modelo aquecido entre lotes editoriais.
- O streaming verifica atividade e fecha a conexão ao finalizar.
- Candidatos locais são preparados antes da IA; uma falha editorial não impede o fallback.
- Há no máximo uma chamada editorial ao Ollama por job de cortes.
- O job termina como `needs_review` ou `cancelled`, nunca permanece indefinidamente em `running`.
- A mensagem do job informa quando o fallback foi usado.
- A geração local é o caminho principal: a transcrição produz janelas distintas e o FFmpeg renderiza os MP4; a IA apenas enriquece os candidatos quando disponível.
- Respostas editoriais parciais não descartam mais candidatos locais: o merge preserva todos os intervalos, marca itens da IA como `enriquecido` e resgata itens omitidos como `bruto` para revisão manual.
- O fallback não anuncia candidatos locais antes do filtro global: quando todos os intervalos colidem com cortes existentes, a lista retornada fica vazia e a mensagem registra o descarte por sobreposição.
- Dossiês vazios ou com diagnóstico de timeout/erro não são aceitos como cache hit; após uma nova tentativa sem momentos válidos, a geração falha explicitamente e o job fica em erro, evitando cache de falha e sucesso silencioso com zero cortes.
- O contexto multimodal é recortado por janela antes de cada step; quando a IA falha ou responde vazio, o resultado usa `needs_review_fallback` e mantém a distinção entre candidatos locais e editoriais.
- A curadoria editorial por steps é single pass: não há mais loop de rodadas/retries; cada janela pede 1-3 momentos independentes e o job registra profiling das fases para localizar gargalos.
- O resultado editorial não é mais descartado quando a filtragem operacional remove todos os intervalos por sobreposição; o dossiê é persistido e a colheita continua impedindo duplicatas.
- Inicializações não interativas recuperam jobs antigos automaticamente, sem aguardar confirmação em stdin.
- A duração total do vídeo chega ao provider para dimensionar o tempo de leitura e geração de transcrições maiores sem permitir limites absurdos.

## Critérios de aceite

- Uma chamada que não responde não mantém o worker preso além do limite configurado, incluindo o timeout HTTP interno.
- Cancelar durante a geração libera o job sem reiniciar manualmente o servidor.
- Ollama indisponível produz fallback local e revisão humana controlada.
- Arquivos e registros são limpos quando o job é cancelado.
- O diagnóstico da rodada registra timeout/rede sem tratar a falha como evidência editorial.
- A IA editorial retorna título, descrição, hashtags e score na mesma resposta.

## Validação

- `py_compile` de `core/cutter.py` e `core/web_server.py`.
- `node --check frontend/app.js`.
- `git diff --check`.
- Teste de cancelamento antes de iniciar uma chamada ao Ollama.
