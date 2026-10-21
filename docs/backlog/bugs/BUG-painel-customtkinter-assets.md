# Assets do CustomTkinter ausentes no executável

## Sintoma

O Painel de Controle empacotado encerrava na inicialização com `FileNotFoundError` para `customtkinter/assets/themes/blue.json` dentro do diretório temporário `_MEI` do PyInstaller.

## Causa e correção

O `.spec` dependia apenas da descoberta automática de dados. Os temas agora são incluídos explicitamente com `collect_data_files('customtkinter', includes=['assets/themes/*.json'])`.

## Validação

- Build limpo com PyInstaller 6.22.3 concluído.
- `blue.json` presente nos artefatos de análise e pacote.
- Executável gerado em `dist/GrowthEnginePainel.exe` e iniciado sem o traceback do tema.