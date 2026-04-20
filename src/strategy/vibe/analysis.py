import time
import re
import json
from datetime import datetime
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from src.logger import logger, log_error, trading_log

class AnalysisMixin:
    def perform_full_market_analysis(self, retry=True) -> bool:
        self.current_action = "시장분석"
        try:
            self.analyzer.update()
            self.apply_ai_strategy_to_all(None)
            self.last_market_analysis_time = time.time()
            self.is_ready = True
            logger.info("시장 분석 완료 및 전략 적용 성공")
            self.current_action = "대기중"
            return True
        except Exception as e:
            log_error(f"시장 분석 실패 (진입 차단 해제): {e}")
            self.is_ready = True 
            self.current_action = "대기중"
            return False

    def update_ai_recommendations(self, themes: List[dict], hot_raw: List[dict], vol_raw: List[dict], progress_cb: Optional[Callable] = None, on_item_found: Optional[Callable] = None):
        try: 
            if on_item_found: self.ai_recommendations = []
            self.ai_recommendations = self.alpha_eng.analyze(themes, hot_raw, vol_raw, self.ai_config.get("min_score", 60.0), progress_cb=progress_cb, kr_vibe=self.current_market_vibe, market_data=self.current_market_data, on_item_found=on_item_found)
            self._save_all_states()
        except Exception as e: log_error(f"AI 추천 업데이트 오류: {e}")

    def get_ai_advice(self, progress_cb: Optional[Callable] = None):
        holdings = self.api.get_balance()
        base_sl = self.exit_mgr.base_sl
        if self.analyzer.kr_vibe.upper() == "DEFENSIVE": base_sl = -3.0
        current_cfg = {"base_tp": self.exit_mgr.base_tp, "base_sl": base_sl, "bear_trig": max(self.recovery_eng.config.get("min_loss_to_buy"), base_sl + 1.0), "bull_trig": self.bull_config.get("min_profit_to_pyramid", 3.0), "ai_amt": self.ai_config["amount_per_trade"]}
        
        candidate_indicators = {}
        for r in self.ai_recommendations[:5]:
            try:
                candles = self.api.get_minute_chart_price(r['code'])
                if candles: candidate_indicators[r['code']] = self.indicator_eng.get_all_indicators(candles)
            except: pass

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_briefing = executor.submit(self.ai_advisor.get_advice, self.analyzer.current_data, self.analyzer.kr_vibe, holdings, current_cfg, self.ai_recommendations, indicators=candidate_indicators)
            future_detailed = executor.submit(self.ai_advisor.get_detailed_report_advice, self.ai_recommendations, self.analyzer.kr_vibe, progress_cb=progress_cb)
            future_holdings = executor.submit(self.ai_advisor.get_holdings_report_advice, holdings, self.analyzer.kr_vibe, self.analyzer.current_data, progress_cb=progress_cb) if holdings else None
            
            self.ai_briefing = future_briefing.result()
            self.ai_detailed_opinion = future_detailed.result()
            if future_holdings: self.ai_holdings_opinion = future_holdings.result()
        return self.ai_briefing

    def parse_and_apply_ai_strategy(self) -> bool:
        if not self.ai_briefing: return False
        try:
            strat_line = next((line for line in self.ai_briefing.split('\n') if "AI[전략]:" in line), "")
            if not strat_line: return False

            tp, sl = re.search(r"익절\s*([+-]?[\d,.]+)", strat_line), re.search(r"손절\s*([+-]?[\d,.]+)", strat_line)
            trig_bear = re.search(r"물타기\s*([+-]?[\d,.]+)", strat_line)
            trig_bull = re.search(r"불타기\s*([+-]?[\d,.]+)", strat_line) or re.search(r"추매\s*([+-]?[\d,.]+)", strat_line)
            amt = re.search(r"금액\s*([\d,]+)\s*원", strat_line)

            if not (tp and sl and trig_bear and trig_bull): return False
            
            raw_tp = abs(float(tp.group(1).replace(',', '')))
            raw_sl = -abs(float(sl.group(1).replace(',', '')))
            raw_trig_bear = -abs(float(trig_bear.group(1).replace(',', '')))
            raw_trig_bull = abs(float(trig_bull.group(1).replace(',', '')))
            
            target_tp = max(2.5, raw_tp) 
            target_sl = min(-2.5, raw_sl)

            target_trig_bear = raw_trig_bear
            if target_trig_bear <= target_sl:
                target_trig_bear = target_sl + 1.0
            target_trig_bear = min(-1.0, target_trig_bear)

            target_trig_bull = raw_trig_bull
            if target_trig_bull >= target_tp:
                target_trig_bull = target_tp - 1.0
            target_trig_bull = max(1.0, target_trig_bull)

            if amt:
                new_amt = int(amt.group(1).replace(',', ''))
                if new_amt < 1000: new_amt *= 10000
            else:
                new_amt = self.recovery_eng.config.get("average_down_amount", 500000)
                log_error(f"AI 금액 파싱 실패, 기존값 {new_amt:,}원 유지")

            tp_mod, sl_mod = self.exit_mgr.get_vibe_modifiers(self.analyzer.kr_vibe)
            calculated_base_tp = target_tp - tp_mod
            calculated_base_sl = target_sl - sl_mod
            
            self.exit_mgr.base_tp = max(2.0, calculated_base_tp)
            self.exit_mgr.base_sl = min(-2.0, calculated_base_sl)
            
            self.recovery_eng.config.update({"min_loss_to_buy": target_trig_bear, "average_down_amount": new_amt, "max_investment_per_stock": int(new_amt * 5)})
            self.bull_config.update({"min_profit_to_pyramid": target_trig_bull, "average_down_amount": new_amt, "max_investment_per_stock": int(new_amt * 5)})
            
            trading_log.log_config(f"AI 전략 자동 반영: TP +{target_tp}%, SL {target_sl}%, 물타기 {target_trig_bear}%, 불타기 +{target_trig_bull}%, 금액 {new_amt:,}원")
            self._save_all_states()
            return True
        except Exception as e:
            log_error(f"AI 전략 파싱 에러: {e}")
            return False
