import math
from typing import Dict, Optional

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
        curr_avg = float(item.get("pchs_avg_pric", 0))
        curr_qty = float(item.get("hldg_qty", 0))
        curr_p = float(item.get("prpr", 0))
        buy_qty = math.floor(amt / curr_p)
        if buy_qty > 0:
            new_avg = ((curr_avg * curr_qty) + (buy_qty * curr_p)) / (curr_qty + buy_qty)
            return {"code": item.get("pdno"), "name": item.get("prdt_name"), "suggested_amt": amt, "type": "물타기",
                    "expected_avg_change": f"{int(new_avg - curr_avg):+,}({abs(((new_avg-curr_avg)/curr_avg*100) if curr_avg>0 else 0):.2f}%)"}
        return {}
