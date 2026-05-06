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
        if cached and (curr_t - cached[0]) < 20: return cached[1]

        # 국장 지수는 네이버(Naver)를 최우선으로 수집 (Yahoo는 지연/프리징 발생 잦음)
        if iscd in ["KOSPI", "KOSDAQ", "KPI200", "VOSPI"]:
            try:
                res = self._index_src_fetch_naver_api(iscd)
                if res:
                    self._index_cache[iscd] = (curr_t, res)
                    return res
            except Exception as e:
                from src.logger import log_error
                log_error(f"⚠️ Naver 국장 지수 수집 오류 ({iscd}): {e}")
            
            # 네이버 실패 시 야후 시도
            try:
                res = self._index_src_fetch_yahoo(iscd)
                if res:
                    self._index_cache[iscd] = (curr_t, res)
                    return res
            except Exception as e:
                pass
            return None

        # 그 외(해외 지수 등)는 Yahoo를 최우선으로 수집
        try:
            res = self._index_src_fetch_yahoo(iscd)
            if res:
                self._index_cache[iscd] = (curr_t, res)
                return res
        except requests.exceptions.Timeout:
            pass  # 타임아웃은 조용히 Naver로 폴백
        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                pass
            else:
                from src.logger import log_error
                log_error(f"⚠️ Yahoo 지수 수집 오류 ({iscd}): {e}")

        # 2. Naver 시도 (Fallback)
        try:
            res = self._index_src_fetch_naver_api(iscd)
            if res:
                self._index_cache[iscd] = (curr_t, res)
                return res
        except Exception as e:
            from src.logger import log_error
            log_error(f"⚠️ Naver 지수 수집 오류 ({iscd}): {e}")
            
        return None

    def _index_src_fetch_yahoo(self, iscd: str) -> Optional[dict]:
        # 야후에서 지원하지 않거나 404가 발생하는 심볼은 네이버로 즉시 패스
        if iscd in ["KPI200", "VOSPI"]:
            return None

        symbol_map = {
            "KOSPI": "^KS11", "KOSDAQ": "^KQ11", "FX_USDKRW": "USDKRW=X",
            "DOW": "^DJI", "NASDAQ": "^IXIC", "S&P500": "^GSPC",
            "NAS_FUT": "NQ=F", "SPX_FUT": "ES=F", "BTC_USD": "BTC-USD",
            "BTC_KRW": "BTC-KRW"
        }
        target = symbol_map.get(iscd, iscd)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{target}?interval=1m&range=1d"
        res = requests.get(url, headers=self.headers, timeout=10)
        if res.status_code != 200:
            raise Exception(f"HTTP {res.status_code}")
        data = res.json()
        try:
            meta = data['chart']['result'][0]['meta']
            curr_p = meta.get('regularMarketPrice', 0)
            prev_c = meta.get('previousClose', 0)
            rate = ((curr_p - prev_c) / prev_c * 100) if prev_c else 0
            return {"name": iscd, "price": curr_p, "rate": rate, "source": "Yahoo API"}
        except Exception as e:
            raise Exception(f"Data Parse Error: {e}")

    def _index_src_fetch_naver_api(self, iscd: str) -> Optional[dict]:
        # 국장 지수: 모바일 API -> 웹 크롤링 2단계 시도
        kr_map = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KPI200": "KPI200", "VOSPI": "VOSPI"}
        if iscd in kr_map:
            # Step 1: Mobile API
            try:
                url = f"https://m.stock.naver.com/api/index/{kr_map[iscd]}/basic"
                res = requests.get(url, headers=self.headers, timeout=5)
                if res.status_code == 200:
                    d = res.json()
                    return {
                        "name": iscd, 
                        "price": float(d['closePrice'].replace(',', '')), 
                        "rate": float(d['fluctuationsRatio']),
                        "source": "Naver API"
                    }
            except: pass
            
            # Step 2: Web Scraping (Last Resort)
            try:
                from bs4 import BeautifulSoup
                code_map = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
                url = f"https://finance.naver.com/sise/sise_index.naver?code={code_map[iscd]}"
                res = requests.get(url, headers=self.headers, timeout=5)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
                    price_val = soup.find('em', {'id': 'now_value'})
                    if price_val:
                        price = float(price_val.text.replace(',', ''))
                        rate_val = soup.find('span', {'id': 'change_value_and_rate'})
                        rate = 0.0
                        if rate_val:
                            # 텍스트 예: "15.22 +0.57%"
                            parts = rate_val.text.strip().split()
                            if len(parts) >= 2:
                                rate = float(parts[1].replace('%', '').replace('+', ''))
                                if '하락' in rate_val.get('class', []) or 'nv01' in str(rate_val):
                                    rate = -abs(rate)
                        return {"name": iscd, "price": price, "rate": rate, "source": "Naver Crawling"}
            except: pass
        
        # 해외 지수: 모바일 API 지원 확대 (DOW, NAS, S&P)
        world_map = {"NASDAQ": "NAS@IXIC", "DOW": "DJI@DJI", "S&P500": "SPI@SPX"}
        if iscd in world_map:
            try:
                url = f"https://m.stock.naver.com/api/index/world/{world_map[iscd]}/basic"
                res = requests.get(url, headers=self.headers, timeout=5)
                if res.status_code == 200:
                    d = res.json()
                    return {
                        "name": iscd,
                        "price": float(d['closePrice'].replace(',', '')),
                        "rate": float(d['fluctuationsRatio']),
                        "source": "Naver API"
                    }
            except: pass

        return None

    def get_multiple_index_prices(self, symbol_map: dict) -> dict:
        """[최적화] ThreadPoolExecutor를 사용하여 지수 데이터를 병렬로 수집합니다."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = {}
        
        # 1. 캐시 확인 및 즉시 반환 가능 항목 필터링
        curr_t = time.time()
        remaining_tasks = {}
        for s, code in symbol_map.items():
            cached = self._index_cache.get(code)
            if cached and (curr_t - cached[0]) < 20:
                results[s] = cached[1]
            else:
                remaining_tasks[s] = code
        
        if not remaining_tasks:
            return results

        # 2. 캐시되지 않은 항목 병렬 요청
        with ThreadPoolExecutor(max_workers=min(len(remaining_tasks), 10)) as executor:
            future_to_symbol = {executor.submit(self.get_index_price, code): s for s, code in remaining_tasks.items()}
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    res = future.result()
                    if res: results[symbol] = res
                except: pass
        return results
