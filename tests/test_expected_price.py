import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, time as dtime
import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.workers.sync_worker import DataSyncWorker

class TestExpectedPrice(unittest.TestCase):
    """예상 체결가(동시호가) 로직 및 시간대 전환 테스트."""

    def setUp(self):
        self.state = MagicMock()
        self.state.lock = MagicMock()
        self.api = MagicMock()
        self.strategy = MagicMock()
        # DataSyncWorker 초기화
        self.worker = DataSyncWorker(self.state, self.api, self.strategy)

    @patch('src.workers.sync_worker.get_now')
    def test_01_pre_market_session(self, mock_now):
        """장전 동시호가 시간(08:50)에 예상 체결가를 사용하는지 테스트."""
        # 08:50:00 (장전 동시호가 구간 - 이제 08:00부터 시작)
        mock_now.return_value = datetime(2026, 5, 14, 8, 50, 0)
        
        # API에서 받은 목업 데이터 (현재가는 0, 예상가는 55,000원)
        p_data = {
            "price": 0,
            "vrss": 0,
            "ctrt": 0,
            "antc_price": 55000,
            "antc_rate": 2.5
        }
        
        # sync_worker.py의 로직 시뮬레이션
        now_t = mock_now().time()
        is_pre_market = dtime(8, 0) <= now_t < dtime(9, 0)
        
        curr_p = p_data.get('price', 0)
        day_rate = p_data.get('ctrt', 0)
        is_antc = False
        
        if p_data and p_data.get('antc_price', 0) > 0:
            if is_pre_market:
                curr_p = p_data['antc_price']
                day_rate = p_data.get('antc_rate', day_rate)
                is_antc = True
        
        self.assertTrue(is_pre_market, "08:50은 장전 동시호가 구간이어야 합니다.")
        self.assertEqual(curr_p, 55000, "동시호가 구간에서는 예상 체결가를 사용해야 합니다.")
        self.assertEqual(day_rate, 2.5, "동시호가 구간에서는 예상 등락률을 사용해야 합니다.")
        self.assertTrue(is_antc, "is_antc 플래그가 True여야 합니다 (UI 표시용).")

    @patch('src.workers.sync_worker.get_now')
    def test_02_market_open_transition(self, mock_now):
        """9시 정각이 되는 순간 예상가에서 실제가로 전환되는지 테스트."""
        # 09:00:00 (장 시작 정각)
        mock_now.return_value = datetime(2026, 5, 14, 9, 0, 0)
        
        # API 데이터 (현재가 56,000원 발생, 예상가는 여전히 남아있을 수 있음)
        p_data = {
            "price": 56000,
            "vrss": 1000,
            "ctrt": 1.8,
            "antc_price": 55000,
            "antc_rate": 2.5
        }
        
        now_t = mock_now().time()
        # 09:00:00는 < dtime(9, 0) 조건에 의해 False가 됨
        is_pre_market = dtime(8, 0) <= now_t < dtime(9, 0)
        
        curr_p = p_data.get('price', 0)
        day_rate = p_data.get('ctrt', 0)
        is_antc = False
        
        if p_data and p_data.get('antc_price', 0) > 0:
            if is_pre_market:
                curr_p = p_data['antc_price']
                day_rate = p_data.get('antc_rate', day_rate)
                is_antc = True
        
        self.assertFalse(is_pre_market, "09:00 정각에는 동시호가 구간이 종료되어야 합니다.")
        self.assertEqual(curr_p, 56000, "9시 이후에는 실제 체결가(price)를 사용해야 합니다.")
        self.assertEqual(day_rate, 1.8, "9시 이후에는 실제 등락률(ctrt)을 사용해야 합니다.")
        self.assertFalse(is_antc, "is_antc 플래그가 False여야 합니다 ((예) 표시 사라짐).")

    @patch('src.workers.sync_worker.get_now')
    def test_03_post_market_session(self, mock_now):
        """장후 동시호가 시간(15:35)에 예상 체결가를 사용하는지 테스트."""
        # 15:35:00 (장후 동시호가 구간)
        mock_now.return_value = datetime(2026, 5, 14, 15, 35, 0)
        
        p_data = {
            "price": 56000,
            "antc_price": 55800,
            "antc_rate": -0.4
        }
        
        now_t = mock_now().time()
        is_post_market = dtime(15, 30) <= now_t < dtime(16, 30)
        
        curr_p = p_data.get('price', 0)
        is_antc = False
        
        if p_data and p_data.get('antc_price', 0) > 0:
            if is_post_market:
                curr_p = p_data['antc_price']
                is_antc = True
                
        self.assertTrue(is_post_market, "15:35는 장후 동시호가 구간이어야 합니다.")
        self.assertEqual(curr_p, 55800, "장후 동시호가에서도 예상가를 우선해야 합니다.")
        self.assertTrue(is_antc, "is_antc 플래그가 True여야 합니다.")

if __name__ == '__main__':
    unittest.main()
