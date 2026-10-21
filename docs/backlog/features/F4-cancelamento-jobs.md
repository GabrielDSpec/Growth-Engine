# F4-CANCELAMENTO-JOBS

## Objetivo
Permitir que a Central de cortes interrompa transcrições e renderizações longas sem deixar o job como concluído ou falho.

## Implementado

- Endpoint `POST /api/jobs/{job_id}/cancel` com isolamento por `perfil_id`.
- Estado intermediário `cancelling` persistido enquanto o worker ainda está encerrando; `cancelled` só é persistido depois da saída do worker e da liberação da chave do `TaskRunner`.
- Workers de upload, transcrição, análise e renderização verificam o cancelamento.
- DirectCompute AMD usa processo monitorado e encerrável.
- Central de cortes exibe o botão de cancelamento, mantém o polling durante `cancelling` e só libera a nova geração quando o job chega a um estado terminal.
- Retomadas `interrupted` podem ser descartadas pela API, e a Central remove estados terminais persistidos no navegador para não reapresentar jobs antigos como ativos após reinício.

## Validação

- `python -m py_compile core/web_server.py core/task_runner.py` passou.
- `node --check frontend/app.js` passou.
- `python -m unittest discover -s tests -p "test_*.py"` passou com 40 testes.
- Reiniciar o servidor com jobs ativos continua bloqueado por segurança; o terminal interativo exige `CONTINUAR` para interromper tarefas.
- Ainda falta validar uma transcrição/renderização real após reinício e testar o caminho completo com Qwen/FFmpeg.
