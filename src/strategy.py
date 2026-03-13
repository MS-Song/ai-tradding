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
        self.bear_config = self.config.get("bear_market", {})
        
        self.state_file = ".trading_state.json"
        self.trade_history = self._load_state()
        
        # 실시간 분석 데이터 저장소 (대시보드 공유용)
        self.current_market_vibe = "Neutral"
        self.current_market_data = {} # 누락된 속성 추가
        self.global_panic = False

    def _load_state(self):
        """파일에서 매매 이력(쿨다운용) 로드"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _save_state(self, stock_code):
        """특정 종목의 매매 시각 저장"""
        self.trade_history[stock_code] = time.time()
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.trade_history, f)
        except Exception as e:
            logger.error(f"상태 저장 실패: {e}")

    def _get_timeout_input(self, prompt, timeout=50):
        """타임아웃이 있는 사용자 입력 (윈도우/리눅스 호환)"""
        print(f"\n{prompt} ({timeout}초 내에 'y' 입력 시 실행): ", end="", flush=True)
        
        if sys.platform == 'win32':
            start_time = time.time()
            while time.time() - start_time < timeout:
                if msvcrt.kbhit():
                    char = msvcrt.getche().decode('utf-8').lower()
                    if char == 'y':
                        print("\n   ✅ 승인되었습니다.")
                        return 'y'
                    if char in ['\r', '\n', 'n']: break
                time.sleep(0.1)
        else:
            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setcbreak(sys.stdin.fileno())
                if select.select([sys.stdin], [], [], timeout)[0]:
                    char = sys.stdin.read(1).lower()
                    if char == 'y':
                        print("\n   ✅ 승인되었습니다.")
                        return 'y'
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        
        print("\n   ⏳ 응답 시간이 초과되었거나 거부되었습니다.")
        return 'n'

    def get_dynamic_thresholds(self, stock_code, market_trend):
        """종목별 가변 익절/손절선 계산 (대시보드 표시용)"""
        # 1. 시장 상황에 따른 TP 보정
        current_tp = self.base_tp
        if market_trend == "bull":
            current_tp = self.bull_config.get("take_profit_threshold", 3.0)
            
        current_sl = self.base_sl
        
        # 2. 거래량 폭발에 따른 보정
        price_data = self.api.get_inquire_price(stock_code)
        is_vol_spike = False
        if price_data:
            vol_ratio = (price_data['vol'] / price_data['prev_vol']) if price_data['prev_vol'] > 0 else 1.0
            if vol_ratio >= 1.5:
                current_tp += 3.0
                current_sl = self.base_sl / 2.0
                is_vol_spike = True
        
        return current_tp, current_sl, is_vol_spike

    def determine_market_trend(self):
        """국내외 지수를 종합하여 시장 트렌드 판별"""
        self.current_market_data = { # 결과를 인스턴스 변수에 저장
            "KOSPI": self.api.get_index_price("0001"),
            "KOSDAQ": self.api.get_index_price("1001"),
            "NASDAQ": self.api.get_index_price("NAS"),
            "S&P500": self.api.get_index_price("SNX")
        }
        
        active_indices = {k: v for k, v in self.current_market_data.items() if v is not None}
        if not active_indices:
            self.current_market_vibe = "Neutral (No Data)"
            return "neutral"

        avg_rate = sum(v['rate'] for v in active_indices.values()) / len(active_indices)
        
        # 글로벌 패닉 체크
        us_indices = [self.current_market_data["NASDAQ"], self.current_market_data["S&P500"]]
        self.global_panic = all(idx and idx['rate'] <= -1.5 for idx in us_indices)

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

    def evaluate_holdings(self, market_trend="neutral"):
        """보유 종목 평가 및 가변 Exit Strategy 실행"""
        holdings = self.api.get_balance()
        if not holdings: return

        for item in holdings:
            stock_code = item.get("pdno")
            stock_name = item.get("prdt_name", stock_code)
            hldg_qty = int(item.get("hldg_qty", 0))
            if hldg_qty <= 0: continue

            evlu_pfls_rt = float(item.get("evlu_pfls_rt", 0.0))
            current_tp, current_sl, _ = self.get_dynamic_thresholds(stock_code, market_trend)

            if evlu_pfls_rt >= current_tp:
                sell_qty = max(1, math.floor(hldg_qty * self.tp_ratio))
                logger.info(f"  💰 [익절] {stock_name} {sell_qty}주 매도 실행.")
                self.api.order_market(stock_code, sell_qty, is_buy=False)
            elif evlu_pfls_rt <= current_sl:
                sell_qty = max(1, math.floor(hldg_qty * self.sl_ratio))
                logger.info(f"  🛡️ [손절] {stock_name} {sell_qty}주 전량 매도 실행.")
                self.api.order_market(stock_code, sell_qty, is_buy=False)

    def evaluate_opportunities(self, market_trend="neutral"):
        """하락장 대응: 물타기 실행"""
        if market_trend != "bear": return

        holdings = self.api.get_balance()
        if not holdings: return

        invest_amount = self.bear_config.get("average_down_amount", 500000)
        min_loss = self.bear_config.get("min_loss_to_buy", -3.0)
        max_limit = self.bear_config.get("max_investment_per_stock", 3000000)
        cooldown_sec = 600

        for item in holdings:
            stock_code = item.get("pdno")
            stock_name = item.get("prdt_name", stock_code)
            evlu_pfls_rt = float(item.get("evlu_pfls_rt", 0.0))
            pchs_amt = int(float(item.get("pchs_amt", 0)))
            if pchs_amt == 0: pchs_amt = int(float(item.get("pchs_avg_pric", 0)) * float(item.get("hldg_qty", 0)))

            last_trade = self.trade_history.get(stock_code, 0)
            if time.time() - last_trade < cooldown_sec: continue
            if evlu_pfls_rt > min_loss: continue
            if pchs_amt >= max_limit: continue

            prompt = f"  ❓ [{stock_name}] 수익률 {evlu_pfls_rt}%! {invest_amount:,}원 추가 매수할까요?"
            if self._get_timeout_input(prompt, timeout=50) == 'y':
                price_data = self.api.get_inquire_price(stock_code)
                if price_data:
                    buy_qty = math.floor(invest_amount / price_data['price'])
                    if buy_qty > 0:
                        if self.api.order_market(stock_code, buy_qty, is_buy=True):
                            self._save_state(stock_code)

    def run_cycle(self, market_trend="neutral"):
        """1회 사이클 실행"""
        self.evaluate_holdings(market_trend)
        self.evaluate_opportunities(market_trend)
