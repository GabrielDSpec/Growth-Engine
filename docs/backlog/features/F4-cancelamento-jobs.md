# F4-CANCELAMENTO-JOBS

## Objetivo
Permitir que a Central de cortes interrompa transcrições e renderizações longas sem deixar o job como concluído ou falho.

## Implementado

- Endpoint `POST /api/jobs/{job_id}/cancel` com isolamento por `perfil_id`.
- Estado terminal persistido como `cancelled`.
- Workers de upload, transcrição, análise e renderização verificam o cancelamento.
- DirectCompute AMD usa processo monitorado e encerrável.
- Central de cortes exibe o botão de cancelamento e encerra o polling.

## Validação pendente

Reiniciar o servidor quando não houver processamento ativo e validar o fluxo completo com uma transcrição e uma renderização reais.
