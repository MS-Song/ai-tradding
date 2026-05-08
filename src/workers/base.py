import threading
import time
from typing import Optional, List
import traceback
from src.logger import log_error

class BaseWorker:
    """모든 백그라운드 워커의 기반이 되는 베이스 클래스.
    
    개별적인 스레드에서 주기적으로 실행되어야 하는 작업을 관리합니다. 
    상태 모니터링, 예외 처리, 실행 간격 조절 등의 공통 기능을 제공합니다.

    Attributes:
        name (str): 워커 식별자.
        state: 시스템 전역 상태를 관리하는 DataManager 인스턴스.
        interval (float): 작업 실행 간격 (초).
        thread: 워커가 실행되는 threading.Thread 객체.
        is_running (bool): 워커의 활성화 여부.
    """
    def __init__(self, name: str, state, interval: float = 1.0):
        """BaseWorker를 초기화합니다.

        Args:
            name (str): 워커 식별자 (예: 'TRADE', 'MARKET').
            state (DataManager): 시스템 전역 상태를 관리하는 인스턴스.
            interval (float, optional): 작업 실행 간격 (초). 기본값 1.0.
        """
        self.name = name
        self.state = state
        self.interval = interval
        self.thread = None
        self.is_running = False

    def start(self):
        """워커 스레드를 생성하고 실행을 시작합니다."""
        if self.thread and self.thread.is_alive():
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, name=f"Worker_{self.name}", daemon=True)
        self.thread.start()

    def stop(self):
        """워커 실행을 중지하도록 플래그를 설정합니다."""
        self.is_running = False

    def _run_loop(self):
        """워커의 메인 실행 루프. 
        
        설정된 간격마다 `run()` 메서드를 호출하며, 발생하는 예외를 포착하여 로깅합니다.
        """
        while self.is_running and self.state.is_running:
            try:
                self.run()
            except Exception as e:
                log_error(f"Worker {self.name} Error: {e}\n{traceback.format_exc()}")
            
            if self.interval > 0:
                time.sleep(self.interval)

    def run(self):
        """실제 수행할 작업을 구현하는 메서드. 서브클래스에서 반드시 오버라이드해야 합니다."""
        pass

    def set_busy(self, msg: str, friendly_name: Optional[str] = None):
        """현재 워커가 작업을 수행 중임을 상태 관리자에 알립니다.

        Args:
            msg (str): 현재 수행 중인 작업 설명.
            friendly_name (str, optional): UI에 표시될 워커의 한글 이름.
        """
        self.state.update_worker_status(self.name, status=msg, friendly_name=friendly_name)

    def set_result(self, result: str, last_task: Optional[str] = None, friendly_name: Optional[str] = None):
        """작업 완료 후 결과 상태를 업데이트합니다.

        Args:
            result (str): 작업 결과 (성공, 실패 등).
            last_task (str, optional): 마지막으로 완료한 작업 상세.
            friendly_name (str, optional): UI에 표시될 워커의 한글 이름.
        """
        self.state.update_worker_status(self.name, status="대기중", result=result, last_task=last_task, friendly_name=friendly_name)
