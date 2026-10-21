# F3 - Transcricao local acelerada por GPU e observavel

**Status:** em implementacao
**Progresso:** 85%
**Prioridade:** critica
**Area:** producao

## Problema confirmado

O upload local usa `WhisperModel("medium", device="cpu", compute_type="int8")`. Em um video de 316 MB, a etapa pode parecer parada porque o status permanece generico e o callback so atualiza quando um segmento e produzido. Em arquivos longos ou com silencio, isso esconde o trabalho real.

## Objetivo

Reduzir o tempo de transcricao usando a GPU AMD disponivel, com comportamento explicito quando o backend de aceleracao nao estiver instalado, e fornecer telemetria suficiente para diferenciar processamento lento de travamento.

## Escopo tecnico

- Detectar a GPU AMD e validar um backend compativel, priorizando Vulkan/whisper.cpp ou HIP/ROCm quando houver binding estavel para o projeto.
- Manter faster-whisper/CTranslate2 como caminho CPU ou CUDA para hardware compativel, sem tratar CUDA como backend valido para a RX 9060 XT.
- Tornar configuraveis por ambiente o modelo, dispositivo, compute type, beam size e VAD.
- Usar GPU por padrao quando a validacao passar; nao cair silenciosamente para CPU.
- Permitir fallback para CPU somente por configuracao explicita ou modo de diagnostico.
- Reutilizar o modelo carregado no processo, evitando recarregamento por video.
- Exibir etapas distintas: preparando arquivo, carregando modelo, decodificando, transcrevendo, reprocessando sem VAD e salvando cache.
- Registrar tempo decorrido, velocidade de audio em tempo real, ETA estimada, duracao do audio, segmentos processados e segmentos aceitos.
- Persistir diagnostico de hardware, modelo, dispositivo e compute type no job.

## Contrato de progresso

O job deve expor ao menos:

```json
{
  "stage": "transcribing",
  "message": "Transcrevendo audio",
  "progress": 42,
  "elapsed_seconds": 38.4,
  "audio_seconds": 912.0,
  "processed_audio_seconds": 383.0,
  "segments_processed": 142,
  "segments_accepted": 137,
  "speed_x": 10.0,
  "eta_seconds": 53,
  "device": "cuda",
  "model": "large-v3"
}
```

## Critérios de aceite

- Um teste de inicialização confirma se o backend CUDA está realmente ativo.
- O status nao exibe apenas `Transcrevendo arquivo local` durante toda a etapa.
- A tela mostra etapa, percentual, tempo decorrido, velocidade, ETA e quantidade de segmentos.
- Um arquivo de 316 MB e medido antes/depois, registrando duracao, hardware e configuracao usada.
- O cache da transcricao continua sendo salvo por `perfil_id` e video.
- Falha do backend AMD informa a causa e a acao corretiva; nao apresenta GPU como ativa quando houve fallback.
- O processamento nao e reiniciado nem duplicado por atualizacoes de polling.
- Testes cobrem GPU indisponivel, GPU disponivel, timeout, silencio prolongado, VAD sem fala e persistencia do diagnostico.

## Riscos e dependencias

- O pacote Python instalado pode ter sido compilado apenas para CPU.
- CTranslate2/faster-whisper usa CUDA para NVIDIA e nao transforma uma GPU AMD em dispositivo CUDA.
- Vulkan/whisper.cpp ou HIP/ROCm precisam ser avaliados no Windows e comparados com a qualidade/velocidade do caminho CPU.
- O modelo `large` exige mais VRAM e pode provocar OOM; deve existir configuracao de modelo menor para recuperacao controlada.
- O benchmark deve medir velocidade de audio, nao apenas tamanho do arquivo, porque MB nao representa duracao nem complexidade de decodificacao.

## Plano de implantacao

1. Diagnosticar GPU AMD, driver, versoes e backend efetivamente disponivel.
2. Criar configuracao de Whisper e healthcheck de transcricao.
3. Migrar o callback para um contrato de progresso detalhado.
4. Atualizar frontend e persistencia do job.
5. Rodar benchmark controlado com o video de 316 MB e comparar CPU/GPU.

Esta tarefa foi registrada antes da implementacao. Nenhum servidor deve ser reiniciado ou alterado ate aprovacao explicita.

## Estado atual

- [x] Modelo, dispositivo e compute type configuraveis por ambiente.
- [x] Diagnostico explicito de que CTranslate2 detecta `cuda_devices=0`.
- [x] Status com etapa, tempo, velocidade, ETA e segmentos.
- [x] Frontend preparado para exibir a telemetria do job.
- [x] Diagnostico deste ambiente: GPU `AMD Radeon RX 9060 XT`, fallback efetivo para `cpu/int8`.
- [x] Validar que o Vulkan enumera a RX 9060 XT com driver AMD proprietario.
- [x] Validar engine `constme.exe`/DirectCompute com a RX 9060 XT; a engine carregou 1259 tensores e 2,95 GB de VRAM no smoke test.
- [x] Integrar DirectCompute no `core/transcriber.py` com saida SRT segmentada e telemetria de backend/GPU.
- [x] Exibir progresso contínuo com timestamp de áudio, duração original, velocidade e ETA; usar estimativa explícita quando o SRT ainda não tiver timestamp.
- [x] Persistir SRT em `media/<perfil_id>/transcripts/<sha256>.srt` e reutilizar o cache antes de iniciar nova transcrição.
- [x] Persistir a causa detalhada quando download, arquivo local, Whisper ou transcrição vazia impedem a conclusão do job.
- [x] Watchdog específico para finalização do SRT DirectCompute, configurável por `WHISPER_DIRECTCOMPUTE_FINALIZATION_TIMEOUT` e separado do timeout global de transcrição.
- [x] O estado de finalização AMD só é emitido quando o SRT fornece timestamp real no fim do áudio; a estimativa de progresso não inicia o watchdog.
- [x] DirectCompute usa 8 threads por padrão, configuráveis por `WHISPER_DIRECTCOMPUTE_THREADS`, com a configuração exposta no progresso persistido.
- [x] Recuperação de startup encerra processos `constme.exe` órfãos antes de retomar transcrições interrompidas.
- [x] DirectCompute gera SRT com timestamps no diretório temporário da execução; a chamada não usa mais `--no-timestamps`.
- [x] Persistir a origem e o hash do arquivo para validar a reutilização da transcrição.
- [ ] Validar execucao real com o arquivo completo e avaliar upgrade do modelo GGML para `large-v3`.
- [ ] Medir benchmark do video de 316 MB em GPU e CPU.