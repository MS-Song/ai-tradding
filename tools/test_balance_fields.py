import os
import sys
import json
import time
from dotenv import load_dotenv

# src 폴더 참조를 위한 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import KISAuth
from src.api import KISAPI

def test_balance_fields():
    print("=== KIS Balance API Field Verification ===")
    load_dotenv()
    
    auth = KISAuth()
    api = KISAPI(auth)
    
    print(f"[*] Account Type: {'Virtual' if auth.is_virtual else 'Real'}")
    
    # 1. 잔고 조회 호출 (강제 갱신)
    print("\n[*] Fetching Full Balance...")
    holdings, asset = api.get_full_balance(force=True)
    
    if not holdings:
        print("[!] No holdings found in this account.")
        return

    print(f"\n[+] Found {len(holdings)} holdings.")
    
    # 2. API 초과 에러 방지를 위해 대기
    print("\n[*] Waiting 3 seconds to avoid rate limit...")
    time.sleep(3)

    print("[*] Inspecting Raw Response from KIS API...")
    url = f"{api.domain}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = auth.get_auth_headers()
    headers["tr_id"] = "VTTC8434R" if auth.is_virtual else "TTTC8434R"
    params = {
        "CANO": auth.cano, "ACNT_PRDT_CD": "01", "AFHR_FLPR_YN": "N", "OFL_YN": "",
        "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    import requests
    res = requests.get(url, headers=headers, params=params, timeout=10)
    data = res.json()
    
    if data.get("rt_cd") == "0":
        sample = data.get("output1", [])[0] if data.get("output1") else None
        if sample:
            print("\n[Raw Holding Data Sample]")
            print(json.dumps(sample, indent=4, ensure_ascii=False))
            
            print("\n[Target Field Analysis]")
            print(f"- pdno (종목코드): {sample.get('pdno')}")
            print(f"- prpr (현재가): {sample.get('prpr')}")
            print(f"- bfdy_zprc (전일종가): {sample.get('bfdy_zprc')}")
            print(f"- prdy_vrss (전일대비): {sample.get('prdy_vrss')}")
            print(f"- prdy_ctrt (전일대비율): {sample.get('prdy_ctrt')}")
        else:
            print("[!] output1 is empty.")
    else:
        print(f"[!] API Failed: {data.get('msg1')}")

if __name__ == "__main__":
    test_balance_fields()
