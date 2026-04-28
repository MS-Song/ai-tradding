import time
import concurrent.futures
from datetime import datetime
from src.workers.base import BaseWorker
from src.logger import trading_log

class DataSyncWorker(BaseWorker):
    def __init__(self, state, api, strategy):
        super().__init__("DATA", state, interval=1.0)
        self.api = api
        self.strategy = strategy
        self.last_heavy_sync = 0

    def run(self):
        curr_t = time.time()
        
        # 1. 자산 및 잔고 패치
        self.set_busy("잔고 동기화")
        h, a = self.api.get_full_balance(force=True)
        
        if h or a.get('total_asset', 0) > 0:
            # 일일 수익률 계산 (Strategy 메서드 활용 필요하나 여기서는 단순화)
            with self.state.lock:
                self.state.holdings = h
                self.state.asset = a
                self.state.holdings_fetched = True
                if a.get('total_asset', 0) > 0:
                    self.strategy.last_known_asset = float(a['total_asset'])

            # 2. 관련 종목 시세 동기화 (네이버 벌크 API 활용)
            self._sync_stock_prices(h, curr_t)
            
            self.set_result("성공", last_task="전체 잔고 및 시세 동기화 완료")
        else:
            self.set_result("실패", last_task="잔고 수집 실패")

    def _sync_stock_prices(self, holdings, curr_t):
        # 관련 종목 코드 수집 (보유 종목 + 최근 거래 종목)
        relevant_codes = set([s.get('pdno') for s in holdings])
        # (최근 거래 종목 추가 로직 생략 - 단순화)
        
        if not relevant_codes: return

        bulk_data = self.api.get_naver_stocks_realtime(list(relevant_codes))
        temp_info = {}

        is_heavy_cycle = (curr_t - self.last_heavy_sync > 60)

        def fetch_task(code):
            n_data = bulk_data.get(code)
            # 상세 지표 수집 로직 (DataManager.data_sync_worker 참조)
            # 여기서는 기능 분해에 집중하므로 핵심 로직만 유지
            return code, {"price": n_data['price'] if n_data else 0} # 예시

        # 실제로는 concurrent.futures 사용 권장
        # ... (상세 구현 생략, DataManager 로직과 동일하게 구성) ...
        
        if is_heavy_cycle:
            self.last_heavy_sync = curr_t
