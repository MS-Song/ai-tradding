import os
import json
import math
import time
import requests
import re
import threading
from datetime import datetime, timedelta, time as dtime
from typing import Dict, List, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.logger import logger, log_error

# --- KIS 프리셋 전략 카탈로그 (10개 공식 전략 + 표준) ---
PRESET_STRATEGIES = {
    "00": {"id": "00", "name": "표준",       "type": "기본",     "desc": "시스템 기본 TP/SL 적용 (Vibe 보정 포함)",
           "default_tp": None, "default_sl": None},  # None이면 시스템 기본값 사용
    "01": {"id": "01", "name": "골든크로스", "type": "추세추종", "desc": "단기 MA가 장기 MA 상향 돌파 시 매수",
           "default_tp": 8.0, "default_sl": -4.0},
    "02": {"id": "02", "name": "모멘텀",     "type": "추세추종", "desc": "최근 N일 수익률 상위 종목 매수",
           "default_tp": 10.0, "default_sl": -5.0},
    "03": {"id": "03", "name": "52주신고가", "type": "돌파매매", "desc": "52주 최고가 갱신 시 매수",
           "default_tp": 12.0, "default_sl": -3.0},
    "04": {"id": "04", "name": "연속상승",   "type": "추세추종", "desc": "N일 연속 종가 상승 시 매수",
           "default_tp": 7.0, "default_sl": -4.0},
    "05": {"id": "05", "name": "이격도",     "type": "역추세",   "desc": "이동평균 대비 과열/침체 판단",
           "default_tp": 5.0, "default_sl": -3.0},
    "06": {"id": "06", "name": "돌파실패",   "type": "손절",     "desc": "전고점 돌파 후 재하락 시 손절",
           "default_tp": 4.0, "default_sl": -2.0},
    "07": {"id": "07", "name": "강한종가",   "type": "모멘텀",   "desc": "종가가 당일 고가 근처 마감 시 매수",
           "default_tp": 6.0, "default_sl": -3.5},
    "08": {"id": "08", "name": "변동성확장", "type": "돌파매매", "desc": "변동성 축소 후 급등 시 매수",
           "default_tp": 9.0, "default_sl": -4.0},
    "09": {"id": "09", "name": "평균회귀",   "type": "역추세",   "desc": "평균에서 크게 이탈 시 반대 방향 매매",
           "default_tp": 4.0, "default_sl": -3.0},
    "10": {"id": "10", "name": "추세필터",   "type": "추세추종", "desc": "장기 MA 위 상승 중이면 매수",
           "default_tp": 8.0, "default_sl": -5.0},
}

# --- 1. MarketAnalyzer: 시장 분석 엔진 ---
class MarketAnalyzer:
    def __init__(self, api):
        self.api = api
        self.current_data = {}
        self.is_panic = False
        self.kr_vibe = "Neutral"
        
        # AI 검증 연동용
        self.ai_advisor = None
        self.ai_call_timestamps = []
        self.last_kospi_rate = 0.0
        self.last_kosdaq_rate = 0.0
        self.ai_override_msg = ""
        self.finalized_ai_vibe = None # 캐시된 마지막 AI 판정

    def update(self) -> Tuple[str, bool]:
        symbol_map = {
            "KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KPI200": "KPI200", "VOSPI": "VOSPI",
            "FX_USDKRW": "FX_USDKRW", "DOW": "DOW", "NASDAQ": "NASDAQ", "S&P500": "S&P500",
            "NAS_FUT": "NAS_FUT", "SPX_FUT": "SPX_FUT", "BTC_USD": "BTC_USD", "BTC_KRW": "BTC_KRW"
        }
        with ThreadPoolExecutor(max_workers=len(symbol_map)) as executor:
            future_to_symbol = {executor.submit(self.api.get_index_price, code): s for s, code in symbol_map.items()}
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    data = future.result()
                    if data: self.current_data[symbol] = data
                except Exception as e:
                    log_error(f"Index Fetch Error ({symbol}): {e}")
        # 1차 평가 (알고리즘 기반 휴리스틱)
        heuristic_vibe = self._check_circuit_breaker()
        if heuristic_vibe == "Neutral":
            heuristic_vibe = self._check_kr_vibe()
        
        # BTC 기반 VIBE 추가 보정: 비트코인 급락 시 Bull -> Neutral 강제 하향
        btc = self.current_data.get("BTC_USD")
        if btc and btc['rate'] <= -2.5 and heuristic_vibe == "Bull":
            heuristic_vibe = "Neutral"
            
        # 2. AI 검증 로직 연결 (단, 오류나 토큰 초과 시 원래 휴리스틱으로 Fallback)
        self.kr_vibe = self._verify_with_ai(heuristic_vibe)
            
        return self.kr_vibe, self.is_panic
        
    def _verify_with_ai(self, heuristic_vibe: str) -> str:
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
            
        if call_ai:
            self.ai_call_timestamps.append(now)
            self.last_kospi_rate = cur_kospi_rate
            self.last_kosdaq_rate = cur_kosdaq_rate
            
            ai_result = self.ai_advisor.verify_market_vibe(self.current_data, heuristic_vibe)
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
        kr_targets = ["KOSPI", "KOSDAQ"]
        active_kr = [self.current_data.get(k) for k in kr_targets if self.current_data.get(k)]
        if not active_kr: return "Neutral"
        avg_rate = sum(idx['rate'] for idx in active_kr) / len(active_kr)
        if avg_rate >= 0.5: return "Bull"
        if avg_rate <= -0.5: return "Bear"
        return "Neutral"

# --- 2. ExitManager: 수익/리스크 관리 ---
class ExitManager:
    def __init__(self, base_tp: float, base_sl: float):
        self.base_tp, self.base_sl = base_tp, base_sl
        self.manual_thresholds: Dict[str, List[float]] = {}

    def get_vibe_modifiers(self, vibe: str) -> Tuple[float, float]:
        """현재 Vibe에 따른 TP/SL 보정치 반환 (Vibe에 따른 실시간 대응)"""
        tp_mod, sl_mod = 0.0, 0.0
        v = vibe.upper()
        if v == "BULL":
            tp_mod = 3.0    # 상승장: 수익 극대화 (익절가 상향)
            sl_mod = 1.0    # 상승장: 손절선 소폭 완화
        elif v == "BEAR":
            tp_mod = -2.0   # 하락장: 짧은 익절 (보수적)
            sl_mod = -2.0   # 하락장: 손절선 타이트하게 관리
        elif v == "DEFENSIVE":
            tp_mod, sl_mod = -3.0, -3.0 # 방어모드: 극도로 보수적
        return tp_mod, sl_mod

    def get_thresholds(self, code: str, kr_vibe: str, price_data: Optional[dict] = None, phase_cfg: dict = None) -> Tuple[float, float, bool]:
        # 1. 특정 종목 수동 설정(Manual)이 있으면 최우선 적용 (보정 없음)
        if code in self.manual_thresholds:
            vals = self.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), True
            
        # 2. 기본값(AI가 설정한 값 포함) 가져오기
        target_tp, target_sl = self.base_tp, self.base_sl
        
        # 3. 시장 분위기(Vibe)에 따른 실시간 보정 적용
        tp_mod, sl_mod = self.get_vibe_modifiers(kr_vibe)
        
        # 시간 페이즈 보정 합산
        if phase_cfg:
            tp_mod += phase_cfg.get('tp_delta', 0)
            # 하락장 예외: Bear/Defensive일 때는 P1의 SL 완화 적용 안 함
            if not (kr_vibe.upper() in ["BEAR", "DEFENSIVE"] and phase_cfg['id'] == "P1"):
                sl_mod += phase_cfg.get('sl_delta', 0)
        
        target_tp += tp_mod
        target_sl += sl_mod
            
        # 4. 개별 종목 변동성(거래량 등)에 따른 추가 보정
        is_vol_spike = False
        if price_data and price_data.get('prev_vol', 0) > 0:
            if price_data['vol'] / price_data['prev_vol'] >= 1.5:
                target_tp += 2.0; is_vol_spike = True # 거래량 폭발 시 익절가 상향
                
        return round(target_tp, 1), round(target_sl, 1), is_vol_spike

# --- 3. TradingEngines: 물타기 & 불타기 ---
class RecoveryEngine:
    def __init__(self, config: dict):
        self.config = config
        self.last_avg_down_prices: Dict[str, float] = {}

    def get_recommendation(self, item: dict, is_panic: bool, current_sl: float) -> Optional[dict]:
        if is_panic: return None
        code = item.get("pdno")
        curr_price, curr_avg = float(item.get("prpr", 0)), float(item.get("pchs_avg_pric", 0))
        curr_rt = float(item.get("evlu_pfls_rt", 0.0))
        
        config_trig = self.config.get("min_loss_to_buy", -3.0)
        min_safety_gap = 1.0
        
        final_trig = config_trig
        if config_trig <= current_sl:
            final_trig = current_sl + min_safety_gap
        elif (config_trig - current_sl) < min_safety_gap:
            final_trig = current_sl + min_safety_gap
            
        if current_sl < curr_rt <= final_trig and curr_price < curr_avg:
            last_p = self.last_avg_down_prices.get(code, curr_avg)
            if code not in self.last_avg_down_prices or ((curr_price - last_p) / last_p * 100) <= -2.0:
                return self._simulate(item, self.config.get("average_down_amount", 500000))
        return None

    def _simulate(self, item: dict, amt: int) -> dict:
        curr_avg, curr_qty, curr_p = float(item.get("pchs_avg_pric", 0)), float(item.get("hldg_qty", 0)), float(item.get("prpr", 0))
        buy_qty = math.floor(amt / curr_p)
        if buy_qty > 0:
            new_avg = ((curr_avg * curr_qty) + (buy_qty * curr_p)) / (curr_qty + buy_qty)
            return {"code": item.get("pdno"), "name": item.get("prdt_name"), "suggested_amt": amt, "type": "물타기",
                    "expected_avg_change": f"{int(new_avg - curr_avg):+,}({abs(((new_avg-curr_avg)/curr_avg*100) if curr_avg>0 else 0):.2f}%)"}
        return {}

class PyramidingEngine:
    def __init__(self, config: dict):
        self.config = config
        self.last_buy_prices: Dict[str, float] = {}

    def get_recommendation(self, item: dict, vibe: str, is_panic: bool, vol_spike: bool, tp_threshold: float) -> Optional[dict]:
        if is_panic or vibe.lower() in ["bear", "defensive"]: return None
        code = item.get("pdno")
        curr_p, curr_avg = float(item.get("prpr", 0)), float(item.get("pchs_avg_pric", 0))
        curr_rt = float(item.get("evlu_pfls_rt", 0.0))
        
        trig = self.config.get("min_profit_to_pyramid", 3.0)
        # 익절과 겹치지 않도록 방어: 불타기 트리거는 현재 설정된 익절값(TP)보다 최소 1.0% 낮아야 함
        trig = min(trig, tp_threshold - 1.0)
        
        if curr_rt >= trig and (vibe.lower() == "bull" or vol_spike) and curr_p > curr_avg:
            last_p = self.last_buy_prices.get(code, curr_avg)
            if curr_p > last_p * 1.02:
                amt = self.config.get("average_down_amount", 500000)
                return {"code": code, "name": item.get("prdt_name"), "suggested_amt": amt, "type": "불타기", "expected_avg_change": "수익 비중 확대"}
        return None

# --- 4. VibeAlphaEngine: AI 자율 매매 ---
class VibeAlphaEngine:
    def __init__(self, api):
        self.api = api
        self.ai_advisor = None # To be injected by strategy for Gemini sentiment
        self._lock = threading.Lock()

    def analyze(self, themes: List[dict], hot_raw: List[dict], vol_raw: List[dict], min_score: float = 60.0, progress_cb: Optional[Callable] = None, kr_vibe: str = "Neutral", market_data: dict = None, on_item_found: Optional[Callable] = None) -> List[dict]:
        """주도 테마 및 랭킹 데이터를 분석하여 국내 종목과 ETF 분리 추출 (병렬 처리)"""
        from src.theme_engine import THEME_KEYWORDS
        
        combined = hot_raw + vol_raw
        candidates = []
        seen = set()

        for item in combined:
            code = item['code']
            if code in seen: continue
            seen.add(code)
            if not (len(code) == 6 and code.isdigit()): continue
            
            my_theme = {"name": "기타", "count": 1}
            for t in themes:
                keywords = THEME_KEYWORDS.get(t['name'], [])
                if any(kw.lower() in item.get('name','').lower() for kw in keywords):
                    my_theme = t; break
            
            is_hot = any(x['code'] == code for x in hot_raw)
            candidates.append((item, my_theme, is_hot))

        # 펀더멘털 데이터 병렬 수집 (속도 개선 핵심)
        current = 0
        total = len(candidates)
        lock = threading.Lock()
        
        stocks_pool, etfs_pool = [], []

        def fetch_detail_and_score(cand):
            nonlocal current
            item, my_theme, is_hot = cand
            code = item['code']
            
            # API 호출 (캐시)
            detail = self.api.get_naver_stock_detail(code)
            # 뉴스 API 호출 (옵션 - 1차 통과시에만 할 수도 있지만 여기서 미리 가져와도 캐시가 있으면 빠름. 그러나 속도를 위해 여기선 제외)
            
            # 스코어 계산시 kr_vibe와 market_data 전달
            item_score = self._calculate_ai_score(item, my_theme, False, kr_vibe, market_data, detail, is_hot)
            
            is_etf = any(ex in item['name'].upper() for ex in ["KODEX", "TIGER", "KBSTAR", "ACE", "RISE", "SOL", "HANARO"])
            is_inverse = "인버스" in item['name']
            
            # Defensive/Bear 가 아닐 때 인버스는 아예 제외. 
            # 인버스가 방어 목적이라 해도 평소엔 불필요하므로 최소 점수 미달 처리, 하지만 방어장이면 가점
            
            with lock:
                current += 1
                if progress_cb:
                    progress_cb(current, total, f"분석 중: {item['name']}")
                    
            if item_score >= min_score:
                res = {**item, "score": item_score, "theme": my_theme['name'], "is_gem": False, "reason": f"{my_theme['name']} 모멘텀", "is_etf": is_etf, "is_inverse": is_inverse}
                if not is_etf:
                    rate = float(item.get('rate', 0))
                    if rate <= 10.0:  # 너무 급등한 종목 제외
                        with lock: stocks_pool.append(res)
                        if on_item_found: on_item_found(res)
                else:
                    with lock: etfs_pool.append(res)
                    if on_item_found: on_item_found(res)

        # 병렬 처리로 지표와 1차 점수 수집
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(fetch_detail_and_score, candidates))

        # 1차 필터링된 종목 중 Top N개 선별
        top_stocks = sorted(stocks_pool, key=lambda x: x['score'], reverse=True)[:10]
        top_etfs = sorted(etfs_pool, key=lambda x: x['score'], reverse=True)[:3]
        
        # 2차: AI 감성 분석 (Gemini Advisor 연동)
        if self.ai_advisor and top_stocks:
            total_ai = len(top_stocks)
            curr_ai = 0
            def apply_sentiment(stock_item):
                nonlocal curr_ai
                code = stock_item['code']
                news = self.api.get_naver_stock_news(code)
                detail = self.api.get_naver_stock_detail(code)
                with lock:
                    curr_ai += 1
                    if progress_cb: progress_cb(curr_ai, total_ai, f"AI 뉴스 심리 분석: {stock_item['name']}")
                
                # Gemini 감성 점수 (호재/악재 판별하여 가감점)
                # 직접 API 호출보다는 get_stock_report_advice를 활용하거나 간단히 처리 (속도 고려)
                # 여기서는 속도를 위해 뉴스 키워드 기반 단순 가점, 또는 짧은 프롬프트 호출
                # 구현 편의상 AI Advisor가 이미 연결되어 있다면 짧은 분석 요청
                if news:
                    news_txt = " ".join(news[:5])
                    # 긍정 키워드 발견 시 소폭 가점, 부정 키워드 시 감점 (1차 휴리스틱 연계)
                    pos = sum(1 for p in ["수주", "흑자", "성장", "돌파", "개발", "MOU", "상장", "공급", "계약"] if p in news_txt)
                    neg = sum(1 for n in ["적자", "하락", "매도", "우려", "리스크", "해지", "소송", "횡령"] if n in news_txt)
                    stock_item['score'] += (pos * 2.0) - (neg * 3.0)
                    if pos > 0: stock_item['reason'] = f"뉴스 호재 모멘텀 및 {stock_item['reason']}"
            
            with ThreadPoolExecutor(max_workers=5) as executor:
                list(executor.map(apply_sentiment, top_stocks))

        # 최종 정렬 후 개별 종목 상위 8개, ETF 상위 2개 선정 (8+2 구조)
        final_stocks = sorted(top_stocks, key=lambda x: x['score'], reverse=True)[:8]
        final_etfs = sorted(top_etfs, key=lambda x: x['score'], reverse=True)[:2]
        
        return final_stocks + final_etfs

    def _calculate_ai_score(self, stock: dict, theme: dict, is_gem: bool, kr_vibe: str = "Neutral", market_data: dict = None, detail: dict = None, is_hot: bool = False) -> float:
        """종목별 입체 점수 산정 (테마 + 등락률 + 실시간 수급 모멘텀 + 펀더멘털 + 장세 기반 보정)"""
        score = 40.0 # 기본 베이스 점수
        rate = abs(float(stock.get('rate', 0)))
        
        # 1. 장세 기반 동적 가중치 설정
        v = str(kr_vibe).upper()
        mo_weight = 3.0   # 모멘텀 가중치 (기본)
        val_weight = 1.0  # 가치형 가중치 (기본)
        div_weight = 0.0  # 배당 가중치 (기본)
        
        if v == "BULL":
            mo_weight = 4.0      # 상승장엔 달리는 말 우선
        elif v == "BEAR":
            mo_weight = 1.5      # 하락장에선 모멘텀 신뢰도 하락
            val_weight = 2.0     # 펀더멘털 중요성 상승
            div_weight = 5.0     # 배당(방어) 메리트 추가
        elif v == "DEFENSIVE":
            mo_weight = 1.0
            val_weight = 2.5
            div_weight = 8.0
        
        # 2. 등락률/테마 점수 (모멘텀)
        # 0%에 가까울수록 선취매 매력도 상승
        score += (5.0 - min(5.0, rate)) * mo_weight
        # 테마 내 밀집도 반영
        score += min(15, theme['count'] * (mo_weight / 2.0))
        
        # 검색 상위 (핫 리스트) 종목 특별 가점 (저평가 가치주 위주 편향 방지 및 모멘텀 편입)
        if is_hot:
            score += 15.0 * mo_weight
        
        # 3. 펀더멘털 지표 보정 및 상대 가치 평가 (업종 PER 비교)
        if not detail:
            detail = self.api.get_naver_stock_detail(stock['code'])
            
        try:
            # PBR 보정
            pbr_val = float(detail.get('pbr', '0').replace(',', '')) if detail.get('pbr') != 'N/A' else 1.0
            if pbr_val <= 1.0: score += (15.0 * val_weight)
            elif pbr_val <= 3.0: score += (8.0 * val_weight)
            elif pbr_val >= 10.0: score -= (15.0 * val_weight)
            
            # PER 보정
            per_val = float(detail.get('per', '0').replace(',', '')) if detail.get('per') != 'N/A' else 20.0
            if per_val <= 10.0: score += (10.0 * val_weight)
            elif per_val <= 20.0: score += (5.0 * val_weight)
            elif per_val >= 50.0: score -= (10.0 * val_weight)
            
            # 업종 상대 PER 보정 (종목 PER가 업종 평균보다 낮을 경우 가산점)
            sector_per_str = str(detail.get('sector_per', '0')).replace(',', '').replace('%', '')
            sector_per = float(sector_per_str) if sector_per_str != 'N/A' else 0.0
            if sector_per > 0 and per_val > 0 and per_val < sector_per:
                score += (8.0 * val_weight) # 업종 대비 저평가 보너스
            
            # 배당률(Yield) 보정 (하락장 방어주 발굴)
            yld_val = float(str(detail.get('yield', '0')).replace(',', '').replace('%', '')) if detail.get('yield') != 'N/A' else 0.0
            if yld_val >= 4.0: score += div_weight
            if yld_val >= 7.0: score += div_weight * 1.5
                
        except: pass
        
        # 4. 인버스 ETF 가점 부여 (방어/하락장 전용)
        is_inverse = "인버스" in stock.get('name', ' ')
        if is_inverse:
            if v in ["BEAR", "DEFENSIVE"]: score += 20.0
            else: score -= 50.0 # 평소에는 인버스 추천 배제
        
        # 5. 거시 지표 기반 기본 컷오프 패널티 (지수 폭락 시 전체 점수 삭감)
        if market_data:
            usd_krw = market_data.get("FX_USDKRW")
            if usd_krw and usd_krw.get('rate', 0) >= 1.0: score -= 3.0 # 환율 급등 시 패널티
            
        if is_gem: score += 10.0
        
        return round(score, 1)

# --- 5. GeminiAdvisor: 생성형 AI 전략 보좌관 ---
class GeminiAdvisor:
    def __init__(self, api):
        self.api = api
        self.model_id = "gemini-2.5-flash-lite"  # 비용 최적화: 실통신 확인된 2.5 Flash-Lite (최저비용 GA)
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def get_advice(self, market_data: dict, vibe: str, holdings: List[dict], current_config: dict, recs: List[dict] = None) -> Optional[str]:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: return "⚠️ GOOGLE_API_KEY가 없습니다."
        
        holdings_txt = "\n".join([f"- {h['prdt_name']}({h['pdno']}): 수익률 {h['evlu_pfls_rt']}%" for h in holdings])
        
        recs_txt = ""
        if recs:
            # 주당 가격을 명확히 인지하도록 '1주당 현재가'라고 명시
            recs_txt = "\n".join([f"- {r['name']}({r['code']}): 1주당 현재가 {int(float(r.get('price',0))):,}원, 금일 등락 {r.get('rate',0):+.1f}%" for r in recs[:5]])

        prompt_text = f"""
        당신은 월스트리트 수석 퀀트 트레이더입니다. 아래의 **[실시간 데이터]**만을 근거로 전략을 브리핑하세요.
        
        [실시간 데이터]
        - 시장Vibe: {vibe}
        - 현재 지수 상태: {json.dumps(market_data)}
        - 현재 포트폴리오: {holdings_txt if holdings else "보유 종목 없음"}
        - **신규 추천 후보 및 1주당 시세**: 
{recs_txt if recs_txt else "추천 후보 없음"}
        - 시스템 매수 설정 금액: {current_config.get('ai_amt'):,}원
        
        [필수 내용 및 절대 규칙 - 위반 시 해고]
        1. **가격 절대 준수**: 추천주의 매수가격은 반드시 위 리스트에 제공된 '1주당 현재가'의 ±3% 이내에서만 제안하세요. 리스트에 없는 가격을 상상해서 적지 마세요.
        2. **매수 가능 여부 확인**: (매수 권장 금액)이 (추천주 1주당 현재가)보다 작으면 절대 추천하지 마세요. 최소 1주는 살 수 있어야 합니다.
        3. **수치 논리**: 추가매수(물타기) 지점 > 손절선(SL), 불타기지점 < 익절선(TP) 공식을 반드시 지키세요.
        4. **[중요] 분량 제한**: AI[액션]과 AI[추천]은 반드시 **각각 단 1줄**로만 요약하세요. 여러 줄 출력 절대 금지.
        
        [답변 형식]
        AI[시장]: 요약 (1줄)
        AI[전략]: 익절 +X.X%, 손절 -Y.Y%, 물타기 -Z.Z%, 불타기 +W.W%, 금액 N원
        AI[액션]: 포트폴리오 조정 및 매수 실행 여부 요약 (1줄 고정)
        AI[추천]: 종목명(코드), 권장매수가 N원, 예상매수주수 M주 (1줄 고정)
        한국어로 대답하세요.
        """
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        endpoint = f"{self.base_url}/models/{self.model_id}:generateContent?key={api_key}"
        try:
            res = requests.post(endpoint, json=payload, timeout=25)
            if res.status_code == 200:
                return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            return f"⚠️ AI 엔진 응답 오류 ({res.status_code})"
        except: return f"⚠️ 분석 엔진 기동 실패"

    def get_detailed_report_advice(self, recs: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key or not recs: return "분석할 종목이 없습니다."
        
        # 각 종목별 입체 데이터 병렬 수집 (현재가, 펀더멘털, 뉴스)
        current = 0
        total = len(recs)
        lock = threading.Lock()
        def fetch_enriched_data(r):
            nonlocal current
            code = r['code']
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            with lock:
                current += 1
                if progress_cb:
                    progress_cb(current, total)
            return f"""
            - {r['name']}({code}) | {r['theme']}
              * 현재가: {int(float(r.get('price',0))):,}원 | 등락률: {r.get('rate',0):+.2f}%
              * 지표: PER {detail.get('per')}, PBR {detail.get('pbr')}, 배당수익률 {detail.get('yield')}, 업종PER {detail.get('sector_per')}
              * 뉴스: {', '.join(news) if news else '최근 뉴스 없음'}
            """.strip()

        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_recs = list(executor.map(fetch_enriched_data, recs))

        recs_txt = "\n".join(enriched_recs)
        
        prompt = f"""
        당신은 월스트리트의 수석 투자 전략가이자 퀀트 분석가입니다. 
        제공된 실시간 데이터(현재가, 펀더멘털, 실시간 뉴스)를 기반으로 입체적인 종목 분석 리포트를 작성하세요.
        
        [시장 장세] {vibe}
        [실시간 추천 종목 상세 데이터]
        {recs_txt}
        
        [분석 가이드라인 및 절대 규칙]
        1. 입체적 접근: 제공된 [지표]와 [뉴스]를 반드시 연계하여 분석하십시오.
           - (예: PER가 업종 평균 대비 낮음(저평가) + 최근 수주 뉴스(모멘텀) 발생 등)
        2. 가격 논리 준수: 모든 제안 가격(매수/목표/손절)은 실시간 [현재가]를 기준으로 산출하십시오.
           - 매수 타점: 현재가 부근의 현실적인 가격.
           - 목표가: 매수 타점 대비 +5% ~ +20% (성장 가능성 및 모멘텀 반영).
           - 손절가: 매수 타점 대비 -3% ~ -7% (리스크 관리).
        3. 종목별 섹션화: 각 종목별로 [투자 근거], [매매 전략(가격)], [성장 가능성 진단]을 명확히 구분하여 작성하세요.
        4. 종합 비중 조절: 현재 장세({vibe})를 고려하여 포트폴리오 비중 조절 조언을 덧붙이세요.
        5. 경고: 임의의 데이터를 생성하지 마십시오. 오직 제공된 [현재가], [지표], [뉴스]만 근거로 삼으십시오.
        
        전문가 어조로 한국어로 12~15줄 내외로 작성하세요.
        """
        try:
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            endpoint = f"{self.base_url}/models/{self.model_id}:generateContent?key={api_key}"
            res = requests.post(endpoint, json=payload, timeout=25)
            if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text']
        except: pass
        return "종목별 입체 분석 의견을 가져오지 못했습니다."

    def get_stock_report_advice(self, code: str, name: str, detail: dict, news: List[str]) -> Optional[str]:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: return "⚠️ GOOGLE_API_KEY가 없습니다."
        
        prompt = f"""
        당신은 월스트리트 수석 투자 전략가입니다. 아래 종목에 대해 [매수/매도 고민 해결사] 관점에서 분석 리포트를 작성하세요.
        
        [종목 정보]
        - 종목명: {name} ({code})
        - 실시간 시세: {int(float(detail.get('price', 0))):,}원 ({detail.get('rate', 0.0):+.2f}%)
        - 시가총액: {detail.get('market_cap')}
        - 지표: PER {detail.get('per')}, PBR {detail.get('pbr')}, 배당수익률 {detail.get('yield')}, 업종PER {detail.get('sector_per')}
        - 최신 뉴스/공시 요약: {', '.join(news) if news else '최근 소식 없음'}
        
        [리포트 필수 포함 내용]
        1. [가격 변동 원인]: 최근 이 종목이 왜 오르거나 내리고 있는가? (수집된 뉴스/공시 및 시세 흐름 기반)
        2. [모멘텀 진단]: 이 흐름이 내일까지 유지될 것인가? (퀀트 데이터 및 수급/뉴스 분석)
        3. [매수/매도 조언]: 지금 사도 될까? 혹은 팔아야 할까? (리스크 관리 중심의 명확한 가이드)
        4. [한줄평]: 이 종목에 대한 가장 날카로운 결론.
        
        전문가 어조로 한국어로 10~15줄 내외로 작성하세요.
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        endpoint = f"{self.base_url}/models/{self.model_id}:generateContent?key={api_key}"
        try:
            res = requests.post(endpoint, json=payload, timeout=25)
            if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text']
        except: pass
        return "종목 심층 분석 리포트를 생성하지 못했습니다."

    def get_holdings_report_advice(self, holdings: List[dict], vibe: str, market_data: dict, progress_cb: Optional[Callable] = None) -> Optional[str]:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key or not holdings: return "보유 중인 종목이 없습니다."
        
        current = 0
        total = len(holdings)
        lock = threading.Lock()
        
        def fetch_enriched_holding(h):
            nonlocal current
            code = h['pdno']
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            
            return f"""
            - {h['prdt_name']}({code})
              * 수익률: {float(h.get('evlu_pfls_rt', 0)):+.2f}% | 평가손익: {int(float(h.get('evlu_pfls_amt', 0))):+,}원
              * 매입평단: {int(float(h.get('pchs_avg_pric', 0))):,}원 | 현재가: {int(float(h.get('prpr', 0))):,}원
              * 지표: PER {detail.get('per')}, PBR {detail.get('pbr')}, 배당 {detail.get('yield')}
              * 최근 뉴스: {', '.join(news[:2]) if news else '소식 없음'}
            """.strip()

        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_holdings = list(executor.map(fetch_enriched_holding, holdings))

        holdings_txt = "\n".join(enriched_holdings)
        
        prompt = f"""
        당신은 월스트리트의 수석 포트폴리오 매니저입니다. 
        아래 보유 종목 데이터와 현재 시장 장세를 분석하여 [보유 종목 리포트]를 작성하세요.
        
        [시장 장세] {vibe}
        [지수 데이터] {json.dumps(market_data)}
        
        [현재 보유 종목 리포트 데이터]
        {holdings_txt}
        
        [분석 필수 포함 내용]
        1. 전체 포트폴리오 진단: 현재 장세({vibe}) 대비 보유 종목들의 구성이 적절한지 평가.
        2. 종목별 대응 전략: 각 종목에 대해 '유지(Hold), 매도(Sell), 비중확대(Add)' 중 하나를 선택하고 근거(뉴스/지표)를 제시.
        3. 리스크 경고: 특히 하락이 깊거나 뉴스가 부정적인 종목에 대한 즉각적인 조치 제안.
        4. 종합 한줄평: 현재 내 자산의 건강 상태.
        
        한국어로 12~15줄 내외로 아주 날카롭고 전문적인 어조로 작성하세요.
        """
        try:
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            endpoint = f"{self.base_url}/models/{self.model_id}:generateContent?key={api_key}"
            res = requests.post(endpoint, json=payload, timeout=25)
            if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text']
        except: pass
        return "보유 종목 심층 분석 의견을 생성하지 못했습니다."

    def get_hot_stocks_report_advice(self, hot_stocks: List[dict], themes: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key or not hot_stocks: return "인기 종목 데이터가 없습니다."
        
        current = 0
        total = min(10, len(hot_stocks))
        lock = threading.Lock()
        
        def fetch_enriched_hot(item):
            nonlocal current
            code = item.get('code', '')
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            return f"""
            - {item.get('name','')}({code}) | 등락률: {float(item.get('rate',0)):+.2f}% | 현재가: {int(float(item.get('price',0))):,}원
              * 지표: PER {detail.get('per')}, PBR {detail.get('pbr')}, 배당 {detail.get('yield')}
              * 최근 뉴스: {', '.join(news[:2]) if news else '소식 없음'}
            """.strip()

        top_stocks = hot_stocks[:10]
        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched = list(executor.map(fetch_enriched_hot, top_stocks))

        stocks_txt = "\n".join(enriched)
        themes_txt = ", ".join([f"{t['name']}({t['count']})" for t in themes[:8]]) if themes else "테마 데이터 없음"
        
        prompt = f"""
        당신은 월스트리트의 수석 트렌드 분석가입니다. 
        아래 실시간 인기 검색 종목과 테마 데이터를 분석하여 [인기 테마 리포트]를 작성하세요.
        
        [시장 장세] {vibe}
        [인기 테마 트렌드] {themes_txt}
        
        [실시간 인기 검색 상위 종목 데이터]
        {stocks_txt}
        
        [분석 필수 포함 내용]
        1. 오늘의 시장 테마: 현재 시장을 관통하는 핵심 투자 테마 2~3개를 선정하고, 왜 주목받고 있는지 분석.
        2. 종목별 핵심 진단: 각 인기 종목에 대해 '주목(Watch), 진입(Entry), 관망(Wait)' 중 하나를 택하고 뉴스/지표 기반 근거 제시.
        3. 테마 지속성 판단: 현재 인기 테마가 단기 테마인지 중장기 추세인지 진단.
        4. 한줄 결론: 오늘의 시장 키워드 한 마디.
        
        한국어로 12~15줄 내외로 날카롭고 전문적인 어조로 작성하세요.
        """
        try:
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            endpoint = f"{self.base_url}/models/{self.model_id}:generateContent?key={api_key}"
            res = requests.post(endpoint, json=payload, timeout=25)
            if res.status_code == 200: return res.json()['candidates'][0]['content']['parts'][0]['text']
        except: pass
        return "인기 종목 분석 리포트를 생성하지 못했습니다."


    def simulate_preset_strategy(self, code: str, name: str, vibe: str, detail: dict = None, news: List[str] = None) -> Optional[dict]:
        """AI가 종목 현황 분석 후 KIS 10개 프리셋 중 최적 전략과 동적 TP/SL을 제안"""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: return None
        
        # 프리셋 목록 텍스트 생성
        preset_list = "\n".join([
            f"  {sid}: {s['name']} ({s['type']}) - {s['desc']} [기본 TP:{s['default_tp']}%, SL:{s['default_sl']}%]"
            for sid, s in PRESET_STRATEGIES.items() if sid != "00"
        ])
        
        detail_txt = ""
        if detail:
            detail_txt = f"현재가: {detail.get('price', 'N/A')}, PER: {detail.get('per', 'N/A')}, PBR: {detail.get('pbr', 'N/A')}, 배당: {detail.get('yield', 'N/A')}, 업종PER: {detail.get('sector_per', 'N/A')}"
        news_txt = ", ".join(news[:5]) if news else "뉴스 없음"
        
        prompt = f"""
        당신은 월스트리트 수석 퀀트 트레이더입니다. 아래 종목에 가장 적합한 매매 전략 프리셋 1개를 선택하고, 해당 전략에 맞는 동적 TP/SL 수치를 계산하세요.
        
        [종목 정보]
        - 종목명: {name} ({code})
        - {detail_txt}
        - 최근 뉴스: {news_txt}
        - 현재 시장 장세: {vibe}
        
        [KIS 공식 프리셋 전략 목록]
{preset_list}
        
        [판단 가이드라인]
        1. 종목의 현재 가격 흐름, 펀더멘털(PER/PBR), 뉴스 모멘텀, 시장 장세를 종합하여 가장 적합한 전략 1개를 선택하세요.
        2. 선택한 전략의 기본 TP/SL을 기반으로, 해당 종목의 특성에 맞게 TP/SL을 ±2% 범위 내에서 동적 조정하세요.
        3. 이 종목의 현재 모멘텀 지속 시간을 예측하여 '유효시간(분)'을 제안하세요. (예: 급등주는 60~120분, 완만한 추세주는 240~360분)
        4. 모멘텀이 강한 종목은 TP를 높게, 변동성이 큰 종목은 SL을 타이트하게 설정하세요.
        
        [필수 응답 형식 - 정확히 이 형식만 출력하세요]
        전략번호: XX
        익절: +X.X%
        손절: -X.X%
        유효시간: N분
        근거: 한줄 설명
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        endpoint = f"{self.base_url}/models/{self.model_id}:generateContent?key={api_key}"
        try:
            res = requests.post(endpoint, json=payload, timeout=15)
            if res.status_code == 200:
                answer = res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
                # 파싱
                sid_match = re.search(r"전략번호[:\s]*(\d{2})", answer)
                tp_match = re.search(r"익절[:\s]*([+-]?[\d.]+)", answer)
                sl_match = re.search(r"손절[:\s]*([+-]?[\d.]+)", answer)
                lt_match = re.search(r"유효시간[:\s]*(\d+)분", answer)
                reason_match = re.search(r"근거[:\s]*(.*)", answer)
                
                if sid_match and tp_match and sl_match:
                    sid = sid_match.group(1)
                    if sid not in PRESET_STRATEGIES or sid == "00":
                        sid = "01"  # fallback
                    return {
                        "preset_id": sid,
                        "preset_name": PRESET_STRATEGIES[sid]["name"],
                        "tp": abs(float(tp_match.group(1))),
                        "sl": -abs(float(sl_match.group(1))),
                        "lifetime_mins": int(lt_match.group(1)) if lt_match else 120,
                        "reason": reason_match.group(1).strip() if reason_match else "AI 분석 기반 자동 선정"
                    }
        except Exception as e:
            log_error(f"프리셋 전략 시뮬레이션 오류: {e}")
        return None

    def verify_market_vibe(self, current_data: dict, heuristic_vibe: str) -> Optional[str]:
        """알고리즘이 1차 판정한 현재 장세를 AI가 최종 교차 검증합니다."""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: return None
        
        prompt = f"""
        당신은 월스트리트 수석 퀀트 트레이더입니다. 아래의 실시간 거시경제/지수 데이터를 바탕으로 현재 시장의 투자 심리(Market Vibe)를 단 하나의 단어로만 답변하세요.
        
        [현재 데이터 요약] 
        - 시장 지표 원본: {json.dumps(current_data)}
        - 기존 휴리스틱 알고리즘의 1차 판단: {heuristic_vibe}
        
        [판단 가이드라인 및 절대 규칙]
        1. 글로벌 증시 침체(나스닥 등 크게 하락), 환율 급등(1400원 이상 고공행진), 또는 비트코인 등 주요 위험자산이 심하게 폭락하면 'Defensive'(방어모드)로 판정합니다.
        2. 지수가 확실한 단기 하락세이거나 투심 회복이 불분명할 때는 'Bear'(하락장)로 진단합니다.
        3. 주요 증시가 오름세이고, VIX가 안정적(안심 구간)이라면 'Bull'(상승장)로 진단합니다.
        4. 방향성이 혼재되어 지지부진하면 'Neutral'(보합장)로 진단합니다.
        
        당신의 응답 라인은 오직 Bull, Bear, Neutral, Defensive 중 정확히 한 단어여야 합니다. 불필요한 서술은 제외하세요.
        """
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        endpoint = f"{self.base_url}/models/{self.model_id}:generateContent?key={api_key}"
        try:
            # 병목이 생기지 않도록 최대 대기 시간(timeout)을 5초 내외로 짧게 제한 (Fallback 전환용)
            res = requests.post(endpoint, json=payload, timeout=5)
            if res.status_code == 200:
                answer = res.json()['candidates'][0]['content']['parts'][0]['text'].strip().upper()
                for valid_vibe in ["BULL", "BEAR", "NEUTRAL", "DEFENSIVE"]:
                    if valid_vibe in answer:
                        return valid_vibe.capitalize()
            return None
        except: 
            # API 제한, 네트워크 에러, 응답 타임아웃 발생 -> 자연스럽게 단독 모드 진입
            return None

# --- VibeStrategy Facade ---
class VibeStrategy:
    def __init__(self, api, config):
        self.api = api
        # 1. .env 기반의 순수 기본 설정 보존 (변경 여부 판단용)
        self.base_config = config.get("vibe_strategy", {})
        
        v_cfg = self.base_config
        self.analyzer = MarketAnalyzer(api)
        self.exit_mgr = ExitManager(v_cfg.get("take_profit_threshold", 5.0), v_cfg.get("stop_loss_threshold", -5.0))
        self.recovery_eng = RecoveryEngine(v_cfg.get("bear_market", {}))
        
        # [추가] 불타기(Pyramiding) 엔진의 독립 구성
        bull_defaults = {"min_profit_to_pyramid": 3.0, "average_down_amount": 500000, "max_investment_per_stock": 25000000, "auto_mode": False}
        self.bull_config = v_cfg.get("bull_market", {})
        for k, v in bull_defaults.items():
            if k not in self.bull_config:
                self.bull_config[k] = v
        self.pyramid_eng = PyramidingEngine(self.bull_config)
        self.alpha_eng = VibeAlphaEngine(api)
        self.ai_advisor = GeminiAdvisor(api)
        self.alpha_eng.ai_advisor = self.ai_advisor
        self.analyzer.ai_advisor = self.ai_advisor # 시장 장세 AI 검증 연결
        self.state_file = "trading_state.json"
        self.last_avg_down_msg = "없음"
        self.last_sell_times: Dict[str, float] = {}
        self.ai_recommendations: List[dict] = []
        self.ai_briefing, self.ai_detailed_opinion = "", ""
        self.ai_holdings_opinion = ""  # 보유 종목 리포트 결과 저장
        self.recommendation_history: Dict[str, List[dict]] = {} # {date: [recs]}
        self.yesterday_recs: List[dict] = []
        # 프리셋 전략 할당 상태 {종목코드: {"preset_id": "01", "name": "골든크로스", "tp": 8.0, "sl": -4.0, "reason": "..."}}
        self.preset_strategies: Dict[str, dict] = {}
        self.yesterday_recs_processed: List[dict] = []
        self._last_closing_bet_date = None
        
        # AI 설정 초기화
        self.ai_config = {
            "amount_per_trade": v_cfg.get("ai_config", {}).get("amount_per_trade", 500000),
            "min_score": v_cfg.get("ai_config", {}).get("min_score", 60.0),
            "max_investment_per_stock": v_cfg.get("ai_config", {}).get("max_investment_per_stock", 2000000),
            "auto_mode": v_cfg.get("ai_config", {}).get("auto_mode", False),
            "auto_apply": v_cfg.get("ai_config", {}).get("auto_apply", False)
        }
        
        # 2. 영속 상태(state) 로드
        self._load_all_states()
        self.update_yesterday_recs()

    def update_yesterday_recs(self):
        """저장된 이력 중 오늘 이전의 가장 최신 추천 목록을 로드"""
        today = datetime.now().strftime('%Y-%m-%d')
        dates = sorted([d for d in self.recommendation_history.keys() if d < today])
        if dates:
            self.yesterday_recs = self.recommendation_history[dates[-1]]
        else:
            self.yesterday_recs = []

    def refresh_yesterday_recs_performance(self, hot_raw, vol_raw):
        """어제 추천 종목의 현재 수익률을 계산하여 캐싱 (TUI 네트워크 지연 방지)"""
        if not self.yesterday_recs: return
        processed = []
        for r in self.yesterday_recs:
            curr_item = next((item for item in (hot_raw + vol_raw) if item and item['code'] == r['code']), None)
            if not curr_item:
                p_data = self.api.get_naver_stock_detail(r['code'])
                curr_p = float(p_data.get('price', r['price']))
            else:
                curr_p = float(curr_item['price'])
            chg = ((curr_p - r['price']) / r['price'] * 100) if r['price'] > 0 else 0
            processed.append({**r, "curr_price": curr_p, "change": chg})
        self.yesterday_recs_processed = sorted(processed, key=lambda x: abs(x['change']), reverse=True)

    def is_modified(self, section: str) -> bool:
        """기본값(.env)과 현재 상태를 비교하여 변경 여부 반환"""
        if section == "STRAT":
            return (self.exit_mgr.base_tp != self.base_config.get("take_profit_threshold") or 
                    self.exit_mgr.base_sl != self.base_config.get("stop_loss_threshold"))
        
        if section == "BEAR":
            bc = self.base_config.get("bear_market", {})
            curr = self.recovery_eng.config
            return (curr.get("average_down_amount") != bc.get("average_down_amount") or
                    curr.get("min_loss_to_buy") != bc.get("min_loss_to_buy") or
                    curr.get("auto_mode") != bc.get("auto_mode"))
        
        if section == "BULL":
            bc = self.base_config.get("bull_market", {})
            curr = self.bull_config
            return (curr.get("average_down_amount") != bc.get("average_down_amount") or
                    curr.get("min_profit_to_pyramid") != bc.get("min_profit_to_pyramid") or
                    curr.get("auto_mode") != bc.get("auto_mode"))
        
        if section == "ALGO":
            ac = self.base_config.get("ai_config", {})
            curr = self.ai_config
            return (curr.get("amount_per_trade") != ac.get("amount_per_trade") or
                    curr.get("auto_mode") != ac.get("auto_mode") or
                    curr.get("min_score") != ac.get("min_score"))
        return False

    def _load_all_states(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    d = json.load(f)
                    if "base_tp" in d: self.exit_mgr.base_tp = d["base_tp"]
                    if "base_sl" in d: self.exit_mgr.base_sl = d["base_sl"]
                    self.exit_mgr.manual_thresholds = d.get("manual_thresholds", {})
                    self.recovery_eng.last_avg_down_prices = d.get("last_avg_down_prices", {})
                    self.pyramid_eng.last_buy_prices = d.get("last_buy_prices", {})
                    self.last_sell_times = d.get("last_sell_times", {})
                    self.last_avg_down_msg = d.get("last_avg_down_msg", "없음")
                    self.recommendation_history = d.get("recommendation_history", {})
                    self.preset_strategies = d.get("preset_strategies", {})
                    # 하위 호환성을 위해 누락된 필드 초기화
                    for code, s in self.preset_strategies.items():
                        if 'buy_time' not in s: s['buy_time'] = None
                        if 'deadline' not in s: s['deadline'] = None
                        if 'is_p3_processed' not in s: s['is_p3_processed'] = False
                    if "ai_config" in d: 
                        self.ai_config.update(d["ai_config"])
                        # auto_apply는 S:셋업(.env)에서 설정하는 값이 항상 우선 적용됨
                        # trading_state.json 값과 관계없이 .env(base_config) 값을 덮어씀
                        self.ai_config["auto_apply"] = self.base_config.get("ai_config", {}).get("auto_apply", False)
                    if "bear_config" in d: self.recovery_eng.config.update(d["bear_config"])
                    if "bull_config" in d: self.bull_config.update(d["bull_config"])
                    self._last_closing_bet_date = d.get("last_closing_bet_date")
            except Exception as e:
                log_error(f"상태 파일 로드 실패: {e}")

    def _save_all_states(self):
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            # 현재 추천 목록이 있으면 오늘 날짜로 히스토리 업데이트
            if self.ai_recommendations:
                self.recommendation_history[today] = [
                    {"code": r['code'], "name": r['name'], "price": float(r.get('price', 0)), "theme": r['theme'], "score": r['score']}
                    for r in self.ai_recommendations
                ]
                # 최근 7일치만 유지
                dates = sorted(self.recommendation_history.keys())
                if len(dates) > 7:
                    for d in dates[:-7]: del self.recommendation_history[d]

            data = {
                "base_tp": self.exit_mgr.base_tp,
                "base_sl": self.exit_mgr.base_sl,
                "manual_thresholds": self.exit_mgr.manual_thresholds,
                "last_avg_down_prices": self.recovery_eng.last_avg_down_prices,
                "last_buy_prices": self.pyramid_eng.last_buy_prices,
                "last_sell_times": self.last_sell_times,
                "last_avg_down_msg": self.last_avg_down_msg,
                "recommendation_history": self.recommendation_history,
                "ai_config": self.ai_config,
                "bear_config": self.recovery_eng.config,
                "bull_config": self.bull_config,
                "preset_strategies": self.preset_strategies,
                "last_closing_bet_date": getattr(self, "_last_closing_bet_date", None)
            }
            with open(self.state_file, "w") as f: json.dump(data, f, indent=4)
        except Exception as e: log_error(f"상태 저장 실패: {e}")

    @property
    def auto_ai_trade(self): return self.ai_config["auto_mode"]
    @auto_ai_trade.setter
    def auto_ai_trade(self, val): self.ai_config["auto_mode"] = val
    @property
    def current_market_vibe(self): return self.analyzer.kr_vibe
    @property
    def global_panic(self): return self.analyzer.is_panic
    @property
    def current_market_data(self): return self.analyzer.current_data
    @property
    def base_tp(self): return self.exit_mgr.base_tp
    @property
    def base_sl(self): return self.exit_mgr.base_sl
    @property
    def bear_config(self): return self.recovery_eng.config
    @property
    def manual_thresholds(self): return self.exit_mgr.manual_thresholds

    def determine_market_trend(self): return self.analyzer.update()
    def save_manual_thresholds(self): self._save_all_states()
    
    def get_market_phase(self) -> dict:
        now = datetime.now().time()
        # Phase 1: 09:00~10:00 (공격)
        if dtime(9, 0) <= now < dtime(10, 0):
            return {"id": "P1", "name": "OFFENSIVE", "tp_delta": 2.0, "sl_delta": -1.0}
        # Phase 3: 14:30~15:10 (결과확정)
        elif dtime(14, 30) <= now < dtime(15, 10):
            return {"id": "P3", "name": "CONCLUSION", "tp_delta": 0.0, "sl_delta": 0.0}
        # Phase 4: 15:10~15:20 (익일준비)
        elif dtime(15, 10) <= now < dtime(15, 20):
            return {"id": "P4", "name": "PREPARATION", "tp_delta": 0.0, "sl_delta": 0.0}
        # Phase 2: 그 외 (수렴/관리)
        elif dtime(10, 0) <= now < dtime(14, 30):
            return {"id": "P2", "name": "CONVERGENCE", "tp_delta": -1.0, "sl_delta": -1.0}
        return {"id": "IDLE", "name": "IDLE", "tp_delta": 0.0, "sl_delta": 0.0}

    def get_dynamic_thresholds(self, code, vibe, p_data=None):
        """프리셋 전략이 할당된 종목은 프리셋 TP/SL을 최우선 적용"""
        phase_cfg = self.get_market_phase()
        ps = self.preset_strategies.get(code)
        if ps and ps.get("preset_id") != "00":
            # 프리셋 전략의 동적 TP/SL을 직접 사용 (Vibe 보정 미적용 - 프리셋 자체가 완성형)
            return ps["tp"], ps["sl"], False
        # 프리셋이 '표준(00)'이거나 미설정 시 기존 로직
        return self.exit_mgr.get_thresholds(code, vibe, p_data, phase_cfg)
    
    def get_preset_label(self, code: str) -> str:
        """종목에 할당된 프리셋 전략 이름 반환 (없으면 빈 문자열)"""
        ps = self.preset_strategies.get(code)
        if ps:
            return ps.get("name", "")
        return ""
    
    def _calculate_deadline(self, preset_id, start_time_str, lifetime_mins):
        if not start_time_str or not lifetime_mins: return None
        try:
            # lifetime_mins가 0이거나 None이 아닌 경우에만 계산, 안전하게 int 변환
            l_mins = int(lifetime_mins)
            
            # [Task 3-1] 전략 그룹별 수명 상한선(Hard Cap) 적용
            if preset_id in ["03", "08", "07"]: # G1: 돌파/폭발형
                l_mins = min(l_mins, 180)
            elif preset_id in ["05", "09", "06"]: # G3: 과매도/반등형
                l_mins = min(l_mins, 240)
            
            if l_mins <= 0: return None
            
            start_dt = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
            deadline_dt = start_dt + timedelta(minutes=l_mins)
            return deadline_dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            log_error(f"Deadline 계산 실패: {e}")
            return None
    
    def assign_preset(self, code: str, preset_id: str, tp: float = None, sl: float = None, reason: str = "", lifetime_mins: int = None):
        """종목에 프리셋 전략 할당 (표준 선택 시 기존 설정으로 복귀)"""
        preset = PRESET_STRATEGIES.get(preset_id)
        if not preset:
            return False
        if preset_id == "00":
            # 표준 모드: 프리셋 해제 (기본 전략으로 복귀)
            if code in self.preset_strategies:
                del self.preset_strategies[code]
        else:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            use_tp = tp if tp is not None else preset["default_tp"]
            use_sl = sl if sl is not None else preset["default_sl"]
            self.preset_strategies[code] = {
                "preset_id": preset_id,
                "name": preset["name"],
                "tp": use_tp,
                "sl": use_sl,
                "reason": reason or preset["desc"],
                "buy_time": now_str,
                "deadline": self._calculate_deadline(preset_id, now_str, lifetime_mins),
                "is_p3_processed": False
            }
        self._save_all_states()
        return True
    
    def auto_assign_preset(self, code: str, name: str) -> Optional[dict]:
        """AI를 활용하여 종목에 최적 프리셋 전략 자동 할당 (자동매수 시 호출)"""
        try:
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            vibe = self.current_market_vibe
            result = self.ai_advisor.simulate_preset_strategy(code, name, vibe, detail, news)
            if result:
                self.assign_preset(code, result["preset_id"], result["tp"], result["sl"], result["reason"], result.get("lifetime_mins"))
                return result
        except Exception as e:
            log_error(f"자동 프리셋 할당 오류: {e}")
        return None

    def record_buy(self, code, price):
        self.recovery_eng.last_avg_down_prices[code] = price
        self.pyramid_eng.last_buy_prices[code] = price
        self._save_all_states()

    def update_ai_recommendations(self, themes, hot_raw, vol_raw, progress_cb: Optional[Callable] = None, on_item_found: Optional[Callable] = None):
        try: 
            # 실시간 업데이트 콜백이 있을 때만 기존 목록을 초기화 (수동 분석 시)
            # 그 외 배경 업데이트 시에는 결과가 나올 때까지 기존 캐시를 유지하여 깜빡임 방지
            if on_item_found:
                self.ai_recommendations = []
                
            recs = self.alpha_eng.analyze(
                themes, hot_raw, vol_raw, 
                self.ai_config.get("min_score", 60.0), 
                progress_cb=progress_cb,
                kr_vibe=self.current_market_vibe,
                market_data=self.current_market_data,
                on_item_found=on_item_found
            )
            self.ai_recommendations = recs
            self._save_all_states()
        except Exception as e:
            log_error(f"AI 추천 업데이트 오류: {e}")

    def get_ai_advice(self, progress_cb: Optional[Callable] = None):
        holdings = self.api.get_balance()
        base_sl = self.exit_mgr.base_sl
        if self.analyzer.kr_vibe.upper() == "DEFENSIVE": base_sl = -3.0
        current_cfg = {
            "base_tp": self.exit_mgr.base_tp, 
            "base_sl": base_sl, 
            "bear_trig": max(self.recovery_eng.config.get("min_loss_to_buy"), base_sl + 1.0), 
            "bull_trig": self.bull_config.get("min_profit_to_pyramid", 3.0), 
            "ai_amt": self.ai_config["amount_per_trade"]
        }
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            # 1. 시장 브리핑 및 전략 제안 (가장 중요) - 추천 종목 정보 추가 전달
            future_briefing = executor.submit(self.ai_advisor.get_advice, self.analyzer.current_data, self.analyzer.kr_vibe, holdings, current_cfg, self.ai_recommendations)
            
            # 2. 추천 종목 입체 분석 리포트
            future_detailed = executor.submit(self.ai_advisor.get_detailed_report_advice, self.ai_recommendations, self.analyzer.kr_vibe, progress_cb=progress_cb)
            
            # 3. 보유 종목 리포트 (있을 때만)
            future_holdings = None
            if holdings:
                future_holdings = executor.submit(self.ai_advisor.get_holdings_report_advice, holdings, self.analyzer.kr_vibe, self.analyzer.current_data, progress_cb=progress_cb)
            
            # 결과 수집
            self.ai_briefing = future_briefing.result()
            self.ai_detailed_opinion = future_detailed.result()
            if future_holdings:
                self.ai_holdings_opinion = future_holdings.result()
            
        return self.ai_briefing

    def parse_and_apply_ai_strategy(self) -> bool:
        """AI[전략] 라인에서 수치를 파싱하여 시스템에 즉시 반영 (Vibe 역산 적용)"""
        if not self.ai_briefing: return False
        try:
            strat_line = ""
            for line in self.ai_briefing.split('\n'):
                if "AI[전략]:" in line: strat_line = line; break
            if not strat_line: return False

            tp = re.search(r"익절\s*([+-]?[\d,.]+)", strat_line)
            sl = re.search(r"손절\s*([+-]?[\d,.]+)", strat_line)
            trig_bear = re.search(r"물타기\s*([+-]?[\d,.]+)", strat_line)
            trig_bull = re.search(r"불타기\s*([+-]?[\d,.]+)", strat_line)
            amt = re.search(r"금액\s*([\d,]+)\s*원", strat_line)
            
            # 구버전 응답(추매) 호환성 지원
            if not trig_bull: trig_bull = re.search(r"추매\s*([+-]?[\d,.]+)", strat_line)
            
            # 핵심 4개(익절/손절/물타기/불타기)는 반드시 있어야 함
            if not (tp and sl and trig_bear and trig_bull): return False
            
            # 1. AI가 제안한 '최종 유효값' 파싱 (모든 수치에서 콤마 제거 후 float 변환)
            target_tp = abs(float(tp.group(1).replace(',', '')))
            target_sl = -abs(float(sl.group(1).replace(',', '')))
            target_trig_bear = -abs(float(trig_bear.group(1).replace(',', '')))
            target_trig_bull = abs(float(trig_bull.group(1).replace(',', '')))
            
            # 금액 파싱: 실패 시 현재 설정값 유지 (AI가 비정형 텍스트를 보낸 경우 방어)
            if amt:
                new_amt = int(amt.group(1).replace(',', ''))
                # [수정] 금액 단위 보정 (만약 AI가 '만원' 단위를 썼을 경우 - 1000원 미만 시 만원 단위로 간주)
                if new_amt < 1000:
                    new_amt *= 10000
            else:
                # 금액 파싱 실패 → 현재 물타기 설정 금액 유지
                new_amt = self.recovery_eng.config.get("average_down_amount", 500000)
                log_error(f"AI 금액 파싱 실패 (원본: {strat_line}), 기존값 {new_amt:,}원 유지")
            
            # 2. 현재 Vibe에 따른 보정치 역산
            tp_mod, sl_mod = self.exit_mgr.get_vibe_modifiers(self.analyzer.kr_vibe)
            
            # 기본값(Base) 설정
            self.exit_mgr.base_tp = target_tp - tp_mod
            self.exit_mgr.base_sl = target_sl - sl_mod
            
            # 3. 물타기 및 불타기 동기화 반영
            self.recovery_eng.config["min_loss_to_buy"] = target_trig_bear
            self.recovery_eng.config["average_down_amount"] = new_amt
            self.recovery_eng.config["max_investment_per_stock"] = int(new_amt * 5)
            
            self.bull_config["min_profit_to_pyramid"] = target_trig_bull
            self.bull_config["average_down_amount"] = new_amt
            self.bull_config["max_investment_per_stock"] = int(new_amt * 5)
            
            self._save_all_states()
            return True
        except Exception as e:
            log_error(f"AI 전략 파싱 에러: {e}")
            return False

    def get_buy_recommendations(self, market_trend):
        holdings = self.api.get_balance(); recs = []
        for h in holdings:
            tp, sl, _ = self.get_dynamic_thresholds(h.get('pdno'), self.analyzer.kr_vibe)
            r = self.recovery_eng.get_recommendation(h, self.analyzer.is_panic, sl)
            if not r: r = self.pyramid_eng.get_recommendation(h, self.analyzer.kr_vibe, self.analyzer.is_panic, False, tp)
            if r: recs.append(r)
        return recs

    def run_cycle(self, market_trend="neutral", skip_trade=False):
        holdings = self.api.get_balance()
        results, curr_t = [], time.time()
        phase = self.get_market_phase()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today = datetime.now().strftime('%Y-%m-%d')

        # [Task 5] Phase 4 (PREPARATION) 종가 베팅 로직
        if phase['id'] == "P4" and not self.global_panic and \
           self.current_market_vibe.upper() in ["BULL", "NEUTRAL"] and \
           self.auto_ai_trade:
            
            if getattr(self, "_last_closing_bet_date", None) != today:
                if self.ai_recommendations:
                    top_rec = self.ai_recommendations[0]
                    code, name = top_rec['code'], top_rec['name']
                    
                    # [Task 5-1] 중복 매수 방지: 이미 보유 중인 종목이면 건너뜀
                    if any(h.get('pdno') == code for h in holdings):
                        logger.info(f"P4 종가 베팅 건너뜀 (이미 보유 중): {name} ({code})")
                        self._last_closing_bet_date = today # 오늘 이미 베팅 시도한 것으로 간주하여 반복 방지
                    else:
                        amt = self.ai_config["amount_per_trade"]
                        if not skip_trade:
                            price = float(top_rec.get('price', 0))
                            qty = math.floor(amt / price) if price > 0 else 0
                            if qty > 0:
                                success, msg = self.api.order_market(code, qty, True)
                                if success:
                                    self._last_closing_bet_date = today
                                    results.append(f"P4 종가 베팅 매수: {name} ({code}) {qty}주")
                                    self.auto_assign_preset(code, name)
                                    self._save_all_states()

        for item in holdings:
            code = item.get("pdno")
            p_strat = self.preset_strategies.get(code)
            
            # [Task 4] 시간 기반 자동 매매 액션 구현
            if p_strat:
                # 1. Time-Stop 체크: 데드라인 초과 시 TP 하향 (수익 보존)
                if p_strat.get('deadline') and now_str > p_strat['deadline']:
                    curr_rt = float(item.get("evlu_pfls_rt", 0.0))
                    if curr_rt >= 0.5:
                        p_strat['tp'] = max(0.5, curr_rt / 2.0)
                        results.append(f"Time-Stop TP 하향: {item.get('prdt_name')} ({p_strat['tp']:.1f}%)")
                    # 처리가 완료된 종목은 deadline을 None으로 설정하여 중복 실행 방지
                    p_strat['deadline'] = None 
                    self._save_all_states()

                # 2. Phase 3 (CONCLUSION): 수익권 50% 분할 매도 및 SL 상향
                if phase['id'] == "P3" and not p_strat.get('is_p3_processed'):
                    curr_rt = float(item.get("evlu_pfls_rt", 0.0))
                    if curr_rt >= 0.5:
                        sell_qty = int(float(item.get('hldg_qty', 0))) // 2
                        if sell_qty > 0 and not skip_trade:
                            success, msg = self.api.order_market(code, sell_qty, False)
                            if success:
                                p_strat['is_p3_processed'] = True
                                # 남은 수량의 SL을 +0.2%(본전 보호)로 상향
                                p_strat['sl'] = 0.2 
                                results.append(f"P3 수익확정(50%): {item.get('prdt_name')}")
                                self._save_all_states()

            # 3. 기존 TP/SL 체크 로직
            tp, sl, _ = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
            rt = float(item.get("evlu_pfls_rt", 0.0))
            action, sell_qty = None, 0
            if rt >= tp:
                if curr_t - self.last_sell_times.get(code, 0) > 3600: 
                    action = "익절"; sell_qty = max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
            elif rt <= sl: 
                action = "손절"; sell_qty = int(item.get('hldg_qty', 0))
            if action and not skip_trade and sell_qty > 0:
                success, msg = self.api.order_market(code, sell_qty, False)
                if success:
                    if action == "익절": self.last_sell_times[code] = curr_t; self._save_all_states()
                    results.append(f"자동 {action}: {item.get('prdt_name')} {sell_qty}주")
        return results
