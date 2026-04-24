import time
import math
import re
from datetime import datetime
from typing import List, Tuple, Optional
from src.logger import logger, log_error, trading_log
from src.utils import is_ai_enabled_time
from src.strategy.constants import PRESET_STRATEGIES

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
                # 1~3순위까지 순회하며 종가 베팅 종목 탐색
                for top_rec in self.ai_recommendations[:3]:
                    code, name = top_rec['code'], top_rec['name']
                    if any(h.get('pdno') == code for h in holdings):
                        logger.info(f"P4 종가 베팅 기보유 종목 보호 갱신: {name} ({code})")
                        results.append(f"🛡️ P4 종가베팅 유지/보호: {name}")
                        self.last_buy_times[code] = time.time()  # 당일 매수 보호 로직 적용 (청산 방어)
                        self._last_closing_bet_date = today
                        self._save_all_states()
                        break  # 기보유 종목으로 베팅 확정하고 종료
                    else:
                        # [CRITICAL] 당일 등락률 하드 필터 (-1.5% ~ +8.0% 범위만 진입 허용)
                        _p4_rate = float(top_rec.get('rate', 0))
                        if _p4_rate > 8.0 or _p4_rate < -1.5:
                            logger.warning(f"P4 종가 베팅 등락률 초과: {name} ({_p4_rate:+.1f}%) -> 다음 순위 탐색")
                            continue
                        price = float(top_rec.get('price', 0))
                        qty = math.floor(self.ai_config["amount_per_trade"] / price) if price > 0 else 0
                        # 가용 현금이 주가 이상이라면 최소 1주 매수 보장
                        if qty == 0 and asset_info.get('cash', 0) >= price:
                            qty = 1
                            
                        if qty > 0 and not skip_trade:
                            success, msg = self.api.order_market(code, qty, True)
                            if success:
                                self._last_closing_bet_date = today
                                results.append(f"P4 종가 베팅 매수: {name} ({code}) {qty}주")
                                m_id = self.ai_advisor.last_used_advisor.model_id if hasattr(self.ai_advisor, 'last_used_advisor') and self.ai_advisor.last_used_advisor else ""
                                trading_log.log_trade("P4종가매수", code, name, price, qty, "AI 추천 기반 종가 베팅", model_id=m_id)
                                self.record_buy(code, price)
                                self.auto_assign_preset(code, name)
                                self._save_all_states()
                                break  # 매수 성공 시 종료
                            else:
                                logger.warning(f"P4 종가 베팅 실패 ({name}): {msg} -> 다음 순위 탐색")

        for item in holdings:
            code = item.get("pdno")
            p_strat = self.preset_eng.preset_strategies.get(code)
            
            if p_strat:
                if p_strat.get('deadline') and now_str > p_strat['deadline']:
                    logger.info(f"Time-Stop: {item.get('prdt_name')} 전략 만료, 재분석 실행")
                    # [추가] AI 실행 시간 체크 (디버그 제외) - 자동 재할당 차단
                    if is_ai_enabled_time() or getattr(self, "debug_mode", False):
                        if not self.auto_assign_preset(code, item.get('prdt_name')):
                            curr_rt = float(item.get("evlu_pfls_rt", 0.0))
                            if curr_rt >= 0.5:
                                p_strat['tp'] = max(0.5, curr_rt / 2.0)
                            p_strat['deadline'] = None 
                    else:
                        logger.info(f"Time-Stop 건너뜀 (Market closed): {item.get('prdt_name')}")
                        # 시간 만료되었으므로 데드라인 초기화하여 반복 로깅 방지
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
                            # [추가] AI 실행 가능 시간 체크 (디버그 모드 제외)
                            if not is_ai_enabled_time() and not getattr(self, "debug_mode", False):
                                self._p3_global_processed[p4_ai_key] = True
                                logger.info(f"P4 AI판단 건너뜀 (Market closed/AI Disabled): {item.get('prdt_name')}")
                                continue

                            detail = self.api.get_naver_stock_detail(code)
                            news = self.api.get_naver_stock_news(code)
                            p_strat = self.preset_strategies.get(code)
                            if p_strat:
                                tp, sl = p_strat.get('tp', 0.0), p_strat.get('sl', 0.0)
                            else:
                                tp, sl, _ = self.get_dynamic_thresholds(code, self.current_market_vibe)
                            should_sell, reason = self.ai_advisor.closing_sell_confirm(code, item.get('prdt_name'), self.current_market_vibe, rt, detail, news, tp=tp, sl=sl)
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
            
            # [추가] 기술적 지표 분석 (MA) 정보 추출
            ma_info = ""
            try:
                ma_analysis = self.indicator_eng.get_dual_timeframe_analysis(self.api, code)
                sig = ma_analysis.get('signal', 'NEUTRAL')
                ma_info = f" [MA:{sig}]"
            except: pass

            # 1. 물타기 체크
            rec_bear = self.recovery_eng.get_recommendation(item, self.global_panic, sl, vibe=market_trend)
            if rec_bear:
                rec_bear['reason'] = f"손절선({sl}%) 근접 하락 대응{ma_info}"
                recs.append(rec_bear)
            
            # 2. 불타기 체크
            rec_bull = self.pyramid_eng.get_recommendation(item, market_trend, self.global_panic, spike, tp)
            if rec_bull:
                rec_bull['reason'] = f"익절선({tp}%) 추종 상승 매수{ma_info}"
                recs.append(rec_bull)
        return recs

    def confirm_buy_decision(self, code: str, name: str, score: float = 0.0) -> Tuple[bool, str]:
        self._cleanup_rejected_stocks()
        if code in self.rejected_stocks: return False, f"당일 매수 거절됨"
        
        # [Safety] indicators 초기화 위치를 함수 최상단으로 이동 (UnboundLocalError 방지)
        indicators = {}
        
        detail = self.api.get_naver_stock_detail(code)
        try: price = float(detail.get('price', 0))
        except: price = 0.0
        if price == 0.0: return False, "실시간 데이터 오류: 시세 0원"
        news = self.api.get_naver_stock_news(code)
        
        try:
            candles = self.api.get_minute_chart_price(code)
            if candles: 
                indicators = self.indicator_eng.get_all_indicators(candles)
            
            # [추가] MA 이중 분석 및 점수 보정
            ma_analysis = self.indicator_eng.get_dual_timeframe_analysis(self.api, code)
            if ma_analysis:
                indicators['ma_analysis'] = ma_analysis
                # 일봉 하락추세(CAUTION)인 경우 AI 점수 20% 감축하여 보수적 접근 유도
                if ma_analysis.get('signal') == "CAUTION":
                    score *= 0.8
        except Exception as e:
            logger.warning(f"지표 분석 중 오류 발생 (스킵): {e}")

        phase = self.get_market_phase()
        is_confirmed, reason = self.ai_advisor.final_buy_confirm(code, name, self.current_market_vibe, detail, news, indicators=indicators, score=score, phase=phase)
        m_id = self.ai_advisor.last_used_advisor.model_id if hasattr(self.ai_advisor, 'last_used_advisor') and self.ai_advisor.last_used_advisor else ""
        
        if not is_confirmed:
            if re.search(r"(?<![0-9])0원", reason) or "가격이 0원" in reason: return False, f"데이터 지연 보류: {reason}"
            self.rejected_stocks[code] = {"reason": reason, "time": time.time()}
            # [추가] 거절 로그 영속성 확보
            trading_log.log_rejection(code, name, reason, model_id=m_id)
            self._save_all_states()
            return False, reason
        
        if m_id: self.last_buy_models[code] = m_id
        return True, reason

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

    def perform_portfolio_batch_review(self, skip_trade=False) -> List[str]:
        """보유 종목 전체에 대해 AI 통합 진단을 수행하고 매도 또는 전략 갱신을 실행합니다."""
        holdings = self.api.get_balance()
        if not holdings: return []
        
        results = []
        # 1. AI 진단을 위한 데이터 보강 (뉴스, 상세 지표 등)
        holdings_data = []
        for h in holdings:
            code = h['pdno']
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            p_strat = self.preset_strategies.get(code)
            if p_strat:
                tp, sl = p_strat.get('tp', 0.0), p_strat.get('sl', 0.0)
            else:
                tp, sl, _ = self.get_dynamic_thresholds(code, self.current_market_vibe)

            # [추가] MA 괴리율 분석 데이터 보강
            ma_gap_str = ""
            try:
                min_candles = self.api.get_minute_chart_price(code)
                if min_candles:
                    closes = [float(c.get('stck_clpr', 0)) for c in min_candles]
                    sma_20 = sum(closes[:20]) / 20 if len(closes) >= 20 else 0
                    if sma_20 > 0:
                        gap = ((float(h.get('prpr', 0)) - sma_20) / sma_20) * 100
                        ma_gap_str = f" | 분봉20MA괴리: {gap:+.2f}%"
            except: pass

            holdings_data.append({
                "code": code, "name": h['prdt_name'],
                "rt": float(h.get('evlu_pfls_rt', 0)),
                "tp": tp, "sl": sl,
                "per": detail.get('per'), "pbr": detail.get('pbr'),
                "news": ", ".join(news[:2]),
                "ma_info": ma_gap_str
            })
        
        # 2. AI Advisor 호출 (배치 분석)
        review = self.ai_advisor.get_portfolio_strategic_review(holdings_data, self.current_market_vibe, self.current_market_data)
        if not review: return ["⚠️ AI 포트폴리오 통합 분석 실패"]
        
        # 3. 분석 결과에 따른 액션 실행
        market_open = is_ai_enabled_time() or getattr(self, "debug_mode", False)
        # 자율 매도 모드(AUTO)가 켜져 있다면 skip_trade 옵션과 상관없이 매매 허용
        can_sell = market_open and (self.auto_sell_mode or not skip_trade)
        
        for code, opinion in review.items():
            name = next((h['name'] for h in holdings_data if h['code'] == code), code)
            action = opinion.get("action", "HOLD").upper()
            reason = opinion.get("reason", "AI 분석 결과")
            
            if action == "SELL":
                # [추가] 구매 후 최소 관망 시간(1시간) 체크 - 수수료 낭비 방지
                # 단, 글로벌 패닉(is_panic) 또는 방어모드(Defensive)인 경우 리스크 관리 차원에서 즉시 매도 허용
                last_buy_t = self.last_buy_times.get(code, 0)
                holding_sec = time.time() - last_buy_t
                is_emergency = self.analyzer.is_panic or self.current_market_vibe.upper() == "DEFENSIVE"
                
                if last_buy_t > 0 and holding_sec < 3600 and not is_emergency:
                    results.append(f"🛡️ 매도 보호: {name} (구매 후 {int(holding_sec/60)}분 경과 - 1시간 미만)")
                    continue

                # [매매 시도 기록] 실제 주문 전 AI의 결정을 먼저 로그에 남김
                trading_log.log_config(f"🤖 AI 자율 매도 결정: [{code}]{name} | 사유: {reason}")
                
                if can_sell:
                    # [즉시 매매 실행]
                    h_item = next((h for h in holdings if h['pdno'] == code), None)
                    if h_item:
                        sell_qty = int(float(h_item.get('hldg_qty', 0)))
                        dm_tag = self.ai_advisor.last_used_advisor.short_id if hasattr(self.ai_advisor, 'last_used_advisor') else "AI"
                        
                        success, res_data = self.api.order_market(code, sell_qty, False)
                        if success:
                            curr_price = float(h_item.get('prpr', 0))
                            profit = (curr_price - float(h_item.get('pchs_avg_pric', 0))) * sell_qty
                            results.append(f"🤖 AI 자율 매도: {name} ({int(profit):+,}원)")
                            trading_log.log_trade("AI자율매도", code, name, curr_price, sell_qty, f"AI 선제적 매도: {reason}", profit=profit, model_id=dm_tag)
                            self.record_sell(code)
                            # 전략 삭제
                            if code in self.preset_strategies: self.assign_preset(code, "00", name=name)
                        else:
                            trading_log.log_config(f"❌ AI 매도 주문 실패: [{code}]{name} | 사유: {res_data}")
                            results.append(f"❌ AI 매도 실패: {name}")
                else:
                    # [장외 시간 또는 skip_trade] - AI 자율 모드인 경우 전략 수치를 타이트하게 조정하여 장 오픈 즉시 대응
                    results.append(f"🔒 AI 매도 권고(장외): {name} | 사유: {reason}")
                    trading_log.log_config(f"🤖 AI 매도 권고(장외): [{code}]{name} | 사유: {reason}")
                    
                    if self.auto_sell_mode:
                        # 다음 거래일 시가 부근에서 즉시 매도되도록 대응
                        h_item = next((h for h in holdings if h['pdno'] == code), None)
                        if h_item and code in self.preset_strategies:
                            curr_rt = float(h_item.get('evlu_pfls_rt', 0))
                            if curr_rt >= 0:
                                # 수익권인 경우: 익절선을 현재 수익률보다 약간 낮게 설정하여 즉시 익절 유도
                                self.preset_strategies[code]['tp'] = max(0.1, curr_rt - 0.1)
                                self.preset_strategies[code]['sl'] = -0.1 # 손절 최소화
                            else:
                                # 손실권인 경우: 손절선을 현재 수익률보다 약간 높게(0에 가깝게) 설정하여 즉시 손절 유도
                                self.preset_strategies[code]['sl'] = min(-0.1, curr_rt + 0.1)
                                self.preset_strategies[code]['tp'] = 0.5 # 익절 기대 포기
                            
                            self.preset_strategies[code]['reason'] = f"[장외매도준비] {reason}"
                            self._save_all_states()
                            results.append(f"🛡️ {name} 장전 매도 준비 완료 (타이트닝)")
            
            elif action == "HOLD":
                # [전략 갱신]
                pid = opinion.get("preset_id", "01")
                tp, sl = float(opinion.get("tp", 5.0)), float(opinion.get("sl", -5.0))
                lifetime = int(opinion.get("lifetime", 120))  # 유효 시간 추가
                if self.assign_preset(code, pid, tp, sl, reason, name=name, lifetime_mins=lifetime):
                    p_name = PRESET_STRATEGIES.get(pid, {}).get("name", pid)
                    results.append(f"📝 전략 갱신: {name} [{p_name}] TP:{tp:+.1f}% SL:{sl:.1f}%")
        
        return results
