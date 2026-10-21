# Fluxo atual de geração de títulos e descrições

**Projeto:** Growth Engine  
**Data da análise:** 2026-09-23  
**Escopo:** títulos editoriais e descrições de publicação dos cortes/Shorts.

Este relatório descreve o comportamento codificado atualmente. `transcriber.py` prepara e persiste a transcrição, mas não é o responsável por pedir títulos ou descrições ao LLM. `tasks.py` também não contém a lógica editorial principal; a orquestração relevante está em `core/web_server.py`, `core/cutter.py`, `core/metadata_ai.py` e `core/publisher.py`.

## 1. Visão geral do fluxo

Há três momentos diferentes:

1. **Curadoria do corte:** a transcrição segmentada é enviada ao pipeline de cortes. A IA pode escolher os intervalos e gerar título, descrição preliminar, hashtags e campos editoriais.
2. **Enriquecimento/refinamento:** candidatos locais podem ser enriquecidos por uma chamada editorial e títulos podem passar por um refinador separado.
3. **Metadados finais do YouTube:** antes de um corte aparecer como pronto ou ser publicado, `_metadata_for_cut()` monta um contexto completo e chama a IA de metadados. Essa chamada gera o título/descrição finais usados pelo publisher.

Existe ainda um quarto caminho independente: o usuário pode editar título e descrição manualmente pela Central.

```text
transcrição
    |
    +--> _run_cut_job() / _process_local_media_job()
            |
            +--> gerar_cortes_com_retry()
                    |
                    +--> _montar_prompt()                 [curadoria principal]
                    +--> _enriquecer_candidatos_com_ia() [título/descrição preliminares]
                    +--> refinar_titulos_com_ia()         [refino de títulos]
                    +--> validar_cortes()
                            |
                            +--> create_cut()
                            +--> _save_publication_description()
                                    |
                                    +--> _metadata_for_cut()
                                            |
                                            +--> gerar_metadados_blindados()
```

## 2. Gatilhos

### 2.1 Geração inicial de cortes e títulos

O gatilho principal é `gerar_cortes_com_retry()` em [core/cutter.py](../../core/cutter.py). Ele é chamado por:

- `_run_cut_job()` em [core/web_server.py](../../core/web_server.py), quando a Central gera cortes a partir de um vídeo que já tem transcrição segmentada.
- `_process_local_media_job()` em [core/web_server.py](../../core/web_server.py), depois que um upload local foi transcrito.

O primeiro contexto de IA é construído em `_montar_prompt()`.

### 2.2 Enriquecimento de título e descrição

Quando candidatos locais são enriquecidos, o gatilho é `_enriquecer_candidatos_com_ia()` em [core/cutter.py](../../core/cutter.py). Essa chamada pede simultaneamente `titulo`, `descricao`, `hashtags`, score e os campos editoriais do candidato.

O refinamento posterior de títulos é feito por `refinar_titulos_com_ia()` no mesmo módulo. Ele pede somente novos títulos; não gera a descrição final.

### 2.3 Descrição final para publicação

O gatilho da descrição editorial final é `_save_publication_description()` em [core/web_server.py](../../core/web_server.py). Ele chama `_metadata_for_cut()` em [core/publisher.py](../../core/publisher.py), que chama `gerar_metadados_blindados()` em [core/metadata_ai.py](../../core/metadata_ai.py).

Há dois usos principais:

- Durante o caminho de publicação/agendamento, antes do upload para o YouTube.
- Na rota `POST /api/cuts/generate-descriptions`, usada pela Central para preencher descrições ausentes antes da revisão.

### 2.4 Edição manual

A rota `POST /api/cuts/metadata`, em [core/web_server.py](../../core/web_server.py), recebe o título e a descrição enviados pelo modal da Central. O frontend usa `saveCutMetadata()` em [frontend/app.js](../../frontend/app.js).

Esse caminho não chama o LLM de metadados. O título passa pela normalização/refinamento local e depois é persistido.

## 3. Inputs enviados para a IA

## 3.1 Curadoria principal: `_montar_prompt()`

A curadoria principal recebe:

- `transcricao_texto`: a transcrição inteira, formatada por segmento como:

  ```text
  [índice] início-fim: texto
  ```

- `duracao_total_seg`: duração estimada do material.
- `segmentos`: lista estruturada com `indice`, `inicio`, `fim` e `texto`.
- `titulo_original`: título original do vídeo, quando disponível.
- `tentativa`: número da rodada de curadoria.
- `cortes_atuais`: candidatos já aceitos nas rodadas anteriores.
- `rejeicoes`: motivos de rejeição das rodadas anteriores.
- `duracao_minima` e `duracao_maxima`: faixa configurável do corte.

Portanto, nesse primeiro momento a IA recebe **a transcrição inteira segmentada**, e não somente o trecho de um corte já definido.

A resposta da curadoria contém candidatos com intervalo, título, gancho, promessa, virada, conclusão, montagem e pontuações.

## 3.2 Enriquecimento editorial: `_enriquecer_candidatos_com_ia()`

Essa chamada recebe apenas os candidatos locais, não a transcrição inteira original. Para cada candidato, o código monta:

```json
{
  "indice": 0,
  "inicio": 10.0,
  "fim": 45.0,
  "texto": "gancho + promessa + virada + conclusao"
}
```

O `texto` é truncado em 700 caracteres. Também é enviado `titulo_original` do vídeo.

Assim, o prompt de enriquecimento recebe o **contexto semântico resumido do trecho**, formado por `gancho`, `promessa`, `virada` e `conclusao`, e não a transcrição completa.

## 3.3 Refinamento de títulos: `refinar_titulos_com_ia()`

Essa chamada recebe, para cada corte:

```json
{
  "indice": 0,
  "titulo_atual": "...",
  "gancho": "...",
  "promessa": "...",
  "virada": "...",
  "conclusao": "..."
}
```

Também recebe `titulo_original` do vídeo. Não recebe a transcrição inteira nem os timestamps.

## 3.4 Metadados finais: `_metadata_for_cut()`

A chamada final para publicação monta este contexto textual:

```text
Título original: <video_titulo>
Título do corte: <titulo>
Transcrição literal do trecho (use para conferir fidelidade, não copie): <transcript>
Descrição manual para revisar (não copie se estiver inadequada): <descricao_publicacao>
Gancho: <gancho>
Promessa: <promessa>
Virada: <virada>
Conclusão: <conclusao>
```

A transcrição do trecho é lida da tabela `videos_historico`, usando `video_id` e `perfil_id`, e é reconstruída a partir de `transcricao_segmentos` quando possível.

Portanto, a IA final recebe:

- título original do vídeo;
- título atual do corte;
- transcrição literal do trecho;
- descrição manual existente, se houver;
- gancho;
- promessa;
- virada;
- conclusão.

Ela recebe o trecho, não a transcrição inteira do vídeo, salvo quando o trecho persistido representar todo o vídeo.

## 4. Prompts codificados

## 4.1 Prompt principal de curadoria

Template em `_montar_prompt()`:

```text
Você é Curador Sênior de Atenção e Diretor de Cortes (Teoria da Vaca Roxa).
Analise exclusivamente o texto abaixo. Não invente falas, eventos, contexto ou timestamps.
Gere candidatos suficientes para que, após a validação, existam pelo menos {MIN_CORTES_PADRAO} cortes independentes.
Nesta rodada, retorne entre {MIN_CORTES_PADRAO} e {MAX_CORTES_SOLICITADOS} candidatos quando houver material.
Nunca invente falas, timestamps ou segmentos apenas para atingir a quantidade.
Os cortes já aceitos nesta execução: {len(cortes_atuais)}. Esta é a rodada {tentativa} de {MAX_TENTATIVAS_QWEN}.
Escolha somente segmentos existentes na transcrição numerada. Retorne segmento_inicio e segmento_fim
como índices inteiros inclusivos copiados exatamente da numeração; não invente índices nem timestamps.
O trecho deve ser uma sequência contínua de segmentos e a diferença entre o primeiro início e o último fim
precisa ficar entre {duracao_minima} e {duracao_maxima} segundos. Nunca selecione apenas um segmento curto
para depois tentar completar a duração com texto inventado.
Os limites precisam preservar frases completas: comece no início de uma ideia, não no meio de uma frase,
e termine somente depois de uma frase concluída (pontuação final ou encerramento inequívoco da fala).
Nunca corte palavra, oração ou contexto no meio. Se o Whisper dividiu uma frase em vários segmentos,
inclua todos os segmentos necessários para fechá-la, respeitando a duração máxima.
Para cada corte, crie um título editorial em pt-BR com 35 a 55 caracteres, pronto para ser usado no YouTube.
O título deve ser uma manchete natural, específica e engajante: use uma palavra-chave ou entidade realmente
presente no trecho, deixe claro o conflito, descoberta ou resultado e crie curiosidade honesta. Não copie uma
frase inteira da transcrição, não use reticências, não entregue um fragmento sem verbo e não comece com
"Trecho", "Corte" ou "Parte". Não use #shorts, emojis, promessa exagerada ou afirmações ausentes.
Aprove um corte somente se ele tiver uma única ideia, conflito ou contraste claro, começo autossuficiente,
desenvolvimento e conclusão. O início deve conter o gancho, sem saudação ou contexto dependente de outro vídeo.
Quando um destaque forte aparecer mais tarde no trecho, você pode sinalizar a montagem
"gancho_contexto_retorno": use uma frase literal do destaque como gancho inicial, depois o contexto,
e retorne ao momento do destaque. Isso é uma oportunidade editorial, não uma licença para inventar
texto ou timestamps; todos os elementos precisam existir na transcrição.
Rejeite cortes que sejam apenas introdução, explicação genérica, anúncio, chamada para curso, cupom ou autopromoção.
Não corte uma frase no meio. Cada corte deve ter entre {duracao_minima} e {duracao_maxima} segundos, conforme a faixa escolhida pelo usuário.
Dê seis subnotas independentes de 0 a 100. Elas medem potencial editorial observável, não desempenho garantido:
distintividade (25%): contraste, novidade ou ângulo memorável;
gancho (20%): força e clareza do início;
clareza_promessa (15%): benefício compreensível sem contexto externo;
autossuficiencia (15%): ideia completa no próprio corte;
compartilhabilidade (15%): motivo concreto para comentar ou enviar a alguém;
evidencia (10%): título, gancho e conclusão sustentados literalmente pelo trecho.
Não use retenção, CTR ou alcance como se fossem medidos; esses dados só existem após publicação.
Título original do vídeo: {titulo_original or "não informado"}
Antes de propor cortes, confira o título original contra a transcrição. Identifique erros ortográficos,
omes próprios, entidades ou afirmações do título que não correspondam ao contexto. Corrija somente o que
puder ser confirmado pela transcrição e mantenha o sentido factual. Para cada corte, o título editorial deve
ser coerente com o vídeo original e não pode contradizer seu tema.
Analise a transcrição segmentada ({duracao_total_seg:.1f}s):
{transcricao_texto}
Retorne EXCLUSIVAMENTE um objeto JSON puro, sem markdown, sem comentários e sem texto antes ou depois.
A chave cortes deve sempre ser uma lista; se houver material, nunca a deixe vazia.
```

O schema solicitado ao final é:

```json
{
  "cortes": [{
    "titulo": "título factual e específico",
    "segmento_inicio": 0,
    "segmento_fim": 0,
    "gancho": "frase ou ideia literal do início do trecho",
    "montagem": "continua ou gancho_contexto_retorno",
    "gancho_inicio": "frase literal usada como abertura, se houver",
    "destaque": "frase literal do momento de maior destaque",
    "promessa": "o que o espectador entenderá",
    "virada": "contraste ou descoberta presente no trecho",
    "conclusao": "como a ideia se fecha no próprio trecho",
    "autossuficiente": true,
    "promocional": false,
    "pontuacoes": {
      "distintividade": 0,
      "gancho": 0,
      "clareza_promessa": 0,
      "autossuficiencia": 0,
      "compartilhabilidade": 0,
      "evidencia": 0
    }
  }]
}
```

## 4.2 Prompt de enriquecimento editorial

Template em `_enriquecer_candidatos_com_ia()`:

```text
Você é um editor de Shorts guiado pela Teoria da Vaca Roxa.
Analise somente os candidatos abaixo e devolva JSON puro. Não altere indice, inicio ou fim.
Escolha os melhores candidatos reais, sem inventar fatos. Gere titulo (35-55 caracteres),
descricao (1-2 frases factuais), hashtags (2-4), score_vaca_roxa (0-100), angulo_diferente,
gancho, promessa, virada, conclusao e pontuacoes.
Preserve nomes, marcas e números da transcrição. Não use clickbait, emojis ou #shorts.
O vídeo original é: {titulo_original or "não informado"}
Candidatos: {json.dumps(contexto, ensure_ascii=False)}
Formato: {"cortes":[{"indice":0,"titulo":"...","descricao":"...","hashtags":[],"score_vaca_roxa":0,"angulo_diferente":"...","gancho":"...","promessa":"...","virada":"...","conclusao":"...","pontuacoes":{}}]}
```

Esse prompt pede explicitamente **título e descrição preliminar**. A descrição recebida é armazenada em memória como `descricao_publicacao` no candidato e, em alguns caminhos, é persistida por `update_cut_metadata()`.

## 4.3 Prompt de refinamento de títulos

Template em `refinar_titulos_com_ia()`:

```text
Você é editor de títulos para YouTube Shorts. Reescreva os títulos dos cortes abaixo.
O título original do vídeo é: {titulo_original or "não informado"}.
Use somente fatos presentes nos campos fornecidos e confirme coerência com o título original. Corrija
ortografia, nomes próprios e entidades do título somente quando a transcrição sustentar a correção. Cada título deve ser uma manchete natural em pt-BR,
específica, completa e curiosa, com 35 a 55 caracteres. Use verbo ou conflito claro, não copie uma frase
inteira, não comece por Trecho, Corte ou Parte, não use emojis, #shorts, reticências ou clickbait.
Retorne somente JSON no formato {"titulos":[{"indice":0,"titulo":"..."}]}.
{json.dumps(itens, ensure_ascii=False)}
```

O campo de entrada `itens` contém `titulo_atual`, `gancho`, `promessa`, `virada` e `conclusao` para cada corte.

## 4.4 Prompt final de metadados do YouTube

Constante `PROMPT_VACA_ROXA_BIGODE` em [core/metadata_ai.py](../../core/metadata_ai.py):

```text
Você é o estrategista sênior de growth do canal @aquelecaradebigode, operando sob a Teoria da Vaca Roxa (Seth Godin).
O mercado está entupido de "vacas comuns" (conteúdo previsível). O corte só vence se for UMA VACA ROXA: algo que faça o espectador fechar o short e pensar "caramba, preciso mostrar isso para alguém" ou gerar um take-double/curiosidade visceral.

ARQUÉTIPOS VALIDADOS DO CANAL:
1. TECH/PERRENGUE: Risco real, erro caro ou descoberta técnica tensa (ex: "Queimei minha nova RX 9060 XT?").
2. MICRO-AVENTURA: Deslocamento / rota incomum com atrito real (ex: "Fui de SP pra Bertioga de trem e Uber").
3. NATUREZA/DESAFIO: Força bruta vs obstáculo hostil (ex: "Drone vs Vento Forte").
4. TURISMO/SAZONAL: Impacto visual bruto em evento/local (ex: "Chuva de Pétalas na ExpoFlora 2025").

CRITÉRIOS DE FILTRAGEM (VACA ROXA):
- O tema é apenas informativo? REJEITE ouforce o ângulo de conflito/descoberta.
- Promessa clara: O espectador entende o ganho/transformação em 1 segundo? [cite: 1]
- Substância: O corte suporta o título sem clickbait mentiroso (mentir é crime/lixo; chamar atenção para algo real é estratégia) [cite: 1].

REGRAS DE OURO PARA O TÍTULO E A DESCRIÇÃO:
- Máximo de 55 caracteres.
- Proibido clichê genérico de IA. Use tensão, conflito ou constatação seca.
- Linguagem de quem fala na roda de amigos, não de release corporativo.
- Preserve nomes próprios, marcas, eventos e números exatamente como aparecem no contexto; não invente grafias.
- Nunca responda "N/A", "NA", "não informado" ou texto vazio.
- Antes de escrever, revise a descrição contra a transcrição literal do trecho.
- Se houver uma descrição manual no contexto, revise-a obrigatoriamente; corrija concordância, fidelidade e clareza sem mudar o teor.
- A descrição deve ser uma paráfrase editorial engajante do que realmente acontece no corte, nunca uma cópia, legenda ou transcrição da fala.
- Use somente fatos, nomes, números e conclusões presentes no contexto. Não invente causas, resultados, promessas, opiniões, dados ou contexto externo.
- A descrição deve ter 1 ou 2 frases curtas, com palavras-chave naturais do assunto e sem clickbait que altere o teor.
- Gere de 2 a 4 hashtags relevantes no campo "hashtags". Elas devem estar diretamente relacionadas ao conteúdo e não podem ser genéricas ou inventadas.

TRANSCRIÇÃO / CONTEXTO DO CORTE:
{contexto}

Analise internamente se o corte é uma Vaca Roxa. Se for, gere o JSON puro abaixo (sem markdown fora):
{
  "vaca_roxa": true,
  "indice_remarkabilidade": "alta/media",
  "pilar": "NOME_DO_PILAR",
  "titulo": "...",
  "descricao": "Descrição curta, engajante e fiel ao conteúdo, em paráfrase e sem copiar a fala.",
  "hashtags": ["#temaDoCorte", "#assuntoRelacionado"],
  "angulo_diferente": "ESCREVA AQUI O MOTIVO REAL DESTE CORTE SER REMARKÁVEL",
  "tags": ["tag1", "tag2", "tag3"]
}
```

O template é preenchido com o texto `contexto` descrito na seção 3.4.

## 5. Modelo, endpoint e formato da chamada

### Curadoria e refinamento

As chamadas de corte usam `core.cutter._gerar_resposta_ollama_http()` ou um worker subprocesso quando há callback de cancelamento:

- Endpoint: `http://localhost:11434/api/generate`
- Modelo: `GROWTH_ENGINE_CUT_MODEL`, padrão `qwen2.5:14b`.
- Streaming HTTP na chamada normal.
- `format: "json"`.
- `temperature: 0.1`.
- `num_ctx: 2048`.
- `num_predict: 1400`.
- Timeout padrão: `GROWTH_ENGINE_OLLAMA_TIMEOUT_SECONDS`, padrão 60 segundos.

### Metadados finais

`gerar_metadados_blindados()` em [core/metadata_ai.py](../../core/metadata_ai.py) usa `urllib.request`:

```json
{
  "model": "qwen2.5:14b",
  "prompt": "<PROMPT_VACA_ROXA_BIGODE preenchido>",
  "stream": false,
  "format": "json"
}
```

O timeout HTTP é 60 segundos. Se qualquer exceção ocorrer, a função imprime o erro e retorna `{}`.

## 6. Tratamento e validação da resposta

### 6.1 Resposta de curadoria

A resposta é limpa de cercas Markdown e convertida com `json.loads()`. Depois:

- os campos de segmento são preservados do candidato original;
- o título é normalizado;
- ruído de áudio e títulos genéricos são rejeitados;
- o título precisa ter evidência no texto do trecho;
- `validar_cortes()` verifica duração, índices, score, campos editoriais, autossuficiência e ausência de conteúdo promocional;
- candidatos inválidos podem seguir para revisão humana ou fallback local.

Títulos genéricos como `A gente`, `Gente`, `Pessoal`, `Bom pessoal`, `Bom galera` e `Então` são considerados insuficientes. O fallback local tenta construir uma manchete a partir de gancho, promessa, virada e conclusão.

### 6.2 Resposta de enriquecimento

`_enriquecer_candidatos_com_ia()` exige status HTTP 200, faz `json.loads()` do campo `response` e percorre `payload["cortes"]`. Os valores de `descricao` e `hashtags` entram no dicionário do candidato.

### 6.3 Resposta de refinamento

`refinar_titulos_com_ia()` faz parse de `payload["titulos"]`, valida `indice`, normaliza o texto e aplica o refinamento local. Se a IA falhar, o código mantém/finaliza o título local; títulos genéricos também são substituídos por um fallback semântico.

### 6.4 Resposta final de metadados

`gerar_metadados_blindados()` lê o campo textual `response` retornado pelo Ollama e aplica `json.loads()` novamente. Se houver erro, retorna `{}`.

`_metadata_for_cut()` então:

1. seleciona `metadata["titulo"]`, com fallback para o título já persistido;
2. restaura entidades usando o título original quando há correspondência;
3. rejeita título sem evidência na transcrição/título original e aplica fallbacks locais;
4. seleciona `descricao`, `descricao_short` ou descrição manual persistida;
5. remove frases repetidas;
6. esvazia a descrição se ela for igual à transcrição;
7. adiciona o link original somente se existir uma descrição válida;
8. normaliza hashtags e tags;
9. retorna `(titulo, descricao, tags)`.

Se a descrição final ficar vazia, o corte não pode ser publicado. O publisher lança `RuntimeError("Resumo editorial não disponível; o Short não pode ser publicado.")`.

## 7. Persistência no SQLite

### 7.1 Tabela principal: `cortes_gerados`

A tabela é criada em `core/database.py`. Os campos relevantes são:

| Campo | Origem/finalidade |
|---|---|
| `id` | Identificador do corte |
| `job_id` | Job que gerou o corte |
| `perfil_id` | Isolamento do perfil/tenant |
| `video_id` | Vídeo fonte |
| `segmento_inicio`, `segmento_fim` | Índices dos segmentos escolhidos |
| `inicio_segundos`, `fim_segundos` | Intervalo temporal |
| `titulo` | Título editorial persistido |
| `gancho` | Gancho do trecho |
| `promessa` | Promessa editorial |
| `virada` | Contraste/descoberta |
| `conclusao` | Fechamento do trecho |
| `descricao_publicacao` | Descrição editorial/manual enviada ao YouTube |
| `score_vaca_roxa` | Score agregado |
| `pontuacoes_json` | Subnotas em JSON |
| `montagem_json` | Intervalos de montagem em JSON |
| `status` | Estado do corte |
| `caminho_saida` | MP4 renderizado |
| `video_titulo` | Título original do vídeo fonte |
| `nome_rodada`, `numero_rodada` | Ciclo/rodada de geração |
| `horario_recomendado_json` | Recomendação de período/dias para agendamento |
| `atualizado_em` | Auditoria da última alteração |

### 7.2 Criação do corte

`create_cut()` em [core/cuts_repository.py](../../core/cuts_repository.py) insere o candidato em `cortes_gerados`. Ele persiste título, gancho, promessa, virada, conclusão, score e intervalos. `descricao_publicacao` é uma coluna adicionada por migração e começa com `''` quando não foi preenchida.

### 7.3 Persistência da descrição final

`update_cut_metadata()` executa:

```sql
UPDATE cortes_gerados
SET titulo = ?, descricao_publicacao = ?, atualizado_em = CURRENT_TIMESTAMP
WHERE id = ? AND perfil_id = ?
```

Esse método é usado por:

- `_save_publication_description()`;
- a rota manual `POST /api/cuts/metadata`;
- caminhos de candidato que já possuem `descricao_publicacao` preliminar.

O filtro por `id` e `perfil_id` é a barreira de isolamento do tenant.

### 7.4 Jobs e diagnósticos

O andamento da geração é persistido em `tarefas_jobs`, nos campos `status`, `progresso`, `mensagem`, `erro` e `resultado_json`. O payload de candidatos pode aparecer em `resultado_json`, mas a fonte definitiva do título/descrição do corte é `cortes_gerados`.

A transcrição usada para conferência é persistida em `videos_historico`, principalmente em:

- `transcricao`;
- `transcricao_segmentos`;
- `titulo`;
- `arquivo_origem`;
- `perfil_id`.

## 8. Edição manual pela Central

O frontend envia:

```json
{
  "cut_id": 123,
  "title": "Título editado",
  "description": "Descrição editada"
}
```

A rota valida a existência do corte no `perfil_id` ativo, limita o título a 100 caracteres, normaliza/refina o texto e chama `update_cut_metadata()`.

Depois da resposta, `frontend/app.js` atualiza as cópias do corte mantidas em `persistedCuts` e `cutSuggestions`, fecha o modal e renderiza novamente os cards.

## 9. Diferenças e riscos observados

1. **Há mais de uma geração de título.** O título pode nascer na curadoria principal, ser alterado no enriquecimento, ser refinado por outro prompt e ser novamente escolhido/validado em `_metadata_for_cut()`.
2. **Há mais de uma geração de descrição.** A descrição preliminar do enriquecimento e a descrição final do publisher não são necessariamente a mesma resposta.
3. **`transcriber.py` não gera metadados.** Ele fornece a evidência textual e os segmentos; a semântica editorial fica em `cutter.py`/`publisher.py`.
4. **Falha da IA final retorna `{}`.** O sistema continua usando fallbacks locais para título, mas não aceita descrição vazia para publicação.
5. **A descrição manual pode ser revisada pela IA final.** O prompt diz para revisar a descrição manual; portanto, ela não é necessariamente enviada literalmente ao YouTube.
6. **O prompt final exige no máximo 55 caracteres para título, mas o código de alguns fallbacks aceita até 100 caracteres no fluxo manual.** O limite de 100 é a validação da rota; a recomendação editorial do LLM é mais curta.
7. **A recomendação de horário é outro prompt.** `PROMPT_HORARIO_CORTE` retorna `periodo`, `dias_preferidos`, `confianca` e `justificativa`; não gera título nem descrição.
8. **O texto do áudio não deve ser usado como descrição.** O publisher limpa a descrição se ela for igual à transcrição e bloqueia a publicação quando não há resumo editorial válido.

## 10. Resposta direta às cinco perguntas

1. **Gatilho:** `gerar_cortes_com_retry()` inicia títulos de candidatos; `_save_publication_description()` -> `_metadata_for_cut()` -> `gerar_metadados_blindados()` inicia a descrição final; `POST /api/cuts/metadata` inicia a edição manual.
2. **Inputs:** a curadoria principal recebe a transcrição inteira segmentada; o enriquecimento recebe o contexto resumido de cada candidato; o refinador recebe título atual e campos editoriais; a chamada final recebe título original, título do corte, transcrição do trecho, descrição manual, gancho, promessa, virada e conclusão.
3. **Prompt:** os quatro templates literais estão documentados nas seções 4.1 a 4.4 e correspondem a `_montar_prompt()`, `_enriquecer_candidatos_com_ia()`, `refinar_titulos_com_ia()` e `PROMPT_VACA_ROXA_BIGODE`.
4. **Tratamento:** todas as respostas esperadas são JSON; o código faz parse do campo `response`, valida índices/campos/evidência, aplica normalização e fallback local, remove descrições que copiam a transcrição e bloqueia publicação sem resumo.
5. **Persistência:** o resultado editorial final fica em `cortes_gerados.titulo` e `cortes_gerados.descricao_publicacao`, protegido por `id` e `perfil_id`; a evidência vem de `videos_historico.transcricao`/`transcricao_segmentos`; diagnósticos do job ficam em `tarefas_jobs`.
