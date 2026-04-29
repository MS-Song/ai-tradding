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
        
        # 1. 시장 트렌드 및 지수 패치
        try:
            self.state.update_worker_status("INDEX", status="시장분석", friendly_name="MARKET_ANAL")
            self.strategy.determine_market_trend()
            
            # [Task] 날짜 변경 감지 시 전일 추천 리스트 갱신
            today_str = datetime.now().strftime('%Y-%m-%d')
            if not hasattr(self, "_last_date") or self._last_date != today_str:
                self.strategy.state_mgr.update_yesterday_recs()
                self._last_date = today_str

            with self.state.lock:
                self.state.market_data = self.strategy.current_market_data
                self.state.vibe = self.strategy.current_market_vibe
                self.state.is_panic = self.strategy.global_panic
                self.state.dema_info = getattr(self.strategy.analyzer, 'dema_info', {})
                
                # 지수 상태에 따른 시장 활성화 여부 판단
                kospi_info = self.state.market_data.get("KOSPI")
                if kospi_info and "status" in kospi_info:
                    self.state.is_kr_market_active = (kospi_info.get("status") == "02")
                else:
                    self.state.is_kr_market_active = is_market_open()
                
            self.state.update_worker_status("INDEX", status="대기 중 (IDLE)", result="성공", last_task="시장 지수 및 VIBE 분석", friendly_name="MARKET_ANAL")
        except RuntimeError:
            self.stop() # 시스템 종료 시
        except Exception as e:
            from src.logger import log_error
            log_error(f"MarketWorker Analysis Error: {e}")
            self.state.update_worker_status("INDEX", status="대기 중 (IDLE)", result="실패", last_task=f"시장분석 오류: {e}", friendly_name="MARKET_ANAL")

        # 2. VIBE 변화 및 장 개시 알림 로직
        self._handle_notifications()

        # 3. 네이버 인기/거래량 종목 수집
        try:
            self.state.update_worker_status("RANKING", status="종목 수집")
            h_raw = self.api.get_naver_hot_stocks()
            v_raw = self.api.get_naver_volume_stocks()
            self.state.update_worker_status("THEME", status="테마 분석")
            self.themes = analyze_popular_themes(h_raw, v_raw)
            
            shared_info = self._extract_price_info(h_raw + v_raw)
            
            with self.state.lock:
                self.state.hot_raw = h_raw
                self.state.vol_raw = v_raw
                # 가격 정보 캐시에 병합
                for c, info in shared_info.items():
                    if c in self.state.stock_info:
                        self.state.stock_info[c].update(info)
                    else:
                        base = {"tp": 0, "sl": 0, "spike": False, "ma_20": 0, "prev_vol": 0, 
                                "day_val": 0, "day_rate": 0, "price": 0}
                        base.update(info)
                        self.state.stock_info[c] = base
                
            self.state.update_worker_status("RANKING", status="대기 중 (IDLE)", result="성공", last_task="인기 종목 탐색 완료")
            self.state.update_worker_status("THEME", status="대기 중 (IDLE)", result="성공", last_task="테마 분석 완료")
            
            # [추가] 전일 추천 종목 성과 실시간 갱신
            self.strategy.refresh_yesterday_recs_performance(h_raw, v_raw)
        except Exception as e:
            self.state.update_worker_status("RANKING", status="대기 중 (IDLE)", result="실패", last_task=f"랭킹 수집 오류: {e}")
            self.state.update_worker_status("THEME", status="대기 중 (IDLE)", result="실패", last_task=f"테마 분석 오류: {e}")

        # 4. AI 추천 및 비용 갱신
        try:
            self._update_ai_data(curr_t)
        except Exception as e:
            from src.logger import log_error
            log_error(f"MarketWorker AI Data Update Error: {e}")
        
        # 5. 복기 엔진 상태 (장 마감 후 체크용)
        self.state.update_worker_status("RETRO", status="대기 중 (IDLE)", result="성공", last_task="투자 복기 엔진 대기 중", friendly_name="RETRO")

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
