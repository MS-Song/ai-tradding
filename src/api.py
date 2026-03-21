import requests
import json
import time
from typing import List, Tuple, Optional
from src.auth import KISAuth

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
        self._cache_duration = 60 

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
                holdings.append({
                    "pdno": h.get("pdno"), "prdt_name": h.get("prdt_name"),
                    "hldg_qty": str(qty), "pchs_avg_pric": h.get("pchs_avg_pric"),
                    "prpr": h.get("prpr"), "evlu_amt": h.get("evlu_amt"), "evlu_pfls_rt": h.get("evlu_pfls_rt")
                })
            raw_summary = data.get("output2", [{}])[0]
            asset_info = {
                "total_asset": self._safe_float(raw_summary.get("tot_evlu_amt")),
                "stock_eval": self._safe_float(raw_summary.get("evlu_amt_smtl_amt")),
                "cash": self._safe_float(raw_summary.get("dnca_tot_amt")),
                "pnl": self._safe_float(raw_summary.get("evlu_pfls_smtl_amt")),
                "deposit": self._safe_float(raw_summary.get("prvs_rcdl_exca_amt") or 0)
            }
            return holdings, asset_info
        except: return [], {"total_asset":0, "stock_eval":0, "cash":0, "pnl":0, "deposit":0}

    def get_balance(self): return self.get_full_balance()[0]

    def get_inquire_price(self, code: str) -> Optional[dict]:
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_auth_headers(); headers.update({"tr_id": "FHKST01010100"})
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=5)
            d = res.json().get("output", {})
            return {"price": self._safe_float(d.get("stck_prpr")), "vol": self._safe_float(d.get("acml_vol")),
                    "prev_vol": self._safe_float(d.get("prdy_vol")), "high": self._safe_float(d.get("stck_hgpr")), "low": self._safe_float(d.get("stck_lwpr"))}
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
                      "DOW": "^DJI", "NASDAQ": "^IXIC", "S&P500": "^GSPC", "NAS_FUT": "NQ=F", "SPX_FUT": "ES=F"}
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

    def get_naver_hot_stocks(self) -> List[dict]:
        curr_t = time.time()
        if self._hot_cache and (curr_t - self._last_hot_time < 60): return self._hot_cache
        results = []
        try:
            url = "https://finance.naver.com/sise/lastsearch2.naver"
            res = requests.get(url, headers=self.headers, timeout=5)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(res.text, 'html.parser')
            table = soup.find('table', {'class': 'type_5'})
            if table:
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) > 5:
                        a = cols[1].find('a')
                        if a:
                            name, code = a.text.strip(), a['href'].split('=')[-1]
                            rate_txt = cols[5].text.strip().replace('%', '').replace('+', '')
                            try:
                                rate = float(rate_txt)
                                if cols[4].find('img') and 'down' in cols[4].find('img')['src'].lower(): rate = -rate        
                            except: rate = 0.0
                            results.append({"code": code, "name": name, "price": cols[3].text.replace(',','').strip(), "rate": rate, "mkt": "KSP" if int(code) < 300000 else "KDQ"})
            self._hot_cache = results[:20]; self._last_hot_time = curr_t
            return results[:20]
        except: return []

    def get_naver_volume_stocks(self) -> List[dict]:
        curr_t = time.time()
        if self._vol_cache and (curr_t - self._last_vol_time < 60): return self._vol_cache
        results = []
        try:
            # sosok=0(코스피), sosok=1(코스닥) 통합 수집
            for sosok in ["0", "1"]:
                url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
                res = requests.get(url, headers=self.headers, timeout=5)
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(res.text, 'html.parser')
                table = soup.find('table', {'class': 'type_2'})
                if table:
                    for row in table.find_all('tr'):
                        cols = row.find_all('td')
                        if len(cols) > 5:
                            a = cols[1].find('a')
                            if a:
                                name, code = a.text.strip(), a['href'].split('=')[-1]
                                rate_txt = cols[4].text.strip().replace('%', '').replace('+', '')
                                try:
                                    rate = float(rate_txt)
                                    if cols[3].find('img') and 'down' in cols[3].find('img')['src'].lower(): rate = -rate        
                                except: rate = 0.0
                                results.append({"code": code, "name": name, "price": cols[2].text.replace(',','').strip(), "rate": rate, "mkt": "KSP" if sosok == "0" else "KDQ"})
            # 셔플 및 정렬 후 상위 40개 선정
            self._vol_cache = results[:40]; self._last_vol_time = curr_t
            return self._vol_cache
        except: return []
