import os
import sys
import threading
import time
import webbrowser

from core.app_secrets import SECRETS_PATH, carregar_segredos_no_ambiente


def main():
    carregar_segredos_no_ambiente()
    if not SECRETS_PATH.exists():
        raise SystemExit("Arquivo config.secrets não encontrado. Execute configurar_segredos.py uma vez.")

    from core.job_repository import list_active_jobs
    active_jobs = list_active_jobs()
    if active_jobs:
        print("ATENÇÃO: existem tarefas pesadas em execução ou na fila:")
        for job in active_jobs:
            print(f"- perfil={job['perfil_id']} tipo={job['tipo']} progresso={job['progresso']}% job={job['job_id']}")
        if not sys.stdin.isatty():
            raise SystemExit("Servidor não iniciado para evitar interromper tarefas ativas.")
        confirmation = input("Digite CONTINUAR para reiniciar e interromper essas tarefas: ").strip()
        if confirmation != "CONTINUAR":
            raise SystemExit("Inicialização cancelada; tarefas preservadas.")

    from core.web_server import start_server

    threading.Thread(
        target=lambda: (time.sleep(1), webbrowser.open("http://127.0.0.1:4174")),
        daemon=True,
    ).start()
    start_server()


if __name__ == "__main__":
    main()