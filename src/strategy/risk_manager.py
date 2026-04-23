import math
from src.logger import logger, log_error

class RiskManager:
    def __init__(self, api, config: dict = None):
        self.api = api
        self.config = config or {}
        # 설정값 (trading_state.json 또는 전역 설정에서 로드)
        self.max_daily_loss_rate = self.config.get("max_daily_loss_rate", 3.0) # 기본 3% 손실 시 차단
        self.risk_per_trade_rate = self.config.get("risk_per_trade_rate", 0.5) # 1회 매매 시 계좌의 0.5% 리스크 감수
        self.atr_multiplier = self.config.get("atr_multiplier", 2.0)          # 2.0 ATR를 손절 범위로 가정
        
        self.is_halted = False
        self.halt_reason = ""

    def update_config(self, config: dict):
        self.config.update(config)
        self.max_daily_loss_rate = self.config.get("max_daily_loss_rate", 3.0)
        self.risk_per_trade_rate = self.config.get("risk_per_trade_rate", 0.5)
        self.atr_multiplier = self.config.get("atr_multiplier", 2.0)

    def check_circuit_breaker(self, asset_info: dict) -> bool:
        """일일 수익률을 체크하여 서킷 브레이커 작동 여부를 판단합니다."""
        # API 조회 실패 등으로 데이터가 없을 경우 이전 상태 유지
        if "daily_pnl_rate" not in asset_info:
            return self.is_halted

        # DataManager에서 계산된 daily_pnl_rate 사용 (전일 대비 자산 변동)
        pnl_rate = float(asset_info.get("daily_pnl_rate", 0))
        
        if pnl_rate <= -self.max_daily_loss_rate:
            if not self.is_halted:
                logger.warning(f"⚠️ [RISK] 서킷 브레이커 발동: 일일 손실 {pnl_rate:.2f}% 도달 (한도 {self.max_daily_loss_rate}%)")
            self.is_halted = True
            self.halt_reason = f"일일 손실 과다 ({pnl_rate:.1f}%)"
            return True
        
        # 손실이 복구되면 차단 해제 (선택 사항 - 보통은 장 마감까지 유지)
        if self.is_halted and pnl_rate > -self.max_daily_loss_rate * 0.7:
             self.is_halted = False
             self.halt_reason = ""
             logger.info(f"✅ [RISK] 서킷 브레이커 해제: 현재 손실 {pnl_rate:.2f}%")
             
        return self.is_halted

    def calculate_position_size(self, code: str, total_asset: float, current_price: float, default_amt: int = 500000) -> int:
        """ ATR 기반의 지능형 포지션 사이징 (수량 산출)
        변동성이 큰 종목은 적게, 작은 종목은 많이 매수하여 리스크를 균등화함.
        """
        if total_asset <= 0 or current_price <= 0: return 0
        
        try:
            # 1. ATR 수집
            atr = self.api.calculate_atr(code)
            
            # ATR 수집 실패 시 (데이터 부족 등) 기본 금액 방식 폴백
            if atr <= 0:
                return math.floor(default_amt / current_price)
            
            # 2. 리스크 총액 = 총 자산 * 리스크 비율 (예: 1억 자산 * 0.5% = 50만원 리스크)
            # 이 50만원은 '손절 시 날려도 되는 최대 금액'을 의미
            risk_budget = total_asset * (self.risk_per_trade_rate / 100.0)
            
            # 3. 수량 = 리스크 총액 / (ATR * 배수)
            # 예: 삼성전자 ATR 1000원, 2.0배 수량 산출 시 2000원 하락 시나리오 대응
            # 수량 = 50만원 / 2000원 = 250주
            qty = math.floor(risk_budget / (atr * self.atr_multiplier))
            
            # 4. 물리적/금액적 제한 (Safety Filters)
            # - 최대 매수 가능 금액 제한 (총 자산의 25% 초과 금지 등)
            max_inv_amt = total_asset * 0.25
            inv_amt = qty * current_price
            if inv_amt > max_inv_amt:
                qty = math.floor(max_inv_amt / current_price)
            
            # - 최소 1주 보장 및 너무 적은 금액 매수 방지 (수량이 0이거나 너무 작으면 매수 안함)
            if qty <= 0: return 0
            
            return int(qty)
            
        except Exception as e:
            log_error(f"포지션 사이징 계산 중 오류 ({code}): {e}")
            return math.floor(default_amt / current_price)
