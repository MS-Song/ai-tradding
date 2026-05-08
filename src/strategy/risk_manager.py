import math
from typing import Tuple
from src.logger import logger, log_error

class RiskManager:
    """계좌 리스크 관리 및 포지션 사이징을 담당하는 엔진.
    
    일일 손실 한도에 따른 서킷 브레이커 작동, 장세별 최소 현금 비중 유지, 
    그리고 ATR(Average True Range) 기반의 지능형 포지션 사이징을 통해 
    포트폴리오의 리스크를 균등화하고 자산을 보호합니다.

    Attributes:
        api: 시세 및 지표 수집용 API 인스턴스.
        config (dict): 리스크 설정 정보 (손실 한도, 리스크 비율 등).
        max_daily_loss_rate (float): 일일 최대 허용 손실률 (%).
        risk_per_trade_rate (float): 1회 매매 시 감수할 계좌 리스크 비율 (%).
        atr_multiplier (float): 포지션 사이징 시 사용할 ATR 배수.
        is_halted (bool): 현재 서킷 브레이커에 의한 매매 중단 여부.
    """
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
        """리스크 관리 설정을 최신화합니다."""
        self.config.update(config)
        self.max_daily_loss_rate = self.config.get("max_daily_loss_rate", 3.0)
        self.risk_per_trade_rate = self.config.get("risk_per_trade_rate", 0.5)
        self.atr_multiplier = self.config.get("atr_multiplier", 2.0)

    def check_circuit_breaker(self, asset_info: dict) -> bool:
        """일일 수익률을 체크하여 서킷 브레이커 작동 여부를 판단합니다.

        [Logic]
        - 일일 손실률이 `max_daily_loss_rate`에 도달하면 모든 신규 매매를 차단합니다.
        - 손실이 일정 수준 이상 복구되면 자동으로 차단을 해제합니다.

        Args:
            asset_info (dict): 현재 자산 및 수익률 정보.

        Returns:
            bool: 매매 중단(Halt) 상태 여부.
        """
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

    def check_cash_safety(self, asset_info: dict, vibe: str) -> Tuple[bool, str]:
        """현재 시장 장세에 따른 최소 현금 보유 비율을 체크합니다.

        [Rules] (GEMINI.md 2.A)
        - DEFENSIVE: 현금 비중 80% 이상 유지 필요.
        - BEAR: 현금 비중 30% 이상 유지 필요.

        Args:
            asset_info (dict): 현재 자산 정보.
            vibe (str): 현재 시장 VIBE.

        Returns:
            Tuple[bool, str]: (현금 부족 여부, 부족 사유 메시지).
        """
        total = float(asset_info.get("total_asset", 0))
        cash = float(asset_info.get("cash", 0))
        if total <= 0: return False, ""
        
        ratio = (cash / total) * 100
        v = vibe.upper()
        
        # 하락장/방어모드에서 신규 매수를 위한 최소 현금 비중 체크
        if v == "DEFENSIVE" and ratio < 80:
            return True, f"방어모드 현금 확보 필요 ({ratio:.1f}% < 80%)"
        if v == "BEAR" and ratio < 30:
            return True, f"하락장 현금 비중 낮음 ({ratio:.1f}% < 30%)"
            
        return False, ""

    def calculate_position_size(self, code: str, total_asset: float, current_price: float, default_amt: int = 500000) -> int:
        """ATR 기반의 지능형 포지션 사이징을 통해 매수 수량을 산출합니다.

        변동성이 큰 종목은 적게, 작은 종목은 많이 매수하여 종목별 리스크를 균등화합니다.
        수량 = (총자산 * 리스크비율) / (ATR * ATR배수)

        Args:
            code (str): 종목 코드.
            total_asset (float): 현재 총 자산.
            current_price (float): 현재가.
            default_amt (int): ATR 수집 실패 시 사용할 기본 매수 금액 (원).

        Returns:
            int: 최종 산출된 매수 수량 (주).
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
