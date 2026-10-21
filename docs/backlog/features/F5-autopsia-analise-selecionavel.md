# Autópsia analítica selecionável

## Objetivo

Permitir que a Autópsia seja executada de forma explícita e previsível, com análise individual ou em lote dos vídeos escolhidos pelo usuário.

## Entregue

- Modal para selecionar vídeos antes de iniciar a análise.
- Filtros independentes para vídeos longos e Shorts.
- Botão individual `Analisar` nos cards pendentes.
- Botão `Analisar todos os pendentes` limitado aos cards apresentados na coluna, após filtro e limite visual.
- Progresso persistente com vídeos processados, porcentagem, mensagem de etapa e ETA.
- Atualização periódica do frontend sem polling duplicado.
- Progresso fracionado durante transcrição, análise e cruzamento de padrões.
- ETA atualizado por heartbeat durante etapas demoradas.
- Geração de ideias baseada exclusivamente nos Top 15 analisados da Autópsia.
- Prompt da geração compactado para enviar apenas evidências relevantes.
- Geração de ideias direcionada ao modelo `qwen2.5:14b`; o modelo Coder permanece para tarefas de programação.
- Timeout configurável por `OPPORTUNITY_AI_TIMEOUT`, com padrão de 600 segundos.

## Critérios de aceite

- Nenhuma análise começa sem IDs explícitos selecionados.
- A ação em lote nunca inclui vídeos fora dos cards visíveis na coluna.
- O status atualiza sem recarregar a página e sem duas rotinas concorrentes para o mesmo job.
- Falhas do Ollama aparecem no status da tarefa e não criam oportunidades falsas.
- O servidor pode ser reiniciado sem deixar uma tarefa pesada ativa indevidamente.

## Validação realizada em 2026-09-21

- `node --check frontend/app.js`
- `python -m py_compile core/opportunities.py core/web_server.py`
- `git diff --check`
- Servidor reiniciado e endpoint `/api/autopsy` validado em HTTP 200.
- Endpoint `/api/opportunities/status` validado após reinício em estado `idle`.
- Modelo local `qwen2.5:14b` confirmado disponível no Ollama.
- Prompt compacto medido com 15 vídeos e aproximadamente 13,9 mil caracteres.

## Pendências

- Executar uma geração completa com o modelo local após reinício e registrar duração real.
- O teste de scheduler foi substituido por `test_scheduler_fills_available_gaming_slots_before_next_day`, validando horarios premium noturnos e a transicao somente quando os horarios futuros do dia acabam.
