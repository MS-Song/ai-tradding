import math
from typing import Dict, Optional

class RecoveryEngine:
    """보유 종목의 하락 대응(물타기, Recovery)을 담당하는 엔진.
    
    손절선(SL) 도달 전 매수 평단가를 낮추어 탈출 또는 수익 전환 기회를 확보합니다.
    시장 장세(VIBE)와 글로벌 패닉 여부에 따라 물타기 집행 여부와 간격을 동적으로 조절합니다.

    Attributes:
        config (dict): 물타기 설정 정보 (트리거 비율, 회당 금액 등).
        last_avg_down_prices (dict): 종목별 직전 물타기 체결 가격 기록.
    """
    def __init__(self, config: dict):
        self.config = config
        self.last_avg_down_prices: Dict[str, float] = {}

    def get_recommendation(self, item: dict, is_panic: bool, current_sl: float, vibe: str = "Neutral") -> Optional[dict]:
        """특정 종목에 대한 물타기 추천 여부를 판단합니다.

        판단 기준:
        1. 글로벌 패닉 및 방어모드(DEFENSIVE) 상황이 아닐 것.
        2. 현재 수익률이 손절선(SL)보다는 높고, 물타기 트리거보다는 낮을 것.
        3. [안전] 물타기 트리거는 항상 실시간 손절선보다 최소 1.0%~2.5% 이상 높게 유지.
        4. 직전 물타기 가격 대비 최소 -2.0% 이상 추가 하락했을 것 (난사 방지).

        Args:
            item (dict): 종목 정보 (현재가, 평단가, 수익률 등).
            is_panic (bool): 글로벌 패닉 여부.
            current_sl (float): 해당 종목의 현재 실시간 손절선 (%).
            vibe (str): 현재 시장 VIBE.

        Returns:
            Optional[dict]: 물타기 추천 정보 (종목코드, 금액 등) 또는 추천하지 않을 경우 None.
        """
        if is_panic: return None
        v = vibe.upper()
        if v == "DEFENSIVE": return None # 방어모드에선 물타기 금지

        code = item.get("pdno")
        curr_price, curr_avg = float(item.get("prpr", 0)), float(item.get("pchs_avg_pric", 0))
        curr_rt = float(item.get("evlu_pfls_rt", 0.0))
        
        config_trig = self.config.get("min_loss_to_buy", -3.0)
        # [수정] 하락장에선 물타기 간격을 넓혀 보수적으로 대응
        min_safety_gap = 1.0
        if v == "BEAR": min_safety_gap = 2.5 
        
        final_trig = config_trig
        # 손절선과 물타기 트리거가 너무 가까우면 자동으로 보정 (Logic Link: GEMINI.md 2.B)
        if config_trig <= current_sl:
            final_trig = current_sl + min_safety_gap
        elif (config_trig - current_sl) < min_safety_gap:
            final_trig = current_sl + min_safety_gap
            
        if current_sl < curr_rt <= final_trig and curr_price < curr_avg:
            last_p = self.last_avg_down_prices.get(code, curr_avg)
            # 직전 물타기 가격 대비 추가 하락 시에만 집행
            if code not in self.last_avg_down_prices or ((curr_price - last_p) / last_p * 100) <= -2.0:
                return self._simulate(item, self.config.get("average_down_amount", 500000))
        return None

    def _simulate(self, item: dict, amt: int) -> dict:
        """물타기 집행 시의 기대 효과(예상 평단가 변화 등)를 시뮬레이션합니다.

        Args:
            item (dict): 현재 보유 종목 정보 (수량, 평단가 포함).
            amt (int): 추가로 투입할 매수 금액 (원).

        Returns:
            dict: 예상 평단가 변화액 및 퍼센트 정보를 포함한 결과 맵.
        """
        curr_avg = float(item.get("pchs_avg_pric", 0))
        curr_qty = float(item.get("hldg_qty", 0))
        curr_p = float(item.get("prpr", 0))
        buy_qty = math.floor(amt / curr_p)
        if buy_qty > 0:
            new_avg = ((curr_avg * curr_qty) + (buy_qty * curr_p)) / (curr_qty + buy_qty)
            diff = int(new_avg - curr_avg)
            diff_rt = abs(((new_avg - curr_avg) / curr_avg * 100) if curr_avg > 0 else 0)
            return {
                "code": item.get("pdno"),
                "name": item.get("prdt_name"),
                "suggested_amt": amt,
                "type": "물타기",
                "expected_avg_change": f"{diff:+,}원 ({diff_rt:.2f}%)"
            }
        return {}

