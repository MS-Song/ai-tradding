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
from src.logger import logger, log_error, trading_log

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
        from src.theme_engine import get_theme_for_stock
        
        combined = hot_raw + vol_raw
        candidates = []
        seen = set()

        # 테마 카운트 맵 생성 (테마별 가산점용)
        theme_count_map = {t['name']: t['count'] for t in themes}

        for item in combined:
            code = item['code']
            if code in seen: continue
            seen.add(code)
            if not (len(code) == 6 and code.isdigit()): continue
            
            # 동적 테마 매핑 활용
            theme_name = get_theme_for_stock(code, item.get('name', ''))
            theme_count = theme_count_map.get(theme_name, 1)
            my_theme = {"name": theme_name, "count": theme_count}
            
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
    def __init__(self, api, ai_config: dict = None):
        self.api = api
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        
        # 기본 모델 설정 (사용자 검증 기반: Group 1 수정 반영)
        self.config = ai_config or {}
        self.preferred_model = self.config.get("preferred_model", "gemini-2.5-flash")
        self.fallback_sequence = self.config.get("fallback_sequence", [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-3.1-pro-preview"
        ])

    def _safe_gemini_call(self, prompt: str, timeout: int = 60) -> Optional[str]:
        """Spec에 정의된 순서대로 모델을 교체하며 재시도 (Timeout 60초 적용)"""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: return None

        # 1순위 preferred_model부터 시작하여 fallback_sequence 순회 (중복 제거)
        models_to_try = [self.preferred_model] + [m for m in self.fallback_sequence if m != self.preferred_model]
        
        last_error = ""
        for model_id in models_to_try:
            endpoint = f"{self.base_url}/models/{model_id}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            try:
                # Spec 요구사항: 부하 시 충분한 대기 시간(60초) 확보
                res = requests.post(endpoint, json=payload, timeout=timeout)
                if res.status_code == 200:
                    result = res.json()
                    if 'candidates' in result and result['candidates']:
                        return result['candidates'][0]['content']['parts'][0]['text'].strip()
                last_error = f"HTTP {res.status_code}"
            except Exception as e:
                last_error = str(e)
            
            # 실패 시 로그 기록 후 다음 모델로 전환
            log_error(f"Gemini Fallback Triggered: Model {model_id} failed ({last_error}). Trying next...")
            
        return None

    def get_advice(self, market_data: dict, vibe: str, holdings: List[dict], current_config: dict, recs: List[dict] = None) -> Optional[str]:
        holdings_txt = "\n".join([f"- {h['prdt_name']}({h['pdno']}): 수익률 {h['evlu_pfls_rt']}%" for h in holdings])
        recs_txt = ""
        if recs:
            recs_txt = "\n".join([f"- {r['name']}({r['code']}): 1주당 현재가 {int(float(r.get('price',0))):,}원, 금일 등락 {r.get('rate',0):+.1f}%" for r in recs[:5]])

        prompt_text = f"""
        당신은 월스트리트 수석 퀀트 트레이더입니다. 아래의 **[실시간 데이터]**만을 근거로 전략을 브리핑하세요.
        [실시간 데이터]
        - 시장Vibe: {vibe}
        - 현재 지수 상태: {json.dumps(market_data)}
        - 현재 포트폴리오: {holdings_txt if holdings else "보유 종목 없음"}
        - 신규 추천 후보: {recs_txt if recs_txt else "추천 후보 없음"}
        - 시스템 매수 설정 금액: {current_config.get('ai_amt'):,}원
        [필수 규칙]
        1. 추천주의 매수가격은 '1주당 현재가'의 ±3% 이내에서만 제안.
        2. (매수 권장 금액)이 (추천주 1주당 현재가)보다 작으면 추천 불가.
        3. 추가매수(물타기) 지점 > 손절선(SL), 불타기지점 < 익절선(TP).
        4. AI[액션]과 AI[추천]은 각각 단 1줄로 요약.
        [답변 형식]
        AI[시장]: 요약
        AI[전략]: 익절 +X.X%, 손절 -Y.Y%, 물타기 -Z.Z%, 불타기 +W.W%, 금액 N원
        AI[액션]: 요약 (1줄)
        AI[추천]: 종목명(코드), 권장매수가 N원, 예상매수주수 M주 (1줄)
        한국어로 대답하세요.
        """
        return self._safe_gemini_call(prompt_text) or "⚠️ AI 엔진 분석 실패 (모든 모델 시도함)"

    def get_detailed_report_advice(self, recs: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
        if not recs: return "분석할 종목이 없습니다."
        current, total = 0, len(recs)
        lock = threading.Lock()
        def fetch_enriched_data(r):
            nonlocal current
            detail = self.api.get_naver_stock_detail(r['code'])
            news = self.api.get_naver_stock_news(r['code'])
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            return f"- {r['name']}({r['code']}) | 현재가: {int(float(r.get('price',0))):,}원 | PER {detail.get('per')}, PBR {detail.get('pbr')} | 뉴스: {', '.join(news[:2])}"

        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_recs = list(executor.map(fetch_enriched_data, recs))
        
        prompt = f"""
        수석 투자 전략가로서 아래 종목들에 대해 [초압축] 입체 분석 리포트를 작성하세요.
        [시장 장세] {vibe}
        [데이터]
        {"\n".join(enriched_recs)}
        [가이드라인 - 필수 준수]
        1. 종목당 **반드시 2줄 이내**로 핵심만 요약 (매우 중요).
        2. 1행: [투자근거/지표], 2행: [목표/손절/전략].
        3. 불필요한 수식어 제거, 날카로운 전문가 어조, 한국어.
        4. 전체 리포트 길이를 최대한 짧게 유지하여 터미널 한 화면에 들어오게 할 것.
        """
        return self._safe_gemini_call(prompt) or "종목별 입체 분석 의견을 가져오지 못했습니다."

    def get_stock_report_advice(self, code: str, name: str, detail: dict, news: List[str]) -> Optional[str]:
        prompt = f"""
        수석 투자 전략가로서 아래 종목에 대해 분석 리포트를 작성하세요.
        [종목 정보] {name}({code}) | {int(float(detail.get('price', 0))):,}원 | PER {detail.get('per')}, PBR {detail.get('pbr')}
        [뉴스 요약] {', '.join(news[:3]) if news else '소식 없음'}
        [필수 내용] 1.가격 변동 원인 2.모멘텀 진단 3.매수/매도 조언 4.한줄평
        전문가 어조, 한국어, 10~15줄.
        """
        return self._safe_gemini_call(prompt) or "종목 심층 분석 리포트를 생성하지 못했습니다."

    def get_holdings_report_advice(self, holdings: List[dict], vibe: str, market_data: dict, progress_cb: Optional[Callable] = None) -> Optional[str]:
        if not holdings: return "보유 중인 종목이 없습니다."
        current, total = 0, len(holdings)
        lock = threading.Lock()
        def fetch_enriched_holding(h):
            nonlocal current
            detail = self.api.get_naver_stock_detail(h['pdno'])
            news = self.api.get_naver_stock_news(h['pdno'])
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            return f"- {h['prdt_name']}({h['pdno']}): 수익률 {float(h.get('evlu_pfls_rt', 0)):+.2f}% | 현재가 {int(float(h.get('prpr', 0))):,}원 | 뉴스 {', '.join(news[:2])}"

        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched_holdings = list(executor.map(fetch_enriched_holding, holdings))

        prompt = f"""
        수석 포트폴리오 매니저로서 보유 종목 리포트를 작성하세요.
        [시장 장세] {vibe} | [지수] {json.dumps(market_data)}
        [보유 데이터]
        {"\n".join(enriched_holdings)}
        [필수 내용] 1.전체 포트폴리오 진단 2.종목별 대응전략(Hold/Sell/Add) 3.리스크 경고 4.한줄평
        한국어, 12~15줄, 날카롭고 전문적인 어조.
        """
        return self._safe_gemini_call(prompt) or "보유 종목 심층 분석 의견을 생성하지 못했습니다."

    def get_hot_stocks_report_advice(self, hot_stocks: List[dict], themes: List[dict], vibe: str, progress_cb: Optional[Callable] = None) -> Optional[str]:
        if not hot_stocks: return "인기 종목 데이터가 없습니다."
        current, total = 0, min(10, len(hot_stocks))
        lock = threading.Lock()
        def fetch_enriched_hot(item):
            nonlocal current
            detail = self.api.get_naver_stock_detail(item.get('code', ''))
            news = self.api.get_naver_stock_news(item.get('code', ''))
            with lock:
                current += 1
                if progress_cb: progress_cb(current, total)
            return f"- {item.get('name','')}: {float(item.get('rate',0)):+.2f}% | PER {detail.get('per')}, PBR {detail.get('pbr')} | 뉴스 {', '.join(news[:2])}"

        with ThreadPoolExecutor(max_workers=5) as executor:
            enriched = list(executor.map(fetch_enriched_hot, hot_stocks[:10]))

        prompt = f"""
        수석 트렌드 분석가로서 인기 테마 리포트를 작성하세요.
        [시장 장세] {vibe} | [테마] {", ".join([f"{t['name']}({t['count']})" for t in themes[:8]])}
        [상위 종목]
        {"\n".join(enriched)}
        [필수 내용] 1.오늘의 시장 테마 2.종목별 핵심 진단(Watch/Entry/Wait) 3.테마 지속성 판단 4.한줄 결론
        한국어, 12~15줄, 날카롭고 전문적인 어조.
        """
        return self._safe_gemini_call(prompt) or "인기 종목 분석 리포트를 생성하지 못했습니다."

    def simulate_preset_strategy(self, code: str, name: str, vibe: str, detail: dict = None, news: List[str] = None) -> Optional[dict]:
        preset_list = "\n".join([f"  {sid}: {s['name']} [기본 TP:{s['default_tp']}%, SL:{s['default_sl']}%]"
                                 for sid, s in PRESET_STRATEGIES.items() if sid != "00"])
        detail_txt = f"현재가: {detail.get('price', 'N/A')}, PER: {detail.get('per', 'N/A')}, PBR: {detail.get('pbr', 'N/A')}" if detail else ""
        prompt = f"""
        가장 적합한 프리셋 전략 1개와 동적 TP/SL을 제안하세요.
        [종목] {name}({code}) | {detail_txt} | 뉴스: {", ".join(news[:5]) if news else "없음"} | 장세: {vibe}
        [프리셋]
{preset_list}
        [형식]
        전략번호: XX
        익절: +X.X%
        손절: -X.X%
        유효시간: N분
        근거: 한줄 설명
        """
        answer = self._safe_gemini_call(prompt)
        if answer:
            try:
                sid_match = re.search(r"전략번호[:\s]*(\d{2})", answer)
                tp_match = re.search(r"익절[:\s]*([+-]?[\d.]+)", answer)
                sl_match = re.search(r"손절[:\s]*([+-]?[\d.]+)", answer)
                lt_match = re.search(r"유효시간[:\s]*(\d+)분", answer)
                reason_match = re.search(r"근거[:\s]*(.*)", answer)
                if sid_match and tp_match and sl_match:
                    sid = sid_match.group(1)
                    if sid not in PRESET_STRATEGIES or sid == "00": sid = "01"
                    return {
                        "preset_id": sid, "preset_name": PRESET_STRATEGIES[sid]["name"],
                        "tp": abs(float(tp_match.group(1))), "sl": -abs(float(sl_match.group(1))),
                        "lifetime_mins": int(lt_match.group(1)) if lt_match else 120,
                        "reason": reason_match.group(1).strip() if reason_match else "AI 분석 기반 자동 선정"
                    }
            except Exception as e: log_error(f"프리셋 시뮬레이션 파싱 오류: {e}")
        return None

    def final_buy_confirm(self, code: str, name: str, vibe: str, detail: dict, news: List[str]) -> Tuple[bool, str]:
        """매수 직전 AI에게 최종 컨펌을 요청합니다."""
        detail_txt = f"현재가: {detail.get('price', 'N/A')}, PER: {detail.get('per', 'N/A')}, PBR: {detail.get('pbr', 'N/A')}, 등락률: {detail.get('rate', 'N/A')}%"
        prompt = f"""
        최종 매수 결정: 아래 종목을 지금 바로 매수해야 할까요?
        [종목] {name}({code}) | {detail_txt}
        [시장 장세] {vibe}
        [최신 뉴스] {", ".join(news[:3]) if news else "없음"}
        
        [답변 형식]
        결정: Yes 또는 No
        사유: 한 줄 요약 (No인 경우 필수)
        """
        answer = self._safe_gemini_call(prompt)
        if answer:
            decision_match = re.search(r"결정[:\s]*(Yes|No)", answer, re.I)
            reason_match = re.search(r"사유[:\s]*(.*)", answer)
            decision = decision_match.group(1).strip().capitalize() if decision_match else "No"
            reason = reason_match.group(1).strip() if reason_match else "AI 판단 근거 부족"
            return (decision == "Yes"), reason
        return False, "API 호출 실패"

    def verify_market_vibe(self, current_data: dict, heuristic_vibe: str) -> Optional[str]:
        prompt = f"""
        실시간 데이터를 바탕으로 현재 시장 Vibe를 한 단어로 답변하세요.
        [데이터] {json.dumps(current_data)} | [알고리즘 판단] {heuristic_vibe}
        [규칙] 1.글로벌 침체/공포 시 'Defensive' 2.하락세 시 'Bear' 3.상승세 시 'Bull' 4.보합 시 'Neutral'
        오직 Bull, Bear, Neutral, Defensive 중 한 단어만 출력하세요.
        """
        # 시장 Vibe 검증은 응답 속도가 중요하므로 짧은 타임아웃(10초) 적용하여 Fallback 전환 가속화
        answer = self._safe_gemini_call(prompt, timeout=10)
        if answer:
            answer_up = answer.upper()
            for v in ["BULL", "BEAR", "NEUTRAL", "DEFENSIVE"]:
                if v in answer_up: return v.capitalize()
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
        self.last_sell_times: Dict[str, float] = {}  # 익절 발생 시각 {code: timestamp}
        self.last_sl_times: Dict[str, float] = {}     # 손절 발생 시각 {code: timestamp}
        self.last_buy_times: Dict[str, float] = {}    # 불타기/물타기 발생 시각 {code: timestamp}
        self.ai_recommendations: List[dict] = []
        self.ai_briefing, self.ai_detailed_opinion = "", ""
        self.ai_holdings_opinion = ""  # 보유 종목 리포트 결과 저장
        self.recommendation_history: Dict[str, List[dict]] = {} # {date: [recs]}
        self.yesterday_recs: List[dict] = []
        # 프리셋 전략 할당 상태 {종목코드: {"preset_id": "01", "name": "골든크로스", "tp": 8.0, "sl": -4.0, "reason": "..."}}
        self.preset_strategies: Dict[str, dict] = {}
        self.yesterday_recs_processed: List[dict] = []
        self._last_closing_bet_date = None
        self.rejected_stocks: Dict[str, str] = {} # [추가] 당일 매수 거절 종목 {code: reason}
        
        # AI 설정 초기화 (사용자 검증 기반: Group 1 수정 반영)
        self.ai_config = {
            "amount_per_trade": v_cfg.get("ai_config", {}).get("amount_per_trade", 500000),
            "min_score": v_cfg.get("ai_config", {}).get("min_score", 60.0),
            "max_investment_per_stock": v_cfg.get("ai_config", {}).get("max_investment_per_stock", 2000000),
            "auto_mode": v_cfg.get("ai_config", {}).get("auto_mode", False),
            "auto_apply": v_cfg.get("ai_config", {}).get("auto_apply", False),
            "preferred_model": v_cfg.get("ai_config", {}).get("preferred_model", "gemini-2.5-flash"),
            "fallback_sequence": v_cfg.get("ai_config", {}).get("fallback_sequence", [
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-3-flash-preview",
                "gemini-3.1-flash-lite-preview",
                "gemini-3.1-pro-preview"
            ])
        }
        
        # [추가] 매매 선행 분석 상태 관리
        self.is_ready = not self.ai_config.get("auto_mode", False)
        self.is_analyzing = False
        self.last_market_analysis_time = 0.0
        self.analysis_interval = 20
        self.analysis_status_msg = "초기화 중..."
        self.current_action = "대기중" # [추가] 현재 실행 중인 액션 상태




        
        # 2. 영속 상태(state) 로드
        self._load_all_states()
        
        # [수정] S:셋업(.env)에서 설정하는 모델이 항상 우선 적용됨
        # trading_state.json의 이전 값보다 .env의 설정값이 최우선
        self.ai_config["preferred_model"] = v_cfg.get("ai_config", {}).get("preferred_model", "gemini-2.5-flash")
        
        # Advisor 초기화 (최종 결정된 ai_config 반영)
        self.ai_advisor = GeminiAdvisor(api, self.ai_config)
        self.alpha_eng.ai_advisor = self.ai_advisor
        self.analyzer.ai_advisor = self.ai_advisor # 시장 장세 AI 검증 연결
        
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
                    self.last_sl_times = d.get("last_sl_times", {})      # 손절 시각
                    self.last_buy_times = d.get("last_buy_times", {})    # 불타기/물타기 시각
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
                "last_sl_times": self.last_sl_times,
                "last_buy_times": self.last_buy_times,
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
    @base_tp.setter
    def base_tp(self, val): self.exit_mgr.base_tp = float(val)

    @property
    def base_sl(self): return self.exit_mgr.base_sl
    @base_sl.setter
    def base_sl(self, val): self.exit_mgr.base_sl = float(val)

    @property
    def bear_config(self): return self.recovery_eng.config
    @property
    def manual_thresholds(self): return self.exit_mgr.manual_thresholds

    def set_manual_threshold(self, code, tp, sl):
        """특정 종목에 대해 수동 TP/SL 설정 (Group 2 안정성 강화)"""
        self.exit_mgr.manual_thresholds[code] = [float(tp), float(sl)]
        self._save_all_states()

    def reset_manual_threshold(self, code):
        """특정 종목의 수동 설정 해제"""
        if code in self.exit_mgr.manual_thresholds:
            del self.exit_mgr.manual_thresholds[code]
            self._save_all_states()

    def perform_full_market_analysis(self, retry=True) -> bool:
        """시장 분석을 선행하여 수치를 적용하고 is_ready 상태를 제어합니다."""
        self.current_action = "전략분석"
        try:
            # 8:시황 분석 및 적용 로직 캡슐화 (기존 8번 기능 핵심 부분)
            self.analyzer.update()
            self.apply_ai_strategy_to_all(None) # DataManager 참조 없이 수행 가능하도록 리팩토링 필요시 조정
            self.last_market_analysis_time = time.time()
            self.is_ready = True
            logger.info("시장 분석 완료 및 전략 적용 성공")
            self.current_action = "대기중"
            return True
        except Exception as e:
            # [긴급 조치] 에러 발생 시 로그를 남기고 즉시 매매 모드로 진입(멈춤 방지)
            log_error(f"시장 분석 실패 (진입 차단 해제): {e}")
            self.is_ready = True 
            self.current_action = "대기중"
            return False


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
        """전략 적용 우선순위: 1.수동(Manual) > 2.프리셋(Preset) > 3.표준(Base+Vibe)"""
        phase_cfg = self.get_market_phase()
        
        # 1. 수동 설정(3:자동 메뉴)이 있으면 최우선 (보정 없음)
        if code in self.exit_mgr.manual_thresholds:
            vals = self.exit_mgr.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), False

        # 2. 프리셋 전략이 할당된 종목 (9:전략 메뉴)
        ps = self.preset_strategies.get(code)
        if ps and ps.get("preset_id") != "00":
            return ps["tp"], ps["sl"], False
            
        # 3. 프리셋이 '표준(00)'이거나 미설정 시 기존 글로벌 로직 (Vibe/Phase 보정 포함)
        return self.exit_mgr.get_thresholds(code, vibe, p_data, phase_cfg)
    
    def get_preset_label(self, code: str) -> str:
        """종목에 적용된 전략 상태 라벨 반환 (우선순위: 수동 > 프리셋 > 표준)"""
        # 1. 수동 설정 여부 확인
        if code in self.exit_mgr.manual_thresholds:
            return "수동"
            
        # 2. 프리셋 전략 확인
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
    
    def assign_preset(self, code: str, preset_id: str, tp: float = None, sl: float = None, reason: str = "", lifetime_mins: int = None, name: str = ""):
        """종목에 프리셋 전략 할당 (표준 선택 시 기존 설정으로 복귀)"""
        preset = PRESET_STRATEGIES.get(preset_id)
        if not preset:
            return False
        
        # 이름이 없는 경우 기존 저장된 정보나 보유 종목에서 찾기 시도
        if not name:
            if code in self.preset_strategies: name = self.preset_strategies[code].get('name', '')
            if not name:
                # API나 DataManager를 직접 참조하기 어려우므로 최대한 인자로 받는 것이 좋음
                pass

        if preset_id == "00":
            # 표준 모드: 프리셋 해제 (기본 전략으로 복귀)
            if code in self.preset_strategies:
                del self.preset_strategies[code]
                name_txt = f" {name}" if name else ""
                trading_log.log_config(f"전략 해제: [{code}]{name_txt} (표준 복귀)")
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
            name_txt = f" {name}" if name else ""
            trading_log.log_config(f"전략 할당: [{code}]{name_txt} ({preset['name']}) | TP:{use_tp}% SL:{use_sl}%")
        self._save_all_states()
        return True
    
    def confirm_buy_decision(self, code: str, name: str) -> Tuple[bool, str]:
        """매수 전 AI에게 최종 의사를 묻고 거절 시 사유를 기록합니다."""
        # 1. 이미 당일 거절된 종목인지 체크
        if code in self.rejected_stocks:
            return False, f"당일 매수 거절됨: {self.rejected_stocks[code]}"
        
        # 2. AI 최종 컨펌 요청
        detail = self.api.get_naver_stock_detail(code)
        news = self.api.get_naver_stock_news(code)
        vibe = self.current_market_vibe
        
        is_confirmed, reason = self.ai_advisor.final_buy_confirm(code, name, vibe, detail, news)
        
        if not is_confirmed:
            self.rejected_stocks[code] = reason
            self._save_all_states()
            # 거절 로그 기록
            trading_log.log_config(f"❌ AI 매수 거절: [{code}]{name} | 사유: {reason}")
            return False, reason
            
        return True, "승인됨"

    def record_buy(self, code, price):
        self.recovery_eng.last_avg_down_prices[code] = price
        self.pyramid_eng.last_buy_prices[code] = price
        self.last_buy_times[code] = time.time()  # 불타기/물타기 시각 기록
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
            
            # 구조화된 로그 기록 (Group 2)
            trading_log.log_config(f"AI 전략 자동 반영: TP +{target_tp}%, SL {target_sl}%, 물타기 {target_trig_bear}%, 불타기 +{target_trig_bull}%, 금액 {new_amt:,}원")
            
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

    # ─────────────────────────────────────────────────────────────────────────
    # 핑퐁 방지 & 긴급 조건 판단 유틸리티
    # ─────────────────────────────────────────────────────────────────────────

    def _is_in_partial_sell_cooldown(self, code: str, curr_t: float) -> bool:
        """
        익절 쿨다운(1시간) 체크.
        불타기/물타기가 마지막 익절 이후에 발생한 경우 쿨다운을 자동 리셋 → 즉시 익절 허용.
        (불타기 후 TP 도달 시 익절 블로킹 방지)
        """
        last_sell_t = self.last_sell_times.get(code, 0)
        last_buy_t  = self.last_buy_times.get(code, 0)
        # 불타기/물타기가 마지막 익절보다 더 최신 → 쿨다운 리셋
        if last_buy_t > last_sell_t:
            return False
        return (curr_t - last_sell_t) < 3600  # 1시간

    def _is_emergency_exit(self, rt: float, tp: float, vol_spike: bool,
                           phase: dict, after_buy: bool = False) -> Tuple[bool, str]:
        """
        익절 쿨다운 바이패스 긴급 조건.
          after_buy=True  (불타기 직후): 기준 완화  TP+2.0%, vol+1.0%
          after_buy=False (일반 쿨다운): 기준 엄격  TP+3.0%, vol+1.5%
        """
        surplus_thr = 2.0 if after_buy else 3.0
        vol_thr     = 1.0 if after_buy else 1.5
        if rt >= tp + surplus_thr:
            return True, f"급등초과+{rt - tp:.1f}%"
        if vol_spike and rt >= tp + vol_thr:
            return True, "거래량폭발"
        if phase['id'] == 'P4' and rt >= 0.5:
            return True, "장마감"
        return False, ""

    def _is_emergency_sl(self, rt: float, sl: float, is_panic: bool,
                         vibe: str, phase: dict, after_avg_down: bool = False) -> Tuple[bool, str]:
        """
        물타기 직후 30분 유예 중에도 즉시 손절을 강제하는 긴급 조건.
          after_avg_down=True  (물타기 직후): 기준 완화  SL-1.0%
          after_avg_down=False (일반):        기준 엄격  SL-2.0%
        """
        extra = 1.0 if after_avg_down else 2.0
        if rt <= sl - extra:
            return True, f"추가급락{rt - sl:.1f}%"
        if is_panic:
            return True, "글로벌패닉"
        if vibe.upper() == "DEFENSIVE":
            return True, "방어모드전환"
        if phase['id'] == 'P4' and rt < 0:
            return True, "장마감청산"
        return False, ""

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
                                    # 구조화된 로그 기록 (Group 2)
                                    trading_log.log_trade("P4종가매수", code, name, price, qty, "AI 추천 기반 종가 베팅")
                                    self.auto_assign_preset(code, name)
                                    self._save_all_states()

        for item in holdings:
            code = item.get("pdno")
            p_strat = self.preset_strategies.get(code)
            
            # [Task 4] 시간 기반 자동 매매 액션 구현
            if p_strat:
                # 1. Time-Stop 체크: 데드라인 초과 시 AI 기반 전략 재수립
                if p_strat.get('deadline') and now_str > p_strat['deadline']:
                    logger.info(f"Time-Stop: {item.get('prdt_name')} 전략 만료, 재분석 실행")
                    # 재분석 성공 시 새 전략 적용
                    success = self.auto_assign_preset(code, item.get('prdt_name'))
                    
                    if not success:
                        # 재수립 실패 시 기존 수익 보존 로직(Fallback) 수행
                        logger.warning(f"전략 재수립 실패: {item.get('prdt_name')} 기존 로직으로 수익 보존")
                        curr_rt = float(item.get("evlu_pfls_rt", 0.0))
                        if curr_rt >= 0.5:
                            p_strat['tp'] = max(0.5, curr_rt / 2.0)
                            results.append(f"Time-Stop TP 하향(Fallback): {item.get('prdt_name')} ({p_strat['tp']:.1f}%)")
                        
                        # Fallback 적용 후 데드라인을 None으로 처리하여 무한 루프 방지
                        p_strat['deadline'] = None 
                    else:
                        results.append(f"🔄 전략 자동 갱신: {item.get('prdt_name')}")
                    
                    self._save_all_states()



                # 2. Phase 3 (CONCLUSION): 수익권 50% 분할 매도 및 SL 상향 (프리셋 종목)
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
                                results.append(f"🏁 P3 수익확정(50%): {item.get('prdt_name')}")
                                trading_log.log_trade("P3수익확정(50%)", code, item.get('prdt_name'),
                                                      float(item.get('prpr', 0)), sell_qty, "Phase3 장마감 대비 분할매도")
                                self._save_all_states()
                        elif curr_rt >= 0.5:
                            # skip_trade 시에도 처리된 것으로 마킹 (테스트 모드 등)
                            p_strat['is_p3_processed'] = True

            else:
                # [핵심 수정] 프리셋 미설정 표준 종목에도 P3/P4 수익확정 로직 적용
                # P3_global: 오늘 날짜별로 종목 처리 여부 추적
                if not hasattr(self, '_p3_global_processed'):
                    self._p3_global_processed = {}
                p3_key = f"{today}_{code}"

                # Phase 3: 수익권이면 50% 분할 매도 + 수동 SL을 본전(+0.2%)으로 상향
                if phase['id'] == "P3" and p3_key not in self._p3_global_processed:
                    curr_rt = float(item.get("evlu_pfls_rt", 0.0))
                    if curr_rt >= 0.5:
                        sell_qty = int(float(item.get('hldg_qty', 0))) // 2
                        if sell_qty > 0 and not skip_trade:
                            success, msg = self.api.order_market(code, sell_qty, False)
                            if success:
                                self._p3_global_processed[p3_key] = True
                                # 수동 TP/SL에 본전 스탑 설정
                                tp_cur, sl_cur, _ = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
                                self.exit_mgr.manual_thresholds[code] = [tp_cur, 0.2]
                                results.append(f"🏁 P3 수익확정(50%): {item.get('prdt_name')} | SL→본전(+0.2%)")
                                trading_log.log_trade("P3수익확정(50%)", code, item.get('prdt_name'),
                                                      float(item.get('prpr', 0)), sell_qty, "Phase3 표준종목 분할매도")
                                self._save_all_states()
                        else:
                            self._p3_global_processed[p3_key] = True

                # Phase 4: 손실권이면 전량 청산 (표준 종목)
                elif phase['id'] == "P4":
                    curr_rt = float(item.get("evlu_pfls_rt", 0.0))
                    p4_key = f"p4_{today}_{code}"
                    if curr_rt < 0 and p4_key not in self._p3_global_processed:
                        sell_qty = int(float(item.get('hldg_qty', 0)))
                        if sell_qty > 0 and not skip_trade:
                            success, msg = self.api.order_market(code, sell_qty, False)
                            if success:
                                self._p3_global_processed[p4_key] = True
                                results.append(f"💤 P4 장마감 손절: {item.get('prdt_name')}")
                                trading_log.log_trade("P4장마감손절", code, item.get('prdt_name'),
                                                      float(item.get('prpr', 0)), sell_qty, "Phase4 비용절감 청산")
                                self._save_all_states()

            # 3. 개선된 TP/SL 체크 (쿨다운 + 긴급 바이패스 포함)
            tp, sl, vol_spike = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
            rt = float(item.get("evlu_pfls_rt", 0.0))
            action, sell_qty, action_reason = None, 0, ""
            last_buy_t  = self.last_buy_times.get(code, 0)
            last_sell_t = self.last_sell_times.get(code, 0)

            if rt >= tp:
                # ── 익절 판단 ──────────────────────────────────────────────
                in_cooldown = self._is_in_partial_sell_cooldown(code, curr_t)
                if not in_cooldown:
                    # 쿨다운 없음: 정상 익절
                    action = "익절"
                    sell_qty = max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
                else:
                    # 쿨다운 중: 긴급 조건 충족 시만 바이패스
                    after_buy = (last_buy_t > last_sell_t)  # 불타기/물타기가 더 최신?
                    is_emg, emg_reason = self._is_emergency_exit(
                        rt, tp, vol_spike, phase, after_buy)
                    if is_emg:
                        action, action_reason = "긴급익절", emg_reason
                        sell_qty = max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
                    else:
                        # 스킵: 익절 쿨다운 중 + 긴급 조건 미충족
                        _elapsed = curr_t - self.last_sell_times.get(code, 0)
                        _rem_min = max(0, int((3600 - _elapsed) / 60))
                        _ctx     = "불타기직후" if after_buy else "익절직후"
                        results.append(
                            f"⏸ 스킵(익절쿨다운/{_ctx}): {item.get('prdt_name')}({code}) "
                            f"수익률 {rt:+.1f}% / TP {tp:+.1f}% / 잔여 {_rem_min}분"
                        )

            elif rt <= sl:
                # ── 손절 판단 ──────────────────────────────────────────────
                # 물타기 직후 30분(1800초) 이내: 즉각 손절 유예, 단 긴급 조건은 바이패스
                after_avg_down = (
                    (curr_t - last_buy_t) < 1800 and
                    last_buy_t > last_sell_t  # 물타기/불타기가 마지막 익절보다 최신
                )
                if after_avg_down:
                    is_emg, emg_reason = self._is_emergency_sl(
                        rt, sl, self.analyzer.is_panic,
                        self.analyzer.kr_vibe, phase, after_avg_down=True)
                    if is_emg:
                        action, action_reason = "긴급손절", emg_reason
                        sell_qty = int(item.get('hldg_qty', 0))
                    else:
                        # 스킵: 물타기 직후 30분 유예 중 + 긴급 조건 미충족
                        _rem_min = max(0, int((1800 - (curr_t - last_buy_t)) / 60))
                        results.append(
                            f"⏸ 스킵(물타기유예): {item.get('prdt_name')}({code}) "
                            f"수익률 {rt:+.1f}% / SL {sl:.1f}% / 잔여 {_rem_min}분"
                        )
                else:
                    # 일반 손절 (쿨다운 없음)
                    action = "손절"
                    sell_qty = int(item.get('hldg_qty', 0))

            if action and not skip_trade and sell_qty > 0:
                self.current_action = f"{action}실행"
                success, msg = self.api.order_market(code, sell_qty, False)
                if success:
                    reason_str = f"({action_reason})" if action_reason else ""
                    curr_p = float(item.get('prpr', 0))
                    pchs_avg = float(item.get('pchs_avg_pric', 0))
                    
                    # 수익금 계산: (현재가 - 매입평단) * 매도수량
                    trade_profit = (curr_p - pchs_avg) * sell_qty
                    
                    if "익절" in action:
                        self.last_sell_times[code] = curr_t
                    elif "손절" in action:
                        self.last_sl_times[code] = curr_t
                    
                    # 구조화된 로그 기록 (Group 2)
                    trading_log.log_trade(action, code, item.get('prdt_name'), curr_p, sell_qty, action_reason or action, profit=trade_profit)
                    
                    self._save_all_states()
                    results.append(f"자동 {action}{reason_str}: {item.get('prdt_name')} {sell_qty}주")
                self.current_action = "대기중"
        return results
