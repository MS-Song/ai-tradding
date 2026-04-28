import threading
import time
import traceback
from src.logger import log_error

class BaseWorker:
    def __init__(self, name: str, state, interval: float = 1.0):
        self.name = name
        self.state = state
        self.interval = interval
        self.thread = None
        self.is_running = False

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, name=f"Worker_{self.name}", daemon=True)
        self.thread.start()

    def stop(self):
        self.is_running = False

    def _run_loop(self):
        while self.is_running and self.state.is_running:
            try:
                self.run()
            except Exception as e:
                log_error(f"Worker {self.name} Error: {e}\n{traceback.format_exc()}")
            
            if self.interval > 0:
                time.sleep(self.interval)

    def run(self):
        """서브클래스에서 구현해야 함"""
        pass

    def set_busy(self, msg: str, friendly_name: Optional[str] = None):
        self.state.update_worker_status(self.name, status=msg, friendly_name=friendly_name)

    def set_result(self, result: str, last_task: Optional[str] = None):
        self.state.update_worker_status(self.name, status="대기중", result=result, last_task=last_task)
