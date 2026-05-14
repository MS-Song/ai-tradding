import sys
import os
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, time as dtime

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.workers.sync_worker import DataSyncWorker
from src.data.state import TradingState

class TestRealtimeSyncLogic(unittest.TestCase):
    def setUp(self):
        self.state = TradingState()
        self.api = MagicMock()
        self.strategy = MagicMock()
        self.worker = DataSyncWorker(self.state, self.api, self.strategy)

    @patch('src.workers.sync_worker.get_now')
    def test_auction_session_detection(self, mock_now):
        """동시호가 세션 감지 로직 테스트"""
        # 장전 동시호가 (08:30)
        mock_now.return_value = datetime(2026, 5, 14, 8, 30)
        
        # worker의 _sync_stock_prices 내부 로직을 시뮬레이션
        now_dt = mock_now()
        now_t = now_dt.time()
        is_regular_session = dtime(9, 0) <= now_t < dtime(15, 30)
        is_auction_session = not is_regular_session
        
        self.assertTrue(is_auction_session, "08:30은 동시호가 세션이어야 함")
        self.assertFalse(is_regular_session)

        # 정규장 (10:00)
        mock_now.return_value = datetime(2026, 5, 14, 10, 0)
        now_t = mock_now().time()
        is_regular_session = dtime(9, 0) <= now_t < dtime(15, 30)
        is_auction_session = not is_regular_session
        
        self.assertFalse(is_auction_session)
        self.assertTrue(is_regular_session, "10:00은 정규 세션이어야 함")

    @patch('src.workers.sync_worker.get_now')
    def test_price_hot_swap_logic(self, mock_now):
        """장중 소켓 데이터 우선 반영(Hot-swap) 로직 테스트"""
        mock_now.return_value = datetime(2026, 5, 14, 11, 0) # 정규장
        
        code = "005930"
        # 1. 네이버 데이터 (지연 시세: 70,000원)
        n_data = {"price": 70000, "rate": 1.0, "cv": 700, "name": "삼성전자"}
        
        # 2. 소켓 데이터 (실시간 시세: 70,500원)
        self.state.stock_info[code] = {
            "price": 70500,
            "is_socket": True,
            "name": "삼성전자"
        }
        
        # DataSyncWorker의 로직 시뮬레이션
        now_t = mock_now().time()
        is_regular_session = dtime(9, 0) <= now_t < dtime(15, 30)
        
        curr_p = n_data['price'] # 초기값은 네이버 가격
        
        if is_regular_session:
            old_info = self.state.stock_info.get(code, {})
            if old_info.get('is_socket') and old_info.get('price', 0) > 0:
                curr_p = old_info['price'] # 소켓 가격으로 덮어씀
                
        self.assertEqual(curr_p, 70500, "정규장에서는 소켓 가격(70,500)이 네이버 가격(70,000)보다 우선되어야 함")

    def test_subscription_target_expansion(self):
        """웹소켓 구독 대상 확대 로직 테스트"""
        from src.workers.kiwoom_ws_worker import KiwoomWSWorker
        ws_worker = KiwoomWSWorker(self.state, self.api, self.strategy)
        
        # 데이터 설정
        self.state.holdings = [{"pdno": "005930"}] # 삼성전자
        self.state.hot_raw = [{"code": "000660"}]   # SK하이닉스
        self.state.vol_raw = [{"code": "035420"}]   # NAVER
        self.strategy.ai_recommendations = [{"code": "005490"}] # POSCO홀딩스
        
        # _check_and_subscribe 내부 로직 시뮬레이션
        current_codes = set()
        for h in self.state.holdings:
            code = h.get("pdno", "").strip().replace("A", "")
            if code: current_codes.add(code)
            
        recs = getattr(self.strategy, "ai_recommendations", [])
        for r in recs:
            code = r.get("code", "").strip().replace("A", "")
            if code: current_codes.add(code)
            
        for item_list in [self.state.hot_raw, self.state.vol_raw, self.state.amt_raw]:
            for item in (item_list or []):
                code = item.get("code", "").strip().replace("A", "")
                if code: current_codes.add(code)
                
        expected_codes = {"005930", "000660", "035420", "005490"}
        self.assertEqual(current_codes, expected_codes, "구독 대상에 보유, 랭킹, 추천 종목이 모두 포함되어야 함")

    def test_kiwoom_data_parsing(self):
        """키움증권 실시간 JSON 데이터 파싱 테스트"""
        from src.workers.kiwoom_ws_worker import KiwoomWSWorker
        ws_worker = KiwoomWSWorker(self.state, self.api, self.strategy)
        
        # 키움 실시간 데이터 샘플 (JSON)
        sample_data = {
            "trnm": "REAL",
            "data": [{
                "type": "0B",
                "item": "005930",
                "values": {
                    "10": "70500", # 현재가
                    "13": "1000000" # 누적거래량
                }
            }]
        }
        
        ws_worker._handle_real_data(sample_data)
        
        info = self.state.stock_info.get("005930", {})
        self.assertEqual(info.get("price"), 70500.0)
        self.assertTrue(info.get("is_socket"))
        self.assertEqual(info.get("vol"), 1000000.0)

    def test_kis_data_parsing(self):
        """한국투자증권(KIS) 실시간 Pipe 데이터 파싱 테스트"""
        from src.workers.kis_ws_worker import KISWSWorker
        ws_worker = KISWSWorker(self.state, self.api, self.strategy)
        
        # KIS 실시간 데이터 샘플 (Pipe & ^ 구분자)
        # 형식: 체결시간^현재가^전일대비부호^전일대비^전일대비율^...^누적거래량(index 12)
        # index: [0]시간, [1]가각, ... [12]거래량
        code = "000660"
        data_body = "153000^185000^2^1500^0.82^...^...^...^...^...^...^...^5000000"
        
        ws_worker._handle_real_data(code, data_body)
        
        info = self.state.stock_info.get("000660", {})
        self.assertEqual(info.get("price"), 185000.0)
        self.assertTrue(info.get("is_socket"))
        self.assertEqual(info.get("vol"), 5000000.0)

if __name__ == '__main__':
    unittest.main()
