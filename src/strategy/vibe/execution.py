import time
import math
import re
from datetime import datetime
from typing import List, Tuple, Optional
from src.logger import logger, log_error, trading_log

class ExecutionMixin:
    def run_cycle(self, market_trend="neutral", skip_trade=False):
        self._cleanup_rejected_stocks()
        holdings = self.api.get_balance()
        results, curr_t = [], time.time()
        phase = self.get_market_phase()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today = datetime.now().strftime('%Y-%m-%d')
        if not hasattr(self, '_p3_global_processed'): self._p3_global_processed = {}
        self._p4_ai_done_this_cycle = False
        
        asset_info = self.api.get_full_balance()[1] if not skip_trade else {}
        if self.start_day_asset > 0 and asset_info.get('total_asset', 0) > 0:
            asset_info['daily_pnl_rate'] = (asset_info['total_asset'] / self.start_day_asset - 1) * 100
        
        if self.risk_mgr.check_circuit_breaker(asset_info):
            return [f"🛑 리스크 상한 도달: {self.risk_mgr.halt_reason} (매매 중단)"]

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
                            m_id = self.ai_advisor.last_used_advisor.model_id if hasattr(self.ai_advisor, 'last_used_advisor') and self.ai_advisor.last_used_advisor else ""
                            trading_log.log_trade("P4종가매수", code, name, float(top_rec.get('price', 0)), qty, "AI 추천 기반 종가 베팅", model_id=m_id)
                            self.record_buy(code, float(top_rec.get('price', 0)))
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
                        p_strat['deadline'] = None 
                    self._save_all_states()

                if phase['id'] == "P3" and not p_strat.get('is_p3_processed') and float(item.get("evlu_pfls_rt", 0.0)) >= 0.5:
                    sell_qty = int(float(item.get('hldg_qty', 0))) // 2
                    if sell_qty > 0 and not skip_trade:
                        if self.api.order_market(code, sell_qty, False)[0]:
                            p_strat['is_p3_processed'], p_strat['sl'] = True, 0.2
                            p3_profit = (float(item.get('prpr', 0)) - float(item.get('pchs_avg_pric', 0))) * sell_qty
                            results.append(f"🏁 P3 수익확정(50%): {item.get('prdt_name')} ({int(p3_profit):+,}원)")
                            m_id = self.last_buy_models.get(code, "")
                            trading_log.log_trade("P3수익확정(50%)", code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, "Phase3 장마감 대비 분할매도", profit=p3_profit, model_id="TL/SP")
                            self._save_all_states()
                    elif skip_trade: p_strat['is_p3_processed'] = True
            else:
                p3_key = f"{today}_{code}"
                if phase['id'] == "P3" and p3_key not in self._p3_global_processed and float(item.get("evlu_pfls_rt", 0.0)) >= 0.5:
                    sell_qty = int(float(item.get('hldg_qty', 0))) // 2
                    if sell_qty > 0 and not skip_trade:
                        if self.api.order_market(code, sell_qty, False)[0]:
                            self._p3_global_processed[p3_key] = True
                            tp_cur, sl_cur, _ = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
                            self.exit_mgr.manual_thresholds[code] = [tp_cur, 0.2]
                            p3_profit = (float(item.get('prpr', 0)) - float(item.get('pchs_avg_pric', 0))) * sell_qty
                            results.append(f"🏁 P3 수익확정(50%): {item.get('prdt_name')} ({int(p3_profit):+,}원) | SL→본전(+0.2%)")
                            m_id = self.last_buy_models.get(code, "")
                            trading_log.log_trade("P3수익확정(50%)", code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, "Phase3 표준종목 분할매도", profit=p3_profit, model_id="TL/SP")
                            self._save_all_states()
                elif phase['id'] == "P4" and float(item.get("evlu_pfls_rt", 0.0)) < 0 and f"p4_{today}_{code}" not in self._p3_global_processed:
                    if (time.time() - self.last_buy_times.get(code, 0)) < 3600:
                        self._p3_global_processed[f"p4_{today}_{code}"] = True
                        results.append(f"🛡️ 당일 매수 P4 보호: {item.get('prdt_name')}")
                    else:
                        sell_qty = int(float(item.get('hldg_qty', 0)))
                        if sell_qty > 0 and not skip_trade and self.api.order_market(code, sell_qty, False)[0]:
                            self._p3_global_processed[f"p4_{today}_{code}"] = True
                            p4_profit = (float(item.get('prpr', 0)) - float(item.get('pchs_avg_pric', 0))) * sell_qty
                            results.append(f"💤 P4 장마감 손절: {item.get('prdt_name')} ({int(p4_profit):+,}원)")
                            m_id = self.last_buy_models.get(code, "")
                            trading_log.log_trade("P4장마감손절", code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, "Phase4 비용절감 청산", profit=p4_profit, model_id="TL/SP")
                            self._save_all_states()

            if phase['id'] == 'P4' and not skip_trade and not self._p4_ai_done_this_cycle:
                p4_ai_key = f"p4_ai_{today}_{code}"
                if p4_ai_key not in self._p3_global_processed and (time.time() - self.last_buy_times.get(code, 0)) >= 3600:
                    sell_qty = int(float(item.get('hldg_qty', 0)))
                    rt = float(item.get("evlu_pfls_rt", 0.0))
                    if sell_qty > 0:
                        self._p4_ai_done_this_cycle = True
                        self.current_action = "P4 AI판단"
                        try:
                            detail = self.api.get_naver_stock_detail(code)
                            news = self.api.get_naver_stock_news(code)
                            should_sell, reason = self.ai_advisor.closing_sell_confirm(code, item.get('prdt_name'), self.current_market_vibe, rt, detail, news)
                            self._p3_global_processed[p4_ai_key] = True
                            if should_sell:
                                if self.api.order_market(code, sell_qty, False)[0]:
                                    p4_profit = (float(item.get('prpr', 0)) - float(item.get('pchs_avg_pric', 0))) * sell_qty
                                    results.append(f"🤖 P4 AI청산: {item.get('prdt_name')} ({int(p4_profit):+,}원)")
                                    m_id = self.last_buy_models.get(code, "")
                                    trading_log.log_trade("P4 AI청산", code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, "P4 AI 장마감 청산", profit=p4_profit, model_id=m_id)
                                    self.record_sell(code)
                                    trading_log.log_config(f"🤖 P4 AI 매도: [{code}]{item.get('prdt_name')} | {reason}")
                                    self._save_all_states()
                            else:
                                trading_log.log_config(f"🔒 P4 AI 유지: [{code}]{item.get('prdt_name')} | {reason}")
                        except Exception as e: log_error(f"P4 AI 매도 판단 오류: {e}")
                        finally: self.current_action = "대기중"

            tp, sl, vol_spike = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
            rt = float(item.get("evlu_pfls_rt", 0.0))
            action, sell_qty, action_reason = None, 0, ""

            if rt >= tp:
                if not self._is_in_partial_sell_cooldown(code, curr_t): action, sell_qty = "익절", max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
                else:
                    is_emg, emg_reason = self._is_emergency_exit(rt, tp, vol_spike, phase, self.last_buy_times.get(code, 0) > self.last_sell_times.get(code, 0))
                    if is_emg: action, action_reason, sell_qty = "긴급익절", emg_reason, max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
            elif rt <= sl:
                if (curr_t - self.last_buy_times.get(code, 0)) < 1800 and self.last_buy_times.get(code, 0) > self.last_sell_times.get(code, 0):
                    is_emg, emg_reason = self._is_emergency_sl(rt, sl, self.analyzer.is_panic, self.analyzer.kr_vibe, phase, True)
                    if is_emg: action, action_reason, sell_qty = "긴급손절", emg_reason, int(item.get('hldg_qty', 0))
                else: action, sell_qty = "손절", int(item.get('hldg_qty', 0))

            if action and not skip_trade and sell_qty > 0:
                self.current_action = f"{action}실행"
                if self.api.order_market(code, sell_qty, False)[0]:
                    self.record_sell(code)
                    m_id = self.last_buy_models.get(code, "")
                    trading_log.log_trade(action, code, item.get('prdt_name'), float(item.get('prpr', 0)), sell_qty, action_reason or action, profit=(float(item.get('prpr', 0)) - float(item.get('pchs_avg_pric', 0))) * sell_qty, model_id="TL/SP")
                    self._save_all_states()
                    results.append(f"자동 {action}{f'({action_reason})' if action_reason else ''}: {item.get('prdt_name')} {sell_qty}주")
                self.current_action = "대기중"
        return results

    def get_buy_recommendations(self, market_trend="neutral"):
        recs = []
        holdings = self.api.get_balance()
        for item in holdings:
            code = item.get("pdno")
            tp, sl, spike = self.get_dynamic_thresholds(code, market_trend)
            
            # 1. 물타기 체크
            rec_bear = self.recovery_eng.get_recommendation(item, self.global_panic, sl)
            if rec_bear:
                rec_bear['reason'] = f"손절선({sl}%) 근접 하락 대응"
                recs.append(rec_bear)
            
            # 2. 불타기 체크
            rec_bull = self.pyramid_eng.get_recommendation(item, market_trend, self.global_panic, spike, tp)
            if rec_bull:
                rec_bull['reason'] = f"익절선({tp}%) 추종 상승 매수"
                recs.append(rec_bull)
        return recs

    def confirm_buy_decision(self, code: str, name: str, score: float = 0.0) -> Tuple[bool, str]:
        self._cleanup_rejected_stocks()
        if code in self.rejected_stocks: return False, f"당일 매수 거절됨"
        detail = self.api.get_naver_stock_detail(code)
        try: price = float(detail.get('price', 0))
        except: price = 0.0
        if price == 0.0: return False, "실시간 데이터 오류: 시세 0원"
        news = self.api.get_naver_stock_news(code)
        indicators = {}
        try:
            candles = self.api.get_minute_chart_price(code)
            if candles: indicators = self.indicator_eng.get_all_indicators(candles)
        except: pass

        is_confirmed, reason = self.ai_advisor.final_buy_confirm(code, name, self.current_market_vibe, detail, news, indicators=indicators, score=score)
        m_id = self.ai_advisor.last_used_advisor.model_id if hasattr(self.ai_advisor, 'last_used_advisor') and self.ai_advisor.last_used_advisor else ""
        
        if not is_confirmed:
            if re.search(r"(?<![0-9])0원", reason) or "가격이 0원" in reason: return False, f"데이터 지연 보류: {reason}"
            self.rejected_stocks[code] = {"reason": reason, "time": time.time()}
            # [추가] 거절 로그 영속성 확보
            trading_log.log_rejection(code, name, reason, model_id=m_id)
            self._save_all_states()
            return False, reason
        
        if m_id: self.last_buy_models[code] = m_id
        return True, "승인됨"

    def get_replacement_target(self, candidate_code: str, candidate_name: str, score: float, holdings: List[dict]) -> Tuple[bool, Optional[str], str]:
        if not holdings: return False, None, "보유 종목 없음"
        c_detail = self.api.get_naver_stock_detail(candidate_code)
        c_news = self.api.get_naver_stock_news(candidate_code)
        candidate_info = {"code": candidate_code, "name": candidate_name, "score": score, "detail": str(c_detail), "news": c_news}
        holdings_info = []
        for h in holdings:
            detail = self.api.get_naver_stock_detail(h['pdno'])
            holdings_info.append({"code": h['pdno'], "name": h['prdt_name'], "rt": float(h.get('evlu_pfls_rt', 0)), "detail": str(detail)})
        return self.ai_advisor.compare_stock_superiority(candidate_info, holdings_info, self.current_market_vibe)
