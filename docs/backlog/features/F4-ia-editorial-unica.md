# F4 - Curadoria Vaca Roxa em chamada editorial única

**Status:** em implementação
**Progresso:** 70%
**Prioridade:** crítica

## Objetivo

Preservar a curadoria editorial da IA sem tornar o Ollama uma dependência para criar ou renderizar os Shorts.

## Fluxo

1. A transcrição local produz candidatos reais com timestamps.
2. Uma única chamada isolada analisa esses candidatos pela Teoria da Vaca Roxa.
3. A resposta retorna score, título, descrição, hashtags, ângulo e evidências editoriais.
4. O FFmpeg renderiza os candidatos locais enriquecidos.
5. Timeout, JSON inválido ou provider indisponível mantêm o fallback local e marcam revisão humana.

## Critérios de aceite

- No máximo uma chamada ao Ollama por job de cortes.
- Título, descrição, hashtags e score vêm da mesma resposta editorial.
- Nenhuma etapa posterior chama o Ollama novamente.
- Os MP4 são renderizados mesmo quando a IA falha.
- O job termina em estado terminal com diagnóstico explícito.
- A Central mostra a etapa atual e diferencia análise editorial de renderização.
- Títulos sem termos verificáveis no trecho não passam para a Central nem para o upload; o fallback local usa o gancho do próprio corte.
- A descrição prévia só é persistida quando é um resumo editorial gerado pela IA ou uma revisão manual; texto literal da transcrição nunca é fallback.

## Pendente

- Executar uma geração real com o provider saudável.
- Executar uma geração real com Ollama saudável e confirmar que todos os resumos aparecem antes da revisão humana.