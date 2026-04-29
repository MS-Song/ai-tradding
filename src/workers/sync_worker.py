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
        self.first_run = True
        self.last_balance_sync = 0

    def run(self):
        curr_t = time.time()
        
        # 1. 잔고 및 자산 정보 패치 (KIS API 호출) - 5초 주기로 제한 (사용자 요청 반영)
        should_fetch_balance = curr_t - getattr(self, "last_balance_sync", 0) > 5.0 or self.first_run
        
        try:
            if should_fetch_balance:
                self.set_busy("잔고 동기화")
                h, a = self.api.get_full_balance()
                self.last_balance_sync = curr_t
                
                if h or a.get('total_asset', 0) > 0:
                    self._update_asset_metrics(a)
                    with self.state.lock:
                        self.state.holdings = h
                        self.state.asset = a
                        self.state.holdings_fetched = True
                        if a.get('total_asset', 0) > 0:
                            self.strategy.last_known_asset = float(a['total_asset'])
                    
                    self.state.update_worker_status("ASSET", result="성공", last_task="계좌 및 평가액 동기화 완료", friendly_name="ASSET")
            
            # 2. 관련 종목 시세 동기화 (네이버 벌크 API 활용 - 이건 Rate Limit 없음)
            # 잔고 데이터가 없는 초기 상태가 아니라면 항상 실행
            current_holdings = self.state.holdings
            if current_holdings or self.first_run:
                self._sync_stock_prices(current_holdings, curr_t)
                self.set_result("성공", last_task="전체 잔고 및 시세 동기화 완료")
                self.first_run = False
                
        except Exception as e:
            if "초당 거래건수를 초과" in str(e):
                self.state.update_worker_status("ASSET", result="대기", last_task="API 속도 제한으로 대기 중")
            else:
                log_error(f"DataSyncWorker Run Error: {e}")
            self.set_result("실패", last_task=f"동기화 오류: {e}")

    def _update_asset_metrics(self, a):
        if not a or a.get('total_asset', 0) <= 0: return
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # [핵심] 일일 수익률 기준점(start_day_asset) 강제 동기화
        # 파일에서 로드된 과거의 잘못된 기준점(stale data)을 방지하기 위해 프로그램 시작 후 첫 실행 시 강제 재설정
        is_first_init = (
            self.strategy.start_day_asset <= 0 or 
            self.strategy.last_asset_date != today_str or
            getattr(self, "first_run", True)
        )
        
        if is_first_init:
            p_asset = a.get('prev_day_asset', 0)
            if p_asset > 0:
                # KIS 전일 평가액이 있으면 기준점으로 사용 (API 신뢰)
                self.strategy.start_day_asset = p_asset
            else:
                # 전일 데이터가 없거나 0이면 현재 자산을 시작점으로 설정 (오늘 수익 0%부터 시작)
                self.strategy.start_day_asset = a['total_asset']
            
            self.strategy.last_asset_date = today_str
            self.first_run = False # 초기화 완료
            with self.state.lock:
                self.state.last_log_msg = f"\033[96m[LOG] 📅 당일 수익률 기준점 초기화: {self.strategy.start_day_asset:,.0f}원\033[0m"
                self.state.last_log_time = time.time()

        a['total_principal'] = getattr(self.strategy, "base_seed_money", 0)
        
        if self.strategy.start_day_asset > 0:
            # [핵심] 일일 수익 및 수익률 계산: 실시간 total_asset 기반
            a['daily_pnl_amt'] = a['total_asset'] - self.strategy.start_day_asset
            a['daily_pnl_rate'] = (a['daily_pnl_amt'] / self.strategy.start_day_asset * 100)

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
            task_id = f"STOCK_{code}"
            # [수정] 캐시된 이름이 있으면 즉시 표시하여 'STOCK_' 코드 노출 최소화
            cached_name = self.state.stock_info.get(code, {}).get('name')
            f_name = f"{code}_{cached_name}" if cached_name else task_id
            self.state.update_worker_status(task_id, status="분석 중", friendly_name=f_name)
            
            # 종목명 찾기 (우선순위: 잔고명 -> Naver 실시간명 -> KIS 상세명 -> 기존 캐시명)
            s_name = next((s.get('prdt_name') for s in holdings if s.get('pdno')==code), None)
            
            p_data = None
            if is_heavy_cycle or code not in self.state.stock_info:
                p_data = self.api.get_inquire_price(code)
            
            if n_data:
                curr_p, day_rate, day_val = n_data['price'], n_data['rate'], n_data['cv']
                if not s_name: s_name = n_data.get('name')
                
                old_info = self.state.stock_info.get(code, {})
                p_data_fallback = {
                    "price": curr_p, "vrss": day_val, "ctrt": day_rate,
                    "vol": n_data.get('aq', 0), "high": n_data.get('hv', curr_p), "low": n_data.get('lv', curr_p),
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
            
            if not s_name: 
                s_name = self.state.stock_info.get(code, {}).get('name')
                if not s_name or s_name == "Unknown":
                    s_name = detail.get('name', code)

            # [수정] 분석 완료된 명칭으로 최종 업데이트
            f_name = f"{code}_{s_name}" if s_name else task_id
            self.state.update_worker_status(task_id, friendly_name=f_name)

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
                        # self.state.worker_names[tid] = f"{c}_{info['name']}"  # 워커명 유지 요청에 따라 제거
                        if ma > 0: self.state.ma_20_cache[c] = ma
                    self.state.update_worker_status(tid, status="IDLE", result="성공", last_task=f"{info['name']} 동기화 완료", friendly_name=f"{c}_{info['name']}")
                except: pass

        # 3.5 [신규] 보유 종목이 아닌 STOCK_ 워커 정리 (상태 제거)
        if self.state.holdings_fetched: # 잔고 데이터가 로드된 상태에서만 정리 수행
            with self.state.lock:
                active_stock_ids = [f"STOCK_{c}" for c in all_codes]
                for w_id in list(self.state.last_times.keys()):
                    if w_id.upper().startswith("STOCK_") and w_id.upper() not in active_stock_ids:
                        # 해당 워커의 모든 흔적 제거
                        self.state.last_times.pop(w_id, None)
                        self.state.worker_statuses.pop(w_id.upper(), None)
                        self.state.worker_results.pop(w_id.upper(), None)
                        self.state.worker_last_tasks.pop(w_id.upper(), None)
                        self.state.worker_names.pop(w_id.upper(), None)

        # 4. 실시간 가격 기반 수익률 및 자산 재계산 (KIS API 지연 대응)
        with self.state.lock:
            eval_delta = 0
            for h in self.state.holdings:
                c = h.get('pdno')
                if c in temp_info:
                    info = temp_info[c]
                    curr_p = float(info['price'])
                    avg_p = float(h.get('pchs_avg_pric', 0))
                    qty = int(float(h.get('hldg_qty', 0)))
                    
                    # 기존 평가금액과 실시간 평가금액 차이 계산
                    old_eval = float(h.get('evlu_amt', 0))
                    new_eval = curr_p * qty
                    eval_delta += (new_eval - old_eval)
                    
                    if avg_p > 0 and curr_p > 0:
                        pnl_amt = (curr_p - avg_p) * qty
                        pnl_rt = ((curr_p / avg_p) - 1) * 100
                        h['evlu_pfls_rt'] = f"{pnl_rt:.2f}"
                        h['evlu_pfls_amt'] = str(int(pnl_amt))
                        h['prpr'] = str(int(curr_p))
                        h['evlu_amt'] = str(int(new_eval)) # 평가금액 업데이트

            # 총자산 및 일일 수익률 즉시 갱신 (지연 방지)
            if eval_delta != 0 and self.state.asset:
                self.state.asset['total_asset'] = float(self.state.asset.get('total_asset', 0)) + eval_delta
                self.state.asset['stock_eval'] = float(self.state.asset.get('stock_eval', 0)) + eval_delta
                self._update_asset_metrics(self.state.asset)

            self.state.stock_info.update(temp_info)
            self.state.last_update_time = datetime.now().strftime('%H:%M:%S')

        if is_heavy_cycle:
            self.last_heavy_sync = curr_t
