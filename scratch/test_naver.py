import requests
from typing import List, Dict

def get_naver_stocks_realtime(codes: List[str]) -> Dict[str, dict]:
    if not codes: return {}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        codes_str = ",".join(codes)
        api_url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{codes_str}"
        res = requests.get(api_url, headers=headers, timeout=5)
        print(f"URL: {api_url}")
        print(f"Status: {res.status_code}")
        results = {}
        if res.status_code == 200:
            data = res.json()
            for area in data.get('result', {}).get('areas', []):
                for item in area.get('datas', []):
                    code = item.get('cd')
                    if not code: continue
                    print(f"Found code: {code}, name: {item.get('nm')}, nv: {item.get('nv')}")
                    price = float(item.get('nv', 0))
                    sign = item.get('rf') 
                    rate = float(item.get('cr', 0.0))
                    cv = float(item.get('cv', 0))
                    if sign in ['4', '5']:
                        rate = -abs(rate)
                        cv = -abs(cv)
                    
                    results[code] = {
                        "name": item.get('nm'), "price": price,
                        "rate": rate,
                        "cv": cv,
                        "aq": float(item.get('aq', 0))
                    }
        return results
    except Exception as e:
        print(f"Error: {e}")
        return {}

if __name__ == "__main__":
    codes = ["003490", "005810", "009830", "298380"] # Korean Air, Poongsan, Hanwha Sol, ABL Bio
    res = get_naver_stocks_realtime(codes)
    print(res)
