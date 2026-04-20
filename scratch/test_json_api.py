import requests
import json

def test_json_api(code):
    url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)
    data = res.json()
    item = data['result']['areas'][0]['datas'][0]
    print(json.dumps(item, indent=2, ensure_ascii=False))
    
    price = item['nv'] # 현재가 (Now Value)
    rate = item['cr']  # 등락률 (Change Rate)
    name = item['nm']  # 종목명
    diff = item['cv']  # 대비 (Change Value)
    
    print(f"Name: {name}, Price: {price}, Rate: {rate}, Diff: {diff}")

test_json_api("005490")
