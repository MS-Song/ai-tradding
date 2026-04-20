import requests
import re
from bs4 import BeautifulSoup

def test_parse(code):
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
    
    today = soup.find('div', {'class': 'today'})
    all_ps = today.find_all('p')
    rate_area = next((p for p in all_ps if '%' in p.text), None)
            
    if rate_area:
        print(f"Rate area HTML: {rate_area}")
        val_match = re.search(r'([\d.]+)\s*%', rate_area.text)
        if val_match:
            val = float(val_match.group(1))
            
            # 모든 자식 요소의 클래스 합치기
            all_classes = set(rate_area.get('class', []))
            for child in rate_area.find_all():
                all_classes.update(child.get('class', []))
            
            print(f"All classes: {all_classes}")
            
            rate = 0.0
            if 'no_up' in all_classes: rate = val
            elif 'no_down' in all_classes: rate = -val
            else:
                text_content = rate_area.text
                print(f"Text content: '{text_content}'")
                if '+' in text_content or '상승' in text_content or '플러스' in text_content:
                    rate = val
                elif '-' in text_content or '하락' in text_content or '마이너스' in text_content:
                    rate = -val
            print(f"FINAL RATE: {rate}")

test_parse("005490")
