import math
from typing import List, Dict, Optional

class IndicatorEngine:
    """기술적 분석 지표(RSI, Bollinger Bands, MACD 등)를 계산하는 엔진"""

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> float:
        """상대강도지수(Relative Strength Index)를 계산합니다.
        
        웰더스 이동평균(Wilder's Smoothing) 방식을 사용하여 가격의 상승/하락 강도를 측정합니다.

        Args:
            prices (List[float]): 최신순 종가 리스트.
            period (int, optional): RSI 계산 기간. 기본값 14.

        Returns:
            float: 0~100 사이의 RSI 값. 데이터 부족 시 50.0 반환.
        """
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
        """볼린저 밴드(Bollinger Bands)를 계산합니다.

        Args:
            prices (List[float]): 최신순 종가 리스트.
            period (int, optional): 이동평균 및 표준편차 계산 기간. 기본값 20.
            multiplier (int, optional): 상/하단 밴드 너비 계수. 기본값 2.0.

        Returns:
            Dict[str, float]: 밴드 정보 (mid, upper, lower, percent_b).
        """
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
        """MACD 지표(Moving Average Convergence Divergence)를 계산합니다.

        Args:
            prices (List[float]): 최신순 종가 리스트.
            fast (int, optional): 단기 EMA 기간. 기본값 12.
            slow (int, optional): 장기 EMA 기간. 기본값 26.
            signal (int, optional): 시그널선 기간. 기본값 9.

        Returns:
            Dict[str, float]: MACD 정보 (macd, signal, hist).
        """
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
        """이중 지수 이동 평균(Double Exponential Moving Average)을 계산합니다.
        
        DEMA = 2 * EMA(n) - EMA(EMA(n)) 식을 사용하여 지연(Lag)을 최소화합니다.

        Args:
            prices (List[float]): 최신순 종가 리스트.
            period (int, optional): 계산 기간. 기본값 20.

        Returns:
            float: 최신 DEMA 값.
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
        """지정된 기간들에 대한 단순이동평균선(SMA)을 계산합니다.

        Args:
            prices (List[float]): 최신순 종가 리스트.
            periods (List[int], optional): 계산할 이동평균 기간 리스트. 기본값 [5, 10, 20, 60].

        Returns:
            Dict[str, float]: 각 기간별 SMA 값을 포함하는 딕셔너리 (예: {"sma_20": 120000.0}).
        """
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
        """지수이동평균(EMA)의 전체 히스토리를 계산하여 반환합니다.

        Args:
            prices (List[float]): 최신순 종가 리스트.
            period (int, optional): 계산 기간. 기본값 20.

        Returns:
            List[float]: 과거부터 현재 순서로 나열된 EMA 값 리스트. 데이터 부족 시 빈 리스트 반환.
        """
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
        
        계산식: DEMA = 2 * EMA(n) - EMA(EMA(n))
        DEMA는 일반 EMA보다 시세 추종 속도가 빠르고 지연(Lag)이 적은 특징이 있습니다.

        Args:
            prices (List[float]): 최신순 종가 리스트.
            period (int, optional): 계산 기간. 기본값 20.

        Returns:
            float: 최신 DEMA 값. 계산 불가 시 0.0 또는 EMA1 값 반환.
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
        """일봉(중기 추세)과 분봉(단기 타점)을 결합한 이중 타임프레임 분석을 수행합니다.

        일봉 20MA 추세와 분봉 20MA 지지 여부를 교차 검증하여 BUY_ZONE, OVERBOUGHT 
        등의 시그널을 생성합니다. KIS API 장애 시 네이버 F-Chart 데이터로 자동 폴백합니다.

        Args:
            api: KIS API 클라이언트 객체.
            code (str): 분석할 종목 코드.
            name (str, optional): 종목명.

        Returns:
            Dict[str, any]: 분석 결과 (daily trend, minute ma, signal, reason).
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
        """캔들 데이터를 받아 종합 기술적 지표 세트를 한 번에 계산하여 반환합니다.

        RSI, 볼린저 밴드, MACD, SMA(5, 10, 20, 60)를 일괄 처리합니다.

        Args:
            candles (List[dict]): API로부터 수집된 캔들 데이터 리스트.

        Returns:
            Dict[str, any]: 모든 기술적 지표를 포함하는 딕셔너리. 데이터가 없거나 유효하지 않으면 빈 딕셔너리 반환.
        """
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
