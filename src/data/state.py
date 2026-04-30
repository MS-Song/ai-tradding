import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

class TradingState:
    def __init__(self):
        # --- 안전 장치 (Recursive Lock) ---
        self.lock = threading.RLock()
        
        # --- UI 및 시스템 메시지 ---
        self.status_msg: str = ""
        self.status_time: float = 0.0
        self.last_log_msg: str = ""
        self.last_log_time: float = 0.0
        self.trading_logs: List[str] = [] # 최근 10개 거래 로그
        
        # --- 핵심 트레이딩 데이터 ---
        self.holdings: List[dict] = []
        self.asset: Dict[str, Any] = {
            "total_asset": 0, "total_principal": 0, "cash": 0, "pnl": 0, 
            "stock_eval": 0, "stock_principal": 0, "daily_pnl_rate": 0.0,
            "daily_pnl_amt": 0.0
        }
        self.stock_info: Dict[str, dict] = {} # 종목별 상세 캐시
        self.ma_20_cache: Dict[str, float] = {} # 종목별 20분봉 MA
        # --- 시황 및 분석 데이터 ---
        self.market_data: Dict[str, Any] = {}
        self.vibe: str = "Neutral"
        self.is_panic: bool = False
        self.dema_info: Dict[str, dict] = {}
        self.ai_costs: Dict[str, float] = {"gemini": 0.0, "groq": 0.0}
        self.recommendations: List[dict] = []
        self.hot_raw: List[dict] = []
        self.vol_raw: List[dict] = []
        
        # --- 수동 제어 플래그 (텔레그램 인바운드 등) ---
        self.manual_panic: bool = False
        self.is_trading_paused: bool = False
        self.force_vibe: Optional[str] = None
        
        # --- 시스템 상태 및 플래그 ---
        from src.utils import is_market_open
        self.is_running: bool = True
        self.is_kr_market_active: bool = is_market_open()
        self.holdings_fetched: bool = False
        self.last_update_time: str = ""
        self.ranking_filter: str = "ALL"
        self.last_terminal_size: tuple = (0, 0)
        
        # --- 워커(Worker) 상태 모니터링 ---
        self.worker_statuses: Dict[str, str] = {}    # 현재 작업 중인 상태
        self.worker_results: Dict[str, str] = {}     # 마지막 작업 결과 (성공/실패)
        self.worker_last_tasks: Dict[str, str] = {}  # 마지막으로 수행한 작업 내용
        self.worker_names: Dict[str, str] = {}       # 워커 ID별 표시 이름
        self.last_times: Dict[str, float] = {}       # 워커별 마지막 갱신 시각
        
        # --- 알림 및 로그 관리 ---
        self.last_notified_vibe: str = "Neutral"
        self.last_notified_halted: bool = False
        self.last_notified_trade_time: str = ""
        self.notified_dates: Dict[str, str] = {"market_start": "", "market_end": ""}
        
        # --- UI 입력 상태 ---
        self.is_input_active: bool = False
        self.input_prompt: str = ""
        self.input_buffer: str = ""
        self.current_prompt_mode: Optional[str] = None
        self.is_full_screen_active: bool = False
        
        # --- 기타 설정 및 차트 ---
        self.chart_data: Dict[str, Any] = {"code": "", "name": "", "candles": [], "time": 0}
        self.update_info: Dict[str, Any] = {
            "has_update": False, "latest_version": "", "download_url": "", 
            "is_downloading": False, "progress": 0
        }
        self.busy_anim_step: int = 0

    @property
    def asset_info(self):
        """하위 호환용: asset 딕셔너리 반환"""
        return self.asset

    # --- 실시간 상태 업데이트 (Thread-Safe) ---
    def update_worker_status(self, worker: str, status: Optional[str] = None, 
                             result: Optional[str] = None, last_task: Optional[str] = None, 
                             friendly_name: Optional[str] = None):
        with self.lock:
            if status is not None:
                self.worker_statuses[worker] = status
            if result is not None:
                self.worker_results[worker] = result
            if last_task is not None:
                self.worker_last_tasks[worker] = last_task
            if friendly_name:
                self.worker_names[worker] = friendly_name
            self.last_times[worker.lower()] = time.time()

    def clear_worker_status(self, worker: str):
        with self.lock:
            self.worker_statuses.pop(worker, None)

    def is_worker_busy(self, worker: str = None) -> bool:
        with self.lock:
            if worker:
                return self.worker_statuses.get(worker, "대기중") != "대기중"
            return any(v != "대기중" for v in self.worker_statuses.values())

    def get_global_busy_msg(self) -> Optional[str]:
        with self.lock:
            statuses = []
            if "GLOBAL" in self.worker_statuses:
                statuses.append(self.worker_statuses["GLOBAL"])
            
            # 기타 워커들
            other = [v for k, v in self.worker_statuses.items() if k != "GLOBAL" and v != "대기중"]
            if other:
                statuses.extend(sorted(list(set(other))))
            
            return " | ".join(statuses) if statuses else None

    def add_trading_log(self, msg: str):
        with self.lock:
            t_str = datetime.now().strftime('%H:%M:%S')
            self.trading_logs.append(f"\033[95m[TRADING] [{t_str}] {msg}\033[0m")
            if len(self.trading_logs) > 10:
                self.trading_logs.pop(0)

    def set_status(self, msg: str, is_error: bool = False):
        with self.lock:
            color = "\033[91m" if is_error else "\033[92m"
            prefix = "[ERROR]" if is_error else "[STATUS]"
            self.status_msg = f"{color}{prefix} {msg}\033[0m"
            self.status_time = time.time()
