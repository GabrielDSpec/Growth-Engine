# F6. Painel Admin e manutenção do sistema

**Status:** em andamento
**Área:** plataforma
**Prioridade:** alta

## Objetivo

Disponibilizar manutenção operacional protegida por perfil administrador, sem expor ações destrutivas para perfis comuns.

## Entrega inicial

- A tabela `perfis` possui `is_admin INTEGER NOT NULL DEFAULT 0`.
- O perfil principal (`1`, e o perfil legado `915361` quando existente) recebe `is_admin=1` pela migração idempotente.
- `GET /api/me` informa o perfil atual e sua autorização.
- Rotas `POST /api/admin/clear-cache`, `/reset-jobs` e `/vacuum-db` exigem `is_admin=1`.
- O frontend exibe o Painel Admin somente após validar `/api/me`.
- Cada operação exige confirmação e apresenta resultado em toast.
- Ao abrir o `painel_controle.py`, o Servidor Web é iniciado automaticamente quando necessário; a UI só confirma sucesso após responder em `127.0.0.1:4174`.
- A aba Serviços oferece controles independentes `Ligar`, `Desligar` e `Reiniciar` para o Servidor Web, além de `Ligar` e `Desligar` para o Ollama, refletindo o estado detectado no polling.
- O executável usa um mutex nomeado no Windows para impedir múltiplas instâncias visíveis do painel; o par pai/filho observado no PyInstaller one-file é apenas o bootstrap do executável.
- No executável frozen, o launcher do Servidor Web usa o Python da `.venv` ao lado do painel, com fallback para `python` no `PATH`, evitando relançar o próprio GUI como processo filho.
- O painel nativo também oferece `Renovar permissões YouTube`, abrindo `/oauth/google/start?perfil_id=<id>&reauthorize=1` quando o servidor web está online; o executável foi reconstruído e sincronizado para a raiz do projeto.
- O seletor de vídeo relacionado da postagem imediata envia explicitamente o perfil ativo ao endpoint, garantindo que o menu seja aberto mesmo quando o wrapper global de `fetch` não estiver disponível.
- A Central de cortes mantém todos os cortes persistidos renderizados; a deduplicação fica restrita ao ID e não descarta cortes válidos apenas porque seus intervalos temporais se sobrepõem.
- Minimizar ou fechar a janela oculta o painel na bandeja do Windows; o menu do ícone oferece `Abrir painel` e `Sair`, sendo a saída explícita responsável por parar o servidor filho.
- O perfil legado `1` é identificado como `Aquele Cara de Bigode`; o perfil `915361` permanece separado para o Pod Ipiranga.
- O botão de reinício bloqueia reinício durante jobs de publicação ativos, evitando interromper a fila; o vínculo relacionado usa seletores alternativos para o campo de busca do Studio.
- A busca do vídeo relacionado cobre diálogos alternativos do Studio, diálogos ARIA, campo visível genérico e botão de pesquisa inicialmente recolhido.

## Limites e próximos passos

A limpeza remove temporários conhecidos e caches de transcrição sem vídeo correspondente nas pastas de mídia dos perfis ativos. A evolução do RBAC multiusuário continua no defeito `DEF-RBAC`; este painel não substitui autorização por função granular.
