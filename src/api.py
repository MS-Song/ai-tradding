import requests
import json
import time
from typing import List, Tuple, Optional
from src.auth import KISAuth
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

class KISAPI:
    def __init__(self, auth: KISAuth):
        self.auth = auth
        self.domain = auth.domain
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self._hot_cache, self._last_hot_time = [], 0
        self._vol_cache, self._last_vol_time = [], 0
        self._detail_cache = {} # {code: (timestamp, data)}
        self._cache_duration = 60
        self._detail_cache_duration = 3600 # 펀더멘털 데이터는 1시간 캐시
    def _safe_float(self, val):
        try:
            if val is None or str(val).strip() == "": return 0.0
            return float(str(val).replace(',', '').strip())
        except: return 0.0

    def _request(self, method, url, **kwargs):
        if self.auth.is_virtual: time.sleep(1.2)
        else: time.sleep(1.1)
        return requests.request(method, url, **kwargs)

    def get_full_balance(self, force=False) -> Tuple[List[dict], dict]:
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self.auth.get_auth_headers()
        headers.update({"tr_id": "VTTC8434R" if self.auth.is_virtual else "TTTC8434R"})
        params = {
            "CANO": self.auth.cano, "ACNT_PRDT_CD": "01",
            "AFHR_FLPR_YN": "N", "OFL_YN": "",
            "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") != "0": return [], {"total_asset":0, "stock_eval":0, "cash":0, "pnl":0, "deposit":0}
            raw_holdings = data.get("output1", [])
            holdings = []
            for h in raw_holdings:
                qty = int(self._safe_float(h.get('hldg_qty', 0)))
                if qty <= 0: continue
                
                # 수치 데이터 안전하게 추출
                pchs_avg = self._safe_float(h.get('pchs_avg_pric', 0))
                prpr = self._safe_float(h.get('prpr', 0))
                evlu_amt = self._safe_float(h.get('evlu_amt', 0))
                evlu_pfls_rt = self._safe_float(h.get('evlu_pfls_rt', 0))
                
                # 전일 대비 변동 데이터 수집 및 폴백 로직
                vrss = self._safe_float(h.get('prdy_vrss', 0))
                ctrt = self._safe_float(h.get('prdy_ctrt', 0))
                bfdy = self._safe_float(h.get('bfdy_zprc', 0))
                
                # 폴백: 전일대비 데이터가 0인데 전일종가가 있는 경우 계산
                if vrss == 0 and bfdy > 0 and prpr > 0:
                    vrss = prpr - bfdy
                    ctrt = (vrss / bfdy) * 100
                else:
                    # 부호 보정
                    sign = h.get('prdy_vrss_sign', '3')
                    if sign == '5': # 하락
                        vrss = -abs(vrss)
                        if ctrt > 0: ctrt = -ctrt
                    elif sign == '2': # 상승
                        vrss = abs(vrss)
                        if ctrt < 0: ctrt = abs(ctrt)

                holdings.append({
                    "pdno": h.get("pdno"), "prdt_name": h.get("prdt_name"),
                    "hldg_qty": str(qty), "pchs_avg_pric": str(pchs_avg),
                    "prpr": str(prpr), "evlu_amt": str(evlu_amt), "evlu_pfls_rt": str(evlu_pfls_rt),
                    "evlu_pfls_amt": h.get("evlu_pfls_amt", "0"),
                    "prdy_vrss": str(vrss), "prdy_ctrt": str(ctrt)
                })
            raw_summary = data.get("output2", [{}])[0]
            # 실제 주식 앱 기준 매핑: 
            # - stock_eval: 주식평가금액 합계
            # - cash: D+2 예상예수금 (가용 현금)
            # - total_asset: 주식평가액 + 예수금
            # - pnl: 평가손익 합계
            stock_eval = self._safe_float(raw_summary.get("evlu_amt_smtl_amt"))
            stock_principal = self._safe_float(raw_summary.get("pchs_amt_smtl_amt"))
            # D+0(dnca_tot_amt) 사용 시 미결제 주식 이중합산 오류 발생! 
            # D+2(prvs_rcdl_excc_amt) 가수도정산금액을 실질 가용 현금(Cash)으로 사용
            cash = self._safe_float(raw_summary.get("prvs_rcdl_excc_amt")) 
            if cash == 0: cash = self._safe_float(raw_summary.get("dnca_tot_amt"))
            
            pnl = self._safe_float(raw_summary.get("evlu_pfls_smtl_amt"))
            total_asset = self._safe_float(raw_summary.get("tot_evlu_amt"))
            
            asset_info = {
                "total_asset": total_asset,
                "total_principal": stock_principal + cash,
                "stock_eval": stock_eval,
                "stock_principal": stock_principal,
                "cash": cash,
                "pnl": pnl,
                "deposit": self._safe_float(raw_summary.get("prvs_rcdl_exca_amt") or 0)
            }
            return holdings, asset_info
        except: return [], {"total_asset":0, "total_principal":0, "stock_eval":0, "stock_principal":0, "cash":0, "pnl":0, "deposit":0}

    def get_balance(self): return self.get_full_balance()[0]

    def get_inquire_price(self, code: str) -> Optional[dict]:
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_auth_headers(); headers.update({"tr_id": "FHKST01010100"})
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=5)
            d = res.json().get("output", {})
            return {
                "price": self._safe_float(d.get("stck_prpr")), 
                "vrss": self._safe_float(d.get("prdy_vrss")),
                "ctrt": self._safe_float(d.get("prdy_ctrt")),
                "vol": self._safe_float(d.get("acml_vol")),
                "prev_vol": self._safe_float(d.get("prdy_vol")), 
                "high": self._safe_float(d.get("stck_hgpr")), 
                "low": self._safe_float(d.get("stck_lwpr"))
            }
        except: return None

    def order_market(self, code: str, qty: int, is_buy: bool, price: int = 0) -> Tuple[bool, str]:
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self.auth.get_auth_headers()
        tr_id = "VTTC0802U" if is_buy else "VTTC0801U"
        if not self.auth.is_virtual: tr_id = "TTTC0802U" if is_buy else "TTTC0801U"
        headers.update({"tr_id": tr_id})
        dvsn = "01" if price == 0 else "00"
        unpr = "0" if price == 0 else str(int(price))
        body = {"CANO": self.auth.cano, "ACNT_PRDT_CD": "01", "PDNO": code, "ORD_DVSN": dvsn, "ORD_QTY": str(int(qty)), "ORD_UNPR": unpr}
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=5)
            data = res.json()
            if data.get("rt_cd") == "0": return True, "성공"
            return False, data.get("msg1", "오류")
        except Exception as e: return False, f"API 오류: {e}"

    def get_index_price(self, iscd="0001"):
        symbol_map = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "KPI200": "069500.KS", "VOSPI": "^VIX", "FX_USDKRW": "USDKRW=X",
                      "DOW": "^DJI", "NASDAQ": "^IXIC", "S&P500": "^GSPC", "NAS_FUT": "NQ=F", "SPX_FUT": "ES=F",
                      "BTC_USD": "BTC-USD", "BTC_KRW": "BTC-KRW"}
        symbol = symbol_map.get(iscd, iscd)
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            data = res.json()
            if 'chart' in data and data['chart']['result']:
                meta = data['chart']['result'][0]['meta']
                curr_p = meta.get('regularMarketPrice', meta.get('chartPreviousClose', 0))
                prev_c = meta.get('previousClose', 0)
                rate = ((curr_p - prev_c) / prev_c * 100) if prev_c != 0 else 0
                return {"name": iscd, "price": curr_p, "rate": rate}
        except: pass
        return None

    def get_naver_stock_detail(self, code: str) -> dict:
        """네이버 금융 상세 페이지에서 핵심 시세 정보 및 펀더멘털 지표 수집 (캐시 적용)"""
        curr_t = time.time()
        if code in self._detail_cache:
            ts, data = self._detail_cache[code]
            if curr_t - ts < self._detail_cache_duration: return data

        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            res = requests.get(url, headers=self.headers, timeout=5)
            if not BeautifulSoup: return {}
            # euc-kr보다 호환성이 높은 cp949로 바이너리 직접 디코딩
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            
            detail = {"name": "Unknown", "price": "0", "rate": 0.0, "per": "N/A", "pbr": "N/A", "yield": "N/A", "sector_per": "N/A", "market_cap": "N/A"}
            
            # 1. 종목명 수집
            wrap = soup.find('div', {'class': 'wrap_company'})
            if wrap and wrap.h2: detail["name"] = wrap.h2.text.strip()
            
            # 2. 실시간 시세 및 등락률 수집
            today = soup.find('div', {'class': 'today'})
            if today:
                p_tag = today.find('em', {'class': 'no_up'}) or today.find('em', {'class': 'no_down'}) or today.find('em', {'class': 'no_none'})
                if p_tag: detail["price"] = p_tag.text.strip().replace(',', '').split()[0]
                
                # 등락률 파싱 (상승/하락/보합 케이스 대응)
                rate_area = today.find('p', {'class': 'no_up'}) or today.find('p', {'class': 'no_down'}) or today.find('p', {'class': 'no_none'})
                if rate_area:
                    rate_val = rate_area.find('span', {'class': 'blind'})
                    if rate_val:
                        r_txt = rate_val.text.strip()
                        try:
                            val_match = re.search(r'\d+\.\d+', r_txt)
                            if val_match:
                                val = float(val_match.group())
                                detail["rate"] = val if "플러스" in r_txt else -val if "마이너스" in r_txt else 0.0
                        except: pass

            # 3. 펀더멘털 지표 및 시가총액 수집
            aside = soup.find('div', {'class': 'aside_invest_info'})
            if aside:
                per_tag = aside.find('em', {'id': '_per'})
                if per_tag: detail["per"] = per_tag.text.strip()
                pbr_tag = aside.find('em', {'id': '_pbr'})
                if pbr_tag: detail["pbr"] = pbr_tag.text.strip()
                yield_tag = aside.find('em', {'id': '_dvr'})
                if yield_tag: detail["yield"] = yield_tag.text.strip()
                s_per_tag = aside.find('em', {'id': '_cper'})
                if s_per_tag: detail["sector_per"] = s_per_tag.text.strip()
                
                # 시가총액
                cap_area = aside.find('th', string='시가총액')
                if cap_area and cap_area.find_next_sibling('td'):
                    detail["market_cap"] = cap_area.find_next_sibling('td').text.strip().replace('\t','').replace('\n','')
            
            self._detail_cache[code] = (curr_t, detail)
            return detail
        except: return {"name": "Error", "price": "0", "rate": 0.0, "per": "N/A", "pbr": "N/A", "yield": "N/A", "sector_per": "N/A", "market_cap": "N/A"}

    def get_naver_stock_news(self, code: str) -> List[str]:
        """네이버 금융 뉴스 섹션에서 최신 헤드라인 수집"""
        try:
            url = f"https://finance.naver.com/item/news.naver?code={code}"
            res = requests.get(url, headers=self.headers, timeout=5)
            if not BeautifulSoup: return []
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            
            news_list = []
            table = soup.find('table', {'class': 'type5'})
            if table:
                titles = table.find_all('td', {'class': 'title'})
                for t in titles[:3]:
                    news_list.append(t.text.strip())
            return news_list
        except: return []

    def get_naver_hot_stocks(self) -> List[dict]:
        curr_t = time.time()
        if self._hot_cache and (curr_t - self._last_hot_time < 60): return self._hot_cache
        results = []
        try:
            url = "https://finance.naver.com/sise/lastsearch2.naver"
            res = requests.get(url, headers=self.headers, timeout=5)
            if not BeautifulSoup: return self._hot_cache or []
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            table = soup.find('table', {'class': 'type_5'})
            if table:
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) > 5:
                        a = cols[1].find('a')
                        if a:
                            try:
                                name = a.text.strip()
                                code = a['href'].split('=')[-1].strip()
                                if not code.isdigit(): continue  # 비정상 코드 건너뜀
                                rate_txt = cols[5].text.strip().replace('%', '').replace('+', '')
                                try:
                                    rate = float(rate_txt)
                                    if cols[4].find('img') and 'down' in cols[4].find('img')['src'].lower(): rate = -rate
                                except: rate = 0.0
                                price_txt = cols[3].text.replace(',', '').strip()
                                mkt = "KSP" if int(code) < 300000 else "KDQ"
                                results.append({"code": code, "name": name, "price": price_txt, "rate": rate, "mkt": mkt})
                            except Exception: continue  # row 파싱 실패 시 건너뜀
            if results:  # 성공적으로 수집된 경우에만 캐시 갱신
                self._hot_cache = results[:20]
                self._last_hot_time = curr_t
            return self._hot_cache or []
        except Exception as e:
            try:
                from src.logger import log_error
                log_error(f"get_naver_hot_stocks Error: {e}")
            except: pass
            return self._hot_cache or []  # 실패 시 기존 캐시 반환

    def get_naver_volume_stocks(self) -> List[dict]:
        curr_t = time.time()
        if self._vol_cache and (curr_t - self._last_vol_time < 60): return self._vol_cache
        results = []
        try:
            for sosok in ["0", "1"]:
                url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
                res = requests.get(url, headers=self.headers, timeout=5)
                if not BeautifulSoup: return self._vol_cache or []
                soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
                table = soup.find('table', {'class': 'type_2'})
                if table:
                    for row in table.find_all('tr'):
                        cols = row.find_all('td')
                        if len(cols) > 5:
                            a = cols[1].find('a')
                            if a:
                                try:
                                    name = a.text.strip()
                                    code = a['href'].split('=')[-1].strip()
                                    if not code.isdigit(): continue  # 비정상 코드 건너뜀
                                    rate_txt = cols[4].text.strip().replace('%', '').replace('+', '')
                                    try:
                                        rate = float(rate_txt)
                                        if cols[3].find('img') and 'down' in cols[3].find('img')['src'].lower(): rate = -rate
                                    except: rate = 0.0
                                    price_txt = cols[2].text.replace(',', '').strip()
                                    results.append({"code": code, "name": name, "price": price_txt, "rate": rate, "mkt": "KSP" if sosok == "0" else "KDQ"})
                                except Exception: continue  # row 파싱 실패 시 건너뜀
            if results:  # 성공적으로 수집된 경우에만 캐시 갱신
                self._vol_cache = results[:40]
                self._last_vol_time = curr_t
            return self._vol_cache or []
        except Exception as e:
            try:
                from src.logger import log_error
                log_error(f"get_naver_volume_stocks Error: {e}")
            except: pass
            return self._vol_cache or []  # 실패 시 기존 캐시 반환

    def get_naver_theme_data(self) -> dict:
        """네이버 금융에서 전체 테마 및 구성 종목 데이터를 수집하여 딕셔너리로 반환"""
        theme_map = {}
        try:
            # 1. 테마 리스트 페이지 (최대 10페이지까지 크롤링하여 전체 테마 확보)
            for page in range(1, 11):
                url = f"https://finance.naver.com/sise/theme.naver?&page={page}"
                res = requests.get(url, headers=self.headers, timeout=10)
                if not BeautifulSoup: return {}
                soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
                
                table = soup.find('table', {'class': 'type_1'})
                if not table: break
                
                # 'col_type1' 클래스를 가진 td 안의 a 태그가 테마 링크
                links = table.find_all('td', {'class': 'col_type1'})
                found_on_page = False
                for l in links:
                    a = l.find('a')
                    if a and 'sise_group_detail.naver' in a['href']:
                        found_on_page = True
                        theme_name = a.text.strip()
                        theme_url = "https://finance.naver.com" + a['href']
                        
                        # 2. 각 테마의 상세 페이지에서 종목 리스트 수집
                        try:
                            # 상세 페이지 요청 간격 조절 (부하 방지)
                            time.sleep(0.1)
                            res_d = requests.get(theme_url, headers=self.headers, timeout=5)
                            soup_d = BeautifulSoup(res_d.content, 'html.parser', from_encoding='cp949')
                            
                            stocks = []
                            table_d = soup_d.find('table', {'class': 'type_5'})
                            if table_d:
                                for row in table_d.find_all('tr'):
                                    name_td = row.find('td', {'class': 'name'})
                                    if name_td and name_td.find('a'):
                                        a_s = name_td.find('a')
                                        stock_name = a_s.text.strip()
                                        stock_code = a_s['href'].split('=')[-1]
                                        stocks.append({"name": stock_name, "code": stock_code})
                            
                            if stocks:
                                theme_map[theme_name] = stocks
                        except: continue
                
                if not found_on_page: break
            return theme_map
        except Exception as e:
            try:
                from src.logger import log_error
                log_error(f"get_naver_theme_data Error: {e}")
            except: pass
            return {}
