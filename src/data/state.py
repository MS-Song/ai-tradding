import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

class TradingState:
    """시스템 전체의 상태 정보를 관리하는 중앙 공유 상태 저장소.
    
    UI 렌더링, 트레이딩 워커, 데이터 수집 워커 등 모든 모듈이 이 객체를 참조하여 
    데이터를 교환합니다. `threading.RLock`을 사용하여 멀티스레드 환경에서의 
    데이터 무결성(Thread-Safety)을 보장합니다.

    Attributes:
        lock (threading.RLock): 재진입 가능한 락 객체.
        status_msg (str): 하단 상태 표시줄에 출력될 시스템 메시지.
        holdings (List[dict]): 현재 보유 종목 리스트.
        asset (Dict[str, Any]): 총 자산, 예수금, 수익률 등 자산 요약 정보.
        market_data (Dict[str, Any]): 주요 지수 및 시황 데이터.
        vibe (str): AI가 판정한 시장 장세 (Bull/Bear/Neutral/Defensive).
        worker_statuses (Dict[str, str]): 실행 중인 워커들의 현재 상태 메시지.
    """
    def __init__(self):
        """TradingState를 초기화하고 모든 상태 변수를 초기화합니다.
        
        기본적으로 한국 시장 개장 여부를 확인하고, 멀티스레드 자산 보호를 위한 
        RLock을 생성합니다.
        """
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
        self.stock_info: Dict[str, dict] = {} # 종목별 상세 캐시 (PER, PBR, 뉴스 등)
        self.ma_20_cache: Dict[str, float] = {} # 종목별 20분봉 MA 캐시
        
        # --- 시황 및 분석 데이터 ---
        self.market_data: Dict[str, Any] = {}
        self.vibe: str = "Neutral"
        self.is_panic: bool = False
        self.dema_info: Dict[str, dict] = {} # 지수별 DEMA 데이터
        self.ai_costs: Dict[str, float] = {"gemini": 0.0, "groq": 0.0} # AI 모델별 누적 비용
        self.recommendations: List[dict] = [] # AI 추천 종목 리스트
        self.hot_raw: List[dict] = [] # 실시간 인기 종목 데이터
        self.vol_raw: List[dict] = [] # 거래량 상위 종목 데이터
        self.amt_raw: List[dict] = [] # 거래대금 상위 종목 데이터
        self.ranking_type: str = "거래량" # 현재 표시 중인 랭킹 타입
        
        # --- 주요 지표 갱신 기록 ---
        self.indicator_updates: Dict[str, dict] = {} # 기술적 지표 갱신 시점 추적
        
        # --- 수동 제어 플래그 (텔레그램 인바운드 등) ---
        self.manual_panic: bool = False
        self.is_trading_paused: bool = False
        self.force_vibe: Optional[str] = None
        self.force_ai_diagnosis: bool = False # AI 즉시 진단 요청 플래그
        
        # --- 시스템 상태 및 플래그 ---
        from src.utils import is_market_open
        self.is_running: bool = True
        self.is_kr_market_active: bool = is_market_open() # 한국 시장 개장 여부
        self.holdings_fetched: bool = False
        self.last_update_time: str = ""
        self.ranking_filter: str = "ALL"
        self.last_terminal_size: tuple = (0, 0)
        
        # --- 워커(Worker) 상태 모니터링 ---
        self.worker_statuses: Dict[str, str] = {}    # 현재 작업 중인 상태 메시지
        self.worker_results: Dict[str, str] = {}     # 마지막 작업 결과 (성공/실패)
        self.worker_last_tasks: Dict[str, str] = {}  # 마지막으로 수행한 구체적 작업 내용
        self.worker_names: Dict[str, str] = {}       # 워커 ID별 가독성 높은 이름
        self.last_times: Dict[str, float] = {}       # 워커별 마지막 갱신 타임스탬프
        
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
    def asset_info(self) -> Dict[str, Any]:
        """하위 호환성을 위해 자산 정보 딕셔너리를 반환합니다.

        Returns:
            Dict[str, Any]: 총 자산, 가용 현금 등이 포함된 자산 요약 정보.
        """
        return self.asset

    # --- 실시간 상태 업데이트 (Thread-Safe) ---
    def update_worker_status(self, worker: str, status: Optional[str] = None, 
                             result: Optional[str] = None, last_task: Optional[str] = None, 
                             friendly_name: Optional[str] = None):
        """특정 워커의 상태 정보를 업데이트합니다.

        Args:
            worker (str): 워커 식별자.
            status (str, optional): 현재 상태 메시지.
            result (str, optional): 작업 결과.
            last_task (str, optional): 마지막 작업 설명.
            friendly_name (str, optional): UI 표시용 이름.
        """
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
        """워커의 현재 상태를 제거합니다 (대기 상태 전환 시 호출).

        Args:
            worker (str): 제거할 워커 식별자.
        """
        with self.lock:
            self.worker_statuses.pop(worker, None)

    def _is_idle(self, status: str) -> bool:
        """주어진 상태 메시지가 '대기' 상태인지 판별합니다.
        
        Args:
            status (str): 확인할 상태 메시지.
            
        Returns:
            bool: 대기 상태면 True.
        """
        if not status: return True
        return status in ["대기중", "대기 중 (IDLE)"]

    def is_worker_busy(self, worker: str = None) -> bool:
        """워커가 현재 작업 중(대기중 아님)인지 확인합니다.

        Args:
            worker (str, optional): 특정 워커만 확인. 생략 시 전체 워커 대상.

        Returns:
            bool: 작업 중이면 True.
        """
        with self.lock:
            if worker:
                return not self._is_idle(self.worker_statuses.get(worker))
            return any(not self._is_idle(v) for v in self.worker_statuses.values())

    def get_global_busy_msg(self) -> Optional[str]:
        """모든 활성 워커의 상태를 결합한 통합 비지(Busy) 메시지를 생성합니다.

        Returns:
            Optional[str]: ' | '로 구분된 활성 워커 상태 문자열. 활성 워커가 없으면 None.
        """
        with self.lock:
            statuses = []
            # GLOBAL 워커가 있고 대기 중이 아닌 경우에만 추가
            global_status = self.worker_statuses.get("GLOBAL")
            if global_status and not self._is_idle(global_status):
                statuses.append(global_status)
            
            # 기타 워커들 중 대기 중이 아닌 것들만 필터링
            other = [v for k, v in self.worker_statuses.items() if k != "GLOBAL" and not self._is_idle(v)]
            if other:
                statuses.extend(sorted(list(set(other))))
            
            return " | ".join(statuses) if statuses else None

    def add_trading_log(self, msg: str):
        """TUI 하단 거래 로그 영역에 새 메시지를 추가합니다.

        최신순으로 최대 10개까지 로그를 유지하며, ANSI 색상 코드를 포함합니다.

        Args:
            msg (str): 추가할 로그 메시지 내용.
        """
        with self.lock:
            t_str = datetime.now().strftime('%H:%M:%S')
            self.trading_logs.append(f"\033[95m[TRADING] [{t_str}] {msg}\033[0m")
            if len(self.trading_logs) > 10:
                self.trading_logs.pop(0)

    def set_status(self, msg: str, is_error: bool = False):
        """하단 상태바에 일시적으로 표시될 시스템 메시지를 설정합니다.

        Args:
            msg (str): 표시할 메시지 내용.
            is_error (bool, optional): 에러 메시지 여부 (빨간색 표시). 기본값 False.
        """
        with self.lock:
            color = "\033[91m" if is_error else "\033[92m"
            prefix = "[ERROR]" if is_error else "[STATUS]"
            self.status_msg = f"{color}{prefix} {msg}\033[0m"
            self.status_time = time.time()
