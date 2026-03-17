import requests
import json

def test_naver():
    targets = [
        ("SERVICE_INDEX", "VOSPI"),
        ("SERVICE_MARKETINDEX", "USDKRW"),
        ("SERVICE_MARKETINDEX", "USD_KRW"),
        ("SERVICE_INDEX", "FX_USDKRW"),
        ("SERVICE_RECENT", "USDKRW")
    ]
    
    print("=== Naver Finance API Key Test ===")
    for service, key in targets:
        url = f"https://polling.finance.naver.com/api/realtime?query={service}:{key}"
        try:
            res = requests.get(url, timeout=3)
            data = res.json()
            print(f"\n--- {service}:{key} ---")
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"[ERROR] {service}:{key} -> {e}")

if __name__ == "__main__":
    test_naver()
