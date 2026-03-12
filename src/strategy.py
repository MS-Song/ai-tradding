from src.logger import logger
import math

class VibeStrategy:
    def __init__(self, api, config):
        self.api = api
        self.config = config.get("vibe_strategy", {})
        
        # 기본 전략 세팅 로드
        self.base_tp = self.config.get("take_profit_threshold", 5.0)
        self.base_sl = self.config.get("stop_loss_threshold", -3.0)
        self.tp_ratio = self.config.get("take_profit_ratio", 0.3)
        self.sl_ratio = self.config.get("stop_loss_ratio", 1.0)
        
        self.bull_config = self.config.get("bull_market", {})
        self.bear_config = self.config.get("bear_market", {})

    def determine_market_trend(self):
        """KOSPI 지수를 기반으로 시장 트렌드(Bull/Bear/Neutral) 판별"""
        index_data = self.api.get_index_price("0001") # KOSPI
        if not index_data:
            logger.warning("지수 정보 조회 실패. 중립(Neutral) 트렌드로 진행합니다.")
            return "neutral"
            
        rate = index_data["rate"]
        price = index_data["price"]
        diff = index_data["diff"]
        
        logger.info(f"[Market Data] KOSPI: {price} ({diff:+}pt, {rate:+}%)")
        
        if rate >= 0.5:
            return "bull"
        elif rate <= -0.5:
            return "bear"
        else:
            return "neutral"

    def evaluate_holdings(self, market_trend="neutral"):
        """보유 종목 평가 및 Exit Strategy 실행"""
        logger.info(f"=== 포트폴리오 평가 시작 (현재 시장 상황: {market_trend.upper()}) ===")
        
        holdings = self.api.get_balance()
        if not holdings:
            logger.info("보유 종목이 없습니다.")
            return

        # 상승장이면 익절 기준을 하향 조정 (예: 5% -> 3%)
        current_tp_threshold = self.base_tp
        if market_trend == "bull":
            current_tp_threshold = self.bull_config.get("take_profit_threshold", 3.0)
            logger.info(f"[Bull Market] 방어적 포지션 적용: 익절 기준 {self.base_tp}% -> {current_tp_threshold}%")

        for item in holdings:
            stock_code = item.get("pdno")
            stock_name = item.get("prdt_name", stock_code)
            hldg_qty = int(item.get("hldg_qty", 0))
            if hldg_qty <= 0:
                continue

            # 수익률 파싱 (KIS API는 퍼센트를 문자열로 전달)
            evlu_pfls_rt = float(item.get("evlu_pfls_rt", 0.0))
            
            logger.info(f"[{stock_name}] 수익률: {evlu_pfls_rt}% | 보유수량: {hldg_qty}")

            # 1. 익절 (Take-Profit)
            if evlu_pfls_rt >= current_tp_threshold:
                sell_qty = max(1, math.floor(hldg_qty * self.tp_ratio))
                logger.info(f"[Vibe Trigger - Take Profit] {stock_name} 수익률 {evlu_pfls_rt}% 달성. {sell_qty}주(30%) 익절 매도 실행.")
                self.api.order_market(stock_code, sell_qty, is_buy=False)
            
            # 2. 손절 (Stop-Loss)
            elif evlu_pfls_rt <= self.base_sl:
                sell_qty = max(1, math.floor(hldg_qty * self.sl_ratio))
                logger.info(f"[Vibe Trigger - Stop Loss] {stock_name} 수익률 {evlu_pfls_rt}% 달성. {sell_qty}주(전량) 손절 매도 실행.")
                self.api.order_market(stock_code, sell_qty, is_buy=False)

    def evaluate_opportunities(self, market_trend="neutral"):
        """하락장(Bear Market) 시 추가 매입(물타기) 로직 실행"""
        if market_trend != "bear":
            return
            
        logger.info("=== 하락장(Bear Market) 기회 탐색 및 추가 매입 시작 ===")
        
        target_stocks = self.bear_config.get("target_stocks", [])
        invest_amount = self.bear_config.get("average_down_amount", 500000)
        
        for stock_code in target_stocks:
            # 현재가 조회
            current_price = self.api.get_inquire_price(stock_code)
            if not current_price:
                continue
                
            # 지정된 금액으로 살 수 있는 수량 계산
            buy_qty = math.floor(invest_amount / current_price)
            if buy_qty > 0:
                logger.info(f"[Vibe Trigger - Average Down] 하락장 방어. {stock_code} {buy_qty}주(약 {invest_amount}원) 시장가 추가 매수 실행.")
                self.api.order_market(stock_code, buy_qty, is_buy=True)
            else:
                logger.warning(f"[{stock_code}] 1주 가격({current_price}원)이 예산({invest_amount}원)을 초과하여 매수 불가.")

    def run_cycle(self, market_trend="neutral"):
        """1회 사이클 실행"""
        self.evaluate_holdings(market_trend)
        self.evaluate_opportunities(market_trend)
        logger.info("=== 사이클 종료 ===\n")
