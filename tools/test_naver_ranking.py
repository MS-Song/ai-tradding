import os
import sys
from dotenv import load_dotenv

# src 폴더 참조를 위한 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import KISAuth
from src.api import KISAPI

def test_naver_ranking():
    print("=== Naver Ranking API Verification ===")
    load_dotenv()
    
    auth = KISAuth()
    api = KISAPI(auth)
    
    # 1. Hot Stocks Test
    print("\n[*] Fetching Naver Hot Search Stocks...")
    hot = api.get_naver_hot_stocks()
    print(f"[+] Found {len(hot)} items")
    if hot:
        for i, item in enumerate(hot[:10], 1):
            print(f"    {i}. {item['name']} ({item['code']}) -> {item['price']:,}원 ({item['rate']:+.2f}%)")
    
    # 2. Volume Stocks Test
    print("\n[*] Fetching Naver Volume Leaders...")
    vol = api.get_naver_volume_stocks()
    print(f"[+] Found {len(vol)} items")
    if vol:
        for i, item in enumerate(vol[:10], 1):
            print(f"    {i}. [{item['mkt']}] {item['name']} ({item['code']}) -> Vol: {item['vol']:,}, {item['rate']:+.2f}%")

    # 3. Filtering Check
    print("\n[*] Checking Filtering Logic...")
    risky_samples = ["삼성전자", "삼성전자우", "관리종목A", "거래정지주"]
    for s in risky_samples:
        is_risky = api._filter_risky_stocks(s)
        print(f"    '{s}': {'Filtered (Risky/Pref)' if is_risky else 'Passed'}")

if __name__ == "__main__":
    test_naver_ranking()
