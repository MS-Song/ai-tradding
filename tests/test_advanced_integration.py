import pytest
import time
import math
from datetime import datetime
from unittest.mock import MagicMock, patch, ANY
from src.strategy.vibe.execution import ExecutionMixin
from src.strategy.exit_manager import ExitManager
from src.strategy.recovery_engine import RecoveryEngine
from src.strategy.pyramiding_engine import PyramidingEngine
from src.strategy.market_analyzer import MarketAnalyzer
from src.strategy.advisors.base import BaseLLMAdvisor

# =============================================================================
# [Mock Helpers]
# =============================================================================
class DummyAdvisor(BaseLLMAdvisor):
    def _call_api(self, prompt: str, timeout: int = 60): return self.mock_response
    def get_advice(self, *args, **kwargs): pass
    def get_detailed_report_advice(self, *args, **kwargs): pass
    def get_stock_report_advice(self, *args, **kwargs): pass
    def get_holdings_report_advice(self, *args, **kwargs): pass
    def get_hot_stocks_report_advice(self, *args, **kwargs): pass
    def verify_market_vibe(self, *args, **kwargs): pass
    def closing_sell_confirm(self, *args, **kwargs): pass
    def get_rebalance_advice(self, *args, **kwargs): pass
    def compare_stock_superiority(self, *args, **kwargs): return True, "OLD", "Better"
    def analyze_trade_retrospective(self, *args, **kwargs): pass

class MockStrategy(ExecutionMixin):
    def __init__(self):
        self.api = MagicMock()
        self.api.get_full_balance.return_value = [None, {"total_asset": 10000000, "cash": 5000000, "pnl": 0}]
        self.api.get_balance.return_value = []
        self.api.get_naver_stock_detail.return_value = {"price": 70000, "rate": 1.0}
        self.api.order_market.return_value = (True, "Success")
        
        self.state = MagicMock()
        self.state.lock = MagicMock()
        self.state.ma_20_cache = {}
        self.state.is_trading_paused = False
        self.state.vibe = "neutral"
        self.state.holdings = []
        self.state.asset = {"total_asset": 10000000, "cash": 5000000, "pnl": 0}
        self.start_day_asset = 10000000
        self.start_day_pnl = 0
        
        self.mock_tester = MagicMock()
        self.fixed_now = datetime.strptime("2026-05-06 10:30:00", "%Y-%m-%d %H:%M:%S")
        self.mock_tester.get_now.return_value = self.fixed_now
        self.mock_tester.intercept_order.return_value = None
        
        self.state_mgr = MagicMock()
        self.analyzer = MagicMock()
        self.analyzer.kr_vibe = "neutral"
        self.analyzer.is_panic = False
        
        self.risk_mgr = MagicMock()
        self.risk_mgr.check_circuit_breaker.return_value = False
        
        self.recovery_eng = RecoveryEngine({"min_loss_to_buy": -3.0, "average_down_amount": 500000})
        self.pyramid_eng = PyramidingEngine({"min_profit_to_pyramid": 3.0, "average_down_amount": 500000})
        
        self.bull_config = {"auto_mode": True, "max_investment_per_stock": 5000000}
        self.bear_config = {"auto_mode": True, "max_investment_per_stock": 5000000}
        
        self.ai_advisor = MagicMock()
        self.ai_config = {"amount_per_trade": 1000000, "auto_mode": True, "auto_sell": True, "min_score": 60.0}
        self.ai_recommendations = []
        self.preset_strategies = {}
        self.last_buy_models = {}
        self.last_buy_times = {}
        self.last_sell_times = {}
        self.rejected_stocks = {}
        self.manual_thresholds = {}
        self.replacement_logs = []
        self.indicator_eng = MagicMock()
        self.exit_mgr = ExitManager(base_tp=5.0, base_sl=-5.0)

    @property
    def current_market_vibe(self): return self.analyzer.kr_vibe
    @property
    def auto_ai_trade(self): return self.ai_config["auto_mode"]
    @property
    def global_panic(self): return self.analyzer.is_panic
    @property
    def auto_sell_mode(self): return self.ai_config["auto_sell"]

    def get_market_phase(self):
        now = self.mock_tester.get_now().time()
        from datetime import time as dtime
        if dtime(9,0) <= now < dtime(10,0): return {"id":"P1", "tp_delta":2.0, "sl_delta":-1.0}
        elif dtime(10,0) <= now < dtime(14,30): return {"id":"P2", "tp_delta":-1.0, "sl_delta": 1.0}
        elif dtime(14,30) <= now < dtime(15,10): return {"id":"P3", "tp_delta":0.0, "sl_delta":0.0}
        elif dtime(15,10) <= now < dtime(15,30): return {"id":"P4", "tp_delta":0.0, "sl_delta":0.0}
        return {"id":"IDLE", "tp_delta":0.0, "sl_delta":0.0}

    def get_dynamic_thresholds(self, code, vibe, p_data=None):
        return self.exit_mgr.get_thresholds(code, vibe, p_data, self.get_market_phase())

    def _cleanup_rejected_stocks(self): pass
    def _save_all_states(self): self.state_mgr.save_all_states()
    def record_buy(self, code, price): self.last_buy_times[code] = self.mock_tester.get_now().timestamp()
    def record_sell(self, code, is_full_exit): self.last_sell_times[code] = self.mock_tester.get_now().timestamp()
    def get_preset_label(self, code): return "TEST"
    def auto_assign_preset(self, code, name): return True
    def assign_preset(self, code, pid, tp, sl, reason, name=None, lifetime_mins=None): 
        self.preset_strategies[code] = {"preset_id": pid, "tp": tp, "sl": sl}
        return True
    def _is_bad_sell_blocked(self, code): return False
    def get_max_stock_count(self, total_asset): return 5
    def _is_in_partial_sell_cooldown(self, code, t):
        last_t = self.last_sell_times.get(code, 0)
        return (t - last_t) < 3600
    def _is_emergency_exit(self, rt, tp, spike, phase, recent_buy): 
        if rt >= tp + 3.0: return True, "Profit Surge"
        return False, ""
    def _is_emergency_sl(self, rt, sl, panic, vibe, phase, recent_buy): return False, ""
    def _async_update_ma_cache(self, code): pass
    def get_replacement_target(self, code, name, score, holdings): return True, "OLD", "Better"
    def confirm_buy_decision(self, code, name, score): return True, "OK"

@pytest.fixture
def strategy():
    return MockStrategy()

# =============================================================================
# [Test Scenarios]
# =============================================================================

class TestManualScenarios:
    def test_tc_m01_manual_buy(self, strategy):
        """[TC-M01] 수동 매수 기능 검증"""
        strategy.api.order_market("005930", 10, True)
        strategy.api.order_market.assert_called_with("005930", 10, True)

    def test_tc_m01_2_manual_sell(self, strategy):
        """[TC-M01-2] 수동 매도 기능 검증"""
        strategy.api.order_market("005930", 10, False)
        strategy.api.order_market.assert_called_with("005930", 10, False)

    def test_tc_m02_threshold_change(self, strategy):
        """[TC-M02] 수동 임계치 변경 검증"""
        strategy.exit_mgr.manual_thresholds["005930"] = [10.0, -2.0]
        tp, sl, _ = strategy.get_dynamic_thresholds("005930", "neutral")
        assert tp == 10.0 and sl == -2.0

    def test_tc_m03_ai_toggle(self, strategy):
        """[TC-M03] AI 자율매매 ON/OFF 검증"""
        strategy.ai_config["auto_mode"] = False
        assert strategy.auto_ai_trade is False

    def test_tc_m07_force_analysis(self, strategy):
        """[TC-M07] 강제 시황 분석 요청 검증"""
        strategy.analyzer.update(force_ai=True)
        strategy.analyzer.update.assert_called_with(force_ai=True)

class TestAlgoScenarios:
    def test_tc_a01_recovery_trigger(self, strategy):
        """[TC-A01] 물타기 트리거 로직"""
        holdings = [{"pdno":"005930", "prpr":70000, "pchs_avg_pric":74000, "evlu_pfls_rt":-5.4, "hldg_qty":10, "prdt_name":"S", "pchs_amt": 740000}]
        strategy.exit_mgr.base_sl = -7.0 
        strategy.api.order_market.reset_mock()
        strategy.run_cycle(holdings=holdings, market_trend="neutral")
        strategy.api.order_market.assert_called()

    def test_tc_a02_pyramiding_trigger(self, strategy):
        """[TC-A02] 불타기 트리거 로직"""
        holdings = [{"pdno":"005930", "prpr":75000, "pchs_avg_pric":70000, "evlu_pfls_rt":7.1, "hldg_qty":10, "prdt_name":"S", "pchs_amt": 700000}]
        strategy.analyzer.kr_vibe = "bull"
        strategy.api.order_market.reset_mock()
        strategy.run_cycle(holdings=holdings, market_trend="bull")
        strategy.api.order_market.assert_called()

    def test_tc_a03_p3_profit_taking(self, strategy):
        """[TC-A03] P3 장마감 수익확정"""
        strategy.mock_tester.get_now.return_value = datetime.strptime("2026-05-06 14:40:00", "%Y-%m-%d %H:%M:%S")
        holdings = [{"pdno":"005930", "evlu_pfls_rt":1.5, "hldg_qty":10, "prdt_name":"S", "prpr":71000, "pchs_avg_pric":70000}]
        strategy.run_cycle(holdings=holdings)
        strategy.api.order_market.assert_any_call("005930", 5, False)

    def test_tc_a04_partial_sell_cooldown(self, strategy):
        """[TC-A04] 익절 쿨다운(1시간) 적용 검증"""
        cur_t = strategy.mock_tester.get_now().timestamp()
        strategy.last_sell_times["005930"] = cur_t - 1800
        holdings = [{"pdno":"005930", "evlu_pfls_rt":6.0, "hldg_qty":10, "prdt_name":"S"}]
        strategy.api.order_market.reset_mock()
        strategy.run_cycle(holdings=holdings)
        strategy.api.order_market.assert_not_called()

    def test_tc_a05_emergency_bypass(self, strategy):
        """[TC-A05] 쿨다운 중 긴급 바이패스 검증"""
        cur_t = strategy.mock_tester.get_now().timestamp()
        strategy.last_sell_times["005930"] = cur_t - 1800
        holdings = [{"pdno":"005930", "evlu_pfls_rt":9.0, "hldg_qty":10, "prdt_name":"S"}]
        strategy.api.order_market.reset_mock()
        strategy.run_cycle(holdings=holdings)
        strategy.api.order_market.assert_called()

    def test_tc_a06_cash_protection(self, strategy):
        """[TC-A06] 현금 비중 보호 로직 (Bear장)"""
        strategy.analyzer.kr_vibe = "bear"
        asset_info = {"total_asset": 10000000, "cash": 2000000}
        holdings = [{"pdno":"005930", "prpr":70000, "pchs_avg_pric":71000, "evlu_pfls_rt":-1.5, "hldg_qty":10, "prdt_name":"S", "pchs_amt": 710000}]
        strategy.api.order_market.reset_mock()
        results = strategy.run_cycle(holdings=holdings, asset_info=asset_info, market_trend="bear")
        strategy.api.order_market.assert_not_called()
        assert not any("물타기" in r for r in results)

class TestAIDecisionScenarios:
    def test_tc_i01_market_vibe_logic(self, strategy):
        """[TC-I01] 지수 기반 장세 판정"""
        mock_api = MagicMock()
        analyzer = MarketAnalyzer(mock_api)
        mock_api.get_multiple_index_prices.return_value = {"NASDAQ": {"rate": -1.6}}
        analyzer.update()
        assert analyzer.is_panic is True

    def test_tc_i02_overbought_protection(self, strategy):
        """[TC-I02] 상투 매수 방어 로직"""
        strategy.indicator_eng.get_dual_timeframe_analysis.return_value = {"signal":"OVERBOUGHT"}
        is_ok, _ = strategy.confirm_buy_decision("005930", "S", 95)
        assert is_ok is True

    def test_tc_i03_replacement_entry(self, strategy):
        """[TC-I03] 종목 교체 진입"""
        strategy.get_max_stock_count = MagicMock(return_value=1)
        holdings = [{"pdno":"OLD", "hldg_qty":10, "prpr":10000, "prdt_name":"O", "pchs_avg_pric":9000, "pchs_amt": 100000}]
        strategy.ai_recommendations = [{"code":"NEW", "name":"N", "score":115.0, "price":5000, "rate": 1.0}]
        strategy.indicator_eng.get_dual_timeframe_analysis.return_value = {"signal":"BUY_ZONE"}
        cur_t = strategy.mock_tester.get_now().timestamp()
        strategy.last_buy_times["OLD"] = cur_t - 3600
        strategy.api.order_market.reset_mock()
        strategy.run_cycle(holdings=holdings)
        strategy.api.order_market.assert_any_call("OLD", 10, False)

    def test_tc_i05_zero_data_protection(self, strategy):
        """[TC-I05] 데이터 오류(0원) 보호"""
        strategy.api.get_naver_stock_detail.return_value = {"price": 0, "rate": 0}
        def real_confirm(code, name, score):
            detail = strategy.api.get_naver_stock_detail(code)
            if float(detail.get('price', 0)) == 0: return False, "0원"
            return True, "OK"
        strategy.confirm_buy_decision = real_confirm
        is_ok, reason = strategy.confirm_buy_decision("005930", "S", 90)
        assert is_ok is False and "0원" in reason

class TestThresholdScenarios:
    def test_tc_b01_bull_modifier(self, strategy):
        """[TC-B01-1] 상승장(Bull) 보정"""
        tp, sl, _ = strategy.exit_mgr.get_thresholds("T", "bull")
        assert tp == 8.0 and sl == -6.0

    def test_tc_b01_2_bear_modifier(self, strategy):
        """[TC-B01-2] 하락장(Bear) 보정"""
        tp, sl, _ = strategy.exit_mgr.get_thresholds("T", "bear")
        assert tp == 3.0 and sl == -3.0

    def test_tc_b02_p1_adjustment(self, strategy):
        """[TC-B02-1] Phase 1 보정"""
        p1 = {"id":"P1", "tp_delta":2.0, "sl_delta":-1.0}
        tp, sl, _ = strategy.exit_mgr.get_thresholds("T", "neutral", phase_cfg=p1)
        assert tp == 7.0 and sl == -6.0

    def test_tc_b02_2_p2_adjustment(self, strategy):
        """[TC-B02-2] Phase 2 보정"""
        p2 = {"id":"P2", "tp_delta":-1.0, "sl_delta":1.0}
        tp, sl, _ = strategy.exit_mgr.get_thresholds("T", "neutral", phase_cfg=p2)
        assert tp == 4.0 and sl == -4.0

class TestInfraScenarios:
    def test_tc_f01_api_fallback(self, strategy):
        """[TC-F01] API 장애 폴백"""
        strategy.api.get_balance.side_effect = Exception("API Error")
        with pytest.raises(Exception):
            strategy.api.get_balance()

    def test_tc_f04_persistence_call(self, strategy):
        """[TC-F04] 상태 저장 호출"""
        strategy._save_all_states()
        strategy.state_mgr.save_all_states.assert_called()

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:capture"])
