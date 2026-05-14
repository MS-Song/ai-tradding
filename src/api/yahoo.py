import requests
import time
from typing import Optional, Dict
from src.api.base import BaseAPI

class YahooAPIClient(BaseAPI):
    """Yahoo Finance 및 Naver Finance를 통한 글로벌 지수 수집 클라이언트.
    
    Yahoo Finance API를 주 데이터 소스로 사용하되, 국내 지수(KOSPI, KOSDAQ)의 정확성과 
    해외 지수 지연 방지를 위해 Naver Finance API 및 웹 크롤링을 Fallback으로 활용하는 
    하이브리드 지수 수집 엔진입니다.

    Attributes:
        _index_cache (dict): 지수별 최근 데이터 캐시 (Time, Data).
        _index_src (str): 현재 주력 데이터 소스.
    """
    def __init__(self):
        """YahooAPIClient를 초기화합니다.
        
        기본 소스인 Yahoo Finance와 보조 소스인 Naver Finance에 대한 
        캐시 및 상태 정보를 초기화합니다.
        """
        super().__init__()
        self._index_cache = {}
        self._index_src = "yahoo"
        self._index_src_fail_counts = {"yahoo": 0, "naver_api": 0}
        self._session = requests.Session()
        self._session.headers.update(self.headers)

    def get_index_price(self, iscd: str) -> Optional[dict]:
        """특정 지수의 현재가와 등락률을 조회합니다.

        국내 지수는 Naver를 최우선으로, 해외 지수는 Yahoo를 최우선으로 조회하며 
        장애 발생 시 상호 Fallback 처리합니다. 20초간 유효한 로컬 캐시를 사용합니다.

        Args:
            iscd (str): 지수 심볼명 (예: KOSPI, NASDAQ, BTC_USD).

        Returns:
            Optional[dict]: 지수 정보(price, rate, source 등)가 포함된 딕셔너리 또는 None.
        """
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
            # ConnectionResetError 등 일시적 오류는 우선 Naver 시도 (로그는 워닝으로)
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                pass
            else:
                from src.logger import logger
                logger.warning(f"⚠️ Yahoo 지수 수집 1차 시도 실패 ({iscd}): {e}")

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
        """Yahoo Finance v8 API를 통해 지수 데이터를 수집합니다.

        Args:
            iscd (str): 지수 심볼명.

        Returns:
            Optional[dict]: 수집된 지수 정보. 실패 시 Exception 발생 또는 None 반환.
        """
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
        
        max_retries = 2
        last_err = None
        for i in range(max_retries + 1):
            try:
                self._wait_for_domain_delta(url)
                res = self._session.get(url, timeout=10)
                if res.status_code != 200:
                    raise Exception(f"HTTP {res.status_code}")
                data = res.json()
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                last_err = e
                if i < max_retries:
                    time.sleep(1 * (i + 1))
                    continue
                raise e
            except Exception as e:
                raise e

        try:
            meta = data['chart']['result'][0]['meta']
            curr_p = meta.get('regularMarketPrice', 0)
            prev_c = meta.get('previousClose', 0)
            rate = ((curr_p - prev_c) / prev_c * 100) if prev_c else 0
            return {"name": iscd, "price": curr_p, "rate": rate, "source": "Yahoo API"}
        except Exception as e:
            raise Exception(f"Data Parse Error: {e}")

    def _index_src_fetch_naver_api(self, iscd: str) -> Optional[dict]:
        """Naver Mobile API 및 웹 크롤링을 통해 지수 데이터를 수집합니다. (Fallback용)

        Args:
            iscd (str): 지수 심볼명.

        Returns:
            Optional[dict]: 수집된 지수 정보. 모든 단계 실패 시 None 반환.
        """
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
        
        # 해외 지수 및 환율: 모바일 API 지원 확대 (DOW, NAS, S&P, FX)
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

        # 원/달러 환율 전용 API (Fallback)
        if iscd == "FX_USDKRW":
            try:
                url = "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW"
                res = requests.get(url, headers=self.headers, timeout=5)
                if res.status_code == 200:
                    d = res.json()
                    return {
                        "name": iscd,
                        "price": float(d['closePrice'].replace(',', '')),
                        "rate": float(d['fluctuationsRatio']),
                        "source": "Naver FX API"
                    }
            except: pass

        return None

    def get_multiple_index_prices(self, symbol_map: dict) -> dict:
        """ThreadPoolExecutor를 사용하여 여러 지수 데이터를 병렬로 수집합니다.

        Args:
            symbol_map (dict): {내부_식별자: 외부_심볼} 형태의 맵.

        Returns:
            dict: 수집된 지수 정보 결과 맵.
        """
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
