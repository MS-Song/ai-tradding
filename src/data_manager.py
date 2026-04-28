import threading
import time
import queue
from datetime import datetime
from typing import Optional, List, Dict, Any

from src.data.state import TradingState
from src.workers.market_worker import MarketWorker
from src.workers.sync_worker import DataSyncWorker
from src.workers.trade_worker import TradeWorker
from src.utils.notifier import TelegramNotifier
from src.logger import log_error, cleanup_text_log, trading_log

class DataManager:
    def __init__(self, api, strategy):
        self.api = api
        self.strategy = strategy
        
        # --- 핵심 상태 관리 객체 (Phase 1) ---
        self.state = TradingState()
        
        # --- 알림 엔진 초기화 ---
        self.notifier = TelegramNotifier(dm=self)
        
        # --- 워커 인스턴스 (Phase 2) ---
        self.workers = {
            "MARKET": MarketWorker(self.state, api, strategy, self.notifier),
            "DATA": DataSyncWorker(self.state, api, strategy),
            "TRADE": TradeWorker(self.state, api, strategy)
        }
        
        # --- 하위 호환용 락 (기존 코드에서 참조함) ---
        self.data_lock = self.state.lock
        self.ui_lock = threading.Lock() # UI 전용 락 유지
        
        # --- 초기 알림 ---
        self.notifier.notify_alert("시스템 시작", "🚀 KIS-Vibe-Trader 엔진이 가동되었습니다. (Modular Arch)")

    # --- 하위 호환성을 위한 프로퍼티 매핑 ---
    @property
    def is_running(self): return self.state.is_running
    @is_running.setter
    def is_running(self, val): self.state.is_running = val
    
    @property
    def status_msg(self): return self.state.status_msg
    @status_msg.setter
    def status_msg(self, val): self.state.status_msg = val
    
    @property
    def status_time(self): return self.state.status_time
    @status_time.setter
    def status_time(self, val): self.state.status_time = val
    
    @property
    def trading_logs(self): return self.state.trading_logs
    
    @property
    def cached_holdings(self): return self.state.holdings
    @property
    def cached_asset(self): return self.state.asset
    @property
    def cached_stock_info(self): return self.state.stock_info
    @property
    def cached_vibe(self): return self.state.vibe
    @property
    def cached_market_data(self): return self.state.market_data
    @property
    def cached_panic(self): return self.state.is_panic
    @property
    def cached_hot_raw(self): return self.state.hot_raw
    @property
    def cached_vol_raw(self): return self.state.vol_raw
    @property
    def cached_recommendations(self): return self.state.recommendations
    @property
    def cached_dema_info(self): return self.state.dema_info
    @property
    def cached_ai_costs(self): return self.state.ai_costs
    @property
    def cached_holdings_fetched(self): return self.state.holdings_fetched
    @property
    def is_kr_market_active(self): return self.state.is_kr_market_active
    @property
    def is_input_active(self): return self.state.is_input_active
    @is_input_active.setter
    def is_input_active(self, val): self.state.is_input_active = val
    @property
    def is_full_screen_active(self): return self.state.is_full_screen_active
    @is_full_screen_active.setter
    def is_full_screen_active(self, val): self.state.is_full_screen_active = val
    @property
    def worker_results(self): return self.state.worker_results
    @property
    def worker_last_tasks(self): return self.state.worker_last_tasks
    @property
    def global_busy_msg(self): return self.state.get_global_busy_msg()
    @property
    def busy_anim_step(self): return self.state.busy_anim_step
    @busy_anim_step.setter
    def busy_anim_step(self, val): self.state.busy_anim_step = val
    @property
    def ma_20_cache(self): return self.state.ma_20_cache

    # --- 필수 메서드 구현 (UI/Interaction 호출용) ---
    def set_busy(self, msg, worker="GLOBAL", friendly_name=None):
        self.state.update_worker_status(worker, status=msg, friendly_name=friendly_name)

    def clear_busy(self, worker="GLOBAL"):
        self.state.clear_worker_status(worker)

    def update_worker_status(self, worker, result=None, last_task=None, friendly_name=None):
        self.state.update_worker_status(worker, result=result, last_task=last_task, friendly_name=friendly_name)

    def is_busy(self):
        return self.state.is_worker_busy()

    def is_blocking_busy(self):
        # GLOBAL 작업 중이면 매매 차단
        return self.state.is_worker_busy("GLOBAL")

    def show_status(self, msg, is_error=False):
        self.state.set_status(msg, is_error)

    def add_log(self, msg):
        with self.state.lock:
            self.state.last_log_msg = f"\033[96m[LOG] {msg}\033[0m"
            self.state.last_log_time = time.time()

    def add_trading_log(self, msg):
        self.state.add_trading_log(msg)
        trading_log.log_config(msg)

    def start_workers(self, is_virtual: bool):
        """메인 루프에서 호출하여 백그라운드 스레드 가동"""
        for worker in self.workers.values():
            worker.start()
        
        # 로그 정리 및 테마 수집은 별도 스레드로 유지 (추후 별도 워커화 가능)
        threading.Thread(target=self._maintenance_loop, daemon=True).start()

    def _maintenance_loop(self):
        """로그 정리 및 주기적 관리 작업"""
        while self.state.is_running:
            try:
                self.set_busy("로그 정리")
                cleanup_text_log("error.log", days_to_keep=2)
                trading_log.cleanup(days_to_keep=2)
                self.update_worker_status("CLEANUP", result="성공", last_task="로그 파일 정리 완료")
            except Exception as e:
                log_error(f"Maintenance Loop Error: {e}")
            finally:
                self.clear_busy()
            
            time.sleep(3600) # 1시간 주기

    def shutdown(self, reason="사용자 종료"):
        self.notifier.notify_alert("시스템 종료", f"🛑 트레이딩 엔진이 종료되었습니다. (사유: {reason})")
        self.state.is_running = False
        for worker in self.workers.values():
            worker.stop()
        time.sleep(1)

    # --- 호환성용 더미/대행 메서드 ---
    def update_all_data(self, is_virtual, force=False, lite=False):
        # 기존에는 수동 동기화 요청 시 사용됨. 워커가 활성화되어 있으므로
        # 여기서는 즉시 갱신이 필요할 경우 워커의 인터벌을 조정하거나 직접 호출 가능.
        # 일단은 워커가 1초 주기로 돌고 있으므로 패스.
        pass

    def notify_latest_trades(self):
        """TradeWorker에서 호출하거나 여기서 별도 처리"""
        # TelegramNotifier가 이미 dm(self)을 가지고 있으므로 내부에서 처리 가능
        pass
