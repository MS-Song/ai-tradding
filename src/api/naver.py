import requests
import time
import random
from typing import List, Dict, Optional, Any
from src.api.base import BaseAPI
from src.utils import safe_cast_float
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

class NaverAPIClient(BaseAPI):
    def __init__(self):
        super().__init__()
        self._detail_cache = {}
        self._cache_duration = 120

    def get_naver_stocks_realtime(self, codes: List[str]) -> Dict[str, dict]:
        if not codes: return {}
        try:
            codes_str = ",".join(codes)
            api_url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{codes_str}"
            res = requests.get(api_url, headers=self.headers, timeout=5)
            results = {}
            if res.status_code == 200:
                data = res.json()
                for area in data.get('result', {}).get('areas', []):
                    for item in area.get('datas', []):
                        code = item.get('cd')
                        if not code: continue
                        price = float(item.get('nv', 0))
                        # [Fix] Naver 실시간 API는 등락률(cr), 등락폭(cv)이 절대값으로 올 때가 많음 -> rf 필드로 부호 결정
                        sign = item.get('rf') # 1: 상한, 2: 상승, 3: 보합, 4: 하한, 5: 하락
                        rate = float(item.get('cr', 0.0))
                        cv = float(item.get('cv', 0))
                        if sign in ['4', '5']:
                            rate = -abs(rate)
                            cv = -abs(cv)
                        
                        results[code] = {
                            "name": item.get('nm'), "price": price,
                            "rate": rate,
                            "cv": cv,
                            "aq": float(item.get('aq', 0)),
                            "hv": float(item.get('hv', price)),
                            "lv": float(item.get('lv', price)),
                            "ov": float(item.get('ov', price))
                        }
                        # [추가] 실시간 캐시 업데이트
                        if not hasattr(self, '_realtime_cache'): self._realtime_cache = {}
                        self._realtime_cache[code] = (time.time(), results[code])
            return results
        except: return {}

    def get_naver_hot_stocks(self) -> List[dict]:
        results = []
        try:
            url = "https://finance.naver.com/sise/lastsearch2.naver"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=5)
            if not BeautifulSoup: return []
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            table = soup.find('table', {'class': 'type_5'})
            if table:
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) > 5:
                        a = cols[1].find('a')
                        if a:
                            name = a.text.strip()
                            code = a['href'].split('=')[-1].strip()
                            if not code.isdigit(): continue
                            rate_txt = cols[5].text.strip().replace('%', '').replace('+', '')
                            try:
                                rate = float(rate_txt)
                                # [Fix] 부호 중복 적용 방지 및 아이콘 탐색 강화
                                icon_img = cols[4].find('img') or cols[5].find('img')
                                if icon_img:
                                    img_src = icon_img.get('src', '').lower()
                                    if 'down' in img_src: rate = -abs(rate)
                                    elif 'up' in img_src: rate = abs(rate)
                            except: rate = 0.0
                            price_txt = cols[3].text.replace(',', '').strip()
                            mkt = "KSP" if int(code) < 300000 else "KDQ"
                            results.append({"code": code, "name": name, "price": price_txt, "rate": rate, "mkt": mkt})
            return results[:20]
        except: return []

    def get_naver_stock_detail(self, code: str, force: bool = False, **kwargs) -> dict:
        curr_t = time.time()
        if not force and code in self._detail_cache:
            ts, data = self._detail_cache[code]
            if curr_t - ts < self._cache_duration: return data
        
        detail = {
            "name": "Unknown", "price": 0, "rate": 0.0, "cv": 0, 
            "market_cap": "N/A", "per": "N/A", "pbr": "N/A", 
            "yield": "N/A", "sector_per": "N/A"
        }
        
        # 1. 실시간 시세 및 기본 정보 (캐시 확인 후 polling API 활용)
        try:
            item = None
            if hasattr(self, '_realtime_cache') and code in self._realtime_cache:
                ts, rt_item = self._realtime_cache[code]
                if curr_t - ts < 10: # 10초 이내 실시간 데이터면 활용
                    item = rt_item
            
            if not item:
                rt_data = self.get_naver_stocks_realtime([code])
                if code in rt_data: item = rt_data[code]
            
            if item:
                detail["name"] = item.get("name", "Unknown")
                detail["price"] = item.get("price", 0)
                detail["rate"] = item.get("rate", 0.0)
                detail["cv"] = item.get("cv", 0)
        except: pass

        # 2. 펀더멘털 및 상세 정보 (HTML 크롤링 - 상세함)
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=5)
            if BeautifulSoup:
                soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
                
                # 종목명 (실시간 API 실패 시 백업)
                if detail["name"] == "Unknown":
                    wrap = soup.find('div', {'class': 'wrap_company'})
                    if wrap and wrap.find('a'):
                        detail["name"] = wrap.find('a').text.strip()
                
                # 시가 및 등락 (실시간 API 실패 시 백업)
                if detail["price"] == 0:
                    today = soup.find('p', {'class': 'no_today'})
                    if today:
                        price_em = today.find('em')
                        if price_em:
                            detail["price"] = safe_cast_float(price_em.text)
                
                # 투자 정보 (시총, PER, PBR 등)
                aside = soup.find('div', {'class': 'aside_invest_info'})
                if aside:
                    # 시가총액
                    mkt_cap_area = aside.find('th', string=lambda x: x and '시가총액' in x)
                    if not mkt_cap_area: # 한국어 direct match 실패 시 find_all로 찾기
                        ths = aside.find_all('th')
                        for th in ths:
                            if '시가총액' in th.text:
                                mkt_cap_area = th
                                break
                    if mkt_cap_area and mkt_cap_area.find_next_sibling('td'):
                        detail["market_cap"] = mkt_cap_area.find_next_sibling('td').text.strip().replace('\n', ' ').replace('\t', '')

                    # PER, PBR, 배당수익률, 업종PER
                    per = aside.find('em', {'id': '_per'})
                    if per: detail["per"] = per.text.strip()
                    pbr = aside.find('em', {'id': '_pbr'})
                    if pbr: detail["pbr"] = pbr.text.strip()
                    dvr = aside.find('em', {'id': '_dvr'}) # 배당수익률
                    if dvr: detail["yield"] = dvr.text.strip()
                    cper = aside.find('em', {'id': '_cper'}) # 업종PER
                    if cper: detail["sector_per"] = cper.text.strip()
            
            self._detail_cache[code] = (curr_t, detail)
            return detail
        except: return detail
    def get_naver_volume_stocks(self) -> List[dict]:
        results = []
        try:
            for sosok in ["0", "1"]:
                url = f"https://finance.naver.com/sise/nxt_sise_quant.naver?sosok={sosok}"
                self._wait_for_domain_delta(url)
                res = requests.get(url, headers=self.headers, timeout=5)
                if not BeautifulSoup: continue
                soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
                table = soup.find('table', {'class': 'type_2'})
                if table:
                    for row in table.find_all('tr'):
                        cols = row.find_all('td')
                        if len(cols) > 5:
                            a = cols[1].find('a')
                            if a:
                                name, code = a.text.strip(), a['href'].split('=')[-1].strip()
                                if not code.isdigit(): continue
                                rate_txt = cols[4].text.strip().replace('%', '').replace('+', '')
                                try:
                                    rate = float(rate_txt)
                                    # [Fix] 부호 중복 적용 방지 및 아이콘 탐색 강화
                                    icon_img = cols[3].find('img') or cols[4].find('img')
                                    if icon_img:
                                        img_src = icon_img.get('src', '').lower()
                                        if 'down' in img_src: rate = -abs(rate)
                                        elif 'up' in img_src: rate = abs(rate)
                                except: rate = 0.0
                                price_txt = cols[2].text.replace(',', '').strip()
                                results.append({"code": code, "name": name, "price": price_txt, "rate": rate, "mkt": "KSP" if sosok == "0" else "KDQ"})
            return results[:40]
        except: return []

    def get_naver_stock_news(self, code: str) -> List[str]:
        try:
            url = f"https://finance.naver.com/item/news.naver?code={code}"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=5)
            if not BeautifulSoup: return []
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            news_list = []
            table = soup.find('table', {'class': 'type5'})
            if table:
                titles = table.find_all('td', {'class': 'title'})
                for t in titles[:3]: news_list.append(f"[뉴스] {t.text.strip()}")
            return news_list
        except: return []

    def get_naver_theme_data(self) -> dict:
        theme_map = {}
        try:
            for page in range(1, 11):
                url = f"https://finance.naver.com/sise/theme.naver?&page={page}"
                self._wait_for_domain_delta(url)
                res = requests.get(url, headers=self.headers, timeout=10)
                if not BeautifulSoup: return {}
                soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
                table = soup.find('table', {'class': 'type_1'})
                if not table: break
                links = table.find_all('td', {'class': 'col_type1'})
                for l in links:
                    a = l.find('a')
                    if a and 'sise_group_detail.naver' in a['href']:
                        theme_name, theme_url = a.text.strip(), "https://finance.naver.com" + a['href']
                        try:
                            self._wait_for_domain_delta(theme_url)
                            res_d = requests.get(theme_url, headers=self.headers, timeout=5)
                            soup_d = BeautifulSoup(res_d.content, 'html.parser', from_encoding='cp949')
                            stocks = []
                            table_d = soup_d.find('table', {'class': 'type_5'})
                            if table_d:
                                for row in table_d.find_all('tr'):
                                    name_td = row.find('td', {'class': 'name'})
                                    if name_td and name_td.find('a'):
                                        a_s = name_td.find('a')
                                        stocks.append({"name": a_s.text.strip(), "code": a_s['href'].split('=')[-1]})
                            if stocks: theme_map[theme_name] = stocks
                        except: continue
            return theme_map
        except: return {}
    def get_naver_minute_chart(self, code: str, count: int = 40) -> List[dict]:
        """네이버 F-Chart XML API를 통해 분봉 데이터를 가져옵니다. (Fallback용)"""
        try:
            url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=minute&count={count}&requestType=0"
            res = requests.get(url, timeout=5)
            if res.status_code != 200: return []
            
            import re
            pattern = re.compile(r'<item data="([^"]+)" />')
            items = pattern.findall(res.text)
            
            candles = []
            for item in items:
                parts = item.split('|')
                if len(parts) >= 6:
                    candles.append({
                        "stck_cntg_hour": parts[0][-6:], 
                        "stck_prpr": parts[4], 
                        "stck_clpr": parts[4]
                    })
            return list(reversed(candles))
        except:
            return []

    def get_market_open_status(self) -> Optional[bool]:
        """네이버 API를 통해 국내 증시 개장 상태를 확인합니다."""
        try:
            url = "https://m.stock.naver.com/api/index/KOSPI/basic"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=5)
            if res.status_code == 200:
                status = res.json().get('marketStatus')
                if status:
                    return status == "OPEN"
        except Exception as e:
            from src.logger import log_error
            log_error(f"⚠️ 시장 상태 조회 오류: {e}")
        return None
