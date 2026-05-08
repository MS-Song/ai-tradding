import time
import math
import re
from datetime import datetime
from typing import List, Tuple, Optional
from src.logger import logger, log_error, trading_log
from src.utils import is_ai_enabled_time, safe_cast_float
from src.strategy.constants import PRESET_STRATEGIES

class ExecutionMixin:
    """트레이딩 엔진의 핵심 매매 실행 로직을 담당하는 믹스인 클래스입니다.

    매매 사이클(run_cycle)을 주도하며 시장 페이즈별(P1~P4) 대응, 실시간 익절/손절 집행, 
    물타기/불타기 전략 추천, 그리고 AI 기반의 자율 매매 및 포트폴리오 통합 진단(Batch Review) 
    기능을 총괄합니다. 모든 주문 실행과 거래 로그 기록의 중앙 허브 역할을 수행합니다.
    """
    def run_cycle(self, market_trend="neutral", skip_trade=False, holdings=None, asset_info=None):
        """메인 트레이딩 사이클을 1회 수행하여 매매 기회를 탐색하고 포지션을 관리합니다.

        프로세스 흐름:
            1. 리스크 체크: 자산 상태 확인 및 서킷 브레이커(일일 손실 한도 등) 점검.
            2. Phase 4 (장 마감): 종가 베팅 보호 갱신 및 신규 종가 베팅 집행.
            3. Phase 4 (배치 리뷰): 전체 보유 종목에 대해 AI 통합 진단 수행 및 조기 청산 결정.
            4. Phase 3 (수익 확정): 수익권(+0.5%↑) 종목의 50% 분할 매도 및 본전 스탑 상향.
            5. 실시간 감시: 개별 종목의 동적 익절/손절(TP/SL) 도달 여부 확인 및 체결.
            6. 비중 조절: 물타기(Recovery) 및 불타기(Pyramiding) 추천 로직 실행.
            7. 자율 매수: AI 추천 종목 신규 진입 및 보유 종목과의 교체(Replacement) 매매.

        Args:
            market_trend (str): 현재 시장 추세 ('BULL', 'BEAR', 'NEUTRAL', 'DEFENSIVE').
            skip_trade (bool): True일 경우 실제 주문을 내지 않고 시뮬레이션만 수행.
            holdings (list, optional): 외부에서 주입된 현재 잔고 정보. 미지정 시 API로 직접 조회.
            asset_info (dict, optional): 자산 요약 정보 (총자산, 가용현금 등).

        Returns:
            list: 해당 사이클에서 발생한 주요 이벤트 메시지(매매 체결, 보호 알림 등) 리스트.
        """
        self._cleanup_rejected_stocks()
        if holdings is None: holdings = self.api.get_balance()
        if asset_info is None: asset_info = self.api.get_full_balance()[1] if not skip_trade else {}
        
        results, curr_t = [], self.mock_tester.get_now().timestamp()
        phase = self.get_market_phase()
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        today = datetime.now().strftime('%Y-%m-%d')
        if not hasattr(self, '_p3_global_processed'): self._p3_global_processed = {}
        self._p4_ai_done_this_cycle = False
        
        if asset_info.get('total_asset', 0) > 0:
            self.last_known_asset = safe_cast_float(asset_info['total_asset'])
            if self.start_day_asset > 0 and self.start_day_pnl != -999999999.0:
                # [개선] 입출금 영향 배제 정확한 일일 수익률 계산 (SyncWorker와 로직 동기화)
                realized_p = trading_log.get_daily_profit()
                fees = trading_log.get_daily_trading_fees()
                curr_unrealized = asset_info.get('pnl', 0)
                init_unrealized = self.start_day_pnl
                
                daily_pnl_amt = (realized_p - fees) + (curr_unrealized - init_unrealized)
                asset_info['daily_pnl_amt'] = daily_pnl_amt
                asset_info['daily_pnl_rate'] = (daily_pnl_amt / self.start_day_asset * 100)
            else:
                # 초기화 전이라면 기본값 설정 (0)
                asset_info['daily_pnl_amt'] = asset_info.get('daily_pnl_amt', 0.0)
                asset_info['daily_pnl_rate'] = asset_info.get('daily_pnl_rate', 0.0)
        
        if self.risk_mgr.check_circuit_breaker(asset_info):
            return [f"🛑 리스크 상한 도달: {self.risk_mgr.halt_reason} (매매 중단)"]

        if phase['id'] == "P4" and not self.global_panic and self.current_market_vibe.upper() in ["BULL", "NEUTRAL"] and self.auto_ai_trade:
            # [개선] 종가 베팅 후보 종목(Top 3)에 대한 보호 갱신은 매 사이클 수행하여 청산 방어력 강화
            # (기존에는 _last_closing_bet_date 체크 때문에 한 번만 실행되어 다른 종목 보호가 누락될 수 있었음)
            if self.ai_recommendations:
                for top_rec in self.ai_recommendations[:3]:
                    code, name = top_rec['code'], top_rec['name']
                    if any(h.get('pdno') == code for h in holdings):
                        # 기보유 종목이거나 방금 매수한 종목인 경우 보호 시간 갱신 (P4 청산 방지)
                        # 단, 너무 잦은 로깅 방지를 위해 1분 주기로만 갱신/로깅
                        now_t = time.time()
                        if (now_t - self.last_buy_times.get(code, 0)) > 60:
                            logger.info(f"🛡️ P4 종가 베팅 후보 보호 갱신: {name} ({code})")
                            self.last_buy_times[code] = now_t
                            # TUI에는 최초 1회 또는 상태 변화 시에만 기록 (노이즈 방지)
                            if getattr(self, "_last_p4_protected_code", None) != code:
                                msg = f"🛡️ 당일 매수 P4 보호: {name}"
                                results.append(msg)
                                if self.state: self.state.add_trading_log(msg)
                                self._last_p4_protected_code = code

            # 실제 신규 매수는 하루 한 번만 집행
            if getattr(self, "_last_closing_bet_date", None) != today and self.ai_recommendations:
                for top_rec in self.ai_recommendations[:3]:
                    code, name = top_rec['code'], top_rec['name']
                    # 이미 보유 중인 경우 위에서 보호 갱신만 하고 매수는 스킵 (다음 순위 탐색)
                    if any(h.get('pdno') == code for h in holdings):
                        self._last_closing_bet_date = today
                        self._save_all_states()
                        break 
                    
                    # [CRITICAL] 당일 등락률 하드 필터 (-1.5% ~ +8.0% 범위만 진입 허용)
                    _p4_rate = safe_cast_float(top_rec.get('rate'))
                    if _p4_rate > 8.0 or _p4_rate < -8.0:
                        logger.warning(f"P4 종가 베팅 등락률 초과: {name} ({_p4_rate:+.1f}%) -> 다음 순위 탐색")
                        continue
                    
                    price = safe_cast_float(top_rec.get('price'))
                    qty = math.floor(self.ai_config["amount_per_trade"] / price) if price > 0 else 0
                    if qty == 0 and asset_info.get('cash', 0) >= price:
                        qty = 1
                        
                    if qty > 0 and not skip_trade:
                        dry_res = self.mock_tester.intercept_order(code, qty, True)
                        success, msg = dry_res if dry_res else self.api.order_market(code, qty, True)
                        if success:
                            self._last_closing_bet_date = today
                            results.append(f"P4 종가 베팅 매수: {name} ({code}) {qty}주")
                            m_id = self.ai_advisor.last_used_advisor.model_id if hasattr(self.ai_advisor, 'last_used_advisor') and self.ai_advisor.last_used_advisor else ""
                            strategy_label = self.get_preset_label(code) or "P4종가"
                            trading_log.log_trade("🤖P4종가매수", code, name, price, qty, f"AI 추천 기반 종가 베팅 ({strategy_label})", model_id=m_id, ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                            trading_log.log_buy_reason(code, name, f"AI 추천 기반 종가 베팅 ({strategy_label})", model_id=m_id)
                            self.record_buy(code, price)
                            self.auto_assign_preset(code, name)
                            self._async_update_ma_cache(code)
                            self._save_all_states()
                            break 
                        else:
                            log_error(f"P4 종가 베팅 매수 실패: [{code}]{name} | {qty}주 | 사유: {msg}")
                            msg_fail = f"❌ P4 종가 베팅 실패: {name} | 사유: {msg}"
                            results.append(msg_fail)
                            if self.state: self.state.add_trading_log(msg_fail)

        # [Phase 4] 통합 배치 리뷰 트리거 (종목이 많은 경우 개별 AI 호출은 너무 느리므로 한 번에 처리)
        if phase['id'] == "P4" and getattr(self, "_last_p4_batch_date", None) != today and not skip_trade:
            self._last_p4_batch_date = today
            logger.info("🚀 P4 진입: 보유 종목 전체 AI 통합 진단 시작 (Batch Review)")
            batch_results = self.perform_portfolio_batch_review(skip_trade=False)
            for br in batch_results:
                results.append(f"🏁 {br}")
            self._save_all_states()

        for item in holdings:
            code, name = item['pdno'], item['prdt_name']
            m_id = "" # 초기화 추가

            p_strat = self.preset_strategies.get(code)
            
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

                if phase['id'] == "P3" and not p_strat.get('is_p3_processed') and safe_cast_float(item.get("evlu_pfls_rt")) >= 0.5:
                    sell_qty = int(float(item.get('hldg_qty', 0))) // 2
                    if sell_qty > 0 and not skip_trade:
                        dry_res = self.mock_tester.intercept_order(code, sell_qty, False)
                        success, msg = dry_res if dry_res else self.api.order_market(code, sell_qty, False)
                        if success:
                            p_strat['is_p3_processed'], p_strat['sl'] = True, 0.2
                            p3_profit = (safe_cast_float(item.get('prpr')) - safe_cast_float(item.get('pchs_avg_pric'))) * sell_qty
                            m_id = self.last_buy_models.get(code, "")
                            strategy_label = self.get_preset_label(code) or "P3수익"
                            # [통합] log_trade가 TUI 및 JSON 로그를 한 번에 처리
                            trading_log.log_trade("P3수익확정(50%)", code, item.get('prdt_name'), safe_cast_float(item.get('prpr')), sell_qty, f"Phase3 장마감 대비 분할매도 ({strategy_label})", profit=p3_profit, model_id="TL/SP", ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                            results.append(f"🏁 {trading_log.last_tui_msg}")
                            self.record_sell(code, is_full_exit=False)
                            self._async_update_ma_cache(code)
                            self._save_all_states()
                        else:
                            # [Fix] P3 수익확정 매도 실패 시 사유 로깅
                            log_error(f"P3 수익확정 매도 실패: [{code}]{item.get('prdt_name')} | {sell_qty}주 | 사유: {msg}")
                            msg_fail = f"❌ P3 수익확정 실패: {item.get('prdt_name')} | 사유: {msg}"
                            results.append(msg_fail)
                            if self.state: self.state.add_trading_log(msg_fail)
                    elif skip_trade: p_strat['is_p3_processed'] = True
            else:
                p3_key = f"{today}_{code}"
                if phase['id'] == "P3" and p3_key not in self._p3_global_processed and safe_cast_float(item.get("evlu_pfls_rt")) >= 0.5:
                    sell_qty = int(float(item.get('hldg_qty', 0))) // 2
                    if sell_qty > 0 and not skip_trade:
                        dry_res = self.mock_tester.intercept_order(code, sell_qty, False)
                        success, msg = dry_res if dry_res else self.api.order_market(code, sell_qty, False)
                        if success:
                            self._p3_global_processed[p3_key] = True
                            tp_cur, sl_cur, _ = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
                            self.exit_mgr.manual_thresholds[code] = [tp_cur, 0.2]
                            p3_profit = (safe_cast_float(item.get('prpr')) - safe_cast_float(item.get('pchs_avg_pric'))) * sell_qty
                            m_id = self.last_buy_models.get(code, "")
                            strategy_label = self.get_preset_label(code) or "P3표준"
                            # [통합] log_trade가 TUI 및 JSON 로그를 한 번에 처리
                            trading_log.log_trade("P3수익확정(50%)", code, item.get('prdt_name'), safe_cast_float(item.get('prpr')), sell_qty, f"Phase3 표준종목 분할매도 ({strategy_label})", profit=p3_profit, model_id="TL/SP", ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                            results.append(f"🏁 {trading_log.last_tui_msg}")
                            self.record_sell(code, is_full_exit=False)
                            self._async_update_ma_cache(code)
                            self._save_all_states()
                        else:
                            # [Fix] P3 표준종목 수익확정 매도 실패 시 사유 로깅
                            log_error(f"P3 수익확정 매도 실패(표준): [{code}]{item.get('prdt_name')} | {sell_qty}주 | 사유: {msg}")
                            msg_fail = f"❌ P3 수익확정 실패: {item.get('prdt_name')} | 사유: {msg}"
                            results.append(msg_fail)
                            if self.state: self.state.add_trading_log(msg_fail)

            # --- [Phase 4] 자동 손실 청산 및 AI 개별 분석 (모든 종목 공통 적용) ---
            if phase['id'] == "P4":
                p4_key = f"p4_{today}_{code}"
                rt = safe_cast_float(item.get("evlu_pfls_rt"))
                if rt < 0 and p4_key not in self._p3_global_processed:
                    # [Safety] 당일 매수 보호 (1시간)
                    if (time.time() - self.last_buy_times.get(code, 0)) < 3600:
                        self._p3_global_processed[p4_key] = True
                        msg = f"🛡️ 당일 매수 P4 보호: {item.get('prdt_name')}"
                        results.append(msg)
                        if self.state: self.state.add_trading_log(msg)
                    else:
                        sell_qty = int(float(item.get('hldg_qty', 0)))
                        if sell_qty > 0 and not skip_trade:
                            self.current_action = "P4청산실행"
                            try:
                                dry_res = self.mock_tester.intercept_order(code, sell_qty, False)
                                success, msg = dry_res if dry_res else self.api.order_market(code, sell_qty, False)
                                if success:
                                    self._p3_global_processed[p4_key] = True
                                    p4_profit = (safe_cast_float(item.get('prpr')) - safe_cast_float(item.get('pchs_avg_pric'))) * sell_qty
                                    m_id = self.last_buy_models.get(code, "")
                                    strategy_label = self.get_preset_label(code) or "P4손절"
                                    # [통합] log_trade가 TUI 및 JSON 로그를 한 번에 처리
                                    trading_log.log_trade("P4장마감손절", code, item.get('prdt_name'), safe_cast_float(item.get('prpr')), sell_qty, f"Phase4 비용절감 청산 ({strategy_label})", profit=p4_profit, model_id=m_id or "TL/SP", ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                                    results.append(trading_log.last_tui_msg)
                                    self.record_sell(code, is_full_exit=True)
                                    if not hasattr(self, 'bad_sell_times'): self.bad_sell_times = {}
                                    self.bad_sell_times[code] = {"time": time.time(), "type": "P4손절"}  # 8시간 차단
                                    self._async_update_ma_cache(code)
                                    self._save_all_states()
                            except Exception as e: log_error(f"P4 청산 중 오류: {e}")
                            finally: self.current_action = "대기중"

                # 배치 리뷰에서 처리되지 않은 종목에 대해 개별 AI 분석 수행 (보험용)
                p4_ai_key = f"p4_ai_{today}_{code}"
                if not skip_trade and not self._p4_ai_done_this_cycle and p4_ai_key not in self._p3_global_processed:
                    # 이미 위에서 손절 처리되었거나 배치 리뷰에서 처리된 종목은 스킵
                    is_processed = (p4_key in self._p3_global_processed) or (p4_ai_key in self._p3_global_processed)
                    # [추가] 구매 후 최소 관망 시간(20분) 체크 - 수수료 낭비 방지
                    if not is_processed and (time.time() - self.last_buy_times.get(code, 0)) >= 1200:
                        sell_qty = int(float(item.get('hldg_qty', 0)))
                        if sell_qty > 0:
                            # [Fix] 플래그를 try 블록 내부로 이동: 예외 발생 시 다음 종목이 AI 판단 기회를 얻도록
                            self.current_action = "P4 AI판단"
                            try:
                                self._p4_ai_done_this_cycle = True  # AI 호출 시작 시점에 세팅
                                # [추가] AI 실행 가능 시간 체크 (디버그 모드 제외)
                                if is_ai_enabled_time() or getattr(self, "debug_mode", False):
                                    detail = self.api.get_naver_stock_detail(code)
                                    news = self.api.get_naver_stock_news(code)
                                    tp_cur, sl_cur, _ = self.get_dynamic_thresholds(code, self.current_market_vibe)
                                    should_sell, reason = self.ai_advisor.closing_sell_confirm(code, item.get('prdt_name'), self.current_market_vibe, rt, detail, news, tp=tp_cur, sl=sl_cur)
                                    self._p3_global_processed[p4_ai_key] = True
                                    if should_sell:
                                        dry_res = self.mock_tester.intercept_order(code, sell_qty, False)
                                        success, msg = dry_res if dry_res else self.api.order_market(code, sell_qty, False)
                                        if success:
                                            p4_profit = (float(item.get('prpr', 0)) - float(item.get('pchs_avg_pric', 0))) * sell_qty
                                            m_id = self.ai_advisor.last_used_advisor.model_id if hasattr(self.ai_advisor, 'last_used_advisor') and self.ai_advisor.last_used_advisor else "AI"
                                            strategy_label = self.get_preset_label(code) or "P4AI"
                                            # [통합] log_trade가 TUI 및 JSON 로그를 한 번에 처리
                                            trading_log.log_trade("🤖AI자율매도", code, item.get('prdt_name'), safe_cast_float(item.get('prpr')), sell_qty, f"P4 AI 장마감 청산 ({strategy_label}): {reason}", profit=p4_profit, model_id=m_id, ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                                            results.append(trading_log.last_tui_msg)
                                            try:
                                                self.record_sell(code, is_full_exit=True)
                                                if not hasattr(self, 'bad_sell_times'): self.bad_sell_times = {}
                                                self.bad_sell_times[code] = {"time": curr_t, "type": "AI매도"}  # 8시간 차단
                                                self._async_update_ma_cache(code)
                                                self._save_all_states()
                                            except Exception as log_e:
                                                log_error(f"P4 AI청산 로그 기록 오류 [{code}|{item.get('prdt_name')}]: {log_e}")
                                    else:
                                        msg = f"🔒 P4 AI 유지: {item.get('prdt_name')}"
                                        results.append(msg)
                                        trading_log.log_config(f"{msg} | {reason}")
                                        if self.state: self.state.add_trading_log(msg)
                                else:
                                    self._p3_global_processed[p4_ai_key] = True
                                    logger.info(f"P4 AI판단 건너뜀 (Market closed/AI Disabled): {item.get('prdt_name')}")
                            except Exception as e:
                                log_error(f"P4 AI 매도 판단 오류 [{code}|{item.get('prdt_name')}]: {e}")
                                self._p4_ai_done_this_cycle = False  # [Fix] 오류 시 플래그 리셋 → 다음 종목 AI 판단 허용
                            finally: self.current_action = "대기중"

            # [추가] P4에서 이미 보호(🛡️) 또는 처리(🏁)된 종목은 일반 SL/TP 로직을 스킵하여 핑퐁 매매 방지
            if phase['id'] == "P4" and p4_key in self._p3_global_processed:
                continue

            tp, sl, vol_spike = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)
            rt = safe_cast_float(item.get("evlu_pfls_rt"))
            action, sell_qty, action_reason = None, 0, ""

            if rt >= tp:
                if not self._is_in_partial_sell_cooldown(code, curr_t): action, sell_qty = "익절", max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
                else:
                    is_emg, emg_reason = self._is_emergency_exit(rt, tp, vol_spike, phase, self.last_buy_times.get(code, 0) > self.last_sell_times.get(code, 0))
                    if is_emg: action, action_reason, sell_qty = "긴급익절", emg_reason, max(1, math.floor(int(item.get('hldg_qty', 0)) * 0.3))
            elif rt <= sl:
                # [복기반영 #1] Defensive 장세에서는 손절선 돌파 즉시 기계적 청산 (물타기 유예 30분 포함, 예외 없음)
                if self.analyzer.kr_vibe.upper() == "DEFENSIVE":
                    action, action_reason, sell_qty = "긴급손절", "Defensive장세_SL즉시", int(item.get('hldg_qty', 0))
                elif (curr_t - self.last_buy_times.get(code, 0)) < 1800 and self.last_buy_times.get(code, 0) > self.last_sell_times.get(code, 0):
                    is_emg, emg_reason = self._is_emergency_sl(rt, sl, self.analyzer.is_panic, self.analyzer.kr_vibe, phase, True)
                    if is_emg: action, action_reason, sell_qty = "긴급손절", emg_reason, int(item.get('hldg_qty', 0))
                else: action, sell_qty = "손절", int(item.get('hldg_qty', 0))

            if action and not skip_trade and sell_qty > 0:
                self.current_action = f"{action}실행"
                try:
                    logger.info(f"🚀 {action} 주문 시작: {item.get('prdt_name')}({code}) {sell_qty}주")
                    dry_res = self.mock_tester.intercept_order(code, sell_qty, False)
                    success, msg = dry_res if dry_res else self.api.order_market(code, sell_qty, False)
                    if success:
                        # [Fix] 익절(30%)은 부분 매도이므로 전략 삭제 제외, 손절은 전체 매도이므로 삭제
                        is_full = action in ["손절", "긴급손절"]
                        self.record_sell(code, is_full_exit=is_full)
                        if is_full:
                            if not hasattr(self, 'bad_sell_times'): self.bad_sell_times = {}
                            self.bad_sell_times[code] = {"time": curr_t, "type": "손절"}  # 24시간 차단
                        m_id = self.last_buy_models.get(code, "")
                        strategy_label = self.get_preset_label(code) or "자동매매"
                        # [통합] log_trade가 TUI 및 JSON 로그를 한 번에 처리
                        trading_log.log_trade(action, code, item.get('prdt_name'), safe_cast_float(item.get('prpr')), sell_qty, f"{action_reason or action} ({strategy_label})", profit=(safe_cast_float(item.get('prpr')) - safe_cast_float(item.get('pchs_avg_pric'))) * sell_qty, model_id=m_id or "TL/SP", ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                        results.append(trading_log.last_tui_msg)
                        self._async_update_ma_cache(code)
                        self._save_all_states()
                    else:
                        logger.error(f"❌ {action} 주문 실패: {msg}")
                except Exception as e:
                    logger.error(f"⚠️ {action} 실행 중 예외 발생: {e}")
                finally:
                    self.current_action = "대기중"

        # --- [추가] 신규 진입 및 추가 매수 엔진 (Bear/Bull/AI) ---
        if not skip_trade and not self.global_panic and phase['id'] in ["P1", "P2"] and not getattr(self.state, "is_trading_paused", False):
            # (A) 물타기/불타기 집행 (기존 종목 비중 조절)
            if self.recovery_eng.config.get("auto_mode") or self.bull_config.get("auto_mode"):
                # [Cash Ratio Check] 하락장 30%, 방어모드 80% 현금 비중 유지 원칙
                total_asset = asset_info.get('total_asset', 0)
                cash = asset_info.get('cash', 0)
                cash_ratio = (cash / total_asset * 100) if total_asset > 0 else 0
                
                buy_recs = self.get_buy_recommendations(market_trend, holdings=holdings)
                for rec in buy_recs:
                    # [Safety] 루프당 최대 1종목 제한
                    if any(x for x in results if "매수" in x or "익절" in x or "손절" in x): break
                    
                    code, name, amt, b_type = rec['code'], rec['name'], rec['suggested_amt'], rec['type']
                    
                    # [Cooldown] 익절/손절 후 2시간 이내 재진입 금지 (핑퐁 방지)
                    if (curr_t - self.last_sell_times.get(code, 0)) < 7200: continue
                    
                    # 현금 비중 보호
                    if b_type == "물타기":
                        if market_trend == "bear" and cash_ratio < 30: continue
                        if market_trend == "defensive" and cash_ratio < 80: continue
                    
                    if cash < amt: continue
                    
                    # 투자 한도 확인 (max_investment_per_stock)
                    h_item = next((h for h in holdings if h['pdno'] == code), None)
                    if h_item:
                        curr_inv = safe_cast_float(h_item.get('pchs_amt'))
                        limit = self.bear_config.get("max_investment_per_stock") if b_type == "물타기" else self.bull_config.get("max_investment_per_stock")
                        if curr_inv + amt > limit: continue
                        
                        price = safe_cast_float(h_item.get('prpr'))
                        qty = math.floor(amt / price) if price > 0 else 0
                        if qty > 0:
                            dry_res = self.mock_tester.intercept_order(code, qty, True)
                            success, msg = dry_res if dry_res else self.api.order_market(code, qty, True)
                            if success:
                                self.record_buy(code, price)
                                strategy_label = self.get_preset_label(code) or b_type
                                # [통합] log_trade가 TUI 및 JSON 로그를 한 번에 처리
                                trading_log.log_trade(f"자동{b_type}", code, name, price, qty, f"{rec.get('reason', '')} ({strategy_label})", model_id="TL/SP", ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                                results.append(trading_log.last_tui_msg)
                                self._async_update_ma_cache(code)
                                self._save_all_states()
                            else:
                                # [Fix] 물타기/불타기 매수 실패 시 사유 로깅
                                log_error(f"{b_type} 매수 실패: [{code}]{name} | {qty}주 | 사유: {msg}")
                                results.append(f"❌ {b_type} 실패: {name} | 사유: {msg}")

            # (B) AI 자율 매수 집행 (신규 종목 진입)
            if self.auto_ai_trade and self.ai_recommendations:
                max_cnt = self.get_max_stock_count(asset_info.get('total_asset', 0))
                curr_cnt = len(holdings)
                
                # [Cash Ratio Check] 신규 진입 시에도 현금 비중 유지
                total_asset = asset_info.get('total_asset', 0)
                cash = asset_info.get('cash', 0)
                cash_ratio = (cash / total_asset * 100) if total_asset > 0 else 0
                
                for rec in self.ai_recommendations:
                    # [Safety] 루프당 최대 1종목 제한
                    if any(x for x in results if "매수" in x or "익절" in x or "손절" in x): break
                    
                    code, name, score = rec['code'], rec['name'], rec.get('score', 0.0)
                    if any(h.get('pdno') == code for h in holdings): continue
                    
                    # [Cooldown] 익절 후 2시간 이내 재진입 금지 (핑퐁 방지)
                    if (time.time() - self.last_sell_times.get(code, 0)) < 7200: continue
                    
                    # [매도 사유별 차등 재진입 차단] 손절=24h, P4손절/AI매도=8h, 교체매도=4h
                    if self._is_bad_sell_blocked(code): continue
                    
                    # [Cooldown] 최근 매수 이력이 있으면 중복 진입 금지 (잔고 동기화 지연 및 API 딜레이 대응)
                    if (time.time() - self.last_buy_times.get(code, 0)) < 600: continue
                    
                    # 현금 비중 보호
                    if market_trend == "bear" and cash_ratio < 30: continue
                    if market_trend == "defensive" and cash_ratio < 80: continue
                    
                    # [Step 1] 최종 구매 컨펌 (Gemini)
                    is_ok, reason = self.confirm_buy_decision(code, name, score)
                    if not is_ok: continue
                    
                    # [Step 2] 한도 및 교체 판단
                    target_code = None
                    if curr_cnt >= max_cnt:
                        # [교체 품질 게이트 #1] 후보 종목의 등락률이 OVERBOUGHT 구간이면 교체 금지
                        # (MA 지표 없이 교체하는 경우도 차단하여 상투 교체 방지)
                        cand_detail = self.api.get_naver_stock_detail(code)
                        cand_rate = safe_cast_float(cand_detail.get('rate'))
                        cand_ma_analysis = self.indicator_eng.get_dual_timeframe_analysis(self.api, code, name=name)
                        cand_sig = cand_ma_analysis.get('signal', 'NEUTRAL') if cand_ma_analysis else 'UNKNOWN'
                        if cand_sig == 'OVERBOUGHT':
                            logger.info(f"🚫 [교체품질게이트] {name} 후보 OVERBOUGHT - 교체 진입 차단")
                            continue
                        if cand_sig == 'UNKNOWN':
                            logger.info(f"⚠️ [교체품질게이트] {name} MA지표 없음 - 교체 진입 차단")
                            continue

                        # [교체 품질 게이트 #2] 후보 score가 기존 보유 종목 중 가장 낮은 score보다 15pt 이상 높아야 교체 허용
                        # Gemini의 주관적 판단에만 의존하지 않고 정량 기준 선제 검증
                        min_holding_score = min(
                            (self.ai_recommendations and next(
                                (r.get('score', 0) for r in self.ai_recommendations if r['code'] == h.get('pdno')), 0
                            ) or 0)
                            for h in holdings
                        ) if holdings else 0
                        if score < min_holding_score + 15.0:
                            logger.info(f"🚫 [교체품질게이트] {name} 점수({score:.1f}) 기존 최저({min_holding_score:.1f}) 대비 15pt 미달 - 교체 차단")
                            continue

                        # [교체 품질 게이트 #3] 교체 대상 후보 종목의 보유 시간이 30분 미만이면 교체 금지
                        # (수수료 낭비 + 수익 실현 기회 박탈 방지)
                        too_fresh = any(
                            h.get('pdno') and (time.time() - self.last_buy_times.get(h['pdno'], 0)) < 1800
                            for h in holdings
                        )
                        if too_fresh:
                            logger.info(f"🚫 [교체품질게이트] 30분 미만 보유 종목 존재 - 교체 대기")
                            continue

                        is_superior, t_code, t_reason = self.get_replacement_target(code, name, score, holdings)
                        if is_superior and t_code:
                            target_code = t_code
                        else:
                            continue
                            
                    # [Step 3] 매수 집행 준비
                    price = safe_cast_float(rec.get('price')) or safe_cast_float(self.api.get_inquire_price(code).get('price'))
                    if price == 0: continue
                    
                    amt = self.ai_config["amount_per_trade"]
                    # [개선] 1회 한도가 부족하더라도 가용 현금이 주가보다 크다면 최소 1주 매수 시도 허용
                    if cash < amt and cash < price:
                        continue # 1주도 살 수 없는 경우만 스킵
                    
                    # 교체 대상 전량 매도
                    if target_code:
                        t_item = next((h for h in holdings if h['pdno'] == target_code), None)
                        if t_item:
                            dry_res = self.mock_tester.intercept_order(target_code, int(float(t_item['hldg_qty'])), False)
                            success, res_data = dry_res if dry_res else self.api.order_market(target_code, int(float(t_item['hldg_qty'])), False)
                            if success:
                                curr_price = safe_cast_float(t_item.get('prpr'))
                                profit = (curr_price - safe_cast_float(t_item.get('pchs_avg_pric'))) * int(safe_cast_float(t_item.get('hldg_qty')))
                                strategy_label = self.get_preset_label(target_code) or "교체매도"
                                trading_log.log_trade("교체매도", target_code, t_item['prdt_name'], curr_price, int(float(t_item['hldg_qty'])), f"교체대상 선정됨 (후보: {name}, 전략: {strategy_label})", profit=profit, model_id="AI", ma_20=self.state.ma_20_cache.get(target_code, 0.0) if self.state else 0.0)
                                self.replacement_logs.append({
                                    "time": now_str,
                                    "out_code": target_code,
                                    "out_name": t_item['prdt_name'],
                                    "in_code": code,
                                    "in_name": name,
                                    "reason": f"AI 교체 판단 (후보: {name})"
                                })
                                self.record_sell(target_code, is_full_exit=True)
                                if not hasattr(self, 'bad_sell_times'): self.bad_sell_times = {}
                                self.bad_sell_times[target_code] = {"time": time.time(), "type": "교체"}  # 4시간 차단
                                results.append(f"🔄 교체매도: {t_item['prdt_name']} (-> {name})")
                                # [추가] 매도 후 가용 현금 로컬 업데이트 (매수 qty 계산 및 안전 체크용)
                                cash += (curr_price * int(float(t_item['hldg_qty'])))
                            else:
                                # [Fix] 교체매도 실패 시에도 구체적 사유 기록 (기존: 사유 누락)
                                fail_reason = res_data if res_data else "응답 없음"
                                log_error(f"교체매도 주문 실패: [{target_code}]{t_item['prdt_name']} | 사유: {fail_reason}")
                                results.append(f"❌ 교체매도 실패: {t_item['prdt_name']} | 사유: {fail_reason}")
                    
                    # 가용 현금 내에서 설정된 한도(amt)까지 최대한 매수
                    qty = math.floor(min(amt, cash) / price) if price > 0 else 0
                    # [개선] 한도(amt)보다 주가가 높더라도 현금이 있다면 최소 1주 매수 보장
                    if qty == 0 and cash >= price:
                        qty = 1
                        
                    if qty > 0:
                        dry_res = self.mock_tester.intercept_order(code, qty, True)
                        success, msg = dry_res if dry_res else self.api.order_market(code, qty, True)
                        if success:
                            self.record_buy(code, price)
                            self.auto_assign_preset(code, name)
                            m_id = self.last_buy_models.get(code, "AI")
                            strategy_label = self.get_preset_label(code) or "AI자율"
                            # [통합] log_trade가 TUI 및 JSON 로그를 한 번에 처리
                            trading_log.log_trade("🤖AI자율매수", code, name, price, qty, f"{reason} ({strategy_label})", model_id=m_id, ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                            results.append(trading_log.last_tui_msg)
                            trading_log.log_buy_reason(code, name, f"{reason} ({strategy_label})", model_id=m_id)
                            self._async_update_ma_cache(code)
                            self._save_all_states()
                        else:
                            # [추가] 매수 실패 시 구체적 사유 로깅 (교체 매매 추적용)
                            err_msg = f"❌ AI자율매수 실패: {name}({code}) | 사유: {msg}"
                            logger.error(err_msg)
                            msg_fail = f"❌ {name} 매수 실패: {msg}"
                            results.append(msg_fail)
                            if self.state: self.state.add_trading_log(msg_fail)
                            
        return results

    def get_buy_recommendations(self, market_trend="neutral", holdings=None):
        """현재 보유 종목 중 물타기(Recovery) 또는 불타기(Pyramiding) 조건에 부합하는 종목을 탐색합니다.

        내부적으로 기술적 지표(MA) 분석을 60초 주기로 캐싱하여 API 호출 부하를 
        최적화하며, 각 추천 엔진의 로직에 현재 시장 장세를 전달합니다.

        Args:
            market_trend (str): 현재 시장 장세.
            holdings (list, optional): 현재 잔고 정보.

        Returns:
            list: 매수 추천 정보(종목코드, 금액, 사유 등)가 포함된 딕셔너리 리스트.
        """
        recs = []
        if holdings is None: holdings = self.api.get_balance()
        for item in holdings:
            code = item.get("pdno")
            name = item.get("prdt_name", code)
            tp, sl, spike = self.get_dynamic_thresholds(code, market_trend)
            
            # [핵심 최적화] 기술적 지표 분석 (MA) 캐싱 적용 (60초 주기)
            if not hasattr(self, '_ma_analysis_cache'): self._ma_analysis_cache = {}
            cache_key = f"ma_{code}"
            cached = self._ma_analysis_cache.get(cache_key)
            
            ma_info = ""
            if cached and (time.time() - cached['time'] < 60):
                ma_analysis = cached['data']
                sig = ma_analysis.get('signal', 'NEUTRAL')
                ma_info = f" [MA:{sig}]"
            else:
                try:
                    ma_analysis = self.indicator_eng.get_dual_timeframe_analysis(self.api, code, name=name)
                    self._ma_analysis_cache[cache_key] = {'data': ma_analysis, 'time': time.time()}
                    sig = ma_analysis.get('signal', 'NEUTRAL')
                    ma_info = f" [MA:{sig}]"
                    # trading_log.log_ai_activity("MA분석", f"[{code}] {name} 지표분석", "COMPLETED", f"Signal: {sig}")
                except Exception as e:
                    trading_log.log_ai_activity("MA분석", f"[{code}] {name} 분석실패", "FAIL", str(e)[:30])
                    logger.warning(f"물타기/불타기 MA분석 실패 ({name}): {e}")

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
        """신규 종목 매수 전, 알고리즘 필터링 및 AI 최종 승인 절차를 수행합니다.

        검증 프로세스 (GEMINI.md 2.D):
            1. 기본 필터: 당일 거절(Rejected) 여부 및 최근 매수 이력 확인.
            2. 가격 필터: 당일 등락률이 -8.0% ~ +8.0% 범위를 벗어날 경우 차단.
            3. 기술 필터: 분봉 20MA 대비 이격도(OVERBOUGHT) 점검 및 매수 구역(BUY_ZONE) 가점.
            4. AI 컨펌: 실시간 뉴스, 시황, 지표를 종합하여 Gemini에게 최종 'Yes/No' 판단 요청.

        Args:
            code (str): 종목 코드.
            name (str): 종목명.
            score (float): AlphaEngine에서 산출된 정량적 스코어.

        Returns:
            Tuple[bool, str]: (매수 승인 여부, 승인/거절 상세 사유).
        """
        self._cleanup_rejected_stocks()
        if code in self.rejected_stocks: return False, f"당일 매수 거절됨"
        
        # [Safety] 최근 매수 이력이 있는 경우 중복 진입 방지 (잔고 동기화 전 중복 호출 차단)
        if (time.time() - self.last_buy_times.get(code, 0)) < 600:
            return False, "최근 매수 이력 있음 (중복 방지)"

        # [신규] 장 초반 안정화 필터 (09:00~09:20)
        # 지수가 BULL이 아닌 경우 AI 점수 커트라인을 대폭 상향하여 리스크 관리
        phase = self.get_market_phase()
        if phase.get('is_stabilizing') and self.current_market_vibe.upper() != "BULL":
            strict_min = self.ai_config.get('min_score', 60.0) + 15.0
            if score < strict_min:
                msg = f"장 초반 안정화 대기 (지수 BULL 미달, 현재 점수 {score:.1f} < 기준 {strict_min:.1f})"
                logger.info(f"⏳ [{name}] {msg}")
                return False, msg
        
        # [Safety] indicators 초기화 위치를 함수 최상단으로 이동 (UnboundLocalError 방지)
        indicators = {}
        
        detail = self.api.get_naver_stock_detail(code)
        price = safe_cast_float(detail.get('price'))
        rate = safe_cast_float(detail.get('rate'))
            
        if price == 0.0: return False, "실시간 데이터 오류: 시세 0원"
        
        # [CRITICAL] 당일 등락률 하드 필터 (-8.0% ~ +8.0% 범위만 진입 허용 - GEMINI.md 준수)
        if rate > 8.0:
            return False, f"진입 제한: 과열 종목 (+{rate:.1f}%)"
        if rate < -8.0:
            return False, f"진입 제한: 과매도/급락 ({rate:.1f}%)"
            
        news = self.api.get_naver_stock_news(code)
        
        # [개선] 캐시 우선 전략: 캐시 데이터가 있으면 즉시 활용하고, 없으면 실시간 계산하여 분석 품질 보장 (유저 요청 반영)
        ma_fetch_success = False
        try:
            ma_20 = self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0
            if ma_20 == 0:
                logger.info(f"🔍 {name}({code}) 지표 캐시 누락 - 실시간 동기화 중...")
                candles = self.api.get_minute_chart_price(code)
                if candles:
                    indicators = self.indicator_eng.get_all_indicators(candles)
                    ma_20 = indicators.get("sma", {}).get("sma_20", 0.0)
                    if ma_20 > 0 and self.state:
                        with self.state.lock:
                            self.state.ma_20_cache[code] = ma_20
            else:
                # 캐시 데이터가 있으면 indicators 구조에 맞춰 주입
                indicators['sma'] = {'sma_20': ma_20}
            
            # [추가] 이중 타임프레임 MA 분석 및 점수 보정 (품질 유지)
            ma_analysis = self.indicator_eng.get_dual_timeframe_analysis(self.api, code, name=name)
            if ma_analysis:
                indicators['ma_analysis'] = ma_analysis
                sig = ma_analysis.get('signal', 'NEUTRAL')
                ma_fetch_success = True
                # [복기반영 #2] Bear/Defensive 장세에서 분봉 20MA CAUTION(이탈) 종목은 진입 직접 차단
                # Bull/Neutral에서는 기존대로 score 감점만 적용
                vibe_upper = self.current_market_vibe.upper()
                if sig == "CAUTION":
                    if vibe_upper in ["BEAR", "DEFENSIVE"]:
                        logger.info(f"🚫 [MA필터] {name} 분봉20MA 이탈(CAUTION) - {vibe_upper} 장세 진입 차단")
                        return False, f"분봉20MA 이탈 확인 중 진입 차단 ({vibe_upper} 장세)"
                    else:
                        score *= 0.8  # Bull/Neutral: 감점만 적용
                elif sig == "OVERBOUGHT":
                    # [핵심] 모든 장세에서 단기 과열(분봉 20MA 이격도 3% 초과)은 Python 코드에서 직접 차단
                    # → Gemini의 '공격적 페르소나'가 우회하지 못하도록 AI 호출 이전에 하드 리턴
                    logger.info(f"🚫 [MA필터] {name} 단기 과열(OVERBOUGHT) - 상투 추격 매수 차단")
                    return False, "분봉 이평선 단기 과열 구간 진입 차단 (상투 매수 방지)"
                elif sig == "BUY_ZONE":
                    # 최적의 매수 타점 (분봉 20MA 지지선 근접) 시 AI 승인 확률 상향을 위해 가점
                    score += 15.0
                trading_log.log_ai_activity("MA분석", f"[{code}] {name} 매수검토용", "COMPLETED", f"Signal: {sig}")
        except Exception as e:
            trading_log.log_ai_activity("MA분석", f"[{code}] {name} 매수검토실패", "FAIL", str(e)[:30])
            logger.warning(f"지표 수급 및 분석 중 오류 (스킵): {e}")

        # [핵심 보완] MA 지표를 전혀 취득하지 못한 경우 → 과열 여부 불명이므로 score에 패널티 적용
        # 데이터 없이 AI가 OVERBOUGHT를 묵인하는 것을 구조적으로 방지
        if not ma_fetch_success:
            score -= 30.0
            logger.info(f"⚠️ [{name}] MA지표 취득 실패 → score 패널티 -30pt (현재: {score:.1f}pt)")
            # 패널티 후 최소 기준(60점) 미달이면 AI 호출 없이 즉시 거절
            if score < self.ai_config.get('min_score', 60.0):
                return False, f"MA지표 없음 + 점수 미달 ({score:.1f}pt < {self.ai_config.get('min_score', 60.0):.1f}pt) - 데이터 충분 후 재시도"

        phase = self.get_market_phase()
        # [개선] AI 호출 실패 시 자동 재시도 로직 추가 (최대 3회)
        is_confirmed, reason = False, "AI 호출 준비 중"
        for i in range(3):
            try:
                trading_log.log_ai_activity("매수검토", f"[{code}] {name} 컨펌시도", "WAIT", f"Score:{score:.1f}")
                is_confirmed, reason = self.ai_advisor.final_buy_confirm(code, name, self.current_market_vibe, detail, news, indicators=indicators, score=score, phase=phase)
                # 성공적으로 판단을 내렸다면 (승인이든 거절이든) 루프 종료
                if "failed" not in reason.lower():
                    res_tag = "승인" if is_confirmed else "거절"
                    trading_log.log_ai_activity("매수검토", f"[{code}] {name} 최종결과", res_tag, reason[:50])
                    break
                logger.warning(f"⚠️ AI 호출 실패로 재시도 중 ({i+1}/3): {reason}")
            except Exception as e:
                reason = f"AI 호출 중 예외 발생: {e}"
                logger.warning(f"⚠️ {reason} - 재시도 중 ({i+1}/3)")
            time.sleep(1)

        m_id = self.ai_advisor.last_used_advisor.model_id if hasattr(self.ai_advisor, 'last_used_advisor') and self.ai_advisor.last_used_advisor else ""
        
        if not is_confirmed:
            # 1. 데이터 오류(0원 등)나 시스템 실패(All failed)인 경우 rejected_stocks에 넣지 않고 다음 사이클에 재시도하도록 함
            if re.search(r"(?<![0-9])0원", reason) or "가격이 0원" in reason or "failed" in reason.lower():
                return False, f"일시적 판단 보류: {reason}"
            
            # 2. AI가 명확하게 '매수 거절' 의견을 낸 경우에만 24시간 차단 리스트에 추가
            self.rejected_stocks[code] = {"reason": reason, "time": time.time()}
            trading_log.log_rejection(code, name, reason, model_id=m_id)
            self._save_all_states()
            return False, reason
        
        if m_id: self.last_buy_models[code] = m_id
        return True, reason

    def get_replacement_target(self, candidate_code: str, candidate_name: str, score: float, holdings: List[dict]) -> Tuple[bool, Optional[str], str]:
        """포트폴리오 한도 도달 시, 신규 후보 종목과 기존 보유 종목을 비교하여 교체 대상을 선정합니다.

        Args:
            candidate_code (str): 신규 진입 후보 종목 코드.
            candidate_name (str): 후보 종목명.
            score (float): 후보 종목의 퀀트 스코어.
            holdings (List[dict]): 현재 보유 중인 종목 리스트.

        Returns:
            Tuple[bool, Optional[str], str]: (교체 수행 여부, 매도할 종목 코드, 교체 결정 사유).
        """
        if not holdings: return False, None, "보유 종목 없음"
        c_detail = self.api.get_naver_stock_detail(candidate_code)
        c_news = self.api.get_naver_stock_news(candidate_code)
        candidate_info = {"code": candidate_code, "name": candidate_name, "score": score, "detail": str(c_detail), "news": c_news}
        holdings_info = []
        for h in holdings:
            detail = self.api.get_naver_stock_detail(h['pdno'])
            holdings_info.append({"code": h['pdno'], "name": h['prdt_name'], "rt": float(h.get('evlu_pfls_rt', 0)), "detail": str(detail)})
        return self.ai_advisor.compare_stock_superiority(candidate_info, holdings_info, self.current_market_vibe)

    def perform_portfolio_batch_review(self, skip_trade=False, include_manual=False) -> List[str]:
        """보유 중인 모든 종목에 대해 AI 통합 진단(Batch Review)을 수행하고 조치합니다.

        개별 종목별 AI 호출 방식을 탈피하여 전 종목 데이터를 한 번에 AI에게 전달함으로써 
        토큰 비용을 절감하고 포트폴리오 차원의 전략적 의사결정(매도/유지/갱신)을 내립니다.

        조치 내용:
            - SELL: 수익권/손실권 관계없이 AI가 매도를 권고한 경우 즉시 청산.
            - HOLD: 전략 프리셋(ID, TP, SL, 유효시간)을 최신 시황에 맞게 자동 업데이트.

        Args:
            skip_trade (bool, optional): 실제 주문 집행 여부. 기본값 False.
            include_manual (bool, optional): 사용자가 수동 설정한 전략도 AI 관리 대상으로 포함할지 여부.

        Returns:
            List[str]: 배치 리뷰 결과 요약 메시지 리스트.
        """
        holdings = self.api.get_balance()
        if not holdings: return []
        
        trading_log.log_ai_activity("보유분석", f"보유 종목({len(holdings)}개) 배치리뷰", "START")
        results = []
        # 1. AI 진단을 위한 데이터 보강 (뉴스, 상세 지표 등)
        holdings_data = []
        for h in holdings:
            code = h['pdno']
            detail = self.api.get_naver_stock_detail(code)
            news = self.api.get_naver_stock_news(code)
            p_strat = self.preset_strategies.get(code)
            
            # [Fix] 수동으로 설정한 전략은 AI 배치 리뷰(자동 갱신) 대상에서 제외하여 사용자 의도 존중
            # 단, include_manual=True인 경우(사용자가 직접 일괄 진단 요청 시)에는 포함하여 AI 관리 모드로 전환
            if p_strat and p_strat.get('is_manual') and not include_manual:
                logger.info(f"🛡️ 전략 보호: [{h['prdt_name']}] 수동 전략 유지 중 (배치 리뷰 스킵)")
                continue

            # [Fix] AI 진단 시에도 TUI 메인 화면과 동일한 '동적 임계치(Vibe/Phase 보정 포함)'를 전달
            # 기존에는 p_strat의 생데이터(Base)를 전달하여 유저가 보는 화면과 AI의 판단 근거가 불일치하는 문제가 있었음
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
            except Exception as e:
                logger.warning(f"배치리뷰 MA괴리율 분석 실패 ({h['prdt_name']}): {e}")

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
            try:  # [Fix] 종목별 독립 try-except: 한 종목 오류가 전체 배치 루프를 중단시키지 않도록
                name = next((h['name'] for h in holdings_data if h['code'] == code), code)
                action = opinion.get("action", "HOLD").upper()
                reason = opinion.get("reason", "AI 분석 결과")
                
                if action == "SELL":
                    # [추가] 구매 후 최소 관망 시간(20분) 체크 - 수수료 낭비 방지
                    last_buy_t = self.last_buy_times.get(code, 0)
                    holding_sec = time.time() - last_buy_t
                    is_emergency = self.analyzer.is_panic or self.current_market_vibe.upper() == "DEFENSIVE"
                    is_manual = self.last_buy_models.get(code) == "수동"
                    
                    # 수동 매수는 20분 무조건 보호, AI 매수는 긴급 상황이 아닐 때만 20분 보호
                    if last_buy_t > 0 and holding_sec < 1200:
                        if is_manual or not is_emergency:
                            results.append(f"🛡️ 수동 매수 보호(AI자율): {name} ({int(holding_sec/60)}분 경과 - 20분 미만)")
                            continue

                    # [매매 시도 기록] 실제 주문 전 AI의 결정을 먼저 로그에 남김
                    msg = f"🤖 AI 자율 매도 결정: {name}"
                    results.append(msg)
                    trading_log.log_config(f"{msg} | 사유: {reason}")
                    if self.state: self.state.add_trading_log(msg)
                    
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
                                strategy_label = self.get_preset_label(code) or "AI자율"
                                # [통합] log_trade가 TUI 및 JSON 로그를 한 번에 처리
                                trading_log.log_trade("🤖AI자율매도", code, name, curr_price, sell_qty, f"AI 선제적 매도 ({strategy_label}): {reason}", profit=profit, model_id=dm_tag, ma_20=self.state.ma_20_cache.get(code, 0.0) if self.state else 0.0)
                                results.append(trading_log.last_tui_msg)
                                # [Fix] 주문 성공 후 로그·상태저장을 별도 격리: 실패해도 주문 사실은 보존
                                try:
                                    self.record_sell(code, is_full_exit=True)
                                    if not hasattr(self, 'bad_sell_times'): self.bad_sell_times = {}
                                    self.bad_sell_times[code] = {"time": time.time(), "type": "AI매도"}  # 8시간 차단
                                    self._async_update_ma_cache(code)
                                except Exception as log_e:
                                    log_error(f"AI자율매도 로그 기록 오류 [{code}|{name}]: {log_e}")
                            else:
                                # [Fix] 매도 실패 시 TUI + error.log 양쪽에 구체적 사유 기록 (기존: TUI에 사유 누락)
                                fail_reason = res_data if res_data else "응답 없음"
                                log_error(f"AI 매도 주문 실패: [{code}]{name} | 수량: {sell_qty}주 | 사유: {fail_reason}")
                                trading_log.log_config(f"❌ AI 매도 주문 실패: [{code}]{name} | 사유: {fail_reason}")
                                fail_log_msg = f"❌ AI 매도 실패: {name} | 사유: {fail_reason}"
                                results.append(fail_log_msg)
                                if self.state: self.state.add_trading_log(fail_log_msg)
                        else:
                            # [Fix] 보유 종목 조회 실패 시 명시적 사유 로깅 (기존: 무시되어 원인 파악 불가)
                            fail_msg = f"❌ AI 매도 실패: {name} | 사유: 잔고에서 종목 미발견 ({code})"
                            log_error(fail_msg)
                            trading_log.log_config(fail_msg)
                            results.append(fail_msg)
                            if self.state: self.state.add_trading_log(fail_msg)
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
            except Exception as e:
                log_error(f"배치 리뷰 종목 처리 오류 [{code}]: {e}")
        
        trading_log.log_ai_activity("보유분석", f"보유 종목 배치리뷰 완료", "COMPLETED", f"결과:{len(results)}건")
        return results

    def _async_update_ma_cache(self, code: str):
        """매매 직후 또는 분석 과정에서 필요한 이동평균선(MA) 데이터를 백그라운드에서 동기화합니다.

        메인 스레드의 병목을 방지하기 위해 비동기 스레드에서 수행하며, API 지연을 
        고려하여 약간의 대기 시간(2초) 후 데이터를 갱신합니다.

        Args:
            code (str): 업데이트할 종목 코드.
        """
        import threading
        def _task():
            try:
                # [개선] 매수/매도 직후에는 잔고 동기화 시간이 필요할 수 있으므로 약간의 지연 후 실행
                time.sleep(2) 
                candles = self.api.get_minute_chart_price(code)
                if candles:
                    inds = self.indicator_eng.get_all_indicators(candles)
                    sma_20 = inds.get("sma", {}).get("sma_20", 0.0)
                    if sma_20 > 0 and self.state:
                        with self.state.lock:
                            self.state.ma_20_cache[code] = sma_20
                            logger.info(f"📊 [후처리] {code} MA20 캐시 업데이트 완료: {int(sma_20):,}")
            except Exception as e:
                log_error(f"MA 캐시 후처리 동기화 실패 ({code}): {e}")
        
        threading.Thread(target=_task, daemon=True, name=f"MA_Sync_{code}").start()
