import os
import sys
import time
from dotenv import load_dotenv

# src 폴더 참조를 위한 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import KISAuth
from src.api import KISAPI

def test_ranking():
    print("=== KIS Ranking API Verification ===")
    load_dotenv()
    
    auth = KISAuth()
    api = KISAPI(auth)
    
    print(f"[*] Account Type: {'Virtual' if auth.is_virtual else 'Real'}")
    print(f"[*] Domain: {api.domain}")
    
    # 1. KOSPI Ranking Test
    print("\n[*] Fetching KOSPI Gainers...")
    gains = api._get_ranking(is_gainer=True)
    print(f"[+] Found {len(gains)} items")
    if gains:
        print(f"    Top 1: {gains[0]['name']} ({gains[0]['code']}) -> {gains[0]['rate']}%")
    
    # 2. KOSDAQ Ranking Test
    print("\n[*] Fetching KOSDAQ Losers...")
    loses = api._get_ranking(is_gainer=False)
    print(f"[+] Found {len(loses)} items")
    if loses:
        print(f"    Worst 1: {loses[0]['name']} ({loses[0]['code']}) -> {loses[0]['rate']}%")

    # 3. Raw Response Check (Special Debug)
    print("\n[*] Checking Raw API Response for KOSPI...")
    mkt_code = "0001"
    url = f"{api.domain}/uapi/domestic-stock/v1/ranking/fluctuation"
    headers = auth.get_auth_headers()
    headers["tr_id"] = "VHPST01700000" if auth.is_virtual else "FHPST01700000"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20170", 
        "FID_INPUT_ISCD": mkt_code, "FID_RANK_SORT_CLS_CODE": "0", 
        "FID_INPUT_CNT_1": "0", "FID_PRC_CLS_CODE": "0", 
        "FID_INQR_RANGE_1": "0", "FID_INQR_RANGE_2": "0", 
        "FID_VOL_CNT": "0", "FID_TRGT_CLS_CODE": "0", 
        "FID_TRGT_EXLS_CLS_CODE": "0000000000", "FID_PRC_RANGE_CLS_CODE": "0", 
        "FID_RSFL_RATE1": "0", "FID_RSFL_RATE2": "0", 
        "FID_DIV_CLS_CODE": "0", "FID_ETC_CLS_CODE": "0", 
        "FID_INPUT_PRICE_1": "0", "FID_INPUT_PRICE_2": "0"
    }
    
    import requests
    res = requests.get(url, headers=headers, params=params)
    print(f"[*] HTTP Status: {res.status_code}")
    data = res.json()
    print(f"[*] rt_cd: {data.get('rt_cd')}")
    print(f"[*] msg1: {data.get('msg1')}")
    
    if data.get('rt_cd') != '0':
        print("[!] Error detected. Trying fallback tr_id (FHPST01700000)...")
        headers["tr_id"] = "FHPST01700000"
        res2 = requests.get(url, headers=headers, params=params)
        data2 = res2.json()
        print(f"[*] Fallback rt_cd: {data2.get('rt_cd')}")
        print(f"[*] Fallback msg1: {data2.get('msg1')}")

if __name__ == "__main__":
    test_ranking()
