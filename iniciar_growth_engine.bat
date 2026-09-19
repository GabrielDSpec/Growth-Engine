@echo off
cd /d "%~dp0"
python -c "from core.app_secrets import carregar_segredos; d=carregar_segredos(); raise SystemExit(0 if len(str(d.get('GOOGLE_CLIENT_ID', ''))) > 10 and len(str(d.get('GOOGLE_CLIENT_SECRET', ''))) > 10 else 1)"
if errorlevel 1 (
	python configurar_segredos.py
	if errorlevel 1 pause & exit /b 1
)
python iniciar_servidor.py
pause