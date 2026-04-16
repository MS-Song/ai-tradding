from typing import Dict, Optional

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
