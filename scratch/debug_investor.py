import os
import sys
from dotenv import load_dotenv
load_dotenv()

from src.auth import KISAuth
from src.api import KISAPI

def test():
    auth = KISAuth()
    api = KISAPI(auth)
    
    # 삼성전자 (005930) 테스트
    code = "005930"
    print(f"--- Testing {code} ---")
    data = api.get_investor_trading_trend(code)
    print(f"Data: {data}")
    
    if data:
        print(f"Cycle: {data.get('cycle')}")
        print(f"History Length: {len(data.get('history', []))}")
    else:
        print("Failed to get data")

if __name__ == "__main__":
    test()
