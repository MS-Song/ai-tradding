import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import random
from typing import List, Dict, Optional, Any
from src.api.base import BaseAPI
from src.utils import safe_cast_float
from src.utils import retry_api
from src.logger import log_error
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

class NaverAPIClient(BaseAPI):
    """네이버 금융(Finance) 데이터를 수집하는 클라이언트.

    실시간 시세(polling API), 인기 검색 종목, 거래량 급증 종목, 종목 상세 정보(PER/PBR), 
    뉴스, 테마 데이터 등을 크롤링 또는 API를 통해 수집합니다.

    Attributes:
        _detail_cache (dict): 종목 상세 정보 캐시.
        _cache_duration (int): 캐시 유효 기간 (초).
    """
    def __init__(self):
        super().__init__()
        self._detail_cache = {}
        self._cache_duration = 120
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        # [v2.0.1] ConnectionResetError(10054) 등 서버 측 연결 끊김에 대한 자동 재시도 설정
        retry_strategy = Retry(
            total=3,                          # 최대 3회 재시도
            backoff_factor=0.5,               # 0.5초, 1초, 2초 백오프
            status_forcelist=[500, 502, 503, 504],  # 서버 에러 시에도 재시도
            allowed_methods=["GET", "POST"],   # GET/POST 모두 재시도 허용
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get_naver_stocks_realtime(self, codes: List[str]) -> Dict[str, dict]:
        """여러 종목의 실시간 시세를 한 번에 조회합니다.

        네이버 polling API를 사용하며, 등락률 부호(rf 필드)를 보정하여 반환합니다.

        Args:
            codes (List[str]): 종목 코드 리스트.

        Returns:
            Dict[str, dict]: 종목 코드를 키로 하는 시세 정보 맵.
        """
        if not codes: return {}
        try:
            codes_str = ",".join(codes)
            api_url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{codes_str}"
            res = self._session.get(api_url, timeout=5)
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
                            "amt": float(item.get('aa', 0)), # [추가] 거래대금 (백만 단위)
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
        """네이버 금융 '인기 검색 종목' TOP 20을 수집합니다.

        Returns:
            List[dict]: 인기 종목 리스트 (코드, 이름, 가격, 등락률 등 포함).
        """
        results = []
        try:
            url = "https://finance.naver.com/sise/lastsearch2.naver"
            self._wait_for_domain_delta(url)
            res = self._session.get(url, timeout=5)
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
                            price = float(price_txt) if price_txt else 0.0
                            mkt = "KSP" if int(code) < 300000 else "KDQ"
                            results.append({"code": code, "name": name, "price": price, "rate": rate, "mkt": mkt})
            return results[:20]
        except: return []

    def get_naver_stock_detail(self, code: str, force: bool = False, **kwargs) -> dict:
        """종목의 상세 정보(시총, PER, PBR 등)를 수집합니다.

        실시간 API와 HTML 크롤링을 결합하여 데이터를 구성하며, 
        단기 캐싱을 통해 불필요한 네트워크 요청을 방지합니다.

        Args:
            code (str): 종목 코드.
            force (bool): 캐시를 무시하고 새로 수집할지 여부.

        Returns:
            dict: 종목 상세 정보 딕셔너리.
        """
        curr_t = time.time()
        if not force and code in self._detail_cache:
            ts, data = self._detail_cache[code]
            if curr_t - ts < self._cache_duration: return data
        
        detail = {
            "name": "Unknown", "price": 0, "rate": 0.0, "cv": 0, 
            "market_cap": "N/A", "per": "N/A", "pbr": "N/A", 
            "yield": "N/A", "sector_per": "N/A",
            "vol": 0, "amt": 0
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
                detail["vol"] = item.get("aq", 0)
                detail["amt"] = item.get("amt", 0)
        except: pass

        # 2. 펀더멘털 및 상세 정보 (HTML 크롤링 - 상세함)
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            self._wait_for_domain_delta(url)
            res = self._session.get(url, timeout=5)
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
        """네이버 금융 '거래량 상위 종목' 리스트를 수집합니다.

        Returns:
            List[dict]: 거래량 상위 종목 리스트 (코스피/코스닥 통합 최대 40개).
        """
        results = []
        try:
            for sosok in ["0", "1"]:
                # [v1.7.2] 안정성을 위해 PC 버전 sise_quant.naver URL 사용
                url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
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
                                    icon_img = cols[3].find('img') or cols[4].find('img')
                                    if icon_img:
                                        img_src = icon_img.get('src', '').lower()
                                        if 'down' in img_src: rate = -abs(rate)
                                        elif 'up' in img_src: rate = abs(rate)
                                except: rate = 0.0
                                price_txt = cols[2].text.replace(',', '').strip()
                                price = float(price_txt) if price_txt else 0.0
                                vol_txt = cols[5].text.replace(',', '').strip()
                                vol = float(vol_txt) if vol_txt else 0.0
                                results.append({"code": code, "name": name, "price": price, "rate": rate, "vol": vol, "mkt": "KSP" if sosok == "0" else "KDQ"})
            # 거래량 기준으로 내림차순 정렬
            results.sort(key=lambda x: x.get('vol', 0), reverse=True)
            return results[:40]
        except: return []

    def get_naver_amount_stocks(self) -> List[dict]:
        """네이버 금융 '거래대금 상위 종목' 리스트를 수집합니다.

        Returns:
            List[dict]: 거래대금 상위 종목 리스트 (코스피/코스닥 통합 최대 40개).
        """
        results = []
        try:
            for sosok in ["0", "1"]:
                # [v1.7.2] sise_amount.naver 404 이슈 해결: sise_quant.naver에서 거래대금 컬럼 추출
                url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
                self._wait_for_domain_delta(url)
                res = requests.get(url, headers=self.headers, timeout=5)
                if not BeautifulSoup: continue
                soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
                table = soup.find('table', {'class': 'type_2'})
                if table:
                    for row in table.find_all('tr'):
                        cols = row.find_all('td')
                        # sise_quant.naver 기준: 0:No, 1:종목명, 2:현재가, 3:전일대비, 4:등락률, 5:거래량, 6:거래대금(백만)
                        if len(cols) > 6:
                            a = cols[1].find('a')
                            if a:
                                name, code = a.text.strip(), a['href'].split('=')[-1].strip()
                                if not code.isdigit(): continue
                                rate_txt = cols[4].text.strip().replace('%', '').replace('+', '')
                                try:
                                    rate = float(rate_txt)
                                    icon_img = cols[3].find('img') or cols[4].find('img')
                                    if icon_img:
                                        img_src = icon_img.get('src', '').lower()
                                        if 'down' in img_src: rate = -abs(rate)
                                        elif 'up' in img_src: rate = abs(rate)
                                except: rate = 0.0
                                price_txt = cols[2].text.replace(',', '').strip()
                                price = float(price_txt) if price_txt else 0.0
                                # 거래대금 (6번째 TD, 백만원 단위)
                                amt_txt = cols[6].text.replace(',', '').strip()
                                amt = float(amt_txt) if amt_txt else 0.0
                                results.append({"code": code, "name": name, "price": price, "rate": rate, "amt": amt, "mkt": "KSP" if sosok == "0" else "KDQ"})
            
            # 거래대금 기준으로 내림차순 정렬
            results.sort(key=lambda x: x.get('amt', 0), reverse=True)
            return results[:40]
        except: return []

    def get_naver_stock_news(self, code: str) -> List[str]:
        """특정 종목의 최신 뉴스 헤드라인을 수집합니다.

        Args:
            code (str): 종목 코드.

        Returns:
            List[str]: 뉴스 헤드라인 리스트 (최대 3개).
        """
        try:
            url = f"https://finance.naver.com/item/news.naver?code={code}"
            self._wait_for_domain_delta(url)
            res = self._session.get(url, timeout=5)
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
        """네이버 금융 '테마별 시세' 데이터를 수집하여 테마-종목 맵을 구축합니다.

        Returns:
            dict: {테마명: [{"name": 종목명, "code": 종목코드}, ...]} 형식의 데이터.
        """
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
                            # [v1.7.2] 테마 상세 수집 시 간격을 더 늘려 차단 방지 (1.0s)
                            time.sleep(1.0)
                            res_d = self._session.get(theme_url, timeout=5)
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
        """네이버 F-Chart XML API를 통해 분봉 데이터를 가져옵니다.

        한국투자증권 API 장애 시 지표 분석을 위한 Fallback용으로 사용됩니다.

        Args:
            code (str): 종목 코드.
            count (int): 가져올 봉 개수.

        Returns:
            List[dict]: 분봉 캔들 리스트.
        """
        try:
            url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=minute&count={count}&requestType=0"
            res = self._session.get(url, timeout=5)
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

    @retry_api(max_retries=2, delay=1.0)
    def get_investor_trading_trend(self, code: str) -> Optional[dict]:
        """네이버 금융에서 특정 종목의 투자자별 매매동향(외인, 기관)을 수집합니다.

        기존 KIS API 대비 과거 이력을 포함하여 상세히 분석할 수 있습니다.

        Args:
            code (str): 종목 코드.

        Returns:
            Optional[dict]: 최신 수급 정보 및 과거 5거래일 이력.
        """
        try:
            url = f"https://finance.naver.com/item/frgn.naver?code={code}"
            self._wait_for_domain_delta(url)
            
            # [수정] 웹페이지 크롤링 시에는 JSON 헤더가 오해를 살 수 있으므로 User-Agent만 포함된 클린 헤더 사용
            clean_headers = {"User-Agent": self.headers.get("User-Agent")}
            res = self._session.get(url, headers=clean_headers, timeout=5)
            if not BeautifulSoup: return None
            
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            tables = soup.find_all('table', {'class': 'type2'})
            table = None
            for t in tables:
                th = t.find('th')
                if th and '날짜' in th.text:
                    table = t
                    break
            
            if not table: return None
            
            rows = table.find_all('tr')
            history = []
            for row in rows:
                cols = row.find_all('td')
                if len(cols) > 8:
                    date = cols[0].text.strip()
                    if not date or '.' not in date: continue
                    
                    # 기관, 외인 순매수 (주 단위)
                    inst = safe_cast_float(cols[5].text.strip().replace(',', ''))
                    frgn = safe_cast_float(cols[6].text.strip().replace(',', ''))
                    hold_rt = safe_cast_float(cols[8].text.strip().replace(',', '').replace('%', ''))
                    
                    history.append({
                        "date": date,
                        "inst_net_buy": inst,
                        "frgn_net_buy": frgn,
                        "frgn_hold_rt": hold_rt
                    })
                    if len(history) >= 10: break # 최근 10거래일 수집
            
            if not history: return None
            
            # 최신 데이터 (오늘)
            latest = history[0]
            return {
                "frgn_net_buy": latest["frgn_net_buy"],
                "inst_net_buy": latest["inst_net_buy"],
                "frgn_hold_rt": latest["frgn_hold_rt"],
                "pnsn_net_buy": 0, # 네이버 상세 페이지에선 연기금 분리 불가 (KIS Fallback 필요)
                "history": history, # 과거 이력 전달 (사이클 분석용)
                "source": "naver"
            }
        except Exception as e:
            log_error(f"Naver Investor Fetch Error (Code: {code}): {e}")
            return None

    def get_market_open_status(self) -> Optional[bool]:
        """네이버 모바일 API를 통해 국내 증시의 실시간 개장 상태를 확인합니다.

        Returns:
            Optional[bool]: 개장 시 True, 마감 시 False, 확인 불가 시 None.
        """
        try:
            url = "https://m.stock.naver.com/api/index/KOSPI/basic"
            self._wait_for_domain_delta(url)
            res = self._session.get(url, timeout=5)
            if res.status_code == 200:
                status = res.json().get('marketStatus')
                if status:
                    return status == "OPEN"
        except Exception as e:
            from src.logger import log_error
            log_error(f"⚠️ 시장 상태 조회 오류: {e}")
        return None
