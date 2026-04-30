import time
from typing import Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.logger import log_error
from src.utils import is_ai_enabled_time

class MarketAnalyzer:
    def __init__(self, api, indicator_eng=None):
        self.api = api
        self.indicator_eng = indicator_eng
        self.current_data = {}
        self.is_panic = False
        self.kr_vibe = "Neutral"
        self.dema_info = {} # [추가] 지수별 DEMA 정보 저장
        
        # AI 검증 연동용
        self.ai_advisor = None
        self.ai_call_timestamps = []
        self.last_kospi_rate = 0.0
        self.last_kosdaq_rate = 0.0
        self.ai_override_msg = ""
        self.finalized_ai_vibe = None # 캐시된 마지막 AI 판정
        self.debug_mode = False
        self.last_analyzed_rates = {} # [추가] 마지막 분석 시점의 등락률 저장
        self.last_dema_update = 0     
        self.last_vibe_update = 0     # [추가] 마지막 Vibe 분석 시간

    def update(self, force_ai: bool = False, external_data: dict = None) -> Tuple[str, bool]:
        """지수 데이터를 업데이트하고 시장 장세를 분석합니다."""
        if external_data:
            # 외부에서 주입된 데이터가 있으면 바로 사용
            for s, data in external_data.items():
                if data: self.current_data[s] = data
        else:
            # 주입된 데이터가 없으면 기존처럼 직접 수집
            symbol_map = {
                "KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KPI200": "KPI200", "VOSPI": "VOSPI",
                "FX_USDKRW": "FX_USDKRW", "DOW": "DOW", "NASDAQ": "NASDAQ", "S&P500": "S&P500",
                "NAS_FUT": "NAS_FUT", "SPX_FUT": "SPX_FUT", "BTC_USD": "BTC_USD", "BTC_KRW": "BTC_KRW"
            }
            try:
                # [최적화] 개별 호출 대신 벌크 API를 사용하여 1회에 모든 지수 수집
                batch_data = self.api.get_multiple_index_prices(symbol_map)
                for s, data in batch_data.items():
                    if data: self.current_data[s] = data
            except RuntimeError:
                return self.kr_vibe, self.is_panic 
        # 1차 평가 (알고리즘 기반 휴리스틱)
        heuristic_vibe = self._check_circuit_breaker()
        if heuristic_vibe == "Neutral":
            heuristic_vibe = self._check_kr_vibe()
        
        # BTC 기반 VIBE 추가 보정: 비트코인 급락 시 Bull -> Neutral 강제 하향
        btc = self.current_data.get("BTC_USD")
        if btc and btc['rate'] <= -2.5 and heuristic_vibe == "Bull":
            heuristic_vibe = "Neutral"
            
        # 2. AI 검증 로직 연결 (단, 오류나 토큰 초과 시 원래 휴리스틱으로 Fallback)
        self.kr_vibe = self._verify_with_ai(heuristic_vibe, force_ai=force_ai)
            
        return self.kr_vibe, self.is_panic
        
    def _verify_with_ai(self, heuristic_vibe: str, force_ai: bool = False) -> str:
        """AI를 통해 시장 장세를 검증받고 오버라이드. (장애 허용 지원)"""
        # 기본적으로 알고리즘 결과를 디폴트로 세팅
        if not self.ai_advisor:
            self.ai_override_msg = ""
            return heuristic_vibe

        now = time.time()
        # 15분 내(900초)의 타임스탬프만 유지
        self.ai_call_timestamps = [t for t in self.ai_call_timestamps if now - t < 900]
        
        kospi_data = self.current_data.get("KOSPI", {})
        kosdaq_data = self.current_data.get("KOSDAQ", {})
        cur_kospi_rate = float(kospi_data.get('rate', self.last_kospi_rate))
        cur_kosdaq_rate = float(kosdaq_data.get('rate', self.last_kosdaq_rate))
        
        is_fluctuated = False
        # 이전 캐시보다 지수가 1.0% 이상 확연하게 바뀌었다면 강제 갱신 조건 체결
        if abs(cur_kospi_rate - self.last_kospi_rate) >= 1.0 or abs(cur_kosdaq_rate - self.last_kosdaq_rate) >= 1.0:
            is_fluctuated = True

        call_ai = False
        if len(self.ai_call_timestamps) == 0:
            call_ai = True # 15분 경과 (호출 이력 없음)
        elif is_fluctuated and len(self.ai_call_timestamps) < 3:
            call_ai = True # 변동 감지 & 3회 리미트 미달
            
        # [추가] AI 실행 가능 시간 체크 (디버그 모드 및 수동 요청 제외)
        if call_ai and not force_ai and not is_ai_enabled_time() and not self.debug_mode:
            call_ai = False
            self.ai_override_msg = " [AI 중단: Market Closed]"

        if call_ai:
            self.ai_call_timestamps.append(now)
            self.last_kospi_rate = cur_kospi_rate
            self.last_kosdaq_rate = cur_kosdaq_rate
            
            # [개선] DEMA 정보를 포함하여 AI에게 전달
            ai_context = {
                "indices": self.current_data,
                "dema_trend": self.dema_info
            }
            ai_result = self.ai_advisor.verify_market_vibe(ai_context, heuristic_vibe)
            if ai_result:
                self.finalized_ai_vibe = ai_result
                if ai_result.upper() != heuristic_vibe.upper():
                    self.ai_override_msg = f" [AI 교정: {ai_result} (기존: {heuristic_vibe})]"
                else:
                    self.ai_override_msg = " [AI 검증 일치]"
            else:
                # 오류/타임아웃 발생 -> 단독 휴리스틱 모드(Fallback)
                if not self.finalized_ai_vibe:
                    self.ai_override_msg = "" # 첫 체결 전이면 메시지 지움

        # 만약 AI 캐시값이 있고, 그게 휴리스틱과 다르면 최신 분석된 AI 결과를 계속 적용
        if self.finalized_ai_vibe:
            if self.finalized_ai_vibe.upper() != heuristic_vibe.upper():
                self.ai_override_msg = f" [AI 교정: {self.finalized_ai_vibe} (기존: {heuristic_vibe})]"
                return self.finalized_ai_vibe
            else:
                self.ai_override_msg = " [AI 검증: 일치]"
                return heuristic_vibe
                
        self.ai_override_msg = ""
        return heuristic_vibe

    def _check_circuit_breaker(self) -> str:
        vix = self.current_data.get("VOSPI")
        if vix and (vix['price'] >= 25.0 or vix['rate'] >= 5.0): return "DEFENSIVE"
        usd_krw = self.current_data.get("FX_USDKRW")
        nas = self.current_data.get("NASDAQ")
        btc = self.current_data.get("BTC_USD")
        
        # 비트코인 5% 이상 폭락 시 방어모드 전환
        if btc and btc['rate'] <= -5.0: return "DEFENSIVE"
        
        if usd_krw and nas and usd_krw['price'] >= 1500.0 and nas['rate'] <= -1.0: return "DEFENSIVE"
        return "Neutral"

    def _check_global_panic(self) -> bool:
        us_targets = ["NASDAQ", "S&P500", "NAS_FUT", "SPX_FUT"]
        for target in us_targets:
            data = self.current_data.get(target)
            if data and data['rate'] <= -1.5: return True
            
        # 비트코인 급락(-3.5% 이상) 시 글로벌 패닉 트리거
        btc = self.current_data.get("BTC_USD")
        if btc and btc['rate'] <= -3.5: return True
        
        return False

    def _check_kr_vibe(self) -> str:
        dema_signals = []
        kr_targets = {"KOSPI": "0001", "KOSDAQ": "1001"}
        active_kr = [self.current_data.get(k) for k in kr_targets if self.current_data.get(k)]
        if not active_kr: return "Neutral"
        
        avg_rate = sum(idx['rate'] for idx in active_kr) / len(active_kr)
        
        # [최적화] DEMA 추세 분석 (30분 주기로 갱신)
        now = time.time()
        if self.indicator_eng and (now - self.last_dema_update > 1800 or not self.dema_info):
            for name, code in kr_targets.items():
                try:
                    # 최근 60일 데이터 수집 (DEMA 계산용)
                    candles = self.api.get_index_chart_price(code, period_div="D")
                    if candles and len(candles) >= 40: # 최소 데이터 확보
                        prices = [float(c.get('stck_clpr', 0)) for c in candles]
                        dema_20 = self.indicator_eng.calculate_dema(prices, 20)
                        curr_p = prices[0]
                        self.dema_info[name] = {"price": curr_p, "dema": dema_20}
                except Exception as e:
                    log_error(f"지수 DEMA 계산 오류 ({name}): {e}")
            self.last_dema_update = now

        for name in kr_targets.keys():
            if name in self.dema_info:
                info = self.dema_info[name]
                if info['price'] > info['dema']: dema_signals.append("BULL")
                elif info['price'] < info['dema']: dema_signals.append("BEAR")

        # 종합 판단: 당일 등락률 + DEMA 추세
        # 1. 강력한 상승 (평균 0.5% 이상 & DEMA 지지)
        if avg_rate >= 0.5 and "BULL" in dema_signals:
            return "Bull"
        # 2. 강력한 하락 (평균 -0.5% 이하 & DEMA 저항)
        if avg_rate <= -0.5 and "BEAR" in dema_signals:
            return "Bear"
        
        # 3. 추세는 상승인데 오늘만 조종이거나, 추세는 하락인데 오늘만 반등인 경우 -> 중립 또는 기존 유지
        # 여기서는 좀 더 보수적으로 접근
        if avg_rate > 0 and dema_signals.count("BULL") == len(kr_targets):
            return "Bull"
        if avg_rate < 0 and dema_signals.count("BEAR") == len(kr_targets):
            return "Bear"
            
        return "Neutral"
