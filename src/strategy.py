import os
import json
import math
import time
from typing import Dict, List, Tuple, Optional
from src.logger import logger

# --- 1. MarketAnalyzer: 시장 분석 엔진 (국내/글로벌 분리) ---
class MarketAnalyzer:
    """글로벌 패닉 감지 및 국내 시장 Vibe(Bull/Bear) 분석 클래스"""
    def __init__(self, api):
        self.api = api
        self.current_data = {}
        self.is_panic = False
        self.kr_vibe = "Neutral"

    def update(self) -> Tuple[str, bool]:
        """최신 지수 데이터를 바탕으로 시장 상태 갱신"""
        self.current_data = {
            "KOSPI": self.api.get_index_price("0001"),
            "KOSDAQ": self.api.get_index_price("1001"),
            "KPI200": self.api.get_index_price("KPI200"),
            "VOSPI": self.api.get_index_price("VOSPI"),
            "FX_USDKRW": self.api.get_index_price("FX_USDKRW"),
            "DOW": self.api.get_index_price("DOW"),
            "NASDAQ": self.api.get_index_price("NAS"),
            "S&P500": self.api.get_index_price("SPX"),
            "NAS_FUT": self.api.get_index_price("NAS_FUT"),
            "SPX_FUT": self.api.get_index_price("SPX_FUT")
        }
        
        # 1. Global Panic 감지 (US 3대 지수/선물 -1.5% 이하 또는 환율 1.0% 이상 급등 시)
        self.is_panic = self._check_global_panic()
        
        # 2. 국내 Vibe 판별 (오직 KOSPI, KOSDAQ 기준)
        self.kr_vibe = self._check_kr_vibe()
        
        return self.kr_vibe, self.is_panic

    def _check_global_panic(self) -> bool:
        """글로벌 지수 및 환율 급락 여부 확인"""
        # US 지수 체크
        us_targets = ["NASDAQ", "S&P500", "NAS_FUT", "SPX_FUT"]
        for target in us_targets:
            data = self.current_data.get(target)
            if data and data['rate'] <= -1.5:
                return True
        
        # 환율 급등 체크 (1.0% 이상 상승 시 위험 신호)
        usd_krw = self.current_data.get("FX_USDKRW")
        if usd_krw and usd_krw['rate'] >= 1.0:
            return True
            
        return False

    def _check_kr_vibe(self) -> str:
        """국내 지수 평균 등락률로 Vibe 결정"""
        kr_targets = ["KOSPI", "KOSDAQ"]
        active_kr = [self.current_data.get(k) for k in kr_targets if self.current_data.get(k)]
        if not active_kr: return "Neutral"
        
        avg_rate = sum(idx['rate'] for idx in active_kr) / len(active_kr)
        if avg_rate >= 0.5: return "Bull"
        if avg_rate <= -0.5: return "Bear"
        return "Neutral"

# --- 2. ExitManager: 익절/손절 엔진 (안전마진 확보) ---
class ExitManager:
    """종목별 TP/SL 계산 및 수동 설정 관리 클래스"""
    def __init__(self, base_tp: float, base_sl: float):
        self.base_tp = base_tp # 기본 5.0
        self.base_sl = base_sl # 기본 -5.0
        self.manual_thresholds: Dict[str, List[float]] = {}

    def get_thresholds(self, code: str, kr_vibe: str, price_data: Optional[dict] = None) -> Tuple[float, float, bool]:
        """보정을 거친 최종 TP/SL 반환 (수동 설정 우선)"""
        # 0. 수동 오버라이드
        if code in self.manual_thresholds:
            vals = self.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), True

        target_tp = self.base_tp
        target_sl = self.base_sl

        # 1. 상승장 보정 (+3.0%) - 대소문자 무관하게 체크
        if kr_vibe.lower() == "bull":
            target_tp += 3.0

        # 2. 거래량 폭발 보정 (+3.0%)
        is_vol_spike = False
        if price_data and price_data.get('prev_vol', 0) > 0:
            vol_ratio = price_data['vol'] / price_data['prev_vol']
            if vol_ratio >= 1.5:
                target_tp += 3.0
                # CRITICAL: 휩쏘 방지를 위해 손절선은 줄이지 않고 유지함
                is_vol_spike = True

        return target_tp, target_sl, is_vol_spike

# --- 3. RecoveryEngine: 물타기 엔진 (가격 기반 쿨다운) ---
class RecoveryEngine:
    """정밀한 물타기 타이밍 및 평단 시뮬레이션 클래스"""
    def __init__(self, config: dict):
        self.config = config
        self.last_avg_down_prices: Dict[str, float] = {} # {code: price}

    def get_recommendation(self, item: dict, is_panic: bool) -> Optional[dict]:
        """물타기 적합 여부 판단 및 결과 반환"""
        if is_panic: return None # 패닉 시 신규 진입/추가 매수 전면 차단
        
        code = item.get("pdno")
        curr_price = float(item.get("prpr", 0))
        curr_avg = float(item.get("pchs_avg_pric", 0))
        curr_rt = float(item.get("evlu_pfls_rt", 0.0))
        
        # 1. 논리적 격리: -3.0% 이하에서 시작하되, 손절선인 -5.0% 터치 전까지만 작동
        if -5.0 < curr_rt <= self.config.get("min_loss_to_buy", -3.0) and curr_price < curr_avg:
            
            # 2. 가격 기반 쿨다운: 직전 매수가 대비 -2.0% 추가 하락 시에만 승인
            last_price = self.last_avg_down_prices.get(code, curr_avg)
            price_drop = ((curr_price - last_price) / last_price * 100) if last_price > 0 else 0
            
            # 기록이 없거나(최초) -2% 이상 더 빠졌을 때만
            if code not in self.last_avg_down_prices or price_drop <= -2.0:
                return self._simulate(item)
        
        return None

    def _simulate(self, item: dict) -> dict:
        """추가 매수 후의 예상 평단 변화 계산"""
        curr_avg = float(item.get("pchs_avg_pric", 0))
        curr_qty = float(item.get("hldg_qty", 0))
        curr_price = float(item.get("prpr", 0))
        spend_amt = self.config.get("average_down_amount", 500000)
        
        buy_qty = math.floor(spend_amt / curr_price)
        if buy_qty > 0:
            new_cost = (curr_avg * curr_qty) + (buy_qty * curr_price)
            new_qty = curr_qty + buy_qty
            new_avg = new_cost / new_qty
            
            diff_rt = ((new_avg - curr_avg) / curr_avg * 100) if curr_avg > 0 else 0
            return {
                "code": item.get("pdno"),
                "name": item.get("prdt_name"),
                "suggested_amt": spend_amt,
                "expected_avg_change": f"{int(new_avg - curr_avg):+,}({abs(diff_rt):.2f}%)"
            }
        return {}

# --- VibeStrategy Facade ---
class VibeStrategy:
    def __init__(self, api, config):
        self.api = api
        v_cfg = config.get("vibe_strategy", {})
        
        self.analyzer = MarketAnalyzer(api)
        self.exit_mgr = ExitManager(v_cfg.get("take_profit_threshold", 5.0), v_cfg.get("stop_loss_threshold", -5.0))
        self.recovery_eng = RecoveryEngine(v_cfg.get("bear_market", {}))
        
        self.state_file = "trading_state.json"
        self.last_avg_down_msg = "없음"
        self._load_all_states()

    def _load_all_states(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self.exit_mgr.manual_thresholds = data.get("manual_thresholds", {})
                    self.recovery_eng.last_avg_down_prices = data.get("last_avg_down_prices", {})
                    self.last_avg_down_msg = data.get("last_avg_down_msg", "없음")
            except: pass

    def _save_all_states(self):
        try:
            data = {
                "manual_thresholds": self.exit_mgr.manual_thresholds,
                "last_avg_down_prices": self.recovery_eng.last_avg_down_prices,
                "last_avg_down_msg": self.last_avg_down_msg
            }
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"상태 저장 실패: {e}")

    # Facade Properties
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
    def manual_thresholds(self): return self.exit_mgr.manual_thresholds
    @property
    def bear_config(self): return self.recovery_eng.config

    def determine_market_trend(self): return self.analyzer.update()
    def save_manual_thresholds(self): self._save_all_states()
    def get_dynamic_thresholds(self, code, vibe, p_data=None): return self.exit_mgr.get_thresholds(code, vibe, p_data)

    def get_buy_recommendations(self, market_trend):
        holdings = self.api.get_balance()
        recs = [self.recovery_eng.get_recommendation(h, self.analyzer.is_panic) for h in holdings]
        return [r for r in recs if r]

    def run_cycle(self, market_trend="neutral", skip_trade=False):
        holdings = self.api.get_balance()
        results = []
        for item in holdings:
            tp, sl, _ = self.get_dynamic_thresholds(item.get("pdno"), self.analyzer.kr_vibe)
            rt = float(item.get("evlu_pfls_rt", 0.0))
            if rt >= tp: action = "익절"
            elif rt <= sl: action = "손절"
            else: continue
            
            if not skip_trade:
                time.sleep(1.1)
                qty = int(item.get("hldg_qty", 0))
                sell_qty = max(1, math.floor(qty * 0.3)) if action == "익절" else qty
                success, msg = self.api.order_market(item.get("pdno"), sell_qty, False)
                if success: results.append(f"자동 {action} 성공: {item.get('prdt_name')}")
        return results

    def record_buy(self, code, price):
        self.recovery_eng.last_avg_down_prices[code] = price
        self._save_all_states()
