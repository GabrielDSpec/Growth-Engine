"""Torre de Controle local do Growth Engine.

Dependências: customtkinter, psutil, requests, pystray e Pillow.
Execute com o mesmo interpretador do projeto para manter o acesso ao SQLite.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import ctypes
import webbrowser
from pathlib import Path
from tkinter import END, StringVar, Tk, messagebox, ttk

import customtkinter as ctk
import psutil
import pystray
import requests
from PIL import Image, ImageDraw


ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DB_PATH = ROOT / "core" / "canal_inteligencia.db"
SERVER_URL = "http://127.0.0.1:4174"
OLLAMA_URL = "http://127.0.0.1:11434"
PROFILE_ID = int(os.getenv("GROWTH_ENGINE_PROFILE_ID", "1"))
_INSTANCE_MUTEX = None


def _acquire_single_instance():
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    _INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "GrowthEnginePainel-SingleInstance")
    if not _INSTANCE_MUTEX:
        return True
    return ctypes.windll.kernel32.GetLastError() != 183


class ControlPanel(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Growth Engine | Torre de Controle")
        self.geometry("1180x760")
        self.minsize(960, 640)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.refresh_in_progress = False
        self.selected_job_id: str | None = None
        self.server_process: subprocess.Popen | None = None
        self.running = True
        self.tray_icon = None
        self.tray_thread = None
        self._tray_transition = False
        self.bind("<Unmap>", self._handle_minimize)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self._configure_style()
        self._build_layout()
        self._start_tray()
        self._schedule_refresh()
        self.after(100, self._drain_results)

    def _create_tray_image(self):
        image = Image.new("RGBA", (64, 64), "#101722")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=10, fill="#287c68")
        draw.rectangle((20, 20, 44, 44), fill="#ffffff")
        draw.rectangle((27, 14, 37, 50), fill="#287c68")
        return image

    def _start_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Abrir painel", self._restore_from_tray, default=True),
            pystray.MenuItem("Sair", self._exit_from_tray),
        )
        self.tray_icon = pystray.Icon(
            "growth-engine",
            self._create_tray_image(),
            "Growth Engine",
            menu,
        )
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def _handle_minimize(self, _event=None):
        if self._tray_transition or not self.running:
            return
        try:
            if self.state() == "iconic":
                self.after_idle(self._hide_to_tray)
        except ctk.TclError:
            pass

    def _hide_to_tray(self):
        if not self.running:
            return
        self._tray_transition = True
        try:
            self.withdraw()
        finally:
            self._tray_transition = False

    def _restore_from_tray(self, _icon=None, _item=None):
        if not self.running:
            return
        self.after(0, self._restore_window)

    def _restore_window(self):
        self._tray_transition = True
        try:
            self.deiconify()
            self.state("normal")
            self.lift()
            self.focus_force()
        finally:
            self._tray_transition = False

    def _exit_from_tray(self, _icon=None, _item=None):
        self.after(0, self._shutdown)

    def _shutdown(self):
        if not self.running:
            return
        self.running = False
        if self.tray_icon:
            self.tray_icon.stop()
        self._stop_server_worker()
        self.destroy()

    def _configure_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except ttk.TclError:
            pass
        style.configure(
            "Treeview",
            background="#17202b",
            foreground="#e8eef5",
            fieldbackground="#17202b",
            borderwidth=0,
            rowheight=30,
        )
        style.configure(
            "Treeview.Heading",
            background="#263548",
            foreground="#ffffff",
            relief="flat",
        )
        style.map("Treeview", background=[("selected", "#1f6aa5")])

    def _build_layout(self):
        header = ctk.CTkFrame(self, fg_color="#101722", corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header,
            text="GROWTH ENGINE",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(side="left", padx=24, pady=(18, 4))
        ctk.CTkLabel(
            header,
            text="TORRE DE CONTROLE",
            text_color="#75b9ff",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=8, pady=(20, 4))
        ctk.CTkButton(
            header,
            text="Renovar permissões YouTube",
            width=210,
            height=32,
            command=self._reauthorize_youtube,
        ).pack(side="right", padx=(8, 12), pady=14)
        self.clock_label = ctk.CTkLabel(header, text="", text_color="#9aa9bb")
        self.clock_label.pack(side="right", padx=(8, 12), pady=18)
        self._update_clock()

        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=18)
        for name in ("Dashboard", "Gestão de Jobs", "Serviços", "Manutenção"):
            self.tabs.add(name)

        self._build_dashboard(self.tabs.tab("Dashboard"))
        self._build_jobs(self.tabs.tab("Gestão de Jobs"))
        self._build_services(self.tabs.tab("Serviços"))
        self._build_maintenance(self.tabs.tab("Manutenção"))

        self.status_var = StringVar(value="Pronto")
        ctk.CTkLabel(self, textvariable=self.status_var, anchor="w", text_color="#91a3b8").pack(fill="x", padx=24, pady=(0, 10))
        self.after(300, self._start_server)

    def _build_dashboard(self, parent):
        cards = ctk.CTkFrame(parent, fg_color="transparent")
        cards.pack(fill="x", pady=8)
        self.server_status = self._status_card(cards, "Servidor Web", "Offline", 0)
        self.ollama_status = self._status_card(cards, "Ollama", "Offline", 1)
        self.cpu_status = self._status_card(cards, "CPU", "0%", 2)
        self.ram_status = self._status_card(cards, "RAM", "0%", 3)

        info = ctk.CTkFrame(parent)
        info.pack(fill="both", expand=True, pady=(16, 0))
        ctk.CTkLabel(info, text="Saúde do ambiente", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=20, pady=(18, 4))
        self.health_text = ctk.CTkTextbox(info, height=220, state="disabled")
        self.health_text.pack(fill="both", expand=True, padx=20, pady=(8, 20))

    def _status_card(self, parent, title, value, column):
        parent.grid_columnconfigure(column, weight=1)
        card = ctk.CTkFrame(parent, fg_color="#17202b")
        card.grid(row=0, column=column, sticky="nsew", padx=5)
        ctk.CTkLabel(card, text=title, text_color="#91a3b8", font=ctk.CTkFont(size=13)).pack(anchor="w", padx=16, pady=(14, 2))
        label = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold"))
        label.pack(anchor="w", padx=16, pady=(0, 14))
        return label

    def _build_jobs(self, parent):
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=8)
        ctk.CTkLabel(toolbar, text="Fila recente", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        self.job_count = ctk.CTkLabel(toolbar, text="0 jobs", text_color="#91a3b8")
        self.job_count.pack(side="left", padx=12)
        ctk.CTkButton(
            toolbar,
            text="Cancelar Job Selecionado",
            fg_color="#b83232",
            hover_color="#8f2525",
            command=self._cancel_selected_job,
        ).pack(side="right")

        table_frame = ctk.CTkFrame(parent)
        table_frame.pack(fill="both", expand=True, pady=(8, 0))
        columns = ("id", "status", "video", "progress", "message", "updated")
        self.jobs_table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {"id": "ID", "status": "Status", "video": "Vídeo", "progress": "Progresso", "message": "Mensagem", "updated": "Atualizado"}
        widths = {"id": 220, "status": 110, "video": 160, "progress": 90, "message": 330, "updated": 150}
        for column in columns:
            self.jobs_table.heading(column, text=headings[column])
            self.jobs_table.column(column, width=widths[column], anchor="w")
        self.jobs_table.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=12)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.jobs_table.yview)
        scrollbar.pack(side="right", fill="y", padx=(0, 12), pady=12)
        self.jobs_table.configure(yscrollcommand=scrollbar.set)
        self.jobs_table.bind("<<TreeviewSelect>>", self._select_job)

    def _build_services(self, parent):
        ctk.CTkLabel(parent, text="Controle de serviços", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(10, 4))
        ctk.CTkLabel(parent, text="Ligue ou desligue cada serviço sem fechar o painel.", text_color="#91a3b8").pack(anchor="w", pady=(0, 20))
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x")
        self.service_buttons = {}
        self._service_card(grid, "Servidor Web", "Servidor Web", self._start_server, self._stop_server, 0, self._restart_server)
        self._service_card(grid, "Ollama", "Ollama", self._start_ollama, self._stop_ollama, 1)

    def _service_card(self, parent, key, title, start_command, stop_command, column, restart_command=None):
        parent.grid_columnconfigure(column, weight=1)
        card = ctk.CTkFrame(parent, fg_color="#17202b")
        card.grid(row=0, column=column, sticky="nsew", padx=6)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=18, pady=(18, 4))
        status = ctk.CTkLabel(card, text="Verificando...", text_color="#91a3b8")
        status.pack(anchor="w", padx=18, pady=(0, 14))
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(0, 14))
        start_button = ctk.CTkButton(actions, text="Ligar", fg_color="#287c68", hover_color="#1d604f", command=start_command)
        start_button.pack(side="left", expand=True, fill="x", padx=4)
        stop_button = ctk.CTkButton(actions, text="Desligar", fg_color="#b83232", hover_color="#8f2525", command=stop_command)
        stop_button.pack(side="left", expand=True, fill="x", padx=4)
        restart_button = None
        if restart_command:
            restart_button = ctk.CTkButton(actions, text="Reiniciar", fg_color="#9a6b22", hover_color="#79531b", command=restart_command)
            restart_button.pack(side="left", expand=True, fill="x", padx=4)
        self.service_buttons[key] = {"status": status, "start": start_button, "stop": stop_button, "restart": restart_button}

    def _build_maintenance(self, parent):
        ctk.CTkLabel(parent, text="Manutenção & limpeza", font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(10, 4))
        ctk.CTkLabel(parent, text="Operações potencialmente demoradas são executadas fora da thread visual.", text_color="#91a3b8").pack(anchor="w", pady=(0, 20))
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x")
        self._action_button(grid, "Limpar Cache de Transcrição", self._clean_cache, 0, "#536b82")
        self._action_button(grid, "Sincronizar Banco de Dados", self._sync_database, 1, "#287c68")
        self.maintenance_log = ctk.CTkTextbox(parent, height=260, state="disabled")
        self.maintenance_log.pack(fill="both", expand=True, pady=(24, 0))

    def _action_button(self, parent, text, command, column, color):
        parent.grid_columnconfigure(column, weight=1)
        ctk.CTkButton(parent, text=text, height=64, fg_color=color, hover_color=color, command=command).grid(row=0, column=column, sticky="ew", padx=6)

    def _update_clock(self):
        if not self.running:
            return
        self.clock_label.configure(text=time.strftime("%d/%m/%Y %H:%M:%S"))
        self.after(1000, self._update_clock)

    def _schedule_refresh(self):
        if self.running:
            self._refresh_async()
            self.after(2500, self._schedule_refresh)

    def _refresh_async(self):
        if self.refresh_in_progress:
            return
        self.refresh_in_progress = True
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            jobs = self._query_jobs()
            server_online = self._probe_url(SERVER_URL)
            ollama_online = self._probe_url(f"{OLLAMA_URL}/api/tags")
            cpu = psutil.cpu_percent(interval=0.2)
            memory = psutil.virtual_memory().percent
            self.result_queue.put(("refresh", {"jobs": jobs, "server": server_online, "ollama": ollama_online, "cpu": cpu, "memory": memory}))
        except Exception as error:
            self.result_queue.put(("error", str(error)))

    @staticmethod
    def _probe_url(url):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return 200 <= response.status < 500
        except (OSError, urllib.error.URLError):
            return False

    def _query_jobs(self):
        if not DB_PATH.exists():
            return []
        with sqlite3.connect(DB_PATH, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT job_id, status, video_id, progresso, mensagem, atualizado_em FROM tarefas_jobs ORDER BY criado_em DESC LIMIT 10"
            ).fetchall()
            return [dict(row) for row in rows]

    def _drain_results(self):
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "refresh":
                    self._apply_refresh(payload)
                elif kind == "message":
                    self.status_var.set(str(payload))
                    self._append_log(str(payload))
                elif kind == "error":
                    self.status_var.set(f"Erro: {payload}")
                    self._append_log(f"ERRO: {payload}")
        except queue.Empty:
            pass
        finally:
            self.refresh_in_progress = False
            if self.running:
                self.after(100, self._drain_results)

    def _apply_refresh(self, data):
        self._set_status(self.server_status, data["server"], "Online", "Offline")
        self._set_status(self.ollama_status, data["ollama"], "Online", "Offline")
        self._set_service_state("Servidor Web", data["server"])
        self._set_service_state("Ollama", data["ollama"])
        self.cpu_status.configure(text=f"{data['cpu']:.0f}%")
        self.ram_status.configure(text=f"{data['memory']:.0f}%")
        self._update_health(data)
        self._update_jobs(data["jobs"])

    @staticmethod
    def _set_status(label, online, positive, negative):
        label.configure(text=positive if online else negative, text_color="#55d187" if online else "#ff6b6b")

    def _set_service_state(self, key, online):
        controls = self.service_buttons.get(key)
        if not controls:
            return
        controls["status"].configure(text="Ligado" if online else "Desligado", text_color="#55d187" if online else "#ff6b6b")
        controls["start"].configure(state="disabled" if online else "normal")
        controls["stop"].configure(state="normal" if online else "disabled")

    def _update_health(self, data):
        self.health_text.configure(state="normal")
        self.health_text.delete("1.0", END)
        lines = [
            f"Servidor Web: {'ONLINE' if data['server'] else 'OFFLINE'} ({SERVER_URL})",
            f"Ollama: {'ONLINE' if data['ollama'] else 'OFFLINE'} ({OLLAMA_URL})",
            f"Banco: {'encontrado' if DB_PATH.exists() else 'ausente'} ({DB_PATH})",
            f"Jobs recentes: {len(data['jobs'])}",
            "Atualização automática a cada 2,5 segundos.",
        ]
        self.health_text.insert("1.0", "\n".join(lines))
        self.health_text.configure(state="disabled")

    def _update_jobs(self, jobs):
        selected = self.selected_job_id
        for item in self.jobs_table.get_children():
            self.jobs_table.delete(item)
        for job in jobs:
            job_id = str(job.get("job_id") or "")
            progress = f"{float(job.get('progresso') or 0):.0f}%"
            self.jobs_table.insert("", END, iid=job_id, values=(job_id, job.get("status", ""), job.get("video_id", ""), progress, job.get("mensagem", ""), job.get("atualizado_em", "")))
        self.job_count.configure(text=f"{len(jobs)} jobs")
        if selected and self.jobs_table.exists(selected):
            self.jobs_table.selection_set(selected)

    def _select_job(self, _event=None):
        selection = self.jobs_table.selection()
        self.selected_job_id = selection[0] if selection else None

    def _cancel_selected_job(self):
        if not self.selected_job_id:
            messagebox.showinfo("Jobs", "Selecione um job na tabela.")
            return
        job_id = self.selected_job_id
        self._run_action(f"Cancelando job {job_id}...", lambda: self._cancel_job_worker(job_id))

    def _reauthorize_youtube(self):
        if not self._probe_url(SERVER_URL):
            self.status_var.set("Ligue o Servidor Web antes de renovar as permissões do YouTube.")
            return
        url = f"{SERVER_URL}/oauth/google/start?perfil_id={PROFILE_ID}&reauthorize=1"
        if webbrowser.open(url):
            self.status_var.set("A página de renovação das permissões do YouTube foi aberta no navegador.")
        else:
            self.status_var.set("Não foi possível abrir o navegador para renovar as permissões do YouTube.")

    def _cancel_job_worker(self, job_id):
        try:
            response = requests.post(f"{SERVER_URL}/api/jobs/{job_id}/cancel", timeout=5)
            if response.status_code not in (200, 202):
                raise RuntimeError(response.text or f"HTTP {response.status_code}")
            return f"Job {job_id} marcado para cancelamento."
        except requests.RequestException:
            with sqlite3.connect(DB_PATH, timeout=10) as connection:
                connection.execute(
                    "UPDATE tarefas_jobs SET status='cancelling', mensagem='Cancelamento solicitado pelo painel', atualizado_em=CURRENT_TIMESTAMP WHERE job_id=? AND status IN ('queued', 'running')",
                    (job_id,),
                )
                connection.commit()
            return f"Job {job_id} marcado no banco; o servidor não respondeu."

    def _start_server(self):
        self._run_action("Iniciando servidor...", self._start_server_worker)

    def _start_server_worker(self):
        if self._probe_url(SERVER_URL):
            return "Servidor já está online."
        if self.server_process and self.server_process.poll() is None:
            return "Servidor já foi iniciado pelo painel."
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if getattr(sys, "frozen", False):
            python_executable = ROOT / ".venv" / "Scripts" / "python.exe"
            if not python_executable.is_file():
                python_path = shutil.which("python")
                if not python_path:
                    raise RuntimeError("Interpretador Python do servidor não encontrado.")
                python_executable = Path(python_path)
        else:
            python_executable = Path(sys.executable)
        self.server_process = subprocess.Popen(
            [str(python_executable), str(ROOT / "iniciar_servidor.py")],
            cwd=ROOT,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self._probe_url(SERVER_URL):
                return "Servidor Web ligado."
            if self.server_process.poll() is not None:
                raise RuntimeError(f"O servidor encerrou durante a inicialização (código {self.server_process.returncode}).")
            time.sleep(0.25)
        raise RuntimeError("O processo do servidor foi criado, mas a porta 4174 não respondeu em 8 segundos.")

    def _stop_server(self):
        self._run_action("Parando servidor...", self._stop_server_worker)

    def _restart_server(self):
        self._run_action("Reiniciando servidor...", self._restart_server_worker)

    def _restart_server_worker(self):
        from core.job_repository import list_active_jobs

        active_jobs = list_active_jobs()
        publishing = [
            job for job in active_jobs
            if job.get("tipo") in {"cut_publish", "cut_publish_now"}
            and job.get("status") in {"queued", "running", "cancelling"}
        ]
        if publishing:
            raise RuntimeError("Não reiniciei o servidor: existe publicação ativa. Cancele o job antes de reiniciar.")
        self._stop_server_worker()
        return self._start_server_worker()

    def _stop_server_worker(self):
        stopped = False
        if self.server_process and self.server_process.poll() is None:
            self._terminate_tree(self.server_process.pid)
            stopped = True
            self.server_process = None
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                command = " ".join(process.info.get("cmdline") or [])
                if "iniciar_servidor.py" in command and process.pid != os.getpid():
                    self._terminate_tree(process.pid)
                    stopped = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return "Servidor parado." if stopped else "Nenhum processo do servidor encontrado."

    @staticmethod
    def _terminate_tree(pid):
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                child.terminate()
            parent.terminate()
            _, alive = psutil.wait_procs(children + [parent], timeout=3)
            for process in alive:
                process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def _start_ollama(self):
        self._run_action("Ligando Ollama...", self._start_ollama_worker)

    def _start_ollama_worker(self):
        if self._probe_url(f"{OLLAMA_URL}/api/tags"):
            return "Ollama já está ligado."
        subprocess.Popen(
            ["ollama", "serve"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self._probe_url(f"{OLLAMA_URL}/api/tags"):
                return "Ollama ligado."
            time.sleep(0.25)
        raise RuntimeError("Ollama não respondeu na porta 11434 em 8 segundos.")

    def _stop_ollama(self):
        self._run_action("Desligando Ollama...", self._stop_ollama_worker)

    def _stop_ollama_worker(self):
        stopped = 0
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (process.info.get("name") or "").lower()
                command = " ".join(process.info.get("cmdline") or []).lower()
                if "ollama" in name or ("ollama" in command and "painel_controle" not in command):
                    self._terminate_tree(process.pid)
                    stopped += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return f"Ollama desligado ({stopped} processo(s) encerrado(s))."

    def _restart_ollama(self):
        self._run_action("Reiniciando Ollama...", self._restart_ollama_worker)

    def _restart_ollama_worker(self):
        killed = 0
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (process.info.get("name") or "").lower()
                command = " ".join(process.info.get("cmdline") or []).lower()
                if "ollama" in name or ("ollama" in command and "painel_controle" not in command):
                    process.terminate()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(1)
        subprocess.Popen(["ollama", "serve"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return f"Ollama reiniciado ({killed} processo(s) encerrado(s))."

    def _clean_cache(self):
        self._run_action("Limpando cache de transcrição...", self._clean_cache_worker)

    def _clean_cache_worker(self):
        transcript_dir = ROOT / "media" / str(PROFILE_ID) / "transcripts"
        removed = 0
        if transcript_dir.exists():
            for path in transcript_dir.iterdir():
                if path.is_file() and path.suffix.lower() in {".srt", ".json"}:
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:
                        pass
        return f"Cache limpo: {removed} arquivo(s) removido(s)."

    def _sync_database(self):
        self._run_action("Sincronizando banco...", self._sync_database_worker)

    def _sync_database_worker(self):
        repaired_cuts = 0
        failed_jobs = 0
        with sqlite3.connect(DB_PATH, timeout=30) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT id, job_id, caminho_saida FROM cortes_gerados WHERE status='concluido'"
            ).fetchall()
            affected_jobs = set()
            for row in rows:
                output = row["caminho_saida"]
                if not output or not Path(output).is_file() or Path(output).stat().st_size == 0:
                    connection.execute(
                        "UPDATE cortes_gerados SET status='falhou', erro='Arquivo físico ausente ou corrompido', atualizado_em=CURRENT_TIMESTAMP WHERE id=?",
                        (row["id"],),
                    )
                    affected_jobs.add(row["job_id"])
                    repaired_cuts += 1
            for job_id in affected_jobs:
                valid = connection.execute(
                    "SELECT 1 FROM cortes_gerados WHERE job_id=? AND status='concluido' AND caminho_saida IS NOT NULL LIMIT 1",
                    (job_id,),
                ).fetchone()
                if not valid:
                    cursor = connection.execute(
                        "UPDATE tarefas_jobs SET status='failed', mensagem='Sincronização: arquivos físicos dos cortes ausentes', erro='Arquivo físico ausente ou corrompido', concluido_em=CURRENT_TIMESTAMP, atualizado_em=CURRENT_TIMESTAMP WHERE job_id=? AND status IN ('completed', 'needs_review')",
                        (job_id,),
                    )
                    failed_jobs += cursor.rowcount
            connection.commit()
        return f"Banco sincronizado: {repaired_cuts} corte(s) reparado(s), {failed_jobs} job(s) marcado(s) como falho(s)."

    def _run_action(self, initial_message, worker):
        self.status_var.set(initial_message)
        threading.Thread(target=self._action_thread, args=(worker,), daemon=True).start()

    def _action_thread(self, worker):
        try:
            result = worker()
            self.result_queue.put(("message", result))
        except Exception as error:
            self.result_queue.put(("error", str(error)))

    def _append_log(self, message):
        if not hasattr(self, "maintenance_log"):
            return
        self.maintenance_log.configure(state="normal")
        self.maintenance_log.insert(END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
        self.maintenance_log.see(END)
        self.maintenance_log.configure(state="disabled")

    def _close(self):
        self._hide_to_tray()


if __name__ == "__main__":
    if not _acquire_single_instance():
        sys.exit(0)
    app = ControlPanel()
    app.mainloop()
