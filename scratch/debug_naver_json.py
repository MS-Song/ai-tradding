import requests
from bs4 import BeautifulSoup

def test_naver_json_header():
    code = "005930"
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print(f"Fetching {url} with JSON header...")
    res = requests.get(url, headers=headers, timeout=5)
    print(f"Status Code: {res.status_code}")
    
    if res.status_code == 200:
        soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
        table = soup.find('table', {'class': 'type2'})
        if table:
            print("Found table!")
        else:
            print("Table NOT found!")
            print(res.text[:500])

if __name__ == "__main__":
    test_naver_json_header()
