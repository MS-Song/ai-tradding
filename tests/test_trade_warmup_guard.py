import unittest
from unittest.mock import MagicMock, patch
import time
import sys
import os
from datetime import datetime

# 프로젝트 루트를 path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.workers.trade_worker import TradeWorker

class TestTradeWarmupGuard(unittest.TestCase):
    def setUp(self):
        self.state = MagicMock()
        self.state.is_kr_market_active = True
        self.state.vibe = "NEUTRAL"
        self.state.holdings = []
        self.state.asset = {}
        self.api = MagicMock()
        self.strategy = MagicMock()
        self.strategy.auto_ai_trade = True
        self.strategy.first_analysis_attempted = False
        self.strategy.debug_mode = False
        self.worker = TradeWorker(self.state, self.api, self.strategy)

    def test_condition_1_auto_trade_off(self):
        self.strategy.auto_ai_trade = False
        self.worker.run()
        self.strategy.run_cycle.assert_not_called()
        found = False
        for call in self.state.update_worker_status.call_args_list:
            if "자동매매 OFF" in str(call.kwargs.get('last_task', '')):
                found = True
                break
        self.assertTrue(found)

    def test_condition_2_warmup_waiting(self):
        self.strategy.auto_ai_trade = True
        self.strategy.first_analysis_attempted = False
        self.worker._warmup_start_time = time.time()
        self.worker.run()
        self.strategy.run_cycle.assert_not_called()
        found = False
        for call in self.state.update_worker_status.call_args_list:
            if "워밍업 대기 중" in str(call.kwargs.get('last_task', '')):
                found = True
                break
        self.assertTrue(found)

    def test_condition_2_1_warmup_timeout_fallback(self):
        self.strategy.auto_ai_trade = True
        self.strategy.first_analysis_attempted = False
        self.worker._warmup_start_time = time.time() - 360 
        self.worker.run()
        self.strategy.run_cycle.assert_called_once()
        found = False
        for call in self.state.update_worker_status.call_args_list:
            if call.kwargs.get('result') == "성공":
                found = True
                break
        self.assertTrue(found)

class TestExecutionEmergencyStrategy(unittest.TestCase):
    def setUp(self):
        from src.strategy.vibe.strategy import VibeStrategy
        self.api = MagicMock()
        self.config = {"ai_config": {"auto_mode": True, "auto_sell": True}}
        
        with patch('src.strategy.vibe.strategy.StateManager'):
            self.strategy = VibeStrategy(self.api, self.config)
            
        self.strategy.state = MagicMock()
        self.strategy.last_buy_times = {}
        self.strategy.last_sell_times = {}
        
        # 하위 엔진 모킹
        self.strategy.exit_mgr = MagicMock()
        self.strategy.exit_mgr.manual_thresholds = {}
        self.strategy.exit_mgr.base_tp = 5.0
        self.strategy.exit_mgr.base_sl = -5.0
        
        self.strategy.preset_eng = MagicMock()
        self.strategy.preset_eng.preset_strategies = {}
        
        self.strategy.analyzer = MagicMock()
        self.strategy.analyzer.kr_vibe = "BULL"
        self.strategy.analyzer.is_panic = False
        self.strategy.first_analysis_attempted = True
        
        mock_phase = {"id": "P1", "name": "오전장", "desc": "장 초반"}
        self.strategy.get_market_phase = MagicMock(return_value=mock_phase)
        self.strategy.get_current_phase = MagicMock(return_value=mock_phase)
        
        self.strategy.mock_tester = MagicMock()
        self.strategy.mock_tester.is_active = False
        self.strategy.mock_tester.intercept_order.return_value = None
        
        self.patcher = patch('src.strategy.vibe.execution.logger')
        self.mock_logger = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_condition_3_global_panic_emergency_assignment(self):
        # DEFENSIVE 장세로 설정하여 시간 비교 로직 우회
        self.strategy.analyzer.kr_vibe = "DEFENSIVE"
        self.strategy.analyzer.is_panic = True
        holdings = [{"pdno": "005930", "prdt_name": "삼성전자", "evlu_pfls_rt": "-2.0", "hldg_qty": "10"}]
        self.strategy.get_dynamic_thresholds = MagicMock(return_value=(5.0, -5.0, False))
        self.strategy.assign_preset = MagicMock()
        self.strategy.run_cycle(market_trend="defensive", skip_trade=False, holdings=holdings, asset_info={})
        self.strategy.assign_preset.assert_called()

    def test_condition_3_extreme_drop_emergency_assignment(self):
        # DEFENSIVE 장세로 설정하여 시간 비교 로직 우회
        self.strategy.analyzer.kr_vibe = "DEFENSIVE"
        self.strategy.analyzer.is_panic = False
        holdings = [{"pdno": "000660", "prdt_name": "SK하이닉스", "evlu_pfls_rt": "-11.0", "hldg_qty": "5"}]
        self.strategy.get_dynamic_thresholds = MagicMock(return_value=(5.0, -5.0, False))
        self.strategy.assign_preset = MagicMock()
        self.strategy.run_cycle(market_trend="defensive", skip_trade=False, holdings=holdings, asset_info={})
        self.strategy.assign_preset.assert_called()

if __name__ == "__main__":
    unittest.main()
