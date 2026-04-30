import time
from datetime import datetime
from src.workers.base import BaseWorker
from src.utils import is_ai_enabled_time, is_market_open
from src.theme_engine import analyze_popular_themes

class MarketWorker(BaseWorker):
    def __init__(self, state, api, strategy, notifier=None):
        super().__init__("INDEX", state, interval=5.0)
        self.api = api
        self.strategy = strategy
        self.notifier = notifier
        self.themes = []

    def run(self):
        curr_t = time.time()
        
        # 1. 지수 데이터 수집 (5초 주기)
        symbol_map = {
            "KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KPI200": "KPI200", "VOSPI": "VOSPI",
            "FX_USDKRW": "FX_USDKRW", "DOW": "DOW", "NASDAQ": "NASDAQ", "S&P500": "S&P500",
            "NAS_FUT": "NAS_FUT", "SPX_FUT": "SPX_FUT", "BTC_USD": "BTC-USD", "BTC_KRW": "BTC-KRW"
        }
        batch_data = {}
        try:
            batch_data = self.api.get_multiple_index_prices(symbol_map)
            with self.state.lock:
                for s, data in batch_data.items():
                    if data: self.state.market_data[s] = data
            # MARKET 하트비트 갱신 (5초)
            self.state.update_worker_status("MARKET", status="대기 중 (IDLE)", result="성공", last_task="하트비트 확인됨", friendly_name="MARKET_CORE")
        except Exception as e:
            from src.logger import log_error
            log_error(f"MarketWorker Data Fetch Error: {e}")
            self.state.update_worker_status("MARKET", status="대기 중 (IDLE)", result="실패", last_task=f"수집 오류: {e}")

        # 2. VIBE 분석 (120초 주기 또는 급격한 지수 변동 시)
        should_analyze_vibe = False
        reason = ""
        last_rates = getattr(self.strategy.analyzer, 'last_analyzed_rates', {})
        for k in ["KOSPI", "KOSDAQ"]:
            curr_rate = batch_data.get(k, {}).get('rate', 0.0)
            last_rate = last_rates.get(k, curr_rate)
            if abs(curr_rate - last_rate) >= 0.3:
                should_analyze_vibe = True
                reason = f"⚡ {k} 급변 ({last_rate:+.2f}% → {curr_rate:+.2f}%)"
                break
        
        vibe_interval = 120
        if curr_t - getattr(self.strategy.analyzer, 'last_vibe_update', 0) > vibe_interval:
            should_analyze_vibe = True
            reason = "⏰ 정기 분석 (120s)"

        if should_analyze_vibe:
            try:
                self.state.update_worker_status("VIBE", status="분석 중", friendly_name="MARKET_ANAL")
                self.strategy.determine_market_trend(force_ai=("⚡" in reason), external_data=batch_data)
                self.strategy.analyzer.last_vibe_update = curr_t
                for k in ["KOSPI", "KOSDAQ"]:
                    self.strategy.analyzer.last_analyzed_rates[k] = batch_data.get(k, {}).get('rate', 0.0)
                
                with self.state.lock:
                    self.state.vibe = self.strategy.current_market_vibe
                    self.state.is_panic = self.strategy.global_panic
                    self.state.dema_info = getattr(self.strategy.analyzer, 'dema_info', {})
                self.state.update_worker_status("VIBE", status="대기 중 (IDLE)", result="성공", last_task=reason)
            except Exception as e:
                from src.logger import log_error
                log_error(f"MarketWorker Vibe Error: {e}")
                self.state.update_worker_status("VIBE", status="대기 중 (IDLE)", result="실패", last_task=f"분석 오류: {e}")

        # 3. 인기/테마 분석 (120초 고정 주기)
        ranking_interval = 120
        if curr_t - getattr(self, "_last_ranking_time", 0) > ranking_interval:
            try:
                self.state.update_worker_status("RANKING", status="수집 중")
                h_raw = self.api.get_naver_hot_stocks()
                v_raw = self.api.get_naver_volume_stocks()
                self.themes = analyze_popular_themes(h_raw, v_raw)
                
                shared_info = self._extract_price_info(h_raw + v_raw)
                with self.state.lock:
                    self.state.hot_raw = h_raw
                    self.state.vol_raw = v_raw
                    for c, info in shared_info.items():
                        if c in self.state.stock_info: self.state.stock_info[c].update(info)
                        else: self.state.stock_info[c] = {"tp": 0, "sl": 0, "spike": False, "ma_20": 0, "prev_vol": 0, "day_val": 0, "day_rate": 0, "price": 0, **info}
                
                self._last_ranking_time = curr_t
                self.strategy.refresh_yesterday_recs_performance(h_raw, v_raw)
                self.state.update_worker_status("RANKING", status="대기 중 (IDLE)", result="성공", last_task="랭킹/테마 갱신 완료")
            except Exception as e:
                from src.logger import log_error
                log_error(f"MarketWorker Ranking Error: {e}")
                self.state.update_worker_status("RANKING", status="대기 중 (IDLE)", result="실패", last_task=f"수집 오류: {e}")

        # 4. 공통 기능 (5초)
        self._handle_notifications()
        self._update_ai_data(curr_t)
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        if not hasattr(self, "_last_date") or self._last_date != today_str:
            self.strategy.state_mgr.update_yesterday_recs()
            self._last_date = today_str
        
        # RETRO 상태는 루프 마지막에 1회 업데이트 (5초)
        self.state.update_worker_status("RETRO", status="대기 중 (IDLE)", result="성공", last_task="복기 엔진 대기 중")

    def _handle_notifications(self):
        with self.state.lock:
            curr_vibe = self.state.vibe
            curr_time_str = datetime.now().strftime('%H:%M')
            today_str = datetime.now().strftime('%Y-%m-%d')
            
            # 1. VIBE 변화 알림
            if curr_vibe != self.state.last_notified_vibe:
                if self.notifier:
                    self.notifier.notify_alert("시장 VIBE 변화", f"🔄 `{self.state.last_notified_vibe}` → `{curr_vibe}`")
                self.state.add_trading_log(f"🌍 시장 VIBE 변화: {self.state.last_notified_vibe} → {curr_vibe}")
                self.state.last_notified_vibe = curr_vibe
            
            # 2. 장 개시 알림
            if "09:00" <= curr_time_str <= "09:05" and self.state.notified_dates.get("market_start") != today_str:
                if self.state.is_kr_market_active:
                    if self.notifier:
                        self.notifier.notify_market_start(curr_vibe)
                    self.state.notified_dates["market_start"] = today_str

            # 4. 장 마감 리포트 (15:30)
            if "15:30" <= curr_time_str <= "15:35" and self.state.notified_dates.get("market_end") != today_str:
                if self.notifier:
                    self.notifier.notify_market_end(self.state.asset)
                self.state.notified_dates["market_end"] = today_str

    def _extract_price_info(self, items):
        info_map = {}
        for item in items:
            code = item.get('code')
            if code:
                try:
                    price = float(str(item.get('price', 0)).replace(',', ''))
                    rate = float(item.get('rate', 0.0))
                    prev_close = price / (1 + rate / 100) if rate != -100 else price
                    info_map[code] = {
                        "price": price, "day_rate": rate, "day_val": price - prev_close,
                        "name": item.get('name', code)
                    }
                except: pass
        return info_map

    def _update_ai_data(self, curr_t):
        from src.logger import log_error
        # 1. AI 추천 업데이트 (5분 주기)
        try:
            if is_ai_enabled_time() or getattr(self.strategy, "debug_mode", False):
                if curr_t - self.state.last_times.get("recommendation", 0) > 300:
                    def rec_prog_cb(c, t, msg=""):
                        self.state.update_worker_status("RECOMMENDATION", status=f"AI분석({c}/{t})")
                    
                    self.strategy.update_ai_recommendations(
                        themes=self.themes,
                        hot_raw=self.state.hot_raw,
                        vol_raw=self.state.vol_raw,
                        progress_cb=rec_prog_cb
                    )
                    
                    with self.state.lock:
                        self.state.recommendations = self.strategy.ai_recommendations
                        self.state.last_times["recommendation"] = curr_t
                    self.state.update_worker_status("RECOMMENDATION", status="대기 중 (IDLE)", result="성공", last_task="AI 추천 종목 리스트 갱신 완료")
        except Exception as e:
            log_error(f"AI 추천 업데이트 오류: {e}")
            self.state.update_worker_status("RECOMMENDATION", status="대기 중 (IDLE)", result="실패", last_task=f"추천 수집 오류: {str(e)[:20]}")

        # 2. 비용 업데이트 (5초 주기)
        try:
            if curr_t - self.state.last_times.get("billing", 0) > 5:
                costs = self.strategy.get_ai_costs()
                with self.state.lock:
                    self.state.ai_costs = costs
                    self.state.last_times["billing"] = curr_t
                self.state.update_worker_status("BILLING", status="대기 중 (IDLE)", result="성공", last_task="AI API 비용 집계")
        except Exception as e:
            log_error(f"AI 비용 집계 오류: {e}")
            self.state.update_worker_status("BILLING", status="대기 중 (IDLE)", result="실패", last_task=f"비용 집계 오류: {str(e)[:20]}")
