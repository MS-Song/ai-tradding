import os
import json
from datetime import datetime
from src.logger import log_error

class StateManager:
    def __init__(self, strategy, state_file="trading_state.json"):
        self.strategy = strategy
        self.state_file = state_file

    def load_all_states(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    d = json.load(f)
                    s = self.strategy
                    
                    if "base_tp" in d: s.exit_mgr.base_tp = d["base_tp"]
                    if "base_sl" in d: s.exit_mgr.base_sl = d["base_sl"]
                    s.exit_mgr.manual_thresholds = d.get("manual_thresholds", {})
                    s.recovery_eng.last_avg_down_prices = d.get("last_avg_down_prices", {})
                    s.pyramid_eng.last_buy_prices = d.get("last_buy_prices", {})
                    s.last_sell_times = d.get("last_sell_times", {})
                    s.last_sl_times = d.get("last_sl_times", {})
                    s.last_buy_times = d.get("last_buy_times", {})
                    s.last_avg_down_msg = d.get("last_avg_down_msg", "없음")
                    s.recommendation_history = d.get("recommendation_history", {})
                    
                    s.preset_eng.preset_strategies = d.get("preset_strategies", {})
                    
                    today = datetime.now().strftime('%Y-%m-%d')
                    if d.get("last_rejected_date") == today:
                        s.rejected_stocks = d.get("rejected_stocks", {})
                    else:
                        s.rejected_stocks = {}

                    for code, ps in s.preset_eng.preset_strategies.items():
                        if 'buy_time' not in ps: ps['buy_time'] = None
                        if 'deadline' not in ps: ps['deadline'] = None
                        if 'is_p3_processed' not in ps: ps['is_p3_processed'] = False
                        
                    if "ai_config" in d: 
                        s.ai_config.update(d["ai_config"])
                        s.ai_config["auto_apply"] = s.base_config.get("ai_config", {}).get("auto_apply", False)
                        
                    if "bear_config" in d: s.recovery_eng.config.update(d["bear_config"])
                    if "bull_config" in d: s.bull_config.update(d["bull_config"])
                    s._last_closing_bet_date = d.get("last_closing_bet_date")
            except Exception as e:
                log_error(f"상태 파일 로드 실패: {e}")

    def save_all_states(self):
        try:
            s = self.strategy
            today = datetime.now().strftime('%Y-%m-%d')
            if s.ai_recommendations:
                s.recommendation_history[today] = [
                    {"code": r['code'], "name": r['name'], "price": float(r.get('price', 0)), "theme": r['theme'], "score": r['score']}
                    for r in s.ai_recommendations
                ]
                dates = sorted(s.recommendation_history.keys())
                if len(dates) > 7:
                    for d in dates[:-7]: del s.recommendation_history[d]

            data = {
                "base_tp": s.exit_mgr.base_tp,
                "base_sl": s.exit_mgr.base_sl,
                "manual_thresholds": s.exit_mgr.manual_thresholds,
                "last_avg_down_prices": s.recovery_eng.last_avg_down_prices,
                "last_buy_prices": s.pyramid_eng.last_buy_prices,
                "last_sell_times": s.last_sell_times,
                "last_sl_times": s.last_sl_times,
                "last_buy_times": s.last_buy_times,
                "last_avg_down_msg": s.last_avg_down_msg,
                "recommendation_history": s.recommendation_history,
                "ai_config": s.ai_config,
                "bear_config": s.recovery_eng.config,
                "bull_config": s.bull_config,
                "preset_strategies": s.preset_eng.preset_strategies,
                "last_closing_bet_date": getattr(s, "_last_closing_bet_date", None),
                "rejected_stocks": s.rejected_stocks,
                "last_rejected_date": today
            }
            with open(self.state_file, "w") as f: json.dump(data, f, indent=4)
        except Exception as e: log_error(f"상태 저장 실패: {e}")

    def update_yesterday_recs(self):
        today = datetime.now().strftime('%Y-%m-%d')
        dates = sorted([d for d in self.strategy.recommendation_history.keys() if d < today])
        if dates:
            self.strategy.yesterday_recs = self.strategy.recommendation_history[dates[-1]]
        else:
            self.strategy.yesterday_recs = []

    def refresh_yesterday_recs_performance(self, hot_raw, vol_raw):
        if not self.strategy.yesterday_recs: return
        processed = []
        for r in self.strategy.yesterday_recs:
            curr_item = next((item for item in (hot_raw + vol_raw) if item and item['code'] == r['code']), None)
            if not curr_item:
                p_data = self.strategy.api.get_naver_stock_detail(r['code'])
                curr_p = float(p_data.get('price', r['price']))
            else:
                curr_p = float(curr_item['price'])
            chg = ((curr_p - r['price']) / r['price'] * 100) if r['price'] > 0 else 0
            processed.append({**r, "curr_price": curr_p, "change": chg})
        self.strategy.yesterday_recs_processed = sorted(processed, key=lambda x: abs(x['change']), reverse=True)
