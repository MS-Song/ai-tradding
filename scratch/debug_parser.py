import requests
import re
from bs4 import BeautifulSoup

def test_parse(code):
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
    
    today = soup.find('div', {'class': 'today'})
    if not today:
        print("Today div not found")
        return

    all_ps = today.find_all('p')
    print(f"Found {len(all_ps)} p tags")
    for i, p in enumerate(all_ps):
        print(f"P[{i}]: text='{p.text.strip()}', class={p.get('class')}")
        
    rate_area = None
    for p in all_ps:
        if '%' in p.text:
            rate_area = p
            break
            
    if rate_area:
        print(f"Rate area text: '{rate_area.text.strip()}'")
        val_match = re.search(r'([\d.]+)\s*%', rate_area.text)
        if val_match:
            val = float(val_match.group(1))
            cls_str = str(rate_area.get('class', []))
            print(f"Matched value: {val}, Class: {cls_str}")
            
            rate = 0.0
            if 'no_up' in cls_str: rate = val
            elif 'no_down' in cls_str: rate = -val
            else:
                blind_txt = rate_area.find('span', {'class': 'blind'})
                r_txt = blind_txt.text.strip() if blind_txt else ""
                print(f"Blind text: '{r_txt}'")
                rate = val if "플러스" in r_txt or "+" in rate_area.text else -val if "마이너스" in r_txt or "-" in rate_area.text else 0.0
            print(f"FINAL RATE: {rate}")
        else:
            print("No match for percentage number")
    else:
        print("No rate area found with '%'")

test_parse("005490")
