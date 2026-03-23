import os
import json
import math
import time
import requests
import re
from typing import Dict, List, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from src.logger import logger, log_error

# --- 1. MarketAnalyzer: 시장 분석 엔진 ---
class MarketAnalyzer:
    def __init__(self, api):
        self.api = api
        self.current_data = {}
        self.is_panic = False
        self.kr_vibe = "Neutral"

    def update(self) -> Tuple[str, bool]:
        import concurrent.futures
        symbol_map = {
            "KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KPI200": "KPI200", "VOSPI": "VOSPI",
            "FX_USDKRW": "FX_USDKRW", "DOW": "DOW", "NASDAQ": "NASDAQ", "S&P500": "S&P500",
            "NAS_FUT": "NAS_FUT", "SPX_FUT": "SPX_FUT"
        }
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(symbol_map)) as executor:
            future_to_symbol = {executor.submit(self.api.get_index_price, code): s for s, code in symbol_map.items()}
            for future in concurrent.futures.as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    data = future.result()
                    if data: self.current_data[symbol] = data
                except Exception as e:
                    log_error(f"Index Fetch Error ({symbol}): {e}")
        self.is_panic = self._check_global_panic()
        self.kr_vibe = self._check_circuit_breaker()
        if self.kr_vibe == "Neutral":
            self.kr_vibe = self._check_kr_vibe()
        return self.kr_vibe, self.is_panic

    def _check_circuit_breaker(self) -> str:
        vix = self.current_data.get("VOSPI")
        if vix and (vix['price'] >= 25.0 or vix['rate'] >= 5.0): return "DEFENSIVE"
        usd_krw = self.current_data.get("FX_USDKRW")
        nas = self.current_data.get("NASDAQ")
        if usd_krw and nas and usd_krw['price'] >= 1500.0 and nas['rate'] <= -1.0: return "DEFENSIVE"
        return "Neutral"

    def _check_global_panic(self) -> bool:
        us_targets = ["NASDAQ", "S&P500", "NAS_FUT", "SPX_FUT"]
        for target in us_targets:
            data = self.current_data.get(target)
            if data and data['rate'] <= -1.5: return True
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

    def get_thresholds(self, code: str, kr_vibe: str, price_data: Optional[dict] = None) -> Tuple[float, float, bool]:
        # 1. 특정 종목 수동 설정(Manual)이 있으면 최우선 적용 (보정 없음)
        if code in self.manual_thresholds:
            vals = self.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), True
            
        # 2. 기본값(AI가 설정한 값 포함) 가져오기
        target_tp, target_sl = self.base_tp, self.base_sl
        
        # 3. 시장 분위기(Vibe)에 따른 실시간 보정 적용
        tp_mod, sl_mod = self.get_vibe_modifiers(kr_vibe)
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

    def get_recommendation(self, item: dict, vibe: str, is_panic: bool, vol_spike: bool) -> Optional[dict]:
        if is_panic or vibe.lower() in ["bear", "defensive"]: return None
        code = item.get("pdno")
        curr_p, curr_avg = float(item.get("prpr", 0)), float(item.get("pchs_avg_pric", 0))
        curr_rt = float(item.get("evlu_pfls_rt", 0.0))
        if curr_rt >= 3.0 and (vibe.lower() == "bull" or vol_spike) and curr_p > curr_avg:
            last_p = self.last_buy_prices.get(code, curr_avg)
            if curr_p > last_p:
                amt = self.config.get("average_down_amount", 500000) // 2
                return {"code": code, "name": item.get("prdt_name"), "suggested_amt": amt, "type": "불타기", "expected_avg_change": "수익 비중 확대"}
        return None

# --- 4. VibeAlphaEngine: AI 자율 매매 ---
class VibeAlphaEngine:
    def __init__(self, api):
        self.api = api

    def analyze(self, themes: List[dict], hot_raw: List[dict], vol_raw: List[dict], min_score: float = 60.0, progress_cb: Optional[Callable] = None) -> List[dict]:
        """주도 테마 및 랭킹 데이터를 분석하여 국내 종목과 ETF 분리 추출 (병렬 처리)"""
        from main import THEME_KEYWORDS
        import threading
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
            
            candidates.append((item, my_theme))

        # 펀더멘털 데이터 병렬 수집 (속도 개선 핵심)
        current = 0
        total = len(candidates)
        lock = threading.Lock()
        def fetch_detail(cand):
            nonlocal current
            item, theme = cand
            # get_naver_stock_detail 내부에서 캐시 처리됨
            self.api.get_naver_stock_detail(item['code'])
            with lock:
                current += 1
                if progress_cb:
                    progress_cb(current, total)
            return cand

        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(fetch_detail, candidates))

        stocks, etfs = [], []
        for item, my_theme in candidates:
            score = self._calculate_ai_score(item, my_theme, False)
            if score < min_score: continue
            
            res = {**item, "score": score, "theme": my_theme['name'], "is_gem": False, "reason": f"{my_theme['name']} 주도주 매수세 유입"}
            is_etf = any(ex in item['name'].upper() for ex in ["KODEX", "TIGER", "KBSTAR", "ACE", "RISE", "SOL", "HANARO"])
            if is_etf:
                etfs.append(res)
            else:
                rate = float(item.get('rate', 0))
                if rate > 10.0: continue 
                stocks.append(res)

        # 개별 종목 상위 6개, ETF 상위 3개 선정
        final_stocks = sorted(stocks, key=lambda x: x['score'], reverse=True)[:6]
        final_etfs = sorted(etfs, key=lambda x: x['score'], reverse=True)[:3]
        for s in final_stocks: s['is_etf'] = False
        for e in final_etfs: e['is_etf'] = True
        
        return final_stocks + final_etfs

    def _calculate_ai_score(self, stock: dict, theme: dict, is_gem: bool) -> float:
        """종목별 입체 점수 산정 (테마 + 등락률 + 펀더멘털)"""
        score = 40.0 # 기본 베이스 점수
        rate = abs(float(stock.get('rate', 0)))
        
        # 1. 등락률/테마 점수 (기본 모멘텀 - 30점 만점)
        # 0%에 가까울수록 선취매 매력도 상승
        score += (5.0 - min(5.0, rate)) * 3
        # 테마 내 밀집도 반영
        score += min(15, theme['count'] * 1.5)
        
        # 2. 펀더멘털 지표 보정 (실적 및 가치 - 30점 만점)
        # 네이버 금융에서 지표 데이터 수집 (캐시를 활용하므로 성능 저하 최소화)
        code = stock['code']
        detail = self.api.get_naver_stock_detail(code)
        
        try:
            # PBR 보정 (PBR 1.0 이하 선호, 20.0 이상 감점)
            pbr_val = float(detail.get('pbr', '0').replace(',', '')) if detail.get('pbr') != 'N/A' else 1.0
            if pbr_val <= 1.0: score += 15.0
            elif pbr_val <= 3.0: score += 8.0
            elif pbr_val >= 10.0: score -= 15.0 # 극심한 고평가 감점 (삼천당제약 케이스 대비)
            
            # PER 보정 (PER 10 이하 선호, 50 이상 감점)
            per_val = float(detail.get('per', '0').replace(',', '')) if detail.get('per') != 'N/A' else 20.0
            if per_val <= 10.0: score += 10.0
            elif per_val <= 20.0: score += 5.0
            elif per_val >= 50.0: score -= 10.0
        except: pass
        
        # 3. 소외주 및 테마 집중도 보너스 (10점)
        if is_gem: score += 10.0
        
        return round(score, 1)

# --- 5. GeminiAdvisor: 생성형 AI 전략 보좌관 ---
class GeminiAdvisor:
    def __init__(self, api):
        self.api = api
        self.model_id = "gemini-3.1-flash-lite-preview"
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def get_advice(self, market_data: dict, vibe: str, holdings: List[dict], current_config: dict) -> Optional[str]:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: return "⚠️ GOOGLE_API_KEY가 없습니다."
        
        holdings_txt = "\n".join([f"- {h['prdt_name']}({h['pdno']}): 수익률 {h['evlu_pfls_rt']}%" for h in holdings])
        prompt_text = f"""
        당신은 월스트리트 수석 퀀트 트레이더입니다. 아래 데이터를 분석해 실전 매매 전략을 3줄로 브리핑하세요.
        
        [데이터]
        - 시장Vibe: {vibe} / 지수: {json.dumps(market_data)}
        - 포트폴리오: {holdings_txt if holdings else "보유 종목 없음"}
        - 현재설정: 익절 {current_config.get('base_tp')}%, 손절 {current_config.get('base_sl')}%, 물타기 {current_config.get('bear_trig')}%
        
        [필수 내용 및 절대 규칙]
        1. 현재 시장 리스크 및 분위기 요약.
        2. [익절/손절/물타기/추매/금액] 통합 수치 제안.
           - [논리 규칙] 추가매수(물타기) 지점은 반드시 손절선(SL)보다 높은(덜 손실인) 수치여야 합니다.
           - [답변 양식] AI[전략]: 익절 +X.X%, 손절 -Y.Y%, 물타기 -Z.Z%, 추매 +W.W%, 금액 N원
        3. 신규 추천주 최우선 순위와 매수 권장 금액.
        
        [답변 형식 엄수] 
        AI[시장]: 요약
        AI[전략]: (위 답변 양식대로 수치만 명확히 기재)
        AI[액션]: 매수 지시 및 포트폴리오 조정
        AI[추천]: 신규 추천 종목 및 매수가격 요약
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
        import threading
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

# --- VibeStrategy Facade ---
class VibeStrategy:
    def __init__(self, api, config):
        self.api = api
        v_cfg = config.get("vibe_strategy", {})
        self.analyzer = MarketAnalyzer(api)
        self.exit_mgr = ExitManager(v_cfg.get("take_profit_threshold", 5.0), v_cfg.get("stop_loss_threshold", -5.0))
        self.recovery_eng = RecoveryEngine(v_cfg.get("bear_market", {}))
        self.pyramid_eng = PyramidingEngine(v_cfg.get("bear_market", {}))
        self.alpha_eng = VibeAlphaEngine(api)
        self.ai_advisor = GeminiAdvisor(api)
        self.state_file = "trading_state.json"
        self.last_avg_down_msg = "없음"
        self.last_sell_times: Dict[str, float] = {}
        self.ai_recommendations: List[dict] = []
        self.ai_briefing, self.ai_detailed_opinion = "", ""
        self.ai_config = {"amount_per_trade": 500000, "min_score": 60.0, "max_investment_per_stock": 2000000, "auto_mode": False}
        self._load_all_states()

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
                    if "ai_config" in d: self.ai_config.update(d["ai_config"])
                    if "bear_config" in d: self.recovery_eng.config.update(d["bear_config"])
            except: pass

    def _save_all_states(self):
        try:
            data = {
                "base_tp": self.exit_mgr.base_tp,
                "base_sl": self.exit_mgr.base_sl,
                "manual_thresholds": self.exit_mgr.manual_thresholds,
                "last_avg_down_prices": self.recovery_eng.last_avg_down_prices,
                "last_buy_prices": self.pyramid_eng.last_buy_prices,
                "last_sell_times": self.last_sell_times,
                "last_avg_down_msg": self.last_avg_down_msg,
                "ai_config": self.ai_config,
                "bear_config": self.recovery_eng.config
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
    def get_dynamic_thresholds(self, code, vibe, p_data=None): return self.exit_mgr.get_thresholds(code, vibe, p_data)
    def record_buy(self, code, price):
        self.recovery_eng.last_avg_down_prices[code] = price
        self.pyramid_eng.last_buy_prices[code] = price
        self._save_all_states()

    def update_ai_recommendations(self, themes, hot_raw, vol_raw, progress_cb: Optional[Callable] = None):
        try: self.ai_recommendations = self.alpha_eng.analyze(themes, hot_raw, vol_raw, self.ai_config.get("min_score", 60.0), progress_cb=progress_cb)
        except: pass

    def get_ai_advice(self, progress_cb: Optional[Callable] = None):
        holdings = self.api.get_balance()
        base_sl = self.exit_mgr.base_sl
        if self.analyzer.kr_vibe.upper() == "DEFENSIVE": base_sl = -3.0
        current_cfg = {"base_tp": self.exit_mgr.base_tp, "base_sl": base_sl, "bear_trig": max(self.recovery_eng.config.get("min_loss_to_buy"), base_sl + 1.0), "ai_amt": self.ai_config["amount_per_trade"]}
        self.ai_briefing = self.ai_advisor.get_advice(self.analyzer.current_data, self.analyzer.kr_vibe, holdings, current_cfg)
        self.ai_detailed_opinion = self.ai_advisor.get_detailed_report_advice(self.ai_recommendations, self.analyzer.kr_vibe, progress_cb=progress_cb)
        return self.ai_briefing

    def parse_and_apply_ai_strategy(self) -> bool:
        """AI[전략] 라인에서 수치를 파싱하여 시스템에 즉시 반영 (Vibe 역산 적용)"""
        if not self.ai_briefing: return False
        try:
            strat_line = ""
            for line in self.ai_briefing.split('\n'):
                if "AI[전략]:" in line: strat_line = line; break
            if not strat_line: return False

            tp = re.search(r"익절\s*([+-]?[\d.]+)", strat_line)
            sl = re.search(r"손절\s*([+-]?[\d.]+)", strat_line)
            trig = re.search(r"물타기\s*([+-]?[\d.]+)", strat_line)
            amt = re.search(r"금액\s*([\d,]+)", strat_line)
            if not (tp and sl and trig and amt): return False
            
            # 1. AI가 제안한 '최종 유효값' 파싱
            target_tp = abs(float(tp.group(1)))
            target_sl = -abs(float(sl.group(1)))
            target_trig = -abs(float(trig.group(1)))
            new_amt = int(amt.group(1).replace(',', ''))
            
            # 2. 현재 Vibe에 따른 보정치 역산
            # 목표값 = Base + Modifier -> Base = 목표값 - Modifier
            tp_mod, sl_mod = self.exit_mgr.get_vibe_modifiers(self.analyzer.kr_vibe)
            
            # 기본값(Base) 설정
            self.exit_mgr.base_tp = target_tp - tp_mod
            self.exit_mgr.base_sl = target_sl - sl_mod
            
            # 3. 물타기 트리거 반영 (손절선과의 격차 자동 보정 포함)
            self.recovery_eng.config["min_loss_to_buy"] = target_trig
            self.recovery_eng.config["average_down_amount"] = new_amt
            self.ai_config["amount_per_trade"] = new_amt
            
            self._save_all_states()
            return True
        except Exception as e:
            log_error(f"AI 전략 파싱 에러: {e}")
            return False

    def get_buy_recommendations(self, market_trend):
        holdings = self.api.get_balance(); recs = []
        for h in holdings:
            _, sl, _ = self.get_dynamic_thresholds(h.get('pdno'), self.analyzer.kr_vibe)
            r = self.recovery_eng.get_recommendation(h, self.analyzer.is_panic, sl)
            if not r: r = self.pyramid_eng.get_recommendation(h, self.analyzer.kr_vibe, self.analyzer.is_panic, False)
            if r: recs.append(r)
        return recs

    def run_cycle(self, market_trend="neutral", skip_trade=False):
        holdings = self.api.get_balance(); results, curr_t = [], time.time()
        for item in holdings:
            code = item.get("pdno")
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
