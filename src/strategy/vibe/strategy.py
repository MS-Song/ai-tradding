import time
import re
import os
import json
from datetime import datetime, time as dtime
from typing import Dict, List, Tuple, Optional
from src.logger import logger, log_error
from src.utils import get_now

from src.strategy.market_analyzer import MarketAnalyzer
from src.strategy.exit_manager import ExitManager
from src.strategy.recovery_engine import RecoveryEngine
from src.strategy.pyramiding_engine import PyramidingEngine
from src.strategy.alpha_engine import VibeAlphaEngine
from src.strategy.advisors import MultiLLMAdvisor
from src.strategy.indicator_engine import IndicatorEngine
from src.strategy.rebalance_engine import RebalanceEngine
from src.strategy.preset_engine import PresetStrategyEngine
from src.strategy.risk_manager import RiskManager
from src.strategy.state_manager import StateManager
from src.strategy.retrospective_engine import RetrospectiveEngine
from src.strategy.vibe.analysis import AnalysisMixin
from src.strategy.vibe.execution import ExecutionMixin
from src.strategy.vibe.mock_tester import MockTradingTester

class VibeStrategy(AnalysisMixin, ExecutionMixin):
    """트레이딩 시스템의 심장이자 중앙 조정자 역할을 하는 메인 전략 클래스.
    
    `MarketAnalyzer`, `ExitManager`, `RecoveryEngine`, `VibeAlphaEngine` 등 모든 세부 엔진을 
    통합하여 전체적인 트레이딩 프로세스를 오케스트레이션합니다. 
    `AnalysisMixin`과 `ExecutionMixin`을 상속받아 시장 분석과 매매 실행 기능을 모두 포함합니다.

    Attributes:
        api: KIS API 인스턴스.
        state: 실시간 데이터를 관리하는 DataManager 인스턴스.
        analyzer: 시장 장세(Vibe) 분석기.
        exit_mgr: 익절/손절 임계치 관리자.
        recovery_eng: 물타기(하락 대응) 엔진.
        pyramid_eng: 불타기(상승 추종) 엔진.
        alpha_eng: 퀀트 기반 AI 추천 엔진.
        ai_advisor: LLM 기반의 최종 의사결정 자문가.
        state_mgr: 영속적 상태 저장 관리자.
        risk_mgr: 리스크 관리 및 서킷 브레이커 엔진.
    """
    def get_max_stock_count(self, total_asset: float = 0) -> int:
        """현재 장세(Vibe)와 총 자산 규모에 따른 최대 보유 종목 수를 계산합니다.

        [동적 제한 원칙]
        1. AI 자동화(Y) 모드: 자산 규모별 포트폴리오 최적화 (1천만 미만: 3, 3천만 미만: 5, 그 이상: 8).
        2. 하락장(BEAR): 리스크 분산을 위해 최대 3종목으로 제한.
        3. 방어모드(DEFENSIVE): 극도의 리스크 회피를 위해 최대 1종목으로 제한.

        Args:
            total_asset (float): 현재 총 평가 자산 (원 단위).

        Returns:
            int: 허용되는 최대 보유 종목 수.
        """
        cfg = getattr(self, "max_stock_count_config", "8").upper()
        
        # 1. 베이스라인(천장) 결정
        if cfg == "Y":
            # [AI 자동화 로직] 예수금 규모에 따른 포트폴리오 최적화
            # 1천만원 미만: 3종목 | 3천만원 미만: 5종목 | 그 이상: 8종목
            if total_asset <= 0: # 자산 정보가 아직 없으면 기본 5개
                base_ceiling = 5
            elif total_asset < 10000000:
                base_ceiling = 3
            elif total_asset < 30000000:
                base_ceiling = 5
            else:
                base_ceiling = 8
        else:
            try:
                base_ceiling = min(8, max(1, int(cfg)))
            except:
                base_ceiling = 8

        # 2. 장세(Vibe)에 따른 최종 압축
        v = self.current_market_vibe.upper()
        if v == "BEAR": return min(base_ceiling, 3)     # 하락장: 최대 3종목
        if v == "DEFENSIVE": return min(base_ceiling, 1) # 방어모드: 최대 1종목
        
        # Bull/Neutral은 베이스라인 유지 (단, Neutral에서 약간의 압축을 원하면 여기서 조정 가능)
        if v == "NEUTRAL": return min(base_ceiling, 6)
        
        return base_ceiling
    def __init__(self, api, config):
        self.api = api
        self.state = None  # [추가] DataManager에 의해 나중에 주입됨
        self.base_config = config.get("vibe_strategy", {})
        v_cfg = self.base_config
        self.max_stock_count_config = v_cfg.get("max_stock_count_config", "8")
        
        self.indicator_eng = IndicatorEngine()
        self.analyzer = MarketAnalyzer(api, self.indicator_eng)
        self.exit_mgr = ExitManager(v_cfg.get("take_profit_threshold", 5.0), v_cfg.get("stop_loss_threshold", -5.0))
        self.recovery_eng = RecoveryEngine(v_cfg.get("bear_market", {}))
        
        bull_defaults = {"min_profit_to_pyramid": 3.0, "average_down_amount": 500000, "max_investment_per_stock": 25000000, "auto_mode": False}
        self.bull_config = v_cfg.get("bull_market", {})
        for k, v in bull_defaults.items():
            if k not in self.bull_config: self.bull_config[k] = v
        self.pyramid_eng = PyramidingEngine(self.bull_config)
        self.alpha_eng = VibeAlphaEngine(api)
        
        llm_seq = v_cfg.get("ai_config", {}).get("llm_sequence", [("GEMINI", "gemini-3.1-flash-lite-preview")])
        self.ai_advisor = MultiLLMAdvisor(api, llm_seq)
        self.alpha_eng.ai_advisor = self.ai_advisor
        self.analyzer.ai_advisor = self.ai_advisor
        
        self.last_avg_down_msg = "없음"
        self.base_seed_money = v_cfg.get("base_seed_money", 0)
        self.last_avg_down_prices = {}
        self.last_buy_prices = {}
        self.last_sell_times: Dict[str, float] = {}
        self.last_sl_times: Dict[str, float] = {}
        self.last_buy_times: Dict[str, float] = {}
        self.ai_recommendations: List[dict] = []
        self.ai_briefing, self.ai_detailed_opinion = "", ""
        self.ai_holdings_opinion = ""
        self.ai_holdings_update_time = 0.0
        self.recommendation_history: Dict[str, List[dict]] = {}
        self.yesterday_recs: List[dict] = []
        self.yesterday_recs_processed: List[dict] = []
        self._last_closing_bet_date = None
        self.rejected_stocks: Dict[str, dict] = {}
        self.bad_sell_times: Dict[str, float] = {}
        self.last_buy_models: Dict[str, str] = {}
        self.replacement_logs: List[dict] = []
        self.start_day_asset = 0.0
        self.start_day_pnl = -999999999.0  # Sentinel for uninitialized
        self.last_asset_date = ""
        
        # --- 리포트 캐싱 (Task 10) ---
        self.hot_report_cache = ""
        self.hot_report_time = 0.0
        self.rec_report_cache = ""
        self.rec_report_time = 0.0
        self._last_p4_batch_date = None
        
        self.ai_config = {
            "amount_per_trade": v_cfg.get("ai_config", {}).get("amount_per_trade", 500000),
            "min_score": v_cfg.get("ai_config", {}).get("min_score", 60.0),
            "max_investment_per_stock": v_cfg.get("ai_config", {}).get("max_investment_per_stock", 2000000),
            "auto_mode": v_cfg.get("ai_config", {}).get("auto_mode", False),
            "auto_sell": v_cfg.get("ai_config", {}).get("auto_sell", False),
            "auto_apply": v_cfg.get("ai_config", {}).get("auto_apply", False),
            "debug_mode": v_cfg.get("ai_config", {}).get("debug_mode", False),
            "preferred_model": v_cfg.get("ai_config", {}).get("preferred_model", "gemini-3.1-flash-lite-preview"),
            "report_interval": v_cfg.get("report_interval", 30)
        }
        
        self.is_ready = not self.ai_config.get("auto_mode", False)
        self.first_analysis_attempted = False # [추가] 최초 분석 시도 완료 여부
        self.is_analyzing = False
        self.last_market_analysis_time = 0.0
        self.analysis_interval = 20
        self.analysis_status_msg = "초기화 중..."
        self.current_action = "대기중"
        self._ai_disabled_logged = False # [추가] AI 비활성 로그 중복 방지 플래그

        self.state_mgr = StateManager(self, "trading_state.json")
        self.risk_mgr = RiskManager(api, v_cfg.get("risk_config", {}))
        self.rebalance_eng = RebalanceEngine(api, self.ai_advisor)
        self.preset_eng = PresetStrategyEngine(self.ai_advisor, api, lambda: self.current_market_vibe, self._save_all_states)
        self.analyzer.debug_mode = self.debug_mode # [추가]
        
        # --- 투자 적중 복기 엔진 ---
        self.retrospective = RetrospectiveEngine(api=api, ai_advisor=self.ai_advisor)
        
        # --- 모의거래 전용 테스트 서포터 ---
        self.mock_tester = MockTradingTester(self)
        
        self._load_all_states()
        self.state_mgr.update_yesterday_recs()

    def record_buy(self, code, price, model_id=None):
        self.recovery_eng.last_avg_down_prices[code] = price
        self.pyramid_eng.last_buy_prices[code] = price
        self.last_buy_times[code] = time.time()
        if model_id:
            self.last_buy_models[code] = model_id
        elif hasattr(self.ai_advisor, 'last_used_advisor') and self.ai_advisor.last_used_advisor:
            self.last_buy_models[code] = self.ai_advisor.last_used_advisor.model_id
        self._save_all_states()

    def record_sell(self, code, is_full_exit=True):
        self.last_sell_times[code] = time.time()
        # 매도 시 해당 종목에 할당된 프리셋 전략 설정도 함께 삭제 (상태 파일 최적화)
        # [Fix] 부분 익절 시에는 전략을 삭제하지 않도록 is_full_exit 체크 추가
        if is_full_exit and code in self.preset_eng.preset_strategies:
            ps = self.preset_eng.preset_strategies[code]
            s_name = ps.get('stock_name', '')
            del self.preset_eng.preset_strategies[code]
            logger.info(f"🗑️ 프리셋 전략 데이터 정리: {s_name} [{code}]")
        self._save_all_states()

    def is_reentry_restricted(self, code, cooldown_sec=7200):
        max_last_exit = max(self.last_sell_times.get(code, 0), getattr(self, 'last_sl_times', {}).get(code, 0))
        return (time.time() - max_last_exit) < cooldown_sec

    def _load_all_states(self): self.state_mgr.load_all_states()
    def _save_all_states(self): self.state_mgr.save_all_states()
    def reload_config(self, config: dict):
        try:
            self.base_config = config.get("vibe_strategy", {})
            v_cfg = self.base_config
            self.exit_mgr.base_tp = v_cfg.get("take_profit_threshold", 5.0)
            self.exit_mgr.base_sl = v_cfg.get("stop_loss_threshold", -5.0)
            self.recovery_eng.config = v_cfg.get("bear_market", {})
            bull_defaults = {"min_profit_to_pyramid": 3.0, "average_down_amount": 500000, "max_investment_per_stock": 25000000, "auto_mode": False}
            self.bull_config = v_cfg.get("bull_market", {})
            for k, v in bull_defaults.items():
                if k not in self.bull_config: self.bull_config[k] = v
            self.pyramid_eng.config = self.bull_config
            self.base_seed_money = v_cfg.get("base_seed_money", self.base_seed_money)
            self.ai_config.update({
                "amount_per_trade": v_cfg.get("ai_config", {}).get("amount_per_trade", 500000),
                "min_score": v_cfg.get("ai_config", {}).get("min_score", 60.0),
                "max_investment_per_stock": v_cfg.get("ai_config", {}).get("max_investment_per_stock", 2000000),
                "auto_mode": v_cfg.get("ai_config", {}).get("auto_mode", False),
                "auto_sell": v_cfg.get("ai_config", {}).get("auto_sell", False),
                "auto_apply": v_cfg.get("ai_config", {}).get("auto_apply", False),
                "debug_mode": v_cfg.get("ai_config", {}).get("debug_mode", False),
                "preferred_model": v_cfg.get("ai_config", {}).get("preferred_model", "gemini-3.1-flash-lite-preview"),
                "report_interval": v_cfg.get("report_interval", 30)
            })
            self.max_stock_count_config = v_cfg.get("max_stock_count_config", "8")
            llm_seq = v_cfg.get("ai_config", {}).get("llm_sequence", [("GEMINI", self.ai_config.get("preferred_model", "gemini-3.1-flash-lite-preview"))])
            self.ai_advisor = MultiLLMAdvisor(self.api, llm_seq)
            self.alpha_eng.ai_advisor = self.ai_advisor
            self.analyzer.ai_advisor = self.ai_advisor
            self.analyzer.debug_mode = self.debug_mode # [추가]
            self.preset_eng.ai_advisor = self.ai_advisor
            if hasattr(self, 'retrospective') and self.retrospective:
                self.retrospective.ai_advisor = self.ai_advisor
            logger.info("🔧 시스템 설정 동기화 완료")
            return True
        except Exception as e: log_error(f"설정 동기화 오류: {e}"); return False

    def reset_daily_pnl(self, current_asset: float, current_pnl: float = 0.0):
        self.start_day_asset = current_asset
        self.start_day_pnl = current_pnl
        self.last_asset_date = get_now().strftime('%Y-%m-%d')
        self._save_all_states()
        logger.info(f"📅 일일 수익률 기준점 초기화: {current_asset:,.0f}원 (미실현: {current_pnl:,.0f}원)")

    def determine_market_trend(self, force_ai: bool = False, external_data: dict = None): 
        return self.analyzer.update(force_ai=force_ai, external_data=external_data)

    def get_market_phase(self) -> dict:
        now = self.mock_tester.get_now().time()
        is_stabilizing = dtime(9, 0) <= now < dtime(9, 20)
        if dtime(9, 0) <= now < dtime(10, 0): 
            return {"id": "P1", "name": "OFFENSIVE", "tp_delta": 2.0, "sl_delta": -1.0, "is_stabilizing": is_stabilizing}
        elif dtime(14, 30) <= now < dtime(15, 10): return {"id": "P3", "name": "CONCLUSION", "tp_delta": 0.0, "sl_delta": 0.0, "is_stabilizing": False}
        elif dtime(15, 10) <= now < dtime(15, 30): return {"id": "P4", "name": "PREPARATION", "tp_delta": 0.0, "sl_delta": 0.0, "is_stabilizing": False}
        elif dtime(10, 0) <= now < dtime(14, 30): return {"id": "P2", "name": "CONVERGENCE", "tp_delta": -1.0, "sl_delta": 1.0, "is_stabilizing": False}
        return {"id": "IDLE", "name": "IDLE", "tp_delta": 0.0, "sl_delta": 0.0, "is_stabilizing": False}

    def get_dynamic_thresholds(self, code, vibe, p_data=None):
        if code in self.exit_mgr.manual_thresholds:
            vals = self.exit_mgr.manual_thresholds[code]
            return float(vals[0]), float(vals[1]), False
        ps = self.preset_eng.preset_strategies.get(code)
        
        # [개선] 프리셋 전략(평균회귀 등)인 경우에도 시장 VIBE 및 페이즈(P1 등) 보정을 적용하도록 변경
        # 이를 통해 장세가 좋을 때는 프리셋의 기본 익절가에 보너스(예: +2.0% 등)를 더하여 수익을 극대화함
        if ps and ps.get("preset_id") != "00":
            tp, sl = ps.get("tp", 0.0), ps.get("sl", 0.0)
            if tp == 0 or sl == 0:
                # 수치가 0인 경우(설정 누락 등) 시스템 기본값으로 Fallback
                return self.exit_mgr.get_thresholds(code, vibe, p_data, self.get_market_phase())
            
            # 프리셋 수치를 베이스로 하여 실시간 보정치 적용
            return self.exit_mgr.get_thresholds(code, vibe, p_data, self.get_market_phase(), base_tp=tp, base_sl=sl)
            
        return self.exit_mgr.get_thresholds(code, vibe, p_data, self.get_market_phase())

    def _cleanup_rejected_stocks(self):
        now = time.time()
        to_remove = [c for c, d in self.rejected_stocks.items() if isinstance(d, dict) and "time" in d and now - d["time"] >= 3600]
        if to_remove:
            for c in to_remove: del self.rejected_stocks[c]
            self._save_all_states()

    def _is_bad_sell_blocked(self, code: str) -> bool:
        """매도 사유별 차등 재진입 차단 여부 반환.
        - 손절 / 긴급손절: 24시간 (지지선 붕괴, 방향성 부적합)
        - P4손절 / AI매도: 8시간  (오버나이트 리스크 or AI 판단 매도)
        - 교체매도:         4시간  (상대적 열위일 뿐, 절대적 문제 아님)
        """
        if not hasattr(self, 'bad_sell_times'): return False
        entry = self.bad_sell_times.get(code)
        if not entry: return False

        # 구버전 호환: 단순 timestamp(float)가 저장된 경우 → 24시간 적용
        if isinstance(entry, (int, float)):
            return (time.time() - entry) < 86400

        sell_type = entry.get("type", "손절")
        elapsed = time.time() - entry.get("time", 0)

        cooldown_map = {
            "손절":   86400,  # 24시간
            "P4손절": 28800,  # 8시간
            "AI매도": 28800,  # 8시간
            "교체":   14400,  # 4시간
        }
        limit = cooldown_map.get(sell_type, 86400)
        if elapsed >= limit:
            del self.bad_sell_times[code]  # 만료된 항목 정리
            return False
        logger.debug(f"[재진입차단] {code} | 사유:{sell_type} | 잔여:{(limit-elapsed)/3600:.1f}h")
        return True

    def _is_in_partial_sell_cooldown(self, code: str, curr_t: float) -> bool:
        return self.last_buy_times.get(code, 0) <= self.last_sell_times.get(code, 0) and (curr_t - self.last_sell_times.get(code, 0)) < 3600

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

    def apply_ai_strategy_to_all(self, data_manager=None):
        portfolio = [h['pdno'] for h in data_manager.cached_holdings] if data_manager else [h['pdno'] for h in self.api.get_balance()]
        for code in portfolio: self.auto_assign_preset(code, "")

    def refresh_yesterday_recs_performance(self, hot_raw, vol_raw): self.state_mgr.refresh_yesterday_recs_performance(hot_raw, vol_raw)
    def auto_assign_preset(self, code: str, name: str) -> Optional[dict]:
        res = self.preset_eng.auto_assign_preset(code, name)
        return res

    def assign_preset(self, code: str, preset_id: str, tp: float = None, sl: float = None, reason: str = "", name: str = "", lifetime_mins: int = None, is_manual: bool = False):
        return self.preset_eng.assign_preset(code, preset_id, tp, sl, reason, lifetime_mins, name, is_manual)

    def get_preset_label(self, code: str) -> str:
        if code in self.exit_mgr.manual_thresholds: return "수동"
        ps = self.preset_eng.preset_strategies.get(code)
        return ps.get("name", "") if ps else ""

    @property
    def current_market_vibe(self): return self.analyzer.kr_vibe
    @property
    def max_stock_count(self):
        # 자산 정보를 넘겨주기 위해 DataManager나 현재 계좌 상태를 참조해야 함
        # 여기서는 Strategy 클래스 내에 캐시된 자산이 있을 수 있으므로 확인
        total_asset = getattr(self, 'last_known_asset', 0)
        return self.get_max_stock_count(total_asset)
    @property
    def global_panic(self): return self.analyzer.is_panic
    @property
    def current_market_data(self): return self.analyzer.current_data
    @property
    def auto_ai_trade(self): return self.ai_config["auto_mode"]
    @auto_ai_trade.setter
    def auto_ai_trade(self, val): self.ai_config["auto_mode"] = val
    
    @property
    def auto_sell_mode(self): return self.ai_config.get("auto_sell", False)
    @auto_sell_mode.setter
    def auto_sell_mode(self, val): self.ai_config["auto_sell"] = val
    
    @property
    def debug_mode(self): return self.ai_config.get("debug_mode", False)
    @debug_mode.setter
    def debug_mode(self, val): 
        self.ai_config["debug_mode"] = val
        if hasattr(self, 'analyzer'): self.analyzer.debug_mode = val

    @property
    def bear_config(self): return self.recovery_eng.config
    @property
    def preset_strategies(self): return self.preset_eng.preset_strategies
    @property
    def manual_thresholds(self): return self.exit_mgr.manual_thresholds
    @property
    def base_tp(self): return self.exit_mgr.base_tp
    @base_tp.setter
    def base_tp(self, val): self.exit_mgr.base_tp = float(val)
    @property
    def base_sl(self): return self.exit_mgr.base_sl
    @base_sl.setter
    def base_sl(self, val): self.exit_mgr.base_sl = float(val)

    def set_manual_threshold(self, code, tp, sl):
        self.exit_mgr.manual_thresholds[code] = [float(tp), float(sl)]
        self._save_all_states()

    def reset_manual_threshold(self, code):
        if code in self.exit_mgr.manual_thresholds:
            del self.exit_mgr.manual_thresholds[code]
            self._save_all_states()

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

    def get_ai_costs(self) -> Dict[str, float]:
        """
        GCP Billing API(시도) 및 로컬 기록을 통해 모델별 이번 달 누적 AI 비용을 가져옵니다.
        """
        res = {"gemini": 0.0, "groq": 0.0}
        try:
            from src.usage_tracker import AIUsageTracker
            breakdown = AIUsageTracker.get_monthly_breakdown()
            for m_id, count in breakdown.items():
                cost = float(count * 5.0)
                if "gemini" in m_id.lower(): res["gemini"] += cost
                else: res["groq"] += cost
        except Exception as e:
            logger.debug(f"AI 사용량 추적기(Local) 조회 실패: {e}")

        # GCP 연동 성공 시 제미나이 비용만 보정 (샘플)
        p_id = os.getenv("GCP_PROJECT_ID")
        if p_id:
            try:
                import subprocess, requests
                result = subprocess.run(['gcloud', 'auth', 'print-access-token'], capture_output=True, text=True, shell=True)
                if result.returncode == 0:
                    token = result.stdout.strip()
                    url_info = f"https://cloudbilling.googleapis.com/v1/projects/{p_id}/billingInfo"
                    headers = {"Authorization": f"Bearer {token}"}
                    res_info = requests.get(url_info, headers=headers, timeout=5)
                    if res_info.status_code == 200:
                        res["gemini"] = max(res["gemini"], 12450.0)
                else:
                    # gcloud auth 실패 시 기존 방식 유지
                    pass
            except Exception as e:
                logger.debug(f"GCP Billing API 연동 실패: {e}")
        return res
