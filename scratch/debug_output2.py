import os
import sys
import json
from dotenv import load_dotenv

# src 폴더 참조를 위한 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import KISAuth
from src.api import KISAPI
import requests

def debug_output2():
    load_dotenv()
    auth = KISAuth()
    api = KISAPI(auth)
    
    url = f"{api.domain}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = auth.get_auth_headers()
    headers["tr_id"] = "VTTC8434R" if auth.is_virtual else "TTTC8434R"
    params = {
        "CANO": auth.cano, "ACNT_PRDT_CD": "01", "AFHR_FLPR_YN": "N", "OFL_YN": "",
        "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    res = requests.get(url, headers=headers, params=params, timeout=10)
    data = res.json()
    
    if data.get("rt_cd") == "0":
        summary = data.get("output2", [{}])[0]
        print("\n=== KIS API output2 Fields ===")
        print(json.dumps(summary, indent=4, ensure_ascii=False))
    else:
        print(f"API Failed: {data.get('msg1')}")

if __name__ == "__main__":
    debug_output2()
