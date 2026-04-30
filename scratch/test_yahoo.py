import requests
import time

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

symbols = ["^KS11", "^KQ11", "^IXIC", "^DJI", "^GSPC"]

for s in symbols:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1m&range=1d"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        print(f"{s}: {res.status_code}")
        if res.status_code == 200:
            data = res.json()
            meta = data['chart']['result'][0]['meta']
            print(f"  Price: {meta.get('regularMarketPrice')}")
    except Exception as e:
        print(f"{s}: Error {e}")
    time.sleep(1)
