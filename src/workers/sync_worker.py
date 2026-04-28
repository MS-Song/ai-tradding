import time
import concurrent.futures
from datetime import datetime
from src.workers.base import BaseWorker
from src.logger import trading_log, log_error

class DataSyncWorker(BaseWorker):
    def __init__(self, state, api, strategy):
        super().__init__("DATA", state, interval=1.0)
        self.api = api
        self.strategy = strategy
        self.last_heavy_sync = 0

    def run(self):
        curr_t = time.time()
        
        # 1. 자산 및 잔고 패치
        try:
            self.set_busy("잔고 동기화")
            h, a = self.api.get_full_balance(force=True)
            
            if h or a.get('total_asset', 0) > 0:
                # 당일 자산 기준점 설정 및 수익률 계산 (DataManager의 _update_daily_metrics 로직)
                self._update_asset_metrics(a)
                
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
        except Exception as e:
            log_error(f"DataSyncWorker Run Error: {e}")
            self.set_result("실패", last_task=f"동기화 오류: {e}")

    def _update_asset_metrics(self, a):
        if not a or a.get('total_asset', 0) <= 0: return
        today_str = datetime.now().strftime('%Y-%m-%d')
        p_asset = a.get('prev_day_asset', 0)
        if p_asset > 0:
            self.strategy.start_day_asset = p_asset
            self.strategy.last_asset_date = today_str
        else:
            if self.strategy.start_day_asset == 0 or self.strategy.last_asset_date != today_str:
                self.strategy.start_day_asset = a['total_asset']
                self.strategy.last_asset_date = today_str
        
        if self.strategy.start_day_asset > 0:
            a['daily_pnl_rate'] = (a['total_asset'] / self.strategy.start_day_asset - 1) * 100
            a['daily_pnl_amt'] = a['total_asset'] - self.strategy.start_day_asset

    def _sync_stock_prices(self, holdings, curr_t):
        recent_codes = set()
        with trading_log.lock:
            now_dt = datetime.now()
            for t in trading_log.data.get("trades", []):
                try:
                    t_dt = datetime.strptime(t["time"], '%Y-%m-%d %H:%M:%S')
                    if (now_dt - t_dt).total_seconds() < 600:
                        recent_codes.add(t["code"])
                    else: break
                except: continue
        
        all_codes = list(set([s.get('pdno') for s in holdings]) | recent_codes)
        if not all_codes: return

        bulk_data = self.api.get_naver_stocks_realtime(all_codes)
        is_heavy_cycle = (curr_t - self.last_heavy_sync > 60)
        
        temp_info = {}
        
        def fetch_stock_task(code):
            n_data = bulk_data.get(code)
            task_id = f"STOCK_{code}"
            
            # 종목명 찾기
            s_name = next((s.get('prdt_name') for s in holdings if s.get('pdno')==code), code)
            if s_name == code: s_name = self.state.stock_info.get(code, {}).get('name', code)
            
            p_data = None
            if is_heavy_cycle or code not in self.state.stock_info:
                p_data = self.api.get_inquire_price(code)
            
            if n_data:
                curr_p, day_rate, day_val = n_data['price'], n_data['rate'], n_data['cv']
                old_info = self.state.stock_info.get(code, {})
                p_data_fallback = {
                    "price": curr_p, "vrss": day_val, "ctrt": day_rate,
                    "vol": n_data['aq'], "high": n_data['hv'], "low": n_data['lv'],
                    "prev_vol": p_data.get("prev_vol", 0) if p_data else old_info.get("prev_vol", 0)
                }
                tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.state.vibe.lower(), p_data_fallback)
                p_vol = p_data_fallback["prev_vol"]
            else:
                if not p_data: p_data = self.api.get_inquire_price(code)
                tp, sl, spike = self.strategy.get_dynamic_thresholds(code, self.state.vibe.lower(), p_data)
                curr_p = p_data.get('price', 0) if p_data else 0
                day_val = p_data.get('vrss', 0) if p_data else 0
                day_rate = p_data.get('ctrt', 0) if p_data else 0
                p_vol = p_data.get('prev_vol', 0) if p_data else 0

            # MA20 계산
            ma_20 = self.state.ma_20_cache.get(code, 0.0)
            if ma_20 == 0 or is_heavy_cycle:
                try:
                    m_candles = self.api.get_minute_chart_price(code)
                    if m_candles:
                        closes = [float(str(c.get('stck_prpr') or c.get('stck_clpr')).strip()) for c in m_candles if (c.get('stck_prpr') or c.get('stck_clpr'))]
                        ma_vals = self.strategy.indicator_eng.calculate_sma(closes, [20])
                        ma_20 = ma_vals.get("sma_20", 0.0)
                except: pass

            return code, {
                "tp": tp, "sl": sl, "spike": spike, "day_val": day_val, "day_rate": day_rate,
                "ma_20": ma_20, "price": curr_p, "prev_vol": p_vol, "name": s_name
            }, task_id, ma_20

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_stock_task, c) for c in all_codes]
            for f in concurrent.futures.as_completed(futures):
                try:
                    c, info, tid, ma = f.result()
                    temp_info[c] = info
                    with self.state.lock:
                        self.state.worker_names[tid] = f"{c}_{info['name']}"
                        if ma > 0: self.state.ma_20_cache[c] = ma
                except: pass

        with self.state.lock:
            self.state.stock_info.update(temp_info)
            self.state.last_update_time = datetime.now().strftime('%H:%M:%S')

        if is_heavy_cycle:
            self.last_heavy_sync = curr_t
