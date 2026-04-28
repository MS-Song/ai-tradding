import requests
import time
from typing import Optional, Dict
from src.api.base import BaseAPI

class YahooAPIClient(BaseAPI):
    def __init__(self):
        super().__init__()
        self._index_cache = {}
        self._index_src = "yahoo"
        self._index_src_fail_counts = {"yahoo": 0, "naver_api": 0}

    def get_index_price(self, iscd: str) -> Optional[dict]:
        curr_t = time.time()
        cached = self._index_cache.get(iscd)
        if cached and (curr_t - cached[0]) < 120: return cached[1]

        # 1. Yahoo 시도
        try:
            res = self._index_src_fetch_yahoo(iscd)
            if res:
                self._index_cache[iscd] = (curr_t, res)
                return res
        except: pass

        # 2. Naver 시도 (Fallback)
        try:
            res = self._index_src_fetch_naver_api(iscd)
            if res:
                self._index_cache[iscd] = (curr_t, res)
                return res
        except: pass
        return None

    def _index_src_fetch_yahoo(self, iscd: str) -> Optional[dict]:
        symbol_map = {
            "KOSPI": "^KS11", "KOSDAQ": "^KQ11", "FX_USDKRW": "USDKRW=X",
            "DOW": "^DJI", "NASDAQ": "^IXIC", "S&P500": "^GSPC",
            "NAS_FUT": "NQ=F", "SPX_FUT": "ES=F", "BTC_USD": "BTC-USD"
        }
        target = symbol_map.get(iscd, iscd)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{target}?interval=1m&range=1d"
        self._wait_for_domain_delta(url)
        res = requests.get(url, headers=self.headers, timeout=5)
        if res.status_code != 200: return None
        data = res.json()
        meta = data['chart']['result'][0]['meta']
        curr_p = meta.get('regularMarketPrice', 0)
        prev_c = meta.get('previousClose', 0)
        rate = ((curr_p - prev_c) / prev_c * 100) if prev_c else 0
        return {"name": iscd, "price": curr_p, "rate": rate}

    def _index_src_fetch_naver_api(self, iscd: str) -> Optional[dict]:
        kr_map = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
        if iscd in kr_map:
            url = f"https://m.stock.naver.com/api/index/{kr_map[iscd]}/basic"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=5)
            d = res.json()
            return {"name": iscd, "price": float(d['closePrice'].replace(',', '')), "rate": float(d['fluctuationsRatio'])}
        return None

    def get_multiple_index_prices(self, symbol_map: dict) -> dict:
        results = {}
        for s, code in symbol_map.items():
            res = self.get_index_price(code)
            if res: results[s] = res
        return results
