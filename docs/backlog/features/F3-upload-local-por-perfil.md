# F3 - Upload Local por Perfil

**Status:** concluído
**Progresso:** 100%

- MP4 bruto em `media/<perfil_id>/uploads/`.
- Downloads em `media/<perfil_id>/downloads/`.
- Cortes em `media/<perfil_id>/shorts/`.
- `X-Profile-Id` obrigatório no endpoint.
- Chave do TaskRunner: `perfil:<perfil_id>:upload:<job_id>`.
- Material, transcrição, evidência e cortes persistidos no tenant.

Validação: `node --check`, `py_compile`, 28 testes e smoke HTTP multipart.
