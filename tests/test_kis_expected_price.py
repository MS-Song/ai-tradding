import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.kis import KISAPIClient

class TestKISExpectedPrice(unittest.TestCase):
    """한국투자증권(KIS) 예상 체결가 파싱 테스트."""

    def setUp(self):
        self.auth = MagicMock()
        self.auth.get_auth_headers.return_value = {"authorization": "Bearer test"}
        self.auth.domain = "https://mockapi.koreainvestment.com"
        self.auth.is_virtual = True
        self.api = KISAPIClient(self.auth)

    @patch('src.api.kis.requests.request')
    def test_get_inquire_price_with_expected_price(self, mock_request):
        """KIS API 응답에서 예상 체결가(antc_cntg_prce)가 올바르게 추출되는지 테스트."""
        # KIS API 응답 목업 (FHKST01010100)
        mock_res = MagicMock()
        mock_res.json.return_value = {
            "rt_cd": "0",
            "output": {
                "stck_prpr": "0",               # 현재가는 0 (장 시작 전)
                "prdy_vrss": "1000",
                "prdy_ctrt": "1.5",
                "prdy_vrss_sign": "1",
                "acml_vol": "0",
                "prdy_vol": "1000000",
                "stck_hgpr": "0",
                "stck_lwpr": "0",
                "per": "10.5",
                "pbr": "1.2",
                "lstn_stkn": "1000000",
                "antc_cntg_prce": "55000",      # 예상 체결가
                "antc_cntg_prdy_ctrt": "2.5"    # 예상 등락률
            }
        }
        mock_request.return_value = mock_res

        # 실행
        price_data = self.api.get_inquire_price("005930")

        # 검증
        self.assertIsNotNone(price_data)
        self.assertEqual(price_data["price"], 0.0)
        self.assertEqual(price_data["antc_price"], 55000.0, "예상 체결가가 55000이어야 합니다.")
        self.assertEqual(price_data["antc_rate"], 2.5, "예상 등락률이 2.5여야 합니다.")
        self.assertEqual(price_data["per"], "10.5")

    @patch('src.api.kis.requests.request')
    def test_get_inquire_price_sign_correction(self, mock_request):
        """등락 부호(sign)가 하락(4, 5)일 때 음수 보정이 잘 되는지 테스트."""
        mock_res = MagicMock()
        mock_res.json.return_value = {
            "rt_cd": "0",
            "output": {
                "stck_prpr": "54000",
                "prdy_vrss": "1000",
                "prdy_ctrt": "1.8",
                "prdy_vrss_sign": "5",          # 하락 부호
                "antc_cntg_prce": "53500",
                "antc_cntg_prdy_ctrt": "-0.9"   # KIS는 이미 마이너스로 줄 수도 있음
            }
        }
        mock_request.return_value = mock_res

        price_data = self.api.get_inquire_price("005930")

        self.assertEqual(price_data["vrss"], -1000.0, "부호가 5일 때 전일대비는 음수여야 합니다.")
        self.assertEqual(price_data["ctrt"], -1.8, "부호가 5일 때 등락률은 음수여야 합니다.")

if __name__ == '__main__':
    unittest.main()
