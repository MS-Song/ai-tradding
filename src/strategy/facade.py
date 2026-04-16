import math
import time
import re
from datetime import datetime, time as dtime
from typing import Dict, List, Tuple, Optional, Callable
from concurrent.futures import ThreadPoolExecutor

from src.logger import logger, log_error, trading_log
from src.strategy.market_analyzer import MarketAnalyzer
from src.strategy.exit_manager import ExitManager
from src.strategy.recovery_engine import RecoveryEngine
from src.strategy.pyramiding_engine import PyramidingEngine
from src.strategy.alpha_engine import VibeAlphaEngine
from src.strategy.advisor import GeminiAdvisor
from src.strategy.preset_engine import PresetStrategyEngine
from src.strategy.state_manager import StateManager
from src.strategy.constants import PRESET_STRATEGIES

class VibeStrategy:
    def __init__(self, api, config):
        self.api = api
        self.base_config = config.get("vibe_strategy", {})
        
        v_cfg = self.base_config
        self.analyzer = MarketAnalyzer(api)
        self.exit_mgr = ExitManager(v_cfg.get("take_profit_threshold", 5.0), v_cfg.get("stop_loss_threshold", -5.0))
        self.recovery_eng = RecoveryEngine(v_cfg.get("bear_market", {}))
        
        bull_defaults = {"min_profit_to_pyramid": 3.0, "average_down_amount": 500000, "max_investment_per_stock": 25000000, "auto_mode": False}
        self.bull_config = v_cfg.get("bull_market", {})
        for k, v in bull_defaults.items():
            if k not in self.bull_config:
                self.bull_config[k] = v
        self.pyramid_eng = PyramidingEngine(self.bull_config)
        self.alpha_eng = VibeAlphaEngine(api)
        self.ai_advisor = GeminiAdvisor(api)
        self.alpha_eng.ai_advisor = self.ai_advisor
        self.analyzer.ai_advisor = self.ai_advisor
        
        self.last_avg_down_msg = "없음"
        self.last_sell_times: Dict[str, float] = {}
        self.last_sl_times: Dict[str, float] = {}
        self.last_buy_times: Dict[str, float] = {}
        self.ai_recommendations: List[dict] = []
        self.ai_briefing, self.ai_detailed_opinion = "", ""
        self.ai_holdings_opinion = ""
        self.recommendation_history: Dict[str, List[dict]] = {}
        self.yesterday_recs: List[dict] = []
        self.yesterday_recs_processed: List[dict] = []
        self._last_closing_bet_date = None
        self.rejected_stocks: Dict[str, str] = {}
        
        self.ai_config = {
            "amount_per_trade": v_cfg.get("ai_config", {}).get("amount_per_trade", 500000),
            "min_score": v_cfg.get("ai_config", {}).get("min_score", 60.0),
            "max_investment_per_stock": v_cfg.get("ai_config", {}).get("max_investment_per_stock", 2000000),
            "auto_mode": v_cfg.get("ai_config", {}).get("auto_mode", False),
            "auto_apply": v_cfg.get("ai_config", {}).get("auto_apply", False),
            "preferred_model": v_cfg.get("ai_config", {}).get("preferred_model", "gemini-2.5-flash"),
            "fallback_sequence": v_cfg.get("ai_config", {}).get("fallback_sequence", [
                "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview",
                "gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview"
            ])
        }
        
        self.is_ready = not self.ai_config.get("auto_mode", False)
        self.is_analyzing = False
        self.last_market_analysis_time = 0.0
        self.analysis_interval = 20
        self.analysis_status_msg = "초기화 중..."
        self.current_action = "대기중"

        # Initialize engines that depend on VibeStrategy state
        self.state_mgr = StateManager(self, "trading_state.json")
        self.preset_eng = PresetStrategyEngine(self.ai_advisor, api, lambda: self.current_market_vibe, self._save_all_states)
        
        # Load state
        self._load_all_states()
        
        self.ai_config["preferred_model"] = v_cfg.get("ai_config", {}).get("preferred_model", "gemini-2.5-flash")
        
        # Update components with latest config
        self.ai_advisor = GeminiAdvisor(api, self.ai_config)
        self.alpha_eng.ai_advisor = self.ai_advisor
        self.analyzer.ai_advisor = self.ai_advisor
        self.preset_eng.ai_advisor = self.ai_advisor
        
        self.state_mgr.update_yesterday_recs()

    def _load_all_states(self): self.state_mgr.load_all_states()
    def _save_all_states(self): self.state_mgr.save_all_states()
    def refresh_yesterday_recs_performance(self, hot_raw, vol_raw): self.state_mgr.refresh_yesterday_recs_performance(hot_raw, vol_raw)

    def is_modified(self, section: str) -> bool:
        if section == "STRAT": return (self.exit_mgr.base_tp != self.base_config.get("take_profit_threshold") or self.exit_mgr.base_sl != self.base_config.get("stop_loss_threshold"))
        if section == "BEAR":
            bc, curr = self.base_config.get("bear_market", {}), self.recovery_eng.config
            return (curr.get("average_down_amount") != bc.get("average_down_amount") or curr.get("min_loss_to_buy") != bc.get("min_loss_to_buy") or curr.get("auto_mode") != bc.get("auto_mode"))
        if section == "BULL":
            bc, curr = self.base_config.get("bull_market", {}), self.bull_config
            return (curr.get("average_down_amount") != bc.get("average_down_amount") or curr.get("min_profit_to_pyramid") != bc.get("min_profit_to_pyramid") or curr.get("auto_mode") != bc.get("auto_mode"))
        if section == "ALGO":
            ac, curr = self.base_config.get("ai_config", {}), self.ai_config
            return (curr.get("amount_per_trade") != ac.get("amount_per_trade") or curr.get("auto_mode") != ac.get("auto_mode") or curr.get("min_score") != ac.get("min_score"))
        return False

    @property
    def preset_strategies(self): return self.preset_eng.preset_strategies
    @property
    def auto_ai_trade(self): return self.ai_config["auto_mode"]
    @auto_ai_trade.setter
    def auto_ai_trade(self, val): self.ai_config["auto_mode"] = val
    @property
    def current_market_vibe(self): return self.analyzer.kr_vibe
    @property
    def global_panic(self): return self.analyzer.is_panic
    @property
    def current_market_data(self): return self.analyzer.current_data
    @property
    def base_tp(self): return self.exit_mgr.base_tp
    @base_tp.setter
    def base_tp(self, val): self.exit_mgr.base_tp = float(val)
    @property
    def base_sl(self): return self.exit_mgr.base_sl
    @base_sl.setter
    def base_sl(self, val): self.exit_mgr.base_sl = float(val)

    @property
    def bear_config(self): return self.recovery_eng.config
    @property
    def manual_thresholds(self): return self.exit_mgr.manual_thresholds

    def set_manual_threshold(self, code, tp, sl):
        self.exit_mgr.manual_thresholds[code] = [float(tp), float(sl)]
        self._save_all_states()

    def reset_manual_threshold(self, code):
        if code in self.exit_mgr.manual_thresholds:
            del self.exit_mgr.manual_thresholds[code]
            self._save_all_states()

    def apply_ai_strategy_to_all(self, data_manager=None):
        portfolio = [h['pdno'] for h in data_manager.cached_holdings] if data_manager else [h['pdno'] for h in self.api.get_balance()]
        for code in portfolio: self.auto_assign_preset(code, "")

    def perform_full_market_analysis(self, retry=True) -> bool:
        self.current_action = "전략분석"
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

    def determine_market_trend(self): return self.analyzer.update()
    def save_manual_thresholds(self): self._save_all_states()

    def get_market_phase(self) -> dict:
        now = datetime.now().time()
        if dtime(9, 0) <= now < dtime(10, 0): return {"id": "P1", "name": "OFFENSIVE", "tp_delta": 2.0, "sl_delta": -1.0}
        elif dtime(14, 30) <= now < dtime(15, 10): return {"id": "P3", "name": "CONCLUSION", "tp_delta": 0.0, "sl_delta": 0.0}
        elif dtime(15, 10) <= now < dtime(15, 20): return {"id": "P4", "name": "PREPARATION", "tp_delta": 0.0, "sl_delta": 0.0}
        elif dtime(10, 0) <= now < dtime(14, 30): return {"id": "P2", "name": "CONVERGENCE", "tp_delta": -1.0, "sl_delta": -1.0}
        return {"id": "IDLE", "name": "IDLE", "tp_delta": 0.0, "sl_delta": 0.0}

    def get_dynamic_thresholds(self, code, vibe, p_data=None):
        phase_cfg = self.get_market_phase()
        if code in self.exit_mgr.manual_thresholds:
            vals = self.exit_mgr.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), False
        ps = self.preset_eng.preset_strategies.get(code)
        if ps and ps.get("preset_id") != "00":
            return ps["tp"], ps["sl"], False
        return self.exit_mgr.get_thresholds(code, vibe, p_data, phase_cfg)

    def get_preset_label(self, code: str) -> str:
        if code in self.exit_mgr.manual_thresholds: return "수동"
        ps = self.preset_eng.preset_strategies.get(code)
        return ps.get("name", "") if ps else ""

    def assign_preset(self, *args, **kwargs): return self.preset_eng.assign_preset(*args, **kwargs)
    def auto_assign_preset(self, code: str, name: str) -> Optional[dict]:
        self.current_action = "전략재수립"
        res = self.preset_eng.auto_assign_preset(code, name)
        self.current_action = "대기중"
        return res

    def confirm_buy_decision(self, code: str, name: str) -> Tuple[bool, str]:
        if code in self.rejected_stocks: return False, f"당일 매수 거절됨: {self.rejected_stocks[code]}"
        detail = self.api.get_naver_stock_detail(code)
        news = self.api.get_naver_stock_news(code)
        is_confirmed, reason = self.ai_advisor.final_buy_confirm(code, name, self.current_market_vibe, detail, news)
        if not is_confirmed:
            self.rejected_stocks[code] = reason
            self._save_all_states()
            trading_log.log_config(f"❌ AI 매수 거절: [{code}]{name} | 사유: {reason}")
            return False, reason
        return True, "승인됨"

    def record_buy(self, code, price):
        self.recovery_eng.last_avg_down_prices[code] = price
        self.pyramid_eng.last_buy_prices[code] = price
        self.last_buy_times[code] = time.time()
        self._save_all_states()

    def update_ai_recommendations(self, themes, hot_raw, vol_raw, progress_cb: Optional[Callable] = None, on_item_found: Optional[Callable] = None):
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
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_briefing = executor.submit(self.ai_advisor.get_advice, self.analyzer.current_data, self.analyzer.kr_vibe, holdings, current_cfg, self.ai_recommendations)
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
            target_tp, target_sl = abs(float(tp.group(1).replace(',', ''))), -abs(float(sl.group(1).replace(',', '')))
            target_trig_bear, target_trig_bull = -abs(float(trig_bear.group(1).replace(',', ''))), abs(float(trig_bull.group(1).replace(',', '')))

            if amt:
                new_amt = int(amt.group(1).replace(',', ''))
                if new_amt < 1000: new_amt *= 10000
            else:
                new_amt = self.recovery_eng.config.get("average_down_amount", 500000)
                log_error(f"AI 금액 파싱 실패, 기존값 {new_amt:,}원 유지")

            tp_mod, sl_mod = self.exit_mgr.get_vibe_modifiers(self.analyzer.kr_vibe)
            self.exit_mgr.base_tp = target_tp - tp_mod
            self.exit_mgr.base_sl = target_sl - sl_mod
            
            self.recovery_eng.config.update({"min_loss_to_buy": target_trig_bear, "average_down_amount": new_amt, "max_investment_per_stock": int(new_amt * 5)})
            self.bull_config.update({"min_profit_to_pyramid": target_trig_bull, "average_down_amount": new_amt, "max_investment_per_stock": int(new_amt * 5)})
            
            trading_log.log_config(f"AI 전략 자동 반영: TP +{target_tp}%, SL {target_sl}%, 물타기 {target_trig_bear}%, 불타기 +{target_trig_bull}%, 금액 {new_amt:,}원")
            self._save_all_states()
            return True
        except Exception as e:
            log_error(f"AI 전략 파싱 에러: {e}")
            return False

    def get_buy_recommendations(self, market_trend):
        recs = []
        for h in self.api.get_balance():
            tp, sl, _ = self.get_dynamic_thresholds(h.get('pdno'), self.analyzer.kr_vibe)
            r = self.recovery_eng.get_recommendation(h, self.analyzer.is_panic, sl) or self.pyramid_eng.get_recommendation(h, self.analyzer.kr_vibe, self.analyzer.is_panic, False, tp)
            if r: recs.append(r)
        return recs

    def _is_in_partial_sell_cooldown(self, code: str, curr_t: float) -> bool: return self.last_buy_times.get(code, 0) <= self.last_sell_times.get(code, 0) and (curr_t - self.last_sell_times.get(code, 0)) < 3600
    def _is_emergency_exit(self, rt: float, tp: float, vol_spike: bool, phase: dict, after_buy: bool = False) -> Tuple[bool, str]:
        if rt >= tp + (2.0 if after_buy else 3.0): return True, f"급등초과+{rt - tp:.1f}%"
        if vol_spike and rt >= tp + (1.0 if after_buy else 1.5): return True, "거래량폭발"
        if phase['id'] == 'P4' and rt >= 0.5: return True, "장마감"
        return False, ""
    def _is_emergency_sl(self, rt: float, sl: float, is_panic: bool, vibe: str, phase: dict, after_avg_down: bool = False) -> Tuple[bool, str]:
        if rt <= sl - (1.0 if after_avg_down else 2.0): return True, f"추가급락{rt - sl:.1f}%"
        if is_panic: return True, "글로벌패닉"
        if vibe.upper() == "DEFENSIVE": return True, "방어모드전환"
        if phase['id'] == 'P4' and rt < 0: return True, "장마감청산"
        return False, ""

    def run_cycle(self, market_trend="neutral", skip_trade=False):
        holdings = self.api.get_balance()
        results, curr_t = [], time.time()
        phase = self.get_market_phase()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today = datetime.now().strftime('%Y-%m-%d')

        if phase['id'] == "P4" and not self.global_panic and self.current_market_vibe.upper() in ["BULL", "NEUTRAL"] and self.auto_ai_trade:
            if getattr(self, "_last_closing_bet_date", None) != today and self.ai_recommendations:
                top_rec = self.ai_recommendations[0]
                code, name = top_rec['code'], top_rec['name']
                if any(h.get('pdno') == code for h in holdings):
                    logger.info(f"P4 종가 베팅 건너뜀 (이미 보유 중): {name} ({code})")
                    self._last_closing_bet_date = today
                else:
                    qty = math.floor(self.ai_config["amount_per_trade"] / float(top_rec.get('price', 0))) if float(top_rec.get('price', 0)) > 0 else 0
                    if qty > 0 and not skip_trade:
                        success, _ = self.api.order_market(code, qty, True)
                        if success:
                            self._last_closing_bet_date = today
                            results.append(f"P4 종가 베팅 매수: {name} ({code}) {qty}주")
                            trading_log.log_trade("P4종가매수", code, name, float(top_rec.get('price', 0)), qty, "AI 추천 기반 종가 베팅")
                            self.auto_assign_preset(code, name)
                            self._save_all_states()

        for item in holdings:
            code = item.get("pdno")
            p_strat = self.preset_eng.preset_strategies.get(code)
            
            if p_strat:
                if p_strat.get('deadline') and now_str > p_strat['deadline']:
                    logger.info(f"Time-Stop: {item.get('prdt_name')} 전략 만료, 재분석 실행")
                    if not self.auto_assign_preset(code, item.get('prdt_name')):
                        curr_rt = float(item.get("evlu_pfls_rt", 0.0))
                        if curr_rt >= 0.5:
                            p_strat['tp'] = max(0.5, curr_rt / 2.0)
                            results.append(f"Time-Stop TP 하향(Fallback): {item.get('prdt_name')} ({p_strat['tp']:.1f}%)")
                        p_strat['deadline'] = None 
                    else:
                        results.append(f"🔄 전략 자동 갱신: {item.get('prdt_name')}")
                    self._save_all_states()

                if phase['id'] == "P3" and not p_strat.get('is_p3_processed') and float(item.get("evlu_pfls_rt", 0.0)) >= 0.5:
                    sell_qty = int(float(item.get('hldg_qty', 0))) // 2
                    if sell_qty > 0 and not skip_trade:
                        if self.api.order_market(code, sell_qty, False)[0]:
                            p_strat['is_p3_processed'], p_strat['sl'] = True, 0.2
                            results.append(f"🏁 P3 수익확정(50%): {item.get('prdt_name')}")
                            trading_log.log_trade("P3수익확정(50%)", code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, "Phase3 장마감 대비 분할매도")
                            self._save_all_states()
                    elif skip_trade: p_strat['is_p3_processed'] = True
            else:
                if not hasattr(self, '_p3_global_processed'): self._p3_global_processed = {}
                p3_key = f"{today}_{code}"
                if phase['id'] == "P3" and p3_key not in self._p3_global_processed and float(item.get("evlu_pfls_rt", 0.0)) >= 0.5:
                    sell_qty = int(float(item.get('hldg_qty', 0))) // 2
                    if sell_qty > 0 and not skip_trade:
                        if self.api.order_market(code, sell_qty, False)[0]:
                            self._p3_global_processed[p3_key] = True
                            tp_cur, sl_cur, _ = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
                            self.exit_mgr.manual_thresholds[code] = [tp_cur, 0.2]
                            results.append(f"🏁 P3 수익확정(50%): {item.get('prdt_name')} | SL→본전(+0.2%)")
                            trading_log.log_trade("P3수익확정(50%)", code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, "Phase3 표준종목 분할매도")
                            self._save_all_states()
                    else: self._p3_global_processed[p3_key] = True
                elif phase['id'] == "P4" and float(item.get("evlu_pfls_rt", 0.0)) < 0 and f"p4_{today}_{code}" not in self._p3_global_processed:
                    sell_qty = int(float(item.get('hldg_qty', 0)))
                    if sell_qty > 0 and not skip_trade and self.api.order_market(code, sell_qty, False)[0]:
                        self._p3_global_processed[f"p4_{today}_{code}"] = True
                        results.append(f"💤 P4 장마감 손절: {item.get('prdt_name')}")
                        trading_log.log_trade("P4장마감손절", code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, "Phase4 비용절감 청산")
                        self._save_all_states()

            tp, sl, vol_spike = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
            rt = float(item.get("evlu_pfls_rt", 0.0))
            action, sell_qty, action_reason = None, 0, ""

            if rt >= tp:
                if not self._is_in_partial_sell_cooldown(code, curr_t): action, sell_qty = "익절", max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
                else:
                    is_emg, emg_reason = self._is_emergency_exit(rt, tp, vol_spike, phase, self.last_buy_times.get(code, 0) > self.last_sell_times.get(code, 0))
                    if is_emg: action, action_reason, sell_qty = "긴급익절", emg_reason, max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
                    else: results.append(f"⏸ 스킵(익절쿨다운): {item.get('prdt_name')}({code}) 수익률 {rt:+.1f}% / TP {tp:+.1f}%")
            elif rt <= sl:
                if (curr_t - self.last_buy_times.get(code, 0)) < 1800 and self.last_buy_times.get(code, 0) > self.last_sell_times.get(code, 0):
                    is_emg, emg_reason = self._is_emergency_sl(rt, sl, self.analyzer.is_panic, self.analyzer.kr_vibe, phase, True)
                    if is_emg: action, action_reason, sell_qty = "긴급손절", emg_reason, int(item.get('hldg_qty', 0))
                    else: results.append(f"⏸ 스킵(물타기유예): {item.get('prdt_name')}({code}) 수익률 {rt:+.1f}% / SL {sl:.1f}%")
                else: action, sell_qty = "손절", int(item.get('hldg_qty', 0))

            if action and not skip_trade and sell_qty > 0:
                self.current_action = f"{action}실행"
                if self.api.order_market(code, sell_qty, False)[0]:
                    if "익절" in action: self.last_sell_times[code] = curr_t
                    elif "손절" in action: self.last_sl_times[code] = curr_t
                    trading_log.log_trade(action, code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, action_reason or action, profit=(float(item.get('prpr', 0)) - float(item.get('pchs_avg_pric', 0))) * sell_qty)
                    self._save_all_states()
                    results.append(f"자동 {action}{f'({action_reason})' if action_reason else ''}: {item.get('prdt_name')} {sell_qty}주")
                self.current_action = "대기중"
        return results
