import unittest
from unittest.mock import patch, MagicMock
import os
import json

from src.auth import KiwoomAuth
from src.api.kiwoom import KiwoomAPIClient
from src.workers.kiwoom_ws_worker import KiwoomWSWorker
from src.data.state import TradingState

class TestKiwoomAuth(unittest.TestCase):
    @patch('src.auth.os.getenv')
    def setUp(self, mock_getenv):
        mock_getenv.side_effect = lambda key, default=None: {
            "KIWOOM_APPKEY": "test_appkey",
            "KIWOOM_SECRET": "test_secret",
            "KIWOOM_ACCOUNT": "1234567890",
            "KIWOOM_IS_VIRTUAL": "TRUE"
        }.get(key, default)
        
        self.auth = KiwoomAuth()
        self.auth.cache_file = ".test_token_cache_kiwoom.json"
        
    def tearDown(self):
        if os.path.exists(self.auth.cache_file):
            os.remove(self.auth.cache_file)

    @patch('src.auth.requests.post')
    def test_generate_token_success(self, mock_post):
        # Mocking a successful token response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "token": "mocked_access_token",
            "return_code": 0
        }
        mock_post.return_value = mock_response

        # Token generation
        success = self.auth.generate_token()
        self.assertTrue(success)
        self.assertEqual(self.auth.access_token, "mocked_access_token")
        
        # Test headers
        headers = self.auth.get_auth_headers()
        self.assertEqual(headers["authorization"], "Bearer mocked_access_token")
        self.assertEqual(headers["appkey"], "test_appkey")
        self.assertEqual(headers["appsecret"], "test_secret")

class TestKiwoomAPIClient(unittest.TestCase):
    def setUp(self):
        self.auth = MagicMock()
        self.auth.get_auth_headers.return_value = {"authorization": "Bearer test"}
        self.auth.domain = "https://mockapi.kiwoom.com"
        self.auth.account = "1234567890"
        self.api = KiwoomAPIClient(self.auth)
        
    @patch('src.api.kiwoom.requests.request')
    def test_get_full_balance(self, mock_request):
        # We need to mock two requests: one for kt00001 (cash) and kt00018 (balance)
        def side_effect(method, url, headers=None, json=None, **kwargs):
            mock_res = MagicMock()
            if headers and headers.get("api-id") == "kt00001":
                mock_res.json.return_value = {
                    "return_code": 0,
                    "d2_entra": "10000",
                    "entr": "5000"
                }
            elif headers and headers.get("api-id") == "kt00018":
                mock_res.json.return_value = {
                    "return_code": 0,
                    "tot_evlt_amt": "20000",
                    "tot_pur_amt": "15000",
                    "prsm_dpst_aset_amt": "30000",
                    "tot_evlt_pl": "5000",
                    "acnt_evlt_remn_indv_tot": [
                        {
                            "stk_cd": "A005930",
                            "stk_nm": "Samsung",
                            "rmnd_qty": "10",
                            "pur_pric": "50000",
                            "cur_prc": "60000",
                            "evlt_amt": "600000",
                            "prft_rt": "20.0",
                            "evltv_prft": "100000",
                            "pred_close_pric": "59000"
                        }
                    ]
                }
            return mock_res
            
        mock_request.side_effect = side_effect
        
        holdings, asset_info = self.api.get_full_balance()
        
        self.assertEqual(len(holdings), 1)
        self.assertEqual(holdings[0]["pdno"], "005930")
        self.assertEqual(holdings[0]["hldg_qty"], "10")
        
        self.assertEqual(asset_info["d2_cash"], 10000)
        self.assertEqual(asset_info["stock_eval"], 20000)
        self.assertEqual(asset_info["total_asset"], 30000)

class TestKiwoomWSWorker(unittest.TestCase):
    def setUp(self):
        self.state = TradingState()
        self.api = MagicMock()
        self.api.auth.is_token_valid.return_value = True
        self.api.auth.access_token = "test_token"
        self.api.auth.ws_domain = "wss://mockapi.kiwoom.com:10000"
        self.strategy = MagicMock()
        self.worker = KiwoomWSWorker(self.state, self.api, self.strategy)
        
    @patch('src.workers.kiwoom_ws_worker.websocket.WebSocketApp')
    @patch('src.workers.kiwoom_ws_worker.threading.Thread')
    def test_connect_and_handle_real(self, mock_thread, mock_ws):
        # We simulate the worker handling a real data payload
        self.state.holdings = [{
            "pdno": "005930",
            "hldg_qty": "10",
            "pchs_avg_pric": "50000",
            "prpr": "50000",
            "evlu_amt": "500000"
        }]
        
        mock_ws_instance = MagicMock()
        mock_ws.return_value = mock_ws_instance
        
        self.worker._connect()
        
        # Manually trigger the on_message to simulate data arrival
        # For Kiwoom 0B REAL data
        payload = {
            "trnm": "REAL",
            "data": [{
                "type": "0B",
                "item": "A005930",
                "values": {
                    "10": "-60000", # Sometimes Kiwoom gives negative prices to indicate down tick
                    "13": "100000"  # Volume
                }
            }]
        }
        
        # We need to access the on_message callback from the mocked args
        on_message_callback = mock_ws.call_args[1]['on_message']
        on_message_callback(mock_ws_instance, json.dumps(payload))
        
        # Validate that the state has been updated
        self.assertIn("005930", self.state.stock_info)
        self.assertEqual(self.state.stock_info["005930"]["price"], 60000.0)
        self.assertEqual(self.state.stock_info["005930"]["vol"], 100000.0)
        
        # Validate holdings update
        self.assertEqual(self.state.holdings[0]["prpr"], "60000.0")
        self.assertEqual(self.state.holdings[0]["evlu_amt"], str(600000.0))

if __name__ == '__main__':
    unittest.main()
