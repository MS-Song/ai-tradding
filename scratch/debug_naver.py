import requests
from bs4 import BeautifulSoup

def test_naver_raw():
    code = "005930"
    url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    print(f"Fetching {url}...")
    res = requests.get(url, headers=headers, timeout=5)
    print(f"Status Code: {res.status_code}")
    
    if res.status_code == 200:
        soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
        table = soup.find('table', {'class': 'type2'})
        if table:
            print("Found table!")
            rows = table.find_all('tr')
            print(f"Row count: {len(rows)}")
        else:
            print("Table NOT found!")
            # Print a bit of HTML to see what we got
            print(res.text[:1000])

if __name__ == "__main__":
    test_naver_raw()
