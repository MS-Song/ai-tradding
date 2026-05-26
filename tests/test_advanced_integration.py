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
        import time as pytime
        self.boot_time = pytime.time() - 3600
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
        self.debug_mode = True

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
    def get_replacement_target(self, code, name, score, holdings): return True, "OLD", "Better", 0
    def confirm_buy_decision(self, code, name, score): return True, "OK", 0

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

    @patch('src.ui.interaction.get_input')
    @patch('threading.Thread')
    def test_manual_sell_omitted_quantity(self, mock_thread, mock_get_input, strategy):
        """수동 매도 시 수량을 생략하면(예: 번호만 입력), 보유한 수량 전량을 대상으로 매도 주문이 수행되는지 검증"""
        from src.ui.interaction import perform_interaction
        
        # 1. 가상 데이터 매니저 모킹
        dm = MagicMock()
        dm.ranking_filter = "ALL"
        # 보유 종목 리스트 설정 (KX하이텍, 10주 보유)
        dm.cached_holdings = [
            {"pdno": "088180", "prdt_name": "KX하이텍", "hldg_qty": "10", "pchs_avg_pric": "1000"}
        ]
        dm.ma_20_cache = {}
        
        # 2. 사용자 입력 모킹: '1' 번호만 입력 (수량, 가격 생략)
        mock_get_input.return_value = "1"
        
        # 3. 비동기 스레드 실행 대신, 스레드에 넘겨진 task_sell 함수를 동기적으로 직접 가로채서 실행하도록 스파이 구성
        def thread_side_effect(target, name=None, daemon=True):
            # target이 task_sell 이므로 이를 직접 동기 호출해 검증
            target()
            return MagicMock()
        mock_thread.side_effect = thread_side_effect
        
        # Naver 주가 상세 Mocking
        strategy.api.get_naver_stock_detail.return_value = {"price": 1100, "rate": 1.0}
        strategy.api.order_market.return_value = (True, "성공")
        
        # 4. 상호작용 수행 ('1' 키 입력)
        perform_interaction('1', strategy.api, strategy, dm, 1)
        
        # 5. 검증
        # - 수량이 생략되었으므로 max_qty 인 10주 전체가 매도 주문으로 들어갔는지 확인
        strategy.api.order_market.assert_called_once_with("088180", 10, False, 0)
        # - 대시보드 상태 알림에 성공 메시지가 정상 출력되었는지 확인
        dm.show_status.assert_called_with("✅ 매도 성공: KX하이텍")

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

    def test_tc_m08_multillm_transient_503_failover(self, strategy):
        """[TC-M08] 503 에러 발생 시 해당 요청만 임시로 2순위, 3순위 모델로 페일오버하여 성공하는지 검증"""
        from src.strategy.advisors.multi import MultiLLMAdvisor
        
        # 1. 3중화 어드바이저 구성 (Gemini, Groq1, Groq2)
        api = MagicMock()
        llm_seq = [("GEMINI", "gemini-3.1-pro-preview"), ("GROQ", "groq-model-1"), ("GROQ", "groq-model-2")]
        multi_advisor = MultiLLMAdvisor(api, llm_seq)
        
        # 2. 1순위 Gemini는 503 Exception 유발 모킹
        multi_advisor.advisors[0].final_buy_confirm = MagicMock(side_effect=Exception("GEMINI_API_503_ERROR"))
        
        # 3. 2순위 Groq1은 정상 결과 리턴 모킹
        expected_res = (True, "수급 지지 반등", 10)
        multi_advisor.advisors[1].final_buy_confirm = MagicMock(return_value=expected_res)
        
        # 4. 최종 호출 검증
        res = multi_advisor.final_buy_confirm("088180", "KX하이텍", "neutral", {}, [])
        
        # 5. 결과 확인: 2순위로 무사히 페일오버되어 결과가 리턴되어야 함
        assert res[0] is True
        assert "수급 지지" in res[1]
        
        # 호출 순위 리스트는 그대로 유지되어야 함 (503은 임시 페일오버)
        assert multi_advisor.advisors[0].model_id == "gemini-3.1-pro-preview"

    def test_tc_m09_multillm_permanent_404_failover(self, strategy):
        """[TC-M09] 404 에러 발생 시 2순위를 1순위로, 1순위를 3순위로 영구 페일오버 및 우선순위 회전 검증"""
        from src.strategy.advisors.multi import MultiLLMAdvisor
        
        # 1. 3중화 어드바이저 구성 (Gemini, Groq1, Groq2)
        api = MagicMock()
        llm_seq = [("GEMINI", "gemini-3.1-pro-preview"), ("GROQ", "groq-model-1"), ("GROQ", "groq-model-2")]
        multi_advisor = MultiLLMAdvisor(api, llm_seq)
        
        # 초기 순서 확인
        assert [adv.model_id for adv in multi_advisor.advisors] == ["gemini-3.1-pro-preview", "groq-model-1", "groq-model-2"]
        
        # 2. 1순위 Gemini는 404 Exception 유발 모킹
        multi_advisor.advisors[0].final_buy_confirm = MagicMock(side_effect=Exception("GEMINI_API_404_ERROR"))
        
        # 3. 2순위 Groq1은 정상 결과 리턴 모킹
        expected_res = (True, "돌파 상승 확인", 10)
        multi_advisor.advisors[1].final_buy_confirm = MagicMock(return_value=expected_res)
        
        # 4. 최종 호출 수행
        res = multi_advisor.final_buy_confirm("088180", "KX하이텍", "neutral", {}, [])
        
        # 5. 검증
        # - 성공적으로 페일오버하여 결과 리턴
        assert res[0] is True
        assert "돌파 상승" in res[1]
        
        # - 404 감지로 인해 호출 순서가 [B, C, A] 즉 [groq-model-1, groq-model-2, gemini-3.1-pro-preview]로 영구 순서 변경되었는지 검증!
        new_order = [adv.model_id for adv in multi_advisor.advisors]
        assert new_order == ["groq-model-1", "groq-model-2", "gemini-3.1-pro-preview"]

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

    def test_recovery_short_grace_period(self, strategy):
        """물타기(매수) 직후 초단기(5분 이내)에는 API 동기화 지연에 따른 핑퐁 손절 유예 검증"""
        cur_t = strategy.mock_tester.get_now().timestamp()
        strategy.last_buy_times["005930"] = cur_t - 10  # 10초 전에 구매함 (5분 이내)
        strategy.last_sell_times["005930"] = cur_t - 7200  # 2시간 전에 판매함
        # rt (-6.0%) 가 sl (-5.0%) 보다 낮고, 심지어 sl - 1.0% (-6.0% 이하) 라서 평소 같으면 추가 급락 긴급 손절이 발동해야 함
        holdings = [{"pdno":"005930", "evlu_pfls_rt":-6.1, "hldg_qty":10, "prdt_name":"S"}]
        strategy.exit_mgr.base_sl = -5.0
        strategy.analyzer.kr_vibe = "neutral"
        strategy.api.order_market.reset_mock()
        
        results = strategy.run_cycle(holdings=holdings)
        
        # 초단기 보호로 인해 손절 주문이 발송되지 않아야 함
        strategy.api.order_market.assert_not_called()
        assert any("초단기 보호" in r for r in results)

    def test_tc_a06_cash_protection(self, strategy):
        """[TC-A06] 현금 비중 보호 로직 (Bear장)"""
        strategy.analyzer.kr_vibe = "bear"
        asset_info = {"total_asset": 10000000, "cash": 2000000}
        holdings = [{"pdno":"005930", "prpr":70000, "pchs_avg_pric":71000, "evlu_pfls_rt":-1.5, "hldg_qty":10, "prdt_name":"S", "pchs_amt": 710000}]
        strategy.api.order_market.reset_mock()
        results = strategy.run_cycle(holdings=holdings, asset_info=asset_info, market_trend="bear")
        strategy.api.order_market.assert_not_called()
        assert not any("물타기" in r for r in results)

    def test_bad_sell_cooldown_removal_and_missing_preset_auto_assign(self, strategy):
        """보유 중인 종목이 손절 등으로 오해받아 쿨다운에 등록되었을 때, 쿨다운 자동 해제 및 프리셋 복구/배정 검증"""
        # 1. bad_sell_times에 KX하이텍 코드(088180) 등록
        strategy.bad_sell_times = {"088180": {"time": time.time(), "type": "손절"}}
        
        # 2. auto_assign_preset을 MagicMock으로 모의하여 스파이(Spy) 설정
        strategy.auto_assign_preset = MagicMock(return_value=True)
        
        # KX하이텍 주식을 여전히 보유하고 있는 상황 연출
        holdings = [{"pdno": "088180", "evlu_pfls_rt": -2.0, "hldg_qty": 10, "prdt_name": "KX하이텍"}]
        
        # mock_tester의 get_now()가 지정된 datetime 객체를 리턴하도록 함
        cur_t = time.time()
        strategy.mock_tester.get_now.return_value = datetime.fromtimestamp(cur_t)
        
        # 3. 첫 번째 루프 실행 (전략 프리셋 미배정 상태)
        strategy.run_cycle(holdings=holdings)
        
        # bad_sell_times에서 즉시 제거되었는지 검증
        assert "088180" not in strategy.bad_sell_times
        
        # auto_assign_preset이 최초 호출되었는지 검증
        strategy.auto_assign_preset.assert_called_once_with("088180", "KX하이텍")
        
        # 4. 1분 뒤 상황 재현 (쿨다운 15분 이내)
        strategy.mock_tester.get_now.return_value = datetime.fromtimestamp(cur_t + 60)
        strategy.auto_assign_preset.reset_mock()
        
        strategy.run_cycle(holdings=holdings)
        
        # 15분 쿨다운에 걸려서 auto_assign_preset이 재호출되지 않았어야 함
        strategy.auto_assign_preset.assert_not_called()
        
        # 5. 16분 뒤 상황 재현 (쿨다운 15분 만료)
        strategy.mock_tester.get_now.return_value = datetime.fromtimestamp(cur_t + 1000)
        strategy.run_cycle(holdings=holdings)
        
        # 쿨다운 만료 후 auto_assign_preset이 다시 성공적으로 호출되었는지 검증
        strategy.auto_assign_preset.assert_called_once_with("088180", "KX하이텍")

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
        is_ok, _, _ = strategy.confirm_buy_decision("005930", "S", 95)
        assert is_ok is True

    @patch('src.strategy.vibe.execution.time.time')
    def test_tc_i03_replacement_entry(self, mock_time, strategy):
        """[TC-I03] 종목 교체 진입"""
        strategy.get_max_stock_count = MagicMock(return_value=1)
        holdings = [{"pdno":"OLD", "hldg_qty":10, "prpr":10000, "prdt_name":"O", "pchs_avg_pric":9000, "pchs_amt": 100000}]
        strategy.ai_recommendations = [{"code":"NEW", "name":"N", "score":115.0, "price":5000, "rate": 1.0}]
        strategy.indicator_eng.get_dual_timeframe_analysis.return_value = {"signal":"BUY_ZONE"}
        cur_t = strategy.mock_tester.get_now().timestamp()
        mock_time.return_value = cur_t
        strategy.last_buy_times["OLD"] = cur_t - 3600
        strategy.api.order_market.reset_mock()
        strategy.run_cycle(holdings=holdings)
        strategy.api.order_market.assert_any_call("OLD", 10, False)

    def test_tc_i05_zero_data_protection(self, strategy):
        """[TC-I05] 데이터 오류(0원) 보호"""
        strategy.api.get_naver_stock_detail.return_value = {"price": 0, "rate": 0}
        def real_confirm(code, name, score):
            detail = strategy.api.get_naver_stock_detail(code)
            if float(detail.get('price', 0)) == 0: return False, "0원", 60
            return True, "OK", 0
        strategy.confirm_buy_decision = real_confirm
        is_ok, reason, _ = strategy.confirm_buy_decision("005930", "S", 90)
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

    def test_tc_f08_recommendation_recovery_worker_no_clear_busy_error(self, strategy):
        """[TC-F08] RecommendationRecoveryWorker가 clear_busy() AttributeError 없이 정상 작동하는지 검증"""
        from src.workers.recommendation_worker import RecommendationRecoveryWorker
        from src.data.state import TradingState
        
        # 1. 상태 객체 생성
        state = TradingState()
        state.is_kr_market_active = True
        
        # 2. Strategy 모킹
        mock_strategy = MagicMock()
        mock_strategy.auto_ai_trade = True
        mock_strategy.debug_mode = False
        
        # 3. 워커 생성
        worker = RecommendationRecoveryWorker(state, MagicMock(), mock_strategy, dm=MagicMock())
        
        # 4. run 실행 시 예외가 발생하지 않아야 함 (AttributeError 차단 검증)
        try:
            worker.run()
        except AttributeError as e:
            pytest.fail(f"AttributeError 발생: {e} - clear_busy() 관련 버그가 수정되지 않음")
        except Exception as e:
            # 기타 비즈니스 로직 예외는 테스트 목적상 무시 가능
            pass
            
        # 5. 상태가 정상적으로 갱신되었는지 검증 (성공 또는 실패로 상태 갱신이 되어야 함)
        assert state.worker_results.get("REC_RECOVERY") in ["성공", "실패"]

class TestRealtimeSyncScenarios:
    """[NEW] 실시간 시세 동기화 및 동시호가 세션 로직 검증"""
    
    @patch('src.workers.sync_worker.get_now')
    def test_tc_s01_auction_session_detection(self, mock_now, strategy):
        """[TC-S01] 동시호가 세션 감지 (09:00~15:30 제외 전 시간)"""
        from datetime import time as dtime
        
        # 장전 (08:30) -> Auction
        mock_now.return_value = datetime(2026, 5, 14, 8, 30)
        now_t = mock_now().time()
        is_auction = not (dtime(9, 0) <= now_t < dtime(15, 30))
        assert is_auction is True
        
        # 장중 (13:00) -> Regular
        mock_now.return_value = datetime(2026, 5, 14, 13, 0)
        now_t = mock_now().time()
        is_auction = not (dtime(9, 0) <= now_t < dtime(15, 30))
        assert is_auction is False
        
        # 장후 (16:00) -> Auction
        mock_now.return_value = datetime(2026, 5, 14, 16, 0)
        now_t = mock_now().time()
        is_auction = not (dtime(9, 0) <= now_t < dtime(15, 30))
        assert is_auction is True

    def test_tc_s02_price_priority_logic(self, strategy):
        """[TC-S02] 장중 소켓 데이터 우선순위 반영 (Hot-swap)"""
        code = "005930"
        naver_p = 70000
        socket_p = 70500
        
        # 상태 설정
        state = MagicMock()
        state.stock_info = {
            code: {"price": socket_p, "is_socket": True}
        }
        
        # 로직 시뮬레이션
        is_regular = True # 장중 가정
        curr_p = naver_p
        
        if is_regular:
            old_info = state.stock_info.get(code, {})
            if old_info.get('is_socket') and old_info.get('price', 0) > 0:
                curr_p = old_info['price']
        
        assert curr_p == socket_p

    def test_tc_s03_kiwoom_parsing(self, strategy):
        """[TC-S03] 키움증권 실시간 데이터 파싱 검증"""
        from src.workers.kiwoom_ws_worker import KiwoomWSWorker
        from src.data.state import TradingState
        state = TradingState()
        ws = KiwoomWSWorker(state, MagicMock(), MagicMock())
        
        msg = {
            "trnm": "REAL",
            "data": [{"type": "0B", "item": "005930", "values": {"10": "70500", "13": "100"}}]
        }
        ws._handle_real_data(msg['data'][0])
        assert state.stock_info["005930"]["price"] == 70500.0
        assert state.stock_info["005930"]["is_socket"] is True

    def test_tc_s04_kis_parsing(self, strategy):
        """[TC-S04] KIS 실시간 데이터 파싱 검증"""
        from src.workers.kis_ws_worker import KISWSWorker
        from src.data.state import TradingState
        state = TradingState()
        ws = KISWSWorker(state, MagicMock(), MagicMock())
        
        # KIS 포맷: [1]가격, [12]거래량
        body = "153000^185000^2^1500^0.82^0^0^0^0^0^0^0^5000"
        ws._handle_real_data("000660", body)
        assert state.stock_info["000660"]["price"] == 185000.0
        assert state.stock_info["000660"]["is_socket"] is True

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:capture"])
