import threading
from concurrent.futures import ThreadPoolExecutor


class TaskRunner:
    """Executa tarefas nomeadas com limite de concorrência e lock por domínio."""

    def __init__(self, max_workers=2, thread_name_prefix="growth-task"):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)
        self._lock = threading.Lock()
        self._active = set()

    def submit(self, name, target, *args, key=None):
        active_key = key or name
        with self._lock:
            if active_key in self._active:
                return False
            self._active.add(active_key)

        def run():
            try:
                target(*args)
            finally:
                with self._lock:
                    self._active.discard(active_key)

        self._executor.submit(run)
        return True

    def is_running(self, name, key=None):
        with self._lock:
            return (key or name) in self._active

    def shutdown(self, wait=True):
        self._executor.shutdown(wait=wait)
