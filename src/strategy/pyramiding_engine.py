from typing import Dict, Optional

class PyramidingEngine:
    """보유 종목의 상승 추종 매수(불타기, Pyramiding)를 담당하는 엔진입니다.

    상승장(BULL) 또는 개별 종목의 거래량 폭발 시, 수익이 발생 중인 종목에 
    추가로 진입하여 수익을 극대화합니다. 실시간 익절선(TP)과의 충돌 방지 및 
    과도한 고점 추격 매수 제한 로직을 통해 안정성을 확보합니다.

    Attributes:
        config (dict): 불타기 설정 정보 (트리거 비율, 회당 매수 금액 등).
        last_buy_prices (dict): 종목별 직전 불타기 매입 가격 기록 (재진입 필터링용).
    """
    def __init__(self, config: dict):
        self.config = config
        self.last_buy_prices: Dict[str, float] = {}

    def get_recommendation(self, item: dict, vibe: str, is_panic: bool, vol_spike: bool, tp_threshold: float) -> Optional[dict]:
        """특정 종목에 대한 불타기(상승 추종 매수) 추천 여부를 판단합니다.

        판단 기준 (GEMINI.md 2.C):
            1. 환경: 글로벌 패닉 상태가 아니며, 시장 장세가 BULL이거나 거래량 폭발 상황일 것.
            2. 상태: 현재가가 매입 평단가보다 높은 수익 구간일 것.
            3. 트리거: 현재 수익률이 설정된 `min_profit_to_pyramid` 이상일 것.
            4. 충돌 방지: 불타기 트리거는 항상 실시간 익절선(TP)보다 최소 1.0% 낮게 자동 보정됩니다.
            5. 재진입 제한: 직전 불타기 매입가 대비 최소 +2.0% 이상 추가 상승 시에만 재진입을 허용합니다.

        Args:
            item (dict): 종목 정보 (현재가, 평단가, 수익률 등).
            vibe (str): 현재 시장 장세 ('BULL', 'BEAR' 등).
            is_panic (bool): 글로벌 패닉 발생 여부.
            vol_spike (bool): 당일 거래량 폭발 여부.
            tp_threshold (float): 해당 종목에 현재 적용 중인 실시간 익절선 (%).

        Returns:
            Optional[dict]: 불타기 추천 상세 정보 (종목코드, 추천금액 등). 추천 대상이 아니면 None.
        """
        if is_panic or vibe.lower() in ["bear", "defensive"]: return None
        code = item.get("pdno")
        curr_p, curr_avg = float(item.get("prpr", 0)), float(item.get("pchs_avg_pric", 0))
        curr_rt = float(item.get("evlu_pfls_rt", 0.0))
        
        trig = self.config.get("min_profit_to_pyramid", 3.0)
        # 익절과 겹치지 않도록 방어: 불타기 트리거는 현재 설정된 익절값(TP)보다 최소 1.0% 낮아야 함
        trig = min(trig, tp_threshold - 1.0)
        
        if curr_rt >= trig and (vibe.lower() == "bull" or vol_spike) and curr_p > curr_avg:
            last_p = self.last_buy_prices.get(code, curr_avg)
            # 직전 불타기 매입가 대비 확실한 상승 시에만 집행
            if curr_p > last_p * 1.02:
                amt = self.config.get("average_down_amount", 500000)
                return {"code": code, "name": item.get("prdt_name"), "suggested_amt": amt, "type": "불타기", "expected_avg_change": "수익 비중 확대"}
        return None

