# F4 - Curadoria manual e cache de candidatos de cortes

## Atualização

- Candidatos estruturalmente válidos agora são renderizados mesmo quando a rodada termina em `needs_review`.
- A Central exibe score, intervalo, evidência e link do MP4 antes da seleção humana.
- A seleção continua separada da aceitação automática: renderizar previamente não marca o candidato como escolhido.

**Status:** em implementacao
**Progresso:** 60%
**Prioridade:** critica
**Area:** producao

## Objetivo

Quando a analise nao atingir nove cortes recomendados, o sistema deve preservar o maximo de candidatos reais encontrados e permitir que o usuario escolha quais serao renderizados. Nenhum candidato pode inventar fala, timestamp ou evidencia.

## Escopo

- Persistir candidatos estruturalmente validos, mesmo quando o score editorial ficar abaixo do limiar recomendado.
- Persistir cada candidato com perfil, video original, titulo do video, job, rodada, score total e subnotas.
- Persistir payload bruto e diagnostico de cada rodada para auditoria e analise futura.
- Exibir candidatos ordenados por score, com alerta para notas baixas ou dados incompletos.
- Permitir selecao individual ou em lote.
- Renderizar somente candidatos selecionados explicitamente.
- Manter candidatos e rodadas consultaveis sem executar novamente a Qwen.

## Estados

`candidato`, `selecionado`, `renderizando`, `concluido`, `rejeitado`, `falhou` e `cancelado`.

## Identidade da rodada

Cada rodada deve manter `perfil_id`, `video_id`, `video_titulo`, `job_id`, `numero_rodada`, `nome_rodada`, `modelo`, `prompt_versao` e `transcricao_hash`. O nome exibido deve ser estavel e legivel, por exemplo `2026-09-19_video-curadoria-01`.

## Aceite

- Candidatos validos estruturalmente com score abaixo de 70 aparecem na tela para revisao.
- A tela mostra score total, subnotas, intervalo, titulo, gancho e rodada.
- Nenhum candidato e renderizado sem selecao explicita.
- A selecao respeita `perfil_id` e nao permite escolher candidato de outro tenant.
- Uma falha de FFmpeg altera apenas o candidato afetado e preserva os demais.
- Uma analise anterior pode ser consultada pelo video original e pelo nome da rodada.
- O servidor ativo nao precisa ser reiniciado durante a gravacao de um video; a nova versao entra no proximo ciclo.

## Estado atual

- [x] Candidatos estruturalmente validos abaixo do score recomendado sao preservados.
- [x] Candidatos de `needs_review` sao persistidos com video original e rodada.
- [x] API de selecao e job de renderizacao sob aprovacao implementados.
- [x] Interface exibe score, rodada, checkbox e acao de renderizacao.
- [ ] Persistir payload bruto completo de cada resposta da Qwen.
- [ ] Persistir motivo individual para cada rejeicao estrutural.
- [ ] Exibir historico completo de rodadas por video.