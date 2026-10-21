# Análise de otimização da renderização de Shorts

**Projeto:** Growth Engine  
**Data:** 2026-09-23  
**Escopo:** `renderizar_corte_shorts`, `renderizar_corte`, filtros verticais e comandos FFmpeg.  
**Status:** unificação CPU e seleção AMF com fallback para CPU aplicadas em 2026-10-02; accurate seek com `-ss` pós-input, `-t` relativo e `-avoid_negative_ts make_zero` aplicado em 2026-10-03 para priorizar integridade de frames; fallback de sincronização e descoberta de containers corrigidos em 2026-10-01; isolamento stateless das requisições Ollama reforçado em 2026-10-03. Render real com a Radeon, benchmark comparativo e cache de detecção facial continuam pendentes.

## Resumo executivo

O projeto possui duas rotas de renderização:

- `core/cutter.py::renderizar_corte_shorts()`: rota usada diretamente pelo pipeline legado, agora delegando a montagem do comando ao helper compartilhado.
- `core/media_tools.py::renderizar_corte()`: rota usada pelo servidor web com `vertical=True`, também delegando ao helper compartilhado.

As duas rotas fazem o seek inicial com `-ss` antes de `-i` e usam `-t` relativo após a entrada, favorecendo velocidade e tornando a duração explícita. O filtro vertical é calculado pelo OpenCV antes do encode. A detecção facial atual não é tracking contínuo: são nove amostras, escolha do maior rosto em cada amostra, média dos centros e um crop fixo aplicado ao vídeo inteiro.

As maiores oportunidades reais são:

1. medir os parâmetros de encode já unificados entre as duas rotas;
2. tornar a duração do corte explícita com `-t`, em vez de depender de `-to` pré-input;
3. validar em render real o encoder AMF selecionável com fallback testado, sem presumir que toda GPU suporta o mesmo backend;
4. reduzir o custo repetido da detecção facial entre cortes do mesmo vídeo;
5. avaliar `scale` mais barato que `lanczos` quando a origem já tem boa resolução;
6. eliminar encode duplicado em montagens não contínuas, quando o filtergraph puder ser validado.

## 1. Fluxo atual

### 1.1 Rota legada

`renderizar_corte_shorts()` em `core/cutter.py`:

1. obtém a duração com FFprobe;
2. adiciona padding inicial e final, normalmente `0.3s` e `0.5s`;
3. limita o intervalo à duração do vídeo;
4. chama `calcular_corte_com_rosto()` para calcular o enquadramento vertical;
5. executa FFmpeg;
6. valida se o arquivo de saída existe e tem tamanho maior que zero.

O comando atual é equivalente a:

```text
ffmpeg -y \
  -ss {inicio_render:.3f} \
  -i {video_origem} \
  -t {duracao_render:.3f} \
  -vf "crop={crop_width}:{crop_height}:{crop_x}:{crop_y},scale=1080:1920:flags=bicubic,format=yuv420p" \
  -map 0:v:0 \
  -map 0:a? \
  -c:v libx264 \
  -preset faster \
  -crf 20 \
  -pix_fmt yuv420p \
  -c:a aac \
  -b:a 160k \
  -movflags +faststart \
  {caminho_saida}
```

### 1.2 Rota usada pelo servidor web

`core/media_tools.py::renderizar_corte()` é chamada por `core/web_server.py` com `vertical=True`.

Ela agora usa o mesmo helper e os mesmos parâmetros explícitos de qualidade:

```text
ffmpeg -y \
  -ss {inicio} \
  -i {caminho_origem} \
  -t {duracao_render} \
  -vf "{filtro_vertical},scale=1080:1920:flags=bicubic,format=yuv420p" \
  -map 0:v:0 \
  -map 0:a? \
  -c:v libx264 -preset faster -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 160k \
  -movflags +faststart \
  {caminho_saida}
```

As duas rotas agora passam pelo mesmo helper, com duração relativa explícita, filtro bicubic, pixel format yuv420p, preset `faster`, CRF 20 e áudio AAC 160k. A comparação de desempenho deve ser feita somente após medir arquivos representativos.

Para montagens não contínuas, o fluxo renderiza intervalos em arquivos temporários e depois concatena com `-c copy`. Isso evita reencode na concatenação, mas cada intervalo já foi codificado separadamente.

## 2. Aceleração de hardware

### 2.1 Estado atual

O pipeline agora seleciona dinamicamente o encoder para encode:

- `SHORTS_ENCODER=auto` prioriza `h264_amf` quando o FFmpeg o anuncia;
- `libx264` com `faster/CRF 20` continua como fallback explícito e automático para falhas de device/AMF;
- a seleção é feita por capacidade reportada por `ffmpeg -encoders` e o resultado é cacheado por executável;
- ainda não há uso de `h264_nvenc`, `h264_qsv`, CUDA, `scale_npp` ou `hwupload`;
- a detecção facial com Haar Cascade do OpenCV também roda pela API convencional de CPU.

Referências a GPU no projeto estão ligadas principalmente à transcrição, não à renderização.

### 2.2 É viável usar GPU dinamicamente?

Sim, mas a seleção deve ser feita por capacidade real do FFmpeg instalado, não apenas pelo nome da placa ou por uma variável de ambiente.

Backends possíveis no Windows:

| Hardware | Encoder provável | Observação |
|---|---|---|
| NVIDIA | `h264_nvenc` | Requer driver NVIDIA e build FFmpeg com NVENC habilitado. |
| AMD | `h264_amf` | Requer driver AMD e suporte AMF na build do FFmpeg. |
| Intel | `h264_qsv` | Requer iGPU/driver Intel e suporte QSV. |
| Sem encoder compatível | `libx264` | Fallback universal de CPU. |

A lógica recomendada é:

1. consultar `ffmpeg -hide_banner -encoders` e verificar se o encoder está disponível;
2. opcionalmente executar um smoke test curto com o encoder selecionado, porque a presença na lista não garante que driver/device estejam operacionais;
3. usar o encoder de hardware somente quando a validação passar;
4. retornar automaticamente a `libx264` quando houver erro de inicialização, device ausente ou incompatibilidade;
5. registrar encoder escolhido, motivo do fallback e tempo de renderização.

Não é recomendável tentar NVIDIA, depois AMD e depois Intel cegamente em toda renderização: isso adiciona latência e produz diagnósticos pouco claros. A preferência pode ser configurável, por exemplo:

```text
SHORTS_ENCODER=auto|libx264|h264_nvenc|h264_amf|h264_qsv
```

Em `auto`, a ordem pode ser definida por plataforma ou configuração do servidor.

### 2.3 GPU não acelera automaticamente toda a pipeline

Mesmo com encoder GPU, estes trechos continuam potencialmente CPU-bound:

- leitura e análise dos frames pelo OpenCV;
- detecção facial Haar;
- filtro `crop` se executado em CPU;
- `scale` se executado em CPU;
- mux e escrita do arquivo.

Para aproveitar uma cadeia totalmente acelerada seria necessário usar filtros compatíveis, como `scale_npp`/CUDA, `scale_qsv` ou equivalentes, além de controlar uploads/downloads entre memória CPU e GPU. Para um corte vertical de poucos segundos, transferir frames para a GPU pode reduzir ou anular o ganho do encode.

A recomendação prática é começar com encode GPU e filtros CPU, medir o tempo total, e só depois avaliar uma cadeia integralmente acelerada.

### 2.4 Diferenças de qualidade entre encoders

`-crf` é uma métrica própria do x264/x265. Encoders de hardware geralmente usam controles diferentes:

- NVENC: normalmente `-rc vbr -cq N -b:v 0` ou uma combinação equivalente;
- AMF: controles variam conforme a versão/build e podem usar `-qp_i/-qp_p` ou bitrate/VBR;
- QSV: pode usar `-global_quality` ou controles de bitrate.

Portanto, não se deve reutilizar `-crf 20` indiscriminadamente com `h264_nvenc`, `h264_amf` ou `h264_qsv`. A função Python deve montar um conjunto de argumentos específico por encoder.

## 3. Ordem de `-ss`, `-to` e `-i`

### 3.1 Estado atual

A ordem atual é:

```text
-ss INICIO -to FIM -i INPUT
```

Como `-ss` está antes de `-i`, ele é um input option e faz seek rápido até um ponto próximo ao keyframe anterior. Isso reduz o custo de localizar o trecho, especialmente em vídeos longos.

`-to` também está antes de `-i`, portanto atua como limite de timestamp da entrada. Essa forma usa timestamps absolutos e é menos explícita do que declarar o início e a duração do corte.

### 3.2 Velocidade versus precisão

Essa ordem favorece velocidade, mas não garante a melhor precisão de frame em todos os formatos. O seek pré-input normalmente chega próximo do ponto solicitado e o decoder pode precisar processar a partir de um keyframe. A precisão observada depende do codec, dos keyframes, dos timestamps e da versão do FFmpeg.

Para um Shorts com padding de `0.3s`/`0.5s`, pequenos desvios de entrada podem ser aceitáveis, mas cortes que começam em uma fala específica ou em um frame decisivo merecem validação.

As opções são:

| Estratégia | Velocidade | Precisão | Uso recomendado |
|---|---:|---:|---|
| `-ss` antes de `-i` | Alta | Menor/variável | Preview e cortes tolerantes a pequenos desvios. |
| `-ss` depois de `-i` | Menor | Alta | Precisão máxima, especialmente em cortes frame-critical. |
| `-ss` antes + `-ss` residual depois | Alta | Alta | Melhor compromisso quando a implementação calcula o seek aproximado e o residual. |

### 3.3 Recomendação

Para a rota normal, manter `-ss` antes de `-i`, mas substituir `-to` por `-t` após a entrada:

```text
-ss {inicio_render} -i {input} -t {duracao} ...
```

Isso torna o tamanho do corte explícito e evita depender de semântica de timestamp absoluto. Para precisão máxima, adicionar um modo configurável, por exemplo:

```text
SHORTS_SEEK_MODE=fast|accurate|hybrid
```

- `fast`: `-ss` antes de `-i`, `-t` depois;
- `accurate`: `-ss` depois de `-i`, `-t` depois;
- `hybrid`: seek pré-input aproximado mais correção pós-input.

A mudança deve ser validada com vídeos H.264/H.265, VFR e diferentes distâncias entre keyframes. Não é seguro afirmar que a ordem atual é simultaneamente a mais rápida e frame-accurate.

## 4. Preset e CRF

### 4.1 Estado atual

Nas duas rotas, por meio de `montar_comando_render()`:

- `libx264`;
- `-preset faster`;
- `-crf 20`;
- `-pix_fmt yuv420p`;
- áudio AAC `160k`.

Na rota web `renderizar_corte()`, os mesmos parâmetros são aplicados pelo helper compartilhado.

### 4.2 `faster` ou `veryfast`

Sim, `faster` ou `veryfast` podem reduzir significativamente o tempo de encode x264. O preset altera principalmente eficiência de compressão e tempo de codificação; não fixa diretamente a qualidade visual quando o CRF permanece igual.

A consequência é:

- mesma faixa de qualidade subjetiva aproximada com CRF igual;
- arquivo potencialmente maior em presets mais rápidos;
- menor eficiência de compressão;
- possível diferença em cenas com movimento, textura fina e ruído;
- o YouTube irá reencodar o arquivo, então pequenas diferenças podem ser irrelevantes após a publicação.

Para Shorts, o perfil CPU aplicado é:

- `faster` como padrão de produção se o tempo for prioridade;
- `veryfast` para preview ou servidores CPU limitados;
- `medium` permanece disponível apenas como variante futura de master/comparação;
- manter `crf 20` como ponto de partida e medir tamanho/qualidade em amostras reais.

Não há base para prometer “nenhuma perda perceptível” sem comparar vídeos representativos. A troca é geralmente aceitável para material 1080x1920 destinado ao YouTube, mas deve ser validada em cenas com rosto, movimento, folhagem, tela de computador e pouca luz.

Uma escolha prática e conservadora seria:

```text
-c:v libx264 -preset faster -crf 20 -pix_fmt yuv420p
```

Se o tamanho do arquivo aumentar demais, testar `crf 21` ou `crf 22`; isso deve ser medido junto com uma inspeção visual, não decidido apenas pelo tamanho.

## 5. Eficiência dos filtros `-vf`

### 5.1 Cadeia atual

O filtro principal é:

```text
crop={W}:{H}:{X}:{Y},scale=1080:1920:flags=bicubic,format=yuv420p
```

O fallback de `core/media_tools.py` é:

```text
crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=bicubic,format=yuv420p
```

### 5.2 Avaliação

A cadeia é simples e correta para uma origem widescreen que precisa virar 9:16. O problema de performance não está em uma cadeia excessivamente longa, mas em três pontos:

1. `bicubic` é o scaler adotado no perfil CPU de produção; `lanczos` fica reservado para comparação de qualidade;
2. o crop é calculado fora do FFmpeg por nove leituras/detecções OpenCV por corte;
3. os filtros permanecem em CPU mesmo quando o encoder poderia usar GPU.

`crop` antes de `scale` é a ordem correta: reduz pixels antes da operação cara de escala. Inverter a ordem desperdiçaria CPU e memória.

### 5.3 Recomendações

- manter `crop,scale`, nessa ordem;
- usar `flags=bicubic` como padrão de produção e deixar `lanczos` como modo de qualidade máxima;
- considerar `flags=bilinear` apenas para preview ou origens já muito comprimidas/pequenas;
- usar dimensões pares e `format=yuv420p` para compatibilidade;
- se houver GPU validada, testar `scale_npp`, `scale_qsv` ou filtro equivalente, medindo o pipeline inteiro;
- manter um fallback centralizado para crop sem rosto;
- cachear as amostras faciais por vídeo para não repetir nove seeks para cada corte.

O crop calculado por média de centros pode enquadrar mal quando o rosto muda de posição entre o início e o fim. Isso é uma questão de qualidade visual, não apenas performance. Um tracking temporal real provavelmente custará mais CPU; só vale adotá-lo se a qualidade do enquadramento justificar o custo.

## 6. Comando FFmpeg otimizado sugerido

Para a rota CPU, com seek rápido, duração explícita, preset mais rápido e escala um pouco mais barata, a sugestão inicial é:

```text
ffmpeg -y \
  -ss {inicio_render:.3f} \
  -i {video_origem} \
  -t {duracao_render:.3f} \
  -vf "crop={crop_width}:{crop_height}:{crop_x}:{crop_y},scale=1080:1920:flags=bicubic,format=yuv420p" \
  -map 0:v:0 \
  -map 0:a? \
  -c:v libx264 \
  -preset faster \
  -crf 20 \
  -pix_fmt yuv420p \
  -c:a aac \
  -b:a 160k \
  -movflags +faststart \
  {caminho_saida}
```

Alterações em relação à rota legada:

- `-to {fim}` vira `-t {duracao}`;
- `-preset medium` vira `faster`;
- `lanczos` vira `bicubic`;
- `format=yuv420p` fica explícito no filtergraph, além de `-pix_fmt`;
- áudio reduzido de `192k` para `160k`, normalmente suficiente para fala em Shorts;
- todos os parâmetros passam a ser comuns às duas rotas.

O `-t` deve ser calculado no Python como:

```python
duracao_render = max(0.001, fim_render - inicio_render)
```

### 6.1 Variante de qualidade máxima

Se a prioridade for qualidade de escala, manter:

```text
scale=1080:1920:flags=lanczos
```

e usar `-preset medium -crf 20`. Essa variante é mais lenta, mas adequada para um master ou comparação de qualidade.

### 6.2 Variante com NVIDIA NVENC

Somente depois de validar o encoder no servidor:

```text
ffmpeg -y \
  -ss {inicio_render:.3f} \
  -i {video_origem} \
  -t {duracao_render:.3f} \
  -vf "crop={crop_width}:{crop_height}:{crop_x}:{crop_y},scale=1080:1920:flags=bicubic,format=yuv420p" \
  -map 0:v:0 \
  -map 0:a? \
  -c:v h264_nvenc \
  -preset p4 \
  -rc vbr \
  -cq 21 \
  -b:v 0 \
  -pix_fmt yuv420p \
  -c:a aac \
  -b:a 160k \
  -movflags +faststart \
  {caminho_saida}
```

`-cq 21` não é equivalente matemático a `-crf 20`; os valores precisam ser calibrados visualmente e por tamanho de arquivo. Para AMD ou Intel, devem ser usados conjuntos de argumentos próprios de `h264_amf` ou `h264_qsv`.

## 7. Adaptação aplicada no Python

### 7.1 Centralizar opções de encode

`obter_opcoes_encoder()` e `montar_comando_render()` foram implementados em `core/media_tools.py`, sem duplicar a montagem nas duas rotas:

```python
def obter_opcoes_encoder(ffmpeg, encoder=None):
  # Prioriza AMF quando anunciado e retorna x264 como fallback.
  ...
```

O seletor implementado:

1. consulta `ffmpeg -encoders`;
2. prioriza `h264_amf` em `auto`;
3. aceita `SHORTS_ENCODER=libx264` ou `SHORTS_ENCODER=h264_amf`;
4. retorna argumentos específicos para o backend;
5. deixa o executor tratar falha real do device e repetir uma vez com `libx264`.

Exemplo de resultado para CPU:

```python
{
    "name": "libx264",
    "args": ["-c:v", "libx264", "-preset", "faster", "-crf", "20", "-pix_fmt", "yuv420p"],
}
```

Exemplo de resultado para NVENC:

```python
{
    "name": "h264_nvenc",
    "args": ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-pix_fmt", "yuv420p"],
}
```

### 7.2 Centralizar montagem do comando

As duas rotas compartilham um helper que recebe:

```python
montar_comando_render(
    ffmpeg,
    origem,
    destino,
    inicio_render,
    duracao_render,
    filtro,
    encoder=None,
)
```

Esse helper:

- usar `-ss` antes de `-i` no modo `fast`;
- usar `-ss` depois de `-i` no modo `accurate`;
- usar `-t`, nunca `-to`, para duração relativa;
- manter `-map 0:v:0` e `-map 0:a?`;
- manter `-movflags +faststart`;
- definir explicitamente o pixel format;
- injeta os parâmetros específicos retornados por `obter_opcoes_encoder()`.

### 7.3 Fallback automático

O fallback implementado acontece em duas fases:

1. **Pré-seleção:** verificar se o encoder aparece em `ffmpeg -encoders`.
2. **Execução:** se o FFmpeg retornar erro reconhecível de AMF/device, registrar o evento e repetir uma única vez com `libx264`.

A repetição deve ocorrer somente para erros reconhecíveis de hardware. Erros de entrada ausente, filtro inválido ou disco cheio não devem ser mascarados como falha de GPU; devem falhar diretamente.

### 7.4 Cache da detecção facial

Como `calcular_corte_com_rosto()` reabre o vídeo e faz nove amostras por corte, uma otimização de alto impacto seria:

- carregar as amostras uma vez por `video_id`/arquivo;
- reaproveitar os frames ou os centros detectados entre cortes;
- invalidar o cache quando o arquivo, resolução ou intervalo de análise mudar.

Isso tende a reduzir mais o tempo total em jobs com muitos cortes do que trocar `medium` por `faster`, especialmente quando os clips são curtos.

## 8. Plano de medição antes do patch

Após a unificação, medir o mesmo conjunto de vídeos e cortes com:

1. CPU `medium`, CRF 20, Lanczos;
2. CPU `faster`, CRF 20, Lanczos;
3. CPU `faster`, CRF 20, Bicubic;
4. encoder GPU disponível, com parâmetros próprios;
5. seek `fast` e `accurate` em pelo menos um vídeo com keyframes espaçados.

Registrar:

- tempo total e tempo por etapa;
- tamanho final;
- resolução, FPS e duração;
- uso de CPU/GPU;
- sucesso do áudio;
- diferença visual em rosto, texto na tela, movimento e baixa luz;
- precisão do primeiro e último frame relevantes.

## Conclusão

Há espaço concreto para otimização, mas a correção estrutural de unificar as duas rotas foi aplicada. O perfil CPU de produção usa `-ss` pré-input com `-t` relativo, `libx264/faster/CRF 20`, `bicubic`, `yuv420p` explícito e AAC `160k`. Ainda falta medir o ganho em vídeos representativos.

GPU está integrada como backend AMF preferencial em `auto`, com fallback para CPU, mas ainda precisa de render real na Radeon para validar driver, qualidade e ganho. Deve ser tratada como backend específico, não como simples substituição de `libx264`; NVIDIA, AMD e Intel usam parâmetros diferentes e podem exigir filtros próprios para acelerar também o crop/scale.

O comando CPU recomendado é:

```text
ffmpeg -y -ss {inicio_render:.3f} -i {video_origem} -t {duracao_render:.3f} -vf "crop={crop_width}:{crop_height}:{crop_x}:{crop_y},scale=1080:1920:flags=bicubic,format=yuv420p" -map 0:v:0 -map 0:a? -c:v libx264 -preset faster -crf 20 -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart {caminho_saida}
```

A adaptação Python deve centralizar a montagem desse comando, selecionar encoder por capacidade real, repetir uma única vez com CPU somente em falhas de hardware e preservar modos configuráveis de seek e qualidade.

## 9. Auditoria de isolamento do pipeline de transcrição

Em 2026-09-24, a rota `transcrever_video_youtube()` foi auditada por risco de colisão entre jobs concorrentes. A implementação anterior gravava o áudio em `./temp_{video_id}.m4a` e localizava o resultado com `os.listdir('.')`. Embora o nome incluísse o vídeo, o arquivo ficava em um namespace global do processo e podia ser reutilizado ou sobrescrito em reprocessamentos simultâneos.

O áudio agora é baixado dentro de um `tempfile.TemporaryDirectory()` exclusivo para cada execução, com remoção automática em sucesso, falha ou cancelamento. A rota não procura mais arquivos temporários no diretório do projeto.

O dicionário global `_WHISPER_RUNTIME`, usado apenas para metadados de progresso e backend, também foi substituído por estado `threading.local()`. O modelo Whisper permanece em cache global como recurso compartilhado; transcrição, segmentos e prompts continuam locais ao job e são persistidos com `video_id` e `perfil_id`.

Essa correção elimina uma classe real de race condition física, mas a auditoria não deve concluir que ela prova, isoladamente, a origem de títulos de outro vídeo. A confirmação exige correlacionar o `job_id`, o hash do arquivo de origem, a transcrição persistida e o prompt enviado ao Ollama no mesmo evento.

## 10. Identidade e cache em downloads do YouTube

O fluxo de download forçado também foi corrigido. Antes, o endpoint criava um `job_id` aleatório e o reutilizava como `video_id` ao inserir o arquivo baixado em `videos_historico`. Isso perdia a identidade da URL original e dificultava auditar ou invalidar o cache por vídeo.

Agora o ID canônico de 11 caracteres é extraído de URLs `watch`, `youtu.be`, `shorts`, `embed` e `live`. Esse ID é usado em `tarefas_jobs`, `videos_historico`, na chave de concorrência e no nome do cache SRT. O SHA-256 completo do arquivo continua sendo calculado por `calcular_hash_arquivo()` e permanece como verificação de conteúdo; ele não é substituído por basename, tamanho ou caminho temporário.

Caches de origem YouTube seguem o formato `cache_transcricao_v=<youtube_id>_<sha256>.srt`. O utilitário `limpar_cache_transcricao.py` lista caches por padrão e exige `--confirm` para removê-los, podendo limitar a limpeza a um perfil ou ID YouTube.

## 11. Correções aplicadas em 2026-10-01

- A sincronização agora tenta a descoberta pública com `yt-dlp` quando a API OAuth falha, incluindo `invalid_grant` por token expirado ou revogado.
- O download forçado aceita o container efetivamente produzido pelo `yt-dlp` (`.mp4`, `.mkv` ou `.webm`), permitindo que o FFmpeg faça a leitura sem depender da extensão MP4.
- A reautorização do perfil Google continua necessária para recuperar métricas oficiais pela Data API; o fallback público sincroniza títulos, IDs e duração, mas não substitui essa credencial.

## 12. Integridade física antes do agendamento

Em 2026-10-02, a listagem de cortes passou a validar `caminho_saida` para todo registro `concluido`. Quando o MP4 está ausente ou vazio, o repositório atualiza o status para `falhou`, grava `Arquivo físico ausente ou corrompido` na coluna `erro` e devolve o registro corrigido ao frontend. As rotas de agendamento individual, em lote e postagem imediata em lote também exigem MP4 existente e não vazio; caso contrário retornam HTTP 400 com `O arquivo de vídeo não foi encontrado no disco` sem criar o job.

## 13. Isolamento stateless das requisições Ollama

Em 2026-10-03, a auditoria do risco de context bleed confirmou que o cutter usa `/api/generate`, não `/api/chat`, e não reutiliza a chave `context` retornada pelo Ollama. O contrato foi reforçado para cada chamada HTTP montar um payload novo, enviar `context: []`, usar temperatura `0.2` e manter `keep_alive: 0`.

O enriquecimento editorial continua criando um prompt independente para cada lote de até cinco candidatos. Nenhum histórico de prompts, resposta ou contexto é armazenado em variável global ou repassado entre lotes. Testes de regressão verificam tanto a identidade independente dos payloads HTTP quanto a separação dos índices presentes em lotes consecutivos.

## 14. Fallback local de títulos sem regras temáticas

Em 2026-10-03, o fallback `_titulo_editorial_local()` deixou de usar um catálogo de regexs associado a temas de vídeos específicos. O título local agora é derivado somente das primeiras palavras significativas da evidência do próprio trecho, após remover marcadores de ruído e vícios de abertura.

Quando a evidência limpa tem menos de três palavras, o fallback usa o intervalo temporal do corte (`Corte do vídeo: [M:SS - M:SS]`) em vez de inventar uma manchete. Essa proteção impede que palavras comuns como `fotos`, `verdade` ou `primeiro` acionem títulos sobre doação de órgãos, motel, caminhada ou qualquer outro assunto externo.

## 15. Accurate seek para integridade dos frames

Em 2026-10-03, a montagem do comando em `montar_comando_render()` deixou de usar seek rápido pré-input. O FFmpeg agora recebe `-i origem -ss inicio -t duracao`, forçando a decodificação até o ponto exato do corte e reduzindo o risco de saída iniciar sem um I-frame válido, especialmente com `h264_amf`.

O comando também inclui `-avoid_negative_ts make_zero` antes de `-map`, normalizando os timestamps das trilhas para o início do arquivo e reduzindo riscos de dessincronização inicial entre áudio e vídeo. A prioridade passa a ser integridade visual e precisão do primeiro frame; benchmark comparativo entre seek rápido e preciso permanece pendente.

## 16. Mensagem de revisão sem candidatos renderizados

Em 2026-10-03, a Central de cortes passou a contar como renderizados somente candidatos com status `concluido` e caminho de saída válido. Quando a IA fica indisponível e o fallback local não produz candidatos, a interface informa que nenhum MP4 foi renderizado na rodada, sem prometer uma lista vazia para revisão humana.

## 17. Modo Force Generate para ciclos sem candidatos novos

Em 2026-10-03, a seleção local passou a insistir quando a deduplicação bloqueia todos os intervalos. Primeiro são tentadas janelas com pontos de entrada deslocados em passos de 15 segundos (`15s`, `30s`, `45s`...) e durações menores, preservando a regra de sobreposição sempre que houver alternativa.

Se a transcrição segmentada válida ainda não produzir um intervalo novo, o último recurso libera o bypass da deduplicação contra ciclos anteriores e entrega o melhor candidato disponível. Assim, a geração não encerra o job com lista vazia apenas porque todo o material restante se parece com cortes já usados.

## 18. Preservação do lote mínimo de cortes

Em 2026-10-03, a deduplicação por sobreposição deixou de ser aplicada entre candidatos locais do mesmo ciclo durante o enriquecimento editorial. Ela continua protegendo contra repetição de intervalos de ciclos anteriores, mas não pode reduzir um conjunto temporalmente variado de nove candidatos para um único corte antes da renderização.

## 19. Progresso de renderização por corte

O worker agora atualiza `tarefas_jobs` antes de cada chamada ao FFmpeg, publicando o estágio `rendering`, a mensagem `Renderizando corte X de N` e um progresso entre 92% e 99%. O encerramento em 100% continua reservado ao término do job, evitando que a interface permaneça em `IA processando resposta` enquanto os arquivos são codificados.

O ETA também deixou de ser herdado da etapa de IA: após cada corte concluído, o worker estima o tempo restante usando a média observada da renderização. No início de um corte o valor é recalculado com a quantidade já concluída, e o frontend passa a receber `elapsed_seconds` do job inteiro e `eta_seconds` atualizados.

## 20. Métrica histórica de duração

`tarefas_jobs.duracao_segundos` agora registra a duração entre `iniciado_em` (ou `criado_em`) e `concluido_em` para estados terminais. A inicialização do banco preenche a coluna para jobs antigos que já possuem timestamps, permitindo calcular médias por tipo de job, vídeo, perfil, status e período sem depender do estado atual da interface.
