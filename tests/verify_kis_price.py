import os
import sys
import time
from dotenv import load_dotenv

# src 폴더 참조를 위한 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import KISAuth
from src.api import KISAPI

def test_kis_price():
    print("=== KIS Price API Verification ===")
    load_dotenv()
    
    auth = KISAuth()
    api = KISAPI(auth)
    
    print(f"[*] Account Type: {'Virtual' if auth.is_virtual else 'Real'}")
    print(f"[*] Domain: {api.domain}")
    
    # 1. KIS API Responsiveness Test
    print("\n[*] Fetching Samsung Electronics Price (KIS)...")
    price_info = api.get_inquire_price("005930")
    assert price_info is not None
    assert price_info['price'] > 0
    print(f"    [+] Price: {price_info['price']:,}원 ({price_info['ctrt']:+.2f}%)")

if __name__ == "__main__":
    test_kis_price()
