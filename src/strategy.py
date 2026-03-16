import os
import time
import json
import math
import sys
from src.logger import logger

# OS별 비차단 입력을 위한 설정
if sys.platform == 'win32':
    import msvcrt
else:
    import select
    import termios
    import tty

class VibeStrategy:
    def __init__(self, api, config):
        self.api = api
        self.config = config.get("vibe_strategy", {})
        
        # 기본 전략 세팅
        self.base_tp = self.config.get("take_profit_threshold", 5.0)
        self.base_sl = self.config.get("stop_loss_threshold", -3.0)
        self.tp_ratio = self.config.get("take_profit_ratio", 0.3)
        self.sl_ratio = self.config.get("stop_loss_ratio", 1.0)
        
        self.bull_config = self.config.get("bull_market", {})
        # Bear 설정 (기본값 로드 후 파일 저장값으로 덮어씀)
        self.bear_config = self.config.get("bear_market", {
            "min_loss_to_buy": -3.0,
            "average_down_amount": 500000,
            "max_investment_per_stock": 3000000,
            "auto_mode": False
        })
        
        self.state_file = "trading_state.json"
        self.last_avg_down_msg = "없음"
        self._load_all_states()
        
        # 실시간 분석 데이터 저장소 (대시보드 공유용)
        self.current_market_vibe = "Neutral"
        self.current_market_data = {} 
        self.global_panic = False

    def _load_all_states(self):
        """파일에서 모든 상태(매매 이력, 수동 설정, 물타기 옵션) 로드"""
        self.trade_history = {}
        self.manual_thresholds = {}
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self.trade_history = data.get("trade_history", {})
                    self.manual_thresholds = data.get("manual_thresholds", {})
                    # 물타기 설정 덮어쓰기
                    if "bear_config" in data:
                        self.bear_config.update(data["bear_config"])
                    self.last_avg_down_msg = data.get("last_avg_down_msg", "없음")
            except:
                pass

    def _save_all_states(self):
        """현재 모든 상태를 파일에 저장"""
        try:
            data = {
                "trade_history": self.trade_history,
                "manual_thresholds": self.manual_thresholds,
                "bear_config": self.bear_config,
                "last_avg_down_msg": self.last_avg_down_msg
            }
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"상태 저장 실패: {e}")

    def save_manual_thresholds(self):
        """수동 설정값 저장 (상위 호환성 유지)"""
        self._save_all_states()

    def _save_state(self, stock_code):
        """특정 종목의 매매 시각 저장 및 전체 저장"""
        self.trade_history[stock_code] = time.time()
        self._save_all_states()

    def _get_timeout_input(self, prompt, timeout=50):
        """타임아웃이 있는 사용자 입력 (윈도우/리눅스 호환)"""
        # TUI 환경에서는 이 함수가 차단적일 수 있으므로 주의 필요
        # 현재는 main.py의 interaction이 우선시됨
        return 'n'

    def get_dynamic_thresholds(self, stock_code, market_trend):
        """종목별 가변 익절/손절선 계산 (대시보드 표시용)"""
        # 0. 수동 설정값이 있으면 우선 반환
        if stock_code in self.manual_thresholds:
            vals = self.manual_thresholds[stock_code]
            return float(vals[0]), float(vals[1]), True 
            
        # 1. 시장 상황에 따른 TP 보정
        current_tp = self.base_tp
        if market_trend == "bull":
            # [팀장 지시] 일괄 3% 지정 대신 기존 값에 +3%를 더하는 상대적 보정 적용
            # "상승장(Bull): 익절 기준을 +3% 상향하여 수익 극대화" (MD의 '낮추어'는 '상향하여'로 재해석)
            current_tp += 3.0
            
        current_sl = self.base_sl
        
        # 2. 거래량 폭발에 따른 보정
        price_data = self.api.get_inquire_price(stock_code)
        is_vol_spike = False
        if price_data and 'vol' in price_data and 'prev_vol' in price_data:
            vol_ratio = (price_data['vol'] / price_data['prev_vol']) if price_data['prev_vol'] > 0 else 1.0
            if vol_ratio >= 1.5:
                current_tp += 3.0
                current_sl = self.base_sl / 2.0
                is_vol_spike = True
        
        return current_tp, current_sl, is_vol_spike

    def determine_market_trend(self):
        """국내외 지수를 종합하여 시장 트렌드 판별"""
        self.current_market_data = {
            "KOSPI": self.api.get_index_price("0001"),
            "KOSDAQ": self.api.get_index_price("1001"),
            "NASDAQ": self.api.get_index_price("NAS"),
            "S&P500": self.api.get_index_price("SPX"),
            "NAS_FUT": self.api.get_index_price("NAS_FUT"),
            "SPX_FUT": self.api.get_index_price("SPX_FUT")
        }
        
        active_indices = {k: v for k, v in self.current_market_data.items() if v is not None}
        if not active_indices:
            self.current_market_vibe = "Neutral (No Data)"
            return "neutral"

        avg_rate = sum(v['rate'] for v in active_indices.values()) / len(active_indices)
        
        # 글로벌 패닉 체크 (본장 및 선물 지수 모두 감시)
        us_indices = [
            self.current_market_data.get("NASDAQ"), 
            self.current_market_data.get("S&P500"),
            self.current_market_data.get("NAS_FUT"),
            self.current_market_data.get("SPX_FUT")
        ]
        # 유효한(None이 아닌) 지수 중 하나라도 -1.5% 이하로 급락하면 패닉으로 간주 (또는 본장 기준)
        active_us = [idx for idx in us_indices if idx is not None]
        self.global_panic = any(idx['rate'] <= -1.5 for idx in active_us) if active_us else False

        if self.global_panic:
            self.current_market_vibe = "Bear (GLOBAL PANIC)"
            return "bear"
        elif avg_rate >= 0.5:
            self.current_market_vibe = "Bull"
            return "bull"
        elif avg_rate <= -0.5:
            self.current_market_vibe = "Bear"
            return "bear"
        else:
            self.current_market_vibe = "Neutral"
            return "neutral"

    def evaluate_holdings(self, market_trend="neutral", skip_trade=False):
        """보유 종목 평가 및 가변 Exit Strategy 실행 (결과 리스트 반환)"""
        holdings = self.api.get_balance()
        if not holdings: return []
        results = []

        for item in holdings:
            stock_code = item.get("pdno")
            stock_name = item.get("prdt_name", stock_code)
            hldg_qty = int(item.get("hldg_qty", 0))
            if hldg_qty <= 0: continue

            evlu_pfls_rt = float(item.get("evlu_pfls_rt", 0.0))
            current_tp, current_sl, _ = self.get_dynamic_thresholds(stock_code, market_trend)

            action_label = ""
            sell_ratio = 1.0
            if evlu_pfls_rt >= current_tp:
                action_label = "익절"
                sell_ratio = self.tp_ratio
            elif evlu_pfls_rt <= current_sl:
                action_label = "손절"
                sell_ratio = self.sl_ratio

            if action_label:
                sell_qty = max(1, math.floor(hldg_qty * sell_ratio))
                msg_base = f"{stock_name} {action_label} 조건 달성 ({evlu_pfls_rt}% / 목표:{current_tp if action_label=='익절' else current_sl}%)"

                if skip_trade:
                    results.append(f"계측 알림(대기중): {msg_base}")
                    continue

                # 실제 매매 호출 전 1초 대기 (TPS 방어)
                time.sleep(1.0)
                success, api_msg = self.api.order_market(stock_code, sell_qty, is_buy=False)
                
                if success:
                    res_txt = f"자동 {action_label} 성공: {stock_name} {sell_qty}주 ({evlu_pfls_rt}%)"
                    results.append(res_txt)
                    self._save_state(stock_code)
                else:
                    results.append(f"자동 {action_label} 실패: {stock_name} ({api_msg})")
        return results

    def get_buy_recommendations(self, market_trend):
        """물타기(추가 매수) 추천 종목 탐색 (수동 실행용)"""
        if market_trend == "panic": return [] # 패닉일 땐 절대 금지
        
        holdings = self.api.get_balance()
        recommendations = []
        
        # 설정값 로드
        buy_trigger = self.bear_config.get("min_loss_to_buy", -3.0) # 예: -3.0%
        max_limit = self.bear_config.get("max_investment_per_stock", 3000000)
        
        for item in holdings:
            stock_code = item.get("pdno")
            stock_name = item.get("prdt_name", stock_code)
            evlu_pfls_rt = float(item.get("evlu_pfls_rt", 0.0))
            pchs_amt = int(float(item.get("pchs_amt", 0)))
            if pchs_amt == 0:
                pchs_amt = int(float(item.get("pchs_avg_pric", 0)) * float(item.get("hldg_qty", 0)))

            # 마지막 매매 후 10분 쿨다운 (잦은 물타기 방지)
            last_trade = self.trade_history.get(stock_code, 0)
            if time.time() - last_trade < 600: continue
            
            # 추천 조건: 수익률이 트리거 이하이고, 아직 최대 투자금액 미만일 때
            if evlu_pfls_rt <= buy_trigger and pchs_amt < max_limit:
                # 손절가(SL)보다는 위에 있어야 함 (손절 구역은 추천 안 함)
                _, current_sl, _ = self.get_dynamic_thresholds(stock_code, market_trend)
                if evlu_pfls_rt > current_sl:
                    recommendations.append({
                        "code": stock_code,
                        "name": stock_name,
                        "rt": evlu_pfls_rt,
                        "suggested_amt": self.bear_config.get("average_down_amount", 500000)
                    })
        return recommendations

    def evaluate_opportunities(self, market_trend="neutral"):
        """자동 물타기 기능을 알림 기반 수동으로 전환하기 위해 비워둠"""
        return []

    def run_cycle(self, market_trend="neutral", skip_trade=False):
        """1회 사이클 실행 및 자동 매매 결과 반환"""
        auto_results = self.evaluate_holdings(market_trend, skip_trade)
        # opportunities_results = self.evaluate_opportunities(market_trend)
        return auto_results
