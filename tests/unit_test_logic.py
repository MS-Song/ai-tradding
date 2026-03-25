import unittest
from src.strategy import ExitManager, RecoveryEngine, VibeAlphaEngine

class MockAPI:
    def get_naver_stock_detail(self, code):
        return {"per": "10.0", "pbr": "1.0", "yield": "2.0", "sector_per": "15.0"}

class TestTradingLogic(unittest.TestCase):
    def setUp(self):
        self.exit_mgr = ExitManager(base_tp=5.0, base_sl=-5.0)
        self.recovery_eng = RecoveryEngine({"min_loss_to_buy": -3.0, "average_down_amount": 500000})
        self.alpha_eng = VibeAlphaEngine(MockAPI())

    def test_exit_manager_vibe_bull(self):
        # Bull market: TP should increase by 3.0, SL by 1.0
        tp, sl, spike = self.exit_mgr.get_thresholds("TEST", "BULL")
        self.assertEqual(tp, 8.0)
        self.assertEqual(sl, -4.0)

    def test_exit_manager_vibe_bear(self):
        # Bear market: TP should decrease by 2.0, SL by 2.0 (tighter)
        tp, sl, spike = self.exit_mgr.get_thresholds("TEST", "BEAR")
        self.assertEqual(tp, 3.0)
        self.assertEqual(sl, -7.0)

    def test_recovery_engine_trigger(self):
        # Current PnL -4.0% is between SL -5.0% and Trigger -3.0%
        item = {
            "pdno": "005930",
            "prdt_name": "삼성전자",
            "prpr": "70000",
            "pchs_avg_pric": "73000",
            "evlu_pfls_rt": "-4.0",
            "hldg_qty": "10"
        }
        # In setup, SL is -5.0. Trigger is -3.0.
        # RecoveryEngine logic: if SL < curr_rt <= final_trig
        rec = self.recovery_eng.get_recommendation(item, is_panic=False, current_sl=-5.0)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["type"], "물타기")

    def test_ai_scoring(self):
        # Test AI scoring logic
        stock = {"code": "005930", "rate": "1.0"}
        theme = {"name": "반도체", "count": 10}
        score = self.alpha_eng._calculate_ai_score(stock, theme, is_gem=False)
        # Base 40 + (5-1)*3=12 + min(15, 10*1.5=15)=15 + PBR(1.0) bonus 15 + PER(10.0) bonus 10 = 92
        self.assertEqual(score, 92.0)

if __name__ == "__main__":
    unittest.main()
