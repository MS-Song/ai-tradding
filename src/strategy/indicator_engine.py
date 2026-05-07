import math
from typing import List, Dict, Optional

class IndicatorEngine:
    """기술적 분석 지표(RSI, Bollinger Bands, MACD 등)를 계산하는 엔진"""

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> float:
        """상대강도지수(RSI)를 계산합니다."""
        if len(prices) < period + 1: return 50.0
        
        # KIS 데이터는 최신순(Index 0이 현재)이므로 계산을 위해 뒤집음 (과거 -> 현재)
        data = list(reversed(prices))
        
        deltas = [data[i+1] - data[i] for i in range(len(data)-1)]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        # 초기값: 단순 평균
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        # 웰더스 이동평균(Wilder's Smoothing) 적용
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, multiplier: float = 2.0) -> Dict[str, float]:
        """볼린저 밴드(중심선, 상단선, 하단선)를 계산합니다."""
        if len(prices) < period: 
            return {"mid": 0, "upper": 0, "lower": 0, "percent_b": 0.5}
        
        # 최신 n일 데이터 추출
        subset = prices[:period]
        avg = sum(subset) / period
        variance = sum([(x - avg) ** 2 for x in subset]) / period
        stdev = math.sqrt(variance)
        
        upper = avg + (stdev * multiplier)
        lower = avg - (stdev * multiplier)
        
        curr_price = prices[0]
        percent_b = (curr_price - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
        
        return {
            "mid": avg,
            "upper": upper,
            "lower": lower,
            "percent_b": percent_b # 밴드 내 현재가 위치 (1.0이면 상단 돌파, 0.0이면 하단 돌파)
        }

    @staticmethod
    def calculate_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, float]:
        """MACD 지표(MACD선, 시그널선, 히스토그램)를 계산합니다."""
        if len(prices) < slow + signal: 
            return {"macd": 0, "signal": 0, "hist": 0}
        
        data = list(reversed(prices)) # 과거 -> 현재
        
        def get_ema(values, n):
            ema = [sum(values[:n]) / n] # 초기값은 SMA
            multiplier = 2 / (n + 1)
            for i in range(n, len(values)):
                ema.append((values[i] - ema[-1]) * multiplier + ema[-1])
            return ema

        ema_fast = get_ema(data, fast)
        ema_slow = get_ema(data, slow)
        
        # 두 EMA의 길이를 맞춤
        offset = slow - fast
        macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
        
        signal_line = get_ema(macd_line, signal)
        
        curr_macd = macd_line[-1]
        curr_signal = signal_line[-1]
        
        return {
            "macd": curr_macd,
            "signal": curr_signal,
            "hist": curr_macd - curr_signal
        }

    @staticmethod
    def calculate_dema(prices: List[float], period: int = 20) -> float:
        """이중 지수 이동 평균(DEMA)을 계산합니다.
        DEMA = 2 * EMA(n) - EMA(EMA(n))
        """
        if len(prices) < period * 2: 
            return prices[0] if prices else 0.0
            
        data = list(reversed(prices)) # 과거 -> 현재
        
        def get_ema_list(values, n):
            if len(values) < n: return values
            ema = [sum(values[:n]) / n]
            multiplier = 2 / (n + 1)
            for i in range(n, len(values)):
                ema.append((values[i] - ema[-1]) * multiplier + ema[-1])
            return ema

        ema1 = get_ema_list(data, period)
        ema2 = get_ema_list(ema1, period)
        
        # ema2는 ema1보다 period-1 만큼 짧음
        curr_ema1 = ema1[-1]
        curr_ema2 = ema2[-1]
        
        dema = (2 * curr_ema1) - curr_ema2
        return dema

    @staticmethod
    def calculate_sma(prices: List[float], periods: List[int] = [5, 10, 20, 60]) -> Dict[str, float]:
        """단순이동평균선(SMA)을 계산합니다."""
        result = {}
        for p in periods:
            if len(prices) >= p:
                subset = prices[:p]
                result[f"sma_{p}"] = sum(subset) / p
            else:
                result[f"sma_{p}"] = 0.0
        return result

    @staticmethod
    def calculate_ema(prices: List[float], period: int = 20) -> List[float]:
        """지수이동평균(EMA)을 계산하여 리스트로 반환합니다. (과거 -> 현재 순서)"""
        if len(prices) < period: return []
        
        # KIS 데이터는 최신순이므로 계산을 위해 뒤집음 (과거 -> 현재)
        data = list(reversed(prices))
        
        ema = [sum(data[:period]) / period] # 초기값은 SMA
        multiplier = 2 / (period + 1)
        
        for i in range(period, len(data)):
            ema_val = (data[i] - ema[-1]) * multiplier + ema[-1]
            ema.append(ema_val)
            
        return ema

    @staticmethod
    def calculate_dema(prices: List[float], period: int = 20) -> float:
        """이중 지수이동평균(DEMA)의 현재값을 계산합니다.
        DEMA = 2 * EMA(n) - EMA(EMA(n))
        """
        ema1 = IndicatorEngine.calculate_ema(prices, period)
        if not ema1: return 0.0
        
        # EMA1의 결과(리스트)를 다시 EMA 취함
        # calculate_ema는 내부에서 reversed를 하므로, 이미 과거->현재인 ema1을 넘기기 전에 다시 뒤집어줌
        ema2 = IndicatorEngine.calculate_ema(list(reversed(ema1)), period)
        if not ema2: return ema1[-1] # fallback to EMA if DEMA cannot be calculated
        
        # DEMA = 2 * EMA1 - EMA2
        dema_val = (2 * ema1[-1]) - ema2[-1]
        return dema_val

    def get_dual_timeframe_analysis(self, api, code: str, name: str = "") -> Dict[str, any]:
        """일봉(중기) + 분봉(단기) 이중 타임프레임 분석을 수행합니다.
        데이터 소스 우선순위:
          분봉: 1) KIS API → 2) 네이버 F-Chart XML
          일봉: 1) KIS API → 2) 네이버 모바일 JSON (get_naver_stocks_realtime 가격 + 과거 이력 없이 오늘 기준)
        """
        analysis = {
            "daily": {"trend": "UNKNOWN", "ma": {}},
            "minute": {"ma": {}},
            "signal": "NEUTRAL",
            "reason": ""
        }

        # 로그용 명칭 (이름이 있으면 이름(코드), 없으면 코드)
        display_name = f"{name}({code})" if name else code

        def safe_float(v):
            try: return float(str(v).strip()) if v and str(v).strip() else 0.0
            except: return 0.0

        try:
            # ── 1. 일봉 분석 (KIS 우선) ──────────────────────────────────
            daily_candles = []
            try:
                daily_candles = api.get_daily_chart_price(code)
            except Exception as e:
                from src.logger import logger
                logger.warning(f"[MA폴백] {display_name} KIS 일봉 실패: {e}")

            if not daily_candles:
                # Fallback: 네이버 F-Chart XML 일봉 데이터
                try:
                    from src.logger import logger
                    if hasattr(api, 'get_naver_daily_chart'):
                        daily_candles = api.get_naver_daily_chart(code)
                        if daily_candles:
                            logger.debug(f"[MA폴백] {display_name} 일봉 → 네이버 F-Chart 사용")
                except Exception as fe:
                    pass

            if daily_candles:
                closes = [safe_float(c.get('stck_prpr') or c.get('stck_clpr')) for c in daily_candles]
                ma_data = self.calculate_sma(closes, [5, 20, 60])
                curr_price = closes[0]
                sma_20 = ma_data.get("sma_20", 0)
                trend = "UP" if curr_price >= sma_20 and sma_20 > 0 else "DOWN"
                analysis["daily"] = {"trend": trend, "ma": ma_data, "curr": curr_price}

            # ── 2. 분봉 분석 (KIS 우선 → 네이버 F-Chart 폴백) ────────────
            minute_candles = []
            minute_source = "KIS"
            try:
                minute_candles = api.get_minute_chart_price(code)
            except Exception as e:
                from src.logger import logger
                logger.warning(f"[MA폴백] {display_name} KIS 분봉 실패: {e}")

            if not minute_candles:
                # Fallback: 네이버 F-Chart XML 분봉 (이미 naver.py에 구현됨)
                try:
                    from src.logger import logger
                    if hasattr(api, 'get_naver_minute_chart'):
                        minute_candles = api.get_naver_minute_chart(code, count=40)
                        if minute_candles:
                            minute_source = "Naver-FChart"
                            logger.debug(f"[MA폴백] {display_name} 분봉 → 네이버 F-Chart XML 사용")
                except Exception as fe:
                    from src.logger import log_error
                    log_error(f"[MA폴백] {display_name} 네이버 F-Chart 분봉 실패: {fe}")

            if minute_candles:
                closes = [safe_float(c.get('stck_prpr') or c.get('stck_clpr')) for c in minute_candles]
                ma_data = self.calculate_sma(closes, [5, 20, 60])
                curr_price = closes[0]
                analysis["minute"] = {"ma": ma_data, "curr": curr_price, "source": minute_source}

                # ── 3. 복합 시그널 로직 ──────────────────────────────────
                sma_20_min = ma_data.get("sma_20", 0)
                daily_trend = analysis["daily"]["trend"]

                if daily_trend == "UP":
                    if sma_20_min > 0:
                        gap_pct = ((curr_price - sma_20_min) / sma_20_min) * 100
                        if -1.5 <= gap_pct <= 1.0:
                            analysis["signal"] = "BUY_ZONE"
                            analysis["reason"] = f"일봉 상승추세 + 분봉 20MA 지지선 근접 [{minute_source}]"
                        elif gap_pct > 3.0:
                            analysis["signal"] = "OVERBOUGHT"
                            analysis["reason"] = f"단기 이평선 괴리 과열 (추격 주의) [{minute_source}]"
                        else:
                            analysis["signal"] = "NEUTRAL"
                            analysis["reason"] = f"일봉 상승추세, 분봉 중립 [{minute_source}]"
                else:
                    analysis["signal"] = "CAUTION"
                    analysis["reason"] = "일봉 하락추세 (역배열 주의)"
            else:
                # 분봉 데이터를 어디서도 가져오지 못한 경우 → UNKNOWN 으로 명시
                analysis["signal"] = "UNKNOWN"
                analysis["reason"] = "분봉 데이터 취득 실패 (KIS + Naver 모두 실패)"

        except Exception as e:
            analysis["reason"] = f"분석 오류: {str(e)}"

        return analysis


    def get_all_indicators(self, candles: List[dict]) -> Dict[str, any]:
        """캔들 데이터를 받아 종합 지표 세트를 반환합니다."""
        if not candles: return {}
        
        # 종가(Close) 리스트 추출
        def safe_float(v):
            try: return float(str(v).strip()) if v and str(v).strip() else 0.0
            except: return 0.0
        closes = [safe_float(c.get('stck_prpr') or c.get('stck_clpr')) for c in candles]
        if not closes: return {}
        
        return {
            "rsi": self.calculate_rsi(closes),
            "bb": self.calculate_bollinger_bands(closes),
            "macd": self.calculate_macd(closes),
            "sma": self.calculate_sma(closes, [5, 10, 20, 60]),
            "curr_price": closes[0]
        }
