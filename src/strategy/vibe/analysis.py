import time
import re
import json
from datetime import datetime
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from src.logger import logger, log_error, trading_log
from src.utils import is_ai_enabled_time

class AnalysisMixin:
    def perform_full_market_analysis(self, retry=True) -> bool:
        """시장 분석을 수행 (수동 호출 및 자동 호출 공용)"""
        was_analyzing = self.is_analyzing
        self.is_analyzing = True
        self.current_action = "시장분석"
        try:
            self.analyzer.update()
            # self.apply_ai_strategy_to_all(None)  <-- 통합 리뷰로 대체됨
            self.last_market_analysis_time = time.time()
            self.is_ready = True
            logger.info("시장 분석 완료 및 전략 적용 성공")
            return True
        except Exception as e:
            log_error(f"시장 분석 실패: {e}")
            self.is_ready = True 
            return False
        finally:
            self.first_analysis_attempted = True
            # 상위에서 이미 플래그를 관리 중인 경우(run_scheduled_analysis 등) 건드리지 않음
            if not was_analyzing:
                self.is_analyzing = False
                self.current_action = "대기중"

    def run_scheduled_analysis(self):
        """백그라운드에서 주기적으로 호출되어 시황 분석, AI 조언 수집, 전략 반영을 일괄 수행"""
        if self.is_analyzing: return
        
        # [추가] AI 토큰 절약을 위한 시간 기반 차단 (디버그 모드 제외)
        if not is_ai_enabled_time() and not getattr(self, "debug_mode", False):
            logger.info("AI 기능을 호출하지 않습니다. (Market closed)")
            return

        self.is_analyzing = True
        try:
            # 1. 시장 시황 분석 (Vibe 결정 등)
            self.perform_full_market_analysis()

            # 1.1 보유 종목 통합 진단 및 자율 매도/전략 갱신 실행 (신규 통합 로직)
            batch_results = self.perform_portfolio_batch_review()
            for res in batch_results:
                logger.info(f"  {res}")
            
            # 2. AI 조언 수집
            self.get_ai_advice()
            
            # 3. AI 전략 파싱 및 전역 설정 반영
            self.parse_and_apply_ai_strategy()
            
            logger.info("✅ 주기적 AI 시황 분석 완료")
        except Exception as e:
            log_error(f"주기적 분석 오류: {e}")
        finally:
            self.is_analyzing = False
            self.current_action = "대기중"

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
                # 기존 RSI/BB/MACD 지표 수집
                candles = self.api.get_minute_chart_price(r['code'])
                if candles: 
                    candidate_indicators[r['code']] = self.indicator_eng.get_all_indicators(candles)
                
                # [추가] 일봉+분봉 이중 MA 분석 수집
                ma_analysis = self.indicator_eng.get_dual_timeframe_analysis(self.api, r['code'])
                if r['code'] not in candidate_indicators: candidate_indicators[r['code']] = {}
                candidate_indicators[r['code']]['ma_analysis'] = ma_analysis
            except Exception as e:
                log_error(f"지표 분석 수집 오류 ({r['code']}): {e}")

        for h in holdings:
            code = h['pdno']
            p_strat = self.preset_strategies.get(code)
            if p_strat:
                h['tp'], h['sl'] = p_strat.get('tp', 0.0), p_strat.get('sl', 0.0)
            else:
                h['tp'], h['sl'], _ = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_briefing = executor.submit(self.ai_advisor.get_advice, self.analyzer.current_data, self.analyzer.kr_vibe, holdings, current_cfg, self.ai_recommendations, indicators=candidate_indicators)
            future_detailed = executor.submit(self.ai_advisor.get_detailed_report_advice, self.ai_recommendations, self.analyzer.kr_vibe, progress_cb=progress_cb)
            future_holdings = executor.submit(self.ai_advisor.get_holdings_report_advice, holdings, self.analyzer.kr_vibe, self.analyzer.current_data, progress_cb=progress_cb) if holdings else None
            
            new_briefing = future_briefing.result()
            if new_briefing:
                self.ai_briefing = new_briefing
            else:
                log_error("AI 시황 브리핑 수집 실패 (기존 데이터 유지)")

            new_detailed = future_detailed.result()
            if new_detailed: self.ai_detailed_opinion = new_detailed

            if future_holdings:
                new_holdings = future_holdings.result()
                if new_holdings:
                    self.ai_holdings_opinion = new_holdings
                    self.ai_holdings_update_time = time.time()
        return self.ai_briefing

    def refresh_holdings_opinion(self, progress_cb: Optional[Callable] = None):
        """보유 종목의 AI 진단 의견만 실시간으로 갱신 ( interaction.py 'R' 연동 )"""
        holdings = self.api.get_balance()
        if not holdings:
            self.ai_holdings_opinion = "보유 중인 종목이 없습니다."
            self.ai_holdings_update_time = time.time()
            return

        for h in holdings:
            code = h['pdno']
            p_strat = self.preset_strategies.get(code)
            if p_strat:
                h['tp'], h['sl'] = p_strat.get('tp', 0.0), p_strat.get('sl', 0.0)
            else:
                h['tp'], h['sl'], _ = self.get_dynamic_thresholds(code, self.analyzer.kr_vibe)

        res = self.ai_advisor.get_holdings_report_advice(holdings, self.analyzer.kr_vibe, self.analyzer.current_data, progress_cb=progress_cb)
        if res:
            self.ai_holdings_opinion = res
            self.ai_holdings_update_time = time.time()

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

            # AI가 제안한 수치를 시스템의 '기본 안전값(Base)'으로 직접 설정합니다.
            # (이전처럼 Vibe를 역산해서 Base를 0.1% 등 비정상적으로 낮추는 로직 폐기)
            self.exit_mgr.base_tp = target_tp
            self.exit_mgr.base_sl = target_sl
            
            # 물타기/불타기는 역산 없이 절대치로 설정 (엔진 내부에서 TP와 충돌 방지 로직 작동)
            self.recovery_eng.config.update({
                "min_loss_to_buy": target_trig_bear, 
                "average_down_amount": new_amt, 
                "max_investment_per_stock": int(new_amt * 5)
            })
            self.bull_config.update({
                "min_profit_to_pyramid": target_trig_bull, 
                "average_down_amount": new_amt, 
                "max_investment_per_stock": int(new_amt * 5)
            })
            
            trading_log.log_config(f"AI 전략 자동 반영: TP +{target_tp}%, SL {target_sl}%, 물타기 {target_trig_bear}%, 불타기 +{target_trig_bull}%, 금액 {new_amt:,}원")
            self._save_all_states()
            return True
        except Exception as e:
            log_error(f"AI 전략 파싱 에러: {e}")
            return False
