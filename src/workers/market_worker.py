import time
from datetime import datetime
from typing import List, Dict, Optional
from src.workers.base import BaseWorker
from src.utils import is_ai_enabled_time, is_market_open
from src.theme_engine import analyze_popular_themes

class MarketWorker(BaseWorker):
    """시장 데이터 수집 및 분석을 총괄하는 핵심 워커.
    
    지수 데이터(KOSPI, KOSDAQ 등) 수집, 시장 장세(Vibe) 분석, 인기 테마 및 랭킹 분석, 
    AI 추천 종목 업데이트, 그리고 장 개시/마감 알림 등 시장 전반의 상태를 동기화합니다.

    Attributes:
        api: 시장 데이터 및 지수를 가져오기 위한 API 클라이언트.
        strategy: 시장 분석 및 전략 수립을 담당하는 VibeStrategy 인스턴스.
        notifier: 텔레그램 알림 전송을 위한 TelegramNotifier 인스턴스.
    """
    def __init__(self, state, api, strategy, notifier=None):
        """MarketWorker를 초기화합니다.

        Args:
            state (DataManager): 시스템 전역 상태 인스턴스.
            api: 시장 데이터를 가져올 API 클라이언트.
            strategy (VibeStrategy): 시장 분석 로직을 포함하는 전략 엔진.
            notifier (TelegramNotifier, optional): 텔레그램 알림 인스턴스.
        """
        super().__init__("INDEX", state, interval=5.0)
        self.api = api
        self.strategy = strategy
        self.notifier = notifier
        self.themes = []

    def run(self):
        """시장 데이터 수집 및 분석 루틴을 주기적으로 실행합니다.
        
        1. 지수 데이터 수집 및 한국 시장 개장 상태 동기화 (5초).
        2. 지수 변동성 또는 정기 주기에 따른 시장 Vibe 분석 (120초).
        3. 인기 검색 및 거래량 상위 종목 기반 테마 분석 (120초).
        4. AI 추천 종목 리스트 및 API 사용 비용 업데이트 (5분).
        5. 장 개시/마감 등 주요 시점 알림 처리.
        """
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
            
            # 1.1 시장 개장 상태 확인 (API 호출)
            market_status = None
            if hasattr(self.api, 'get_market_open_status'):
                market_status = self.api.get_market_open_status()
            
            with self.state.lock:
                for s, data in batch_data.items():
                    if data: 
                        self.state.market_data[s] = data
                        val = data.get('price', '')
                        rate = data.get('rate', 0.0)
                        source = data.get('source', '지수 API')
                        self.state.indicator_updates[s] = {
                            "time": curr_t, 
                            "status": "성공", 
                            "value": f"{val} ({rate:+.2f}%)",
                            "rate": rate,
                            "remark": f"{source} 갱신"
                        }
                
                # 시장 상태 동기화 (API 성공 시 API 결과 사용, 실패 시 시간 기반 fallback)
                if market_status is not None:
                    self.state.is_kr_market_active = market_status
                    self.state.indicator_updates["한국장"] = {
                        "time": curr_t,
                        "status": "성공",
                        "value": "오픈" if market_status else "마감",
                        "rate": 0,
                        "remark": "KIS API 갱신"
                    }
                else:
                    self.state.is_kr_market_active = is_market_open()
                    self.state.indicator_updates["한국장"] = {
                        "time": curr_t,
                        "status": "성공",
                        "value": "오픈" if self.state.is_kr_market_active else "마감",
                        "rate": 0,
                        "remark": "시간 기반 Fallback"
                    }

            # MARKET 하트비트 갱신 (5초)
            self.state.update_worker_status("MARKET", status="대기 중 (IDLE)", result="성공", last_task="하트비트 확인됨", friendly_name="MARKET_CORE")
        except Exception as e:
            from src.logger import log_error
            log_error(f"MarketWorker Data Fetch Error: {e}")
            self.state.update_worker_status("MARKET", status="대기 중 (IDLE)", result="실패", last_task=f"수집 오류: {e}")
            # 에러 발생 시 시간 기반 fallback 적용
            with self.state.lock:
                self.state.is_kr_market_active = is_market_open()
                self.state.indicator_updates["한국장"] = {
                    "time": time.time(),
                    "status": "실패",
                    "value": "오픈" if self.state.is_kr_market_active else "마감",
                    "rate": 0,
                    "remark": "API 수집 오류 (시간 기반 Fallback)"
                }
                self.state.indicator_updates["지수통합수집"] = {
                    "time": time.time(),
                    "status": "실패",
                    "value": "-",
                    "rate": 0,
                    "remark": f"API 에러: {e}"
                }
            if self.notifier:
                try:
                    self.notifier.notify_alert("지표 갱신 실패", f"⚠️ <b>지수/시장 갱신</b> 중 오류가 발생했습니다.\n비고: {e}")
                except:
                    pass

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
        if (curr_t - getattr(self.strategy.analyzer, 'last_vibe_update', 0) > vibe_interval) or self.state.force_ai_diagnosis:
            should_analyze_vibe = True
            reason = "🧠 즉시 진단 요청" if self.state.force_ai_diagnosis else "⏰ 정기 분석 (120s)"

        if should_analyze_vibe:
            try:
                self.state.update_worker_status("VIBE", status="분석 중", friendly_name="MARKET_ANAL")
                self.strategy.determine_market_trend(force_ai=("⚡" in reason or "🧠" in reason), external_data=batch_data)
                self.strategy.analyzer.last_vibe_update = curr_t
                for k in ["KOSPI", "KOSDAQ"]:
                    self.strategy.analyzer.last_analyzed_rates[k] = batch_data.get(k, {}).get('rate', 0.0)
                
                with self.state.lock:
                    self.state.vibe = getattr(self.state, "force_vibe", None) or self.strategy.current_market_vibe
                    if getattr(self.state, "manual_panic", False):
                        self.state.is_panic = True
                    else:
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
        """시장 분위기 변화 및 장 개시/마감 알림을 주기적으로 체크하고 처리합니다.

        Logic:
            1. VIBE 변화: 시장 장세(Bull/Bear 등) 변경 시 텔레그램 알림 및 로그 기록.
            2. 장 개시: 오전 09:00 시점에 당일 최초 1회 개장 알림 전송.
            3. 장 마감: 오후 15:30 시점에 당일 최초 1회 자산 현황 리포트 전송.
        """
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

            # 3. 장 마감 리포트 (15:30)
            if "15:30" <= curr_time_str <= "15:35" and self.state.notified_dates.get("market_end") != today_str:
                if self.notifier:
                    self.notifier.notify_market_end(self.state.asset)
                self.state.notified_dates["market_end"] = today_str

    def _extract_price_info(self, items: List[Dict]) -> Dict[str, Dict]:
        """네이버 인기/거래량 상위 종목의 원시 데이터에서 핵심 가격 정보를 추출합니다.

        Args:
            items (List[dict]): 네이버 금융 API에서 수집된 종목 리스트.

        Returns:
            Dict[str, dict]: 종목 코드를 키로 하고, 가격/등락률/전일대비/종목명을 포함하는 맵.
        """
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

    def _update_ai_data(self, curr_t: float):
        """AI 추천 종목 리스트와 모델별 API 사용 비용 정보를 업데이트합니다.

        Args:
            curr_t (float): 현재 시각 (timestamp).

        Logic:
            1. AI 추천 (5분 주기): 장중이거나 디버그/강제 요청 시 AlphaEngine을 통해 추천 리스트 갱신.
            2. 비용 집계 (5초 주기): GCP Billing 또는 로컬 로그 기반 모델별 누적 비용 동기화.
            3. 강제 진단 완료 후 처리: 사용자 요청에 의한 분석 완료 시 텔레그램 요약 전송.
        """
        from src.logger import log_error
        # 1. AI 추천 업데이트 (5분 주기)
        try:
            # 수동 진단 요청(force_ai_diagnosis) 시에는 장외 시간이라도 AI 분석 허용
            if is_ai_enabled_time() or getattr(self.strategy, "debug_mode", False) or self.state.force_ai_diagnosis:
                if (curr_t - self.state.last_times.get("recommendation", 0) > 300) or self.state.force_ai_diagnosis:
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

        # 3. 플래그 초기화
        if self.state.force_ai_diagnosis:
            # 즉시 진단 완료 후 텔레그램으로 요약 결과 전송
            if self.notifier:
                recs = self.state.recommendations[:5]
                rec_str = ""
                if not recs:
                    rec_str = "🔹 추천 종목이 없습니다."
                else:
                    for r in recs:
                        score = r.get('score', 0)
                        code = r.get('code', '000000')
                        name = r.get('name', 'Unknown')
                        rec_str += f"┣ <code>[{score:.0f}점]</code> {code} <b>{name}</b>\n"
                
                msg = (
                    f"✅ <b>AI 즉시 진단 완료</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🌍 <b>현재 VIBE</b>: <code>{self.state.vibe}</code>\n"
                    f"💡 <b>추천 종목 TOP 5</b>:\n{rec_str}\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                self.notifier.send_message(msg)

            with self.state.lock:
                self.state.force_ai_diagnosis = False
