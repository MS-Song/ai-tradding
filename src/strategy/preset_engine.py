from datetime import datetime, timedelta
from typing import Dict, Optional
from src.strategy.constants import PRESET_STRATEGIES
from src.logger import log_error, trading_log

class PresetStrategyEngine:
    def __init__(self, ai_advisor, api=None, get_vibe_cb=None, state_save_cb=None):
        self.preset_strategies: Dict[str, dict] = {}
        self.ai_advisor = ai_advisor
        self.api = api
        self.get_vibe = get_vibe_cb
        self.save_state = state_save_cb
        
    def _calculate_deadline(self, preset_id, start_time_str, lifetime_mins):
        if not start_time_str or not lifetime_mins: return None
        try:
            l_mins = int(lifetime_mins)
            if preset_id in ["03", "08", "07"]:
                l_mins = min(l_mins, 180)
            elif preset_id in ["05", "09", "06"]:
                l_mins = min(l_mins, 240)
            
            if l_mins <= 0: return None
            
            start_dt = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
            deadline_dt = start_dt + timedelta(minutes=l_mins)
            return deadline_dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            log_error(f"Deadline 계산 실패: {e}")
            return None
            
    def assign_preset(self, code: str, preset_id: str, tp: float = None, sl: float = None, reason: str = "", lifetime_mins: int = None, name: str = ""):
        preset = PRESET_STRATEGIES.get(preset_id)
        if not preset: return False
            
        if not name and code in self.preset_strategies:
            name = self.preset_strategies[code].get('name', '')

        if preset_id == "00":
            if code in self.preset_strategies:
                del self.preset_strategies[code]
                trading_log.log_config(f"전략 해제: [{code}]{name} -> 표준 복귀")
        else:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            use_tp = tp if tp is not None else preset["default_tp"]
            use_sl = sl if sl is not None else preset["default_sl"]
            self.preset_strategies[code] = {
                "preset_id": preset_id,
                "name": preset["name"],
                "tp": use_tp,
                "sl": use_sl,
                "reason": reason or preset["desc"],
                "buy_time": now_str,
                "deadline": self._calculate_deadline(preset_id, now_str, lifetime_mins),
                "is_p3_processed": False
            }
            trading_log.log_config(f"전략 할당: [{code}]{name} -> {preset['name']} | TP:{use_tp}% SL:{use_sl}%")
            
        if self.save_state: self.save_state()
        return True

    def auto_assign_preset(self, code: str, name: str) -> Optional[dict]:
        try:
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            vibe = self.get_vibe() if self.get_vibe else "Neutral"
            result = self.ai_advisor.simulate_preset_strategy(code, name, vibe, detail, news)
            if result:
                self.assign_preset(code, result["preset_id"], result["tp"], result["sl"], result["reason"], result.get("lifetime_mins"), name=name)
                return result
        except Exception as e:
            log_error(f"자동 프리셋 할당 오류: {e}")
        return None
