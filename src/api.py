import requests
import json
import time
import random
from typing import List, Tuple, Optional
from datetime import datetime
from src.auth import KISAuth
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

import threading
from urllib.parse import urlparse

from src.utils import retry_api

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
        self._chart_cache = {} # {code_type: (timestamp, data)}
        self._cache_duration = 60
        self._detail_cache_duration = 120 # 펀더멘털 데이터 실시간성 강화를 위해 2분 캐시
        self._index_cache = {}           # {iscd: (timestamp, data)}
        self._index_src = "yahoo"        # 현재 활성 소스: yahoo | naver_api | naver_crawl
        self._index_src_fail_counts = {"yahoo": 0, "naver_api": 0, "naver_crawl": 0}
        self._index_src_disable_until = {"yahoo": 0, "naver_api": 0, "naver_crawl": 0}

        # 도메인별 쓰로틀링 (Throttling) 설정
        self._domain_lock = threading.Lock()
        self._last_request_times = {} # {domain: timestamp}
        self._min_interval = 0.33      # 초당 3회 초과 요청 방지 (0.33초 간격)

    def _wait_for_domain_delta(self, url: str):
        """동일 도메인에 대해 일정 시간 간격(self._min_interval)을 두고 호출하도록 제어"""
        domain = urlparse(url).netloc
        with self._domain_lock:
            last_t = self._last_request_times.get(domain, 0)
            now = time.time()
            wait_t = last_t + self._min_interval - now
            if wait_t > 0:
                time.sleep(wait_t)
            self._last_request_times[domain] = time.time()

    def _get_cached_chart(self, key: str, ttl: int = 300) -> Optional[List[dict]]:
        """메모리 내 차트 데이터 캐시 조회 (기본 5분 유효)"""
        if key in self._chart_cache:
            ts, data = self._chart_cache[key]
            if time.time() - ts < ttl: return data
        return None

    def _set_cached_chart(self, key: str, data: List[dict]):
        self._chart_cache[key] = (time.time(), data)

    def _safe_float(self, val):
        try:
            if val is None or str(val).strip() == "": return 0.0
            return float(str(val).replace(',', '').strip())
        except: return 0.0

    def _request(self, method, url, **kwargs):
        if self.auth.is_virtual: time.sleep(1.2)
        else: time.sleep(1.1)
        return requests.request(method, url, **kwargs)

    def _wait_for_domain_delta(self, url: str):
        """동일 도메인에 대한 과도한 요청을 방지하기 위해 대기합니다. (Thread-safe)"""
        try:
            domain = urlparse(url).netloc
            if not domain: return
            
            with self._domain_lock:
                now = time.time()
                last_time = self._last_request_times.get(domain, 0)
                elapsed = now - last_time
                
                if elapsed < self._min_interval:
                    wait_time = self._min_interval - elapsed
                    time.sleep(wait_time)
                    now = time.time() # sleep 후 시간 갱신
                
                self._last_request_times[domain] = now
        except: pass

    @retry_api(max_retries=3, delay=1.5)
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

    @retry_api(max_retries=2, delay=1.2)
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

    @retry_api(max_retries=3, delay=2.0)
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

    @retry_api(max_retries=2, delay=2.0)
    def get_daily_chart_price(self, code: str, start_date: str = "", end_date: str = "") -> List[dict]:
        """국내주식 일봉 차트 조회 (FHKST03010100) + 캐싱 적용"""
        cache_key = f"day_{code}_{start_date}_{end_date}"
        cached = self._get_cached_chart(cache_key, ttl=1800) # 일봉은 30분 캐시
        if cached: return cached

        time.sleep(random.uniform(0.1, 0.3))
        
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        headers = self.auth.get_auth_headers()
        headers.update({"tr_id": "FHKST03010100"})
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "0"
        }
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") != "0": return []
            result = data.get("output2", [])
            if result: self._set_cached_chart(cache_key, result)
            return result
        except: return []

    @retry_api(max_retries=2, delay=1.5)
    def get_minute_chart_price(self, code: str, target_time: str = "") -> List[dict]:
        """국내주식 분봉 차트 조회 (FHKST03010200) + 캐싱 및 지터 적용"""
        cache_key = f"min_{code}_{target_time or 'now'}"
        cached = self._get_cached_chart(cache_key)
        if cached: return cached

        # Anti-Blocking Jitter
        time.sleep(random.uniform(0.1, 0.3))

        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = self.auth.get_auth_headers()
        headers.update({"tr_id": "FHKST03010200"})
        if not target_time:
            from datetime import datetime
            target_time = datetime.now().strftime('%H%M%S')
            if target_time > "153000": target_time = "153000"

        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_TM_1": target_time,
            "FID_PW_RES_PRC": "0"
        }
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") != "0": 
                # [Phase 3] KIS 실패 시 Naver Fallback
                return self._get_naver_minute_chart_fallback(code)
            result = data.get("output2", [])
            if not result: return self._get_naver_minute_chart_fallback(code)
            if result: self._set_cached_chart(cache_key, result)
            return result
        except: 
            return self._get_naver_minute_chart_fallback(code)

    def _get_naver_minute_chart_fallback(self, code: str) -> List[dict]:
        """KIS API 실패 시 네이버 금융 모바일 API를 통해 분봉 데이터를 가져옵니다 (Anti-Blocking)."""
        url = f"https://m.stock.naver.com/api/stock/{code}/chart/minute?count=60"
        try:
            time.sleep(random.uniform(0.2, 0.5)) # 분산 지터
            res = requests.get(url, timeout=5)
            if res.status_code != 200: return []
            data = res.json()
            
            # 네이버 데이터를 KIS 형식(output2)으로 변환
            # KIS 형식 필드: stck_clpr, stck_hgpr, stck_lwpr, stck_oprc, stck_cntg_vol
            # Naver 형식: { "price": ..., "high": ..., "low": ..., "open": ..., "volume": ..., "time": ... }
            converted = []
            for item in reversed(data.get("items", [])): # KIS는 최신순
                converted.append({
                    "stck_clpr": str(item["close"]),
                    "stck_hgpr": str(item["high"]),
                    "stck_lwpr": str(item["low"]),
                    "stck_oprc": str(item["open"]),
                    "cntg_vol": str(item["volume"]),
                    "stck_cntg_hour": item["time"][-6:] # HHMMSS
                })
            return converted
        except: return []

    def calculate_atr(self, code: str, period: int = 14) -> float:
        """최근 n일간의 ATR(Average True Range)을 계산합니다."""
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=period + 10)).strftime('%Y%m%d')
        
        candles = self.get_daily_chart_price(code, start_date, end_date)
        if len(candles) < period: return 0.0
        
        # candles는 최신순(역순)으로 오므로 정렬 필요 없음 (보통 KIS는 최신순)
        # TR 계산: Max((H-L), abs(H-PC), abs(L-PC))
        tr_list = []
        for i in range(len(candles) - 1): # 마지막 데이터는 이전 종가가 없으므로 제외
            curr = candles[i]
            prev = candles[i+1]
            
            h = float(curr.get('stck_hgpr', 0))
            l = float(curr.get('stck_lwpr', 0))
            pc = float(prev.get('stck_clpr', 0))
            
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)
            if len(tr_list) >= period: break
            
        if not tr_list: return 0.0
        return sum(tr_list) / len(tr_list)

    # ─────────────────────────────────────────────────────────────────
    # 지수 데이터 수집 3-소스 구조: yahoo → naver_api → naver_crawl
    # 각 소스가 실패하면 fail_count 증가 → 3회 초과 시 10분 차단
    # ─────────────────────────────────────────────────────────────────
    def _index_src_fetch_yahoo(self, iscd: str) -> Optional[dict]:
        """소스 1: Yahoo Finance v8 chart API"""
        import re
        symbol_map = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11", "KPI200": "069500.KS",
                      "VOSPI": "^VIX", "FX_USDKRW": "USDKRW=X",
                      "DOW": "^DJI", "NASDAQ": "^IXIC", "S&P500": "^GSPC",
                      "NAS_FUT": "NQ=F", "SPX_FUT": "ES=F",
                      "BTC_USD": "BTC-USD", "BTC_KRW": "BTC-KRW"}
        symbol = symbol_map.get(iscd, iscd)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        self._wait_for_domain_delta(url)
        res = requests.get(url, headers=self.headers, timeout=5)
        if res.status_code == 429:
            raise ConnectionError(f"Yahoo Finance 429 Rate Limit ({iscd})")
        res.raise_for_status()
        data = res.json()
        if not (data.get('chart', {}).get('result')): return None
        meta = data['chart']['result'][0]['meta']
        curr_p = meta.get('regularMarketPrice', meta.get('chartPreviousClose', 0))
        prev_c = meta.get('previousClose', 0)
        rate = ((curr_p - prev_c) / prev_c * 100) if prev_c else 0
        return {"name": iscd, "price": curr_p, "rate": rate}

    def _index_src_fetch_naver_api(self, iscd: str) -> Optional[dict]:
        """소스 2: 네이버 금융 모바일 JSON API / 업비트 공개 API"""
        kr_map = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KPI200": "KPI200"}
        if iscd in kr_map:
            url = f"https://m.stock.naver.com/api/index/{kr_map[iscd]}/basic"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=5)
            res.raise_for_status()
            d = res.json()
            return {"name": iscd, "price": float(d['closePrice'].replace(',', '')),
                    "rate": float(d['fluctuationsRatio'])}
        if iscd == "BTC_KRW":
            url = "https://api.upbit.com/v1/ticker?markets=KRW-BTC"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=5)
            res.raise_for_status()
            d = res.json()[0]
            return {"name": iscd, "price": d['trade_price'],
                    "rate": round(d['signed_change_rate'] * 100, 4)}
        if iscd == "BTC_USD":
            # USDT-BTC를 USD 대용으로 활용
            url = "https://api.upbit.com/v1/ticker?markets=USDT-BTC"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=5)
            res.raise_for_status()
            d = res.json()[0]
            return {"name": iscd, "price": d['trade_price'],
                    "rate": round(d['signed_change_rate'] * 100, 4)}
        return None  # 해당 소스에서 지원하지 않는 지수

    def _index_src_fetch_naver_crawl(self, iscd: str) -> Optional[dict]:
        """소스 3: 네이버 금융 HTML 크롤링 (글로벌 지수 / 환율)"""
        import re
        if not BeautifulSoup: return None

        def _parse_naver_world(symbol_str):
            url = f"https://finance.naver.com/world/sise.naver?symbol={symbol_str}"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=6)
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            p_str = soup.find('p', {'class': 'no_today'}).text.strip()
            p_val = float(re.search(r'[\d,.]+', p_str).group().replace(',', ''))
            r_str = soup.find('p', {'class': 'no_exday'}).text
            m = re.search(r'([\d.]+)\s*%', r_str)
            r_val = float(m.group(1)) if m else 0.0
            if '하락' in r_str and r_val > 0: r_val = -r_val
            return {"name": iscd, "price": p_val, "rate": r_val}

        world_map = {"DOW": "DJI@DJI", "NASDAQ": "NAS@IXIC", "S&P500": "SPI@SPX",
                     "NAS_FUT": "NAS@NASFUT", "SPX_FUT": "SPI@SPXFUT"}
        if iscd in world_map:
            return _parse_naver_world(world_map[iscd])

        if iscd == "FX_USDKRW":
            url = "https://finance.naver.com/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW"
            self._wait_for_domain_delta(url)
            res = requests.get(url, headers=self.headers, timeout=6)
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            p_val = float(re.search(r'[\d,.]+', soup.find('p', {'class': 'no_today'}).text).group().replace(',', ''))
            r_str = soup.find('p', {'class': 'no_exday'}).text
            m = re.search(r'([\d.]+)\s*%', r_str)
            r_val = float(m.group(1)) if m else 0.0
            if '하락' in r_str and r_val > 0: r_val = -r_val
            return {"name": iscd, "price": p_val, "rate": r_val}

        if iscd == "VOSPI":
            url = "https://finance.naver.com/world/sise.naver?symbol=VIX@VIX"
            return _parse_naver_world("VIX@VIX")

        return None  # 해당 소스에서 지원하지 않는 지수

    def get_index_price(self, iscd: str = "0001") -> Optional[dict]:
        """지수 데이터 수집 오케스트레이터: yahoo → naver_api → naver_crawl 순서로 시도.
        소스 실패 시 fail_count 증가, 3회 초과 시 해당 소스를 10분간 차단하고 다음 소스로 전환.
        모든 소스 실패 시 만료된 캐시를 최종 폴백으로 반환."""
        from src.logger import log_error
        curr_t = time.time()

        # 120초(2분) 캐시 체크
        cached = self._index_cache.get(iscd)
        if cached and (curr_t - cached[0]) < 120:
            return cached[1]

        SOURCES = [
            ("yahoo",        self._index_src_fetch_yahoo),
            ("naver_api",    self._index_src_fetch_naver_api),
            ("naver_crawl",  self._index_src_fetch_naver_crawl),
        ]
        prev_src = self._index_src

        for src_name, fetch_fn in SOURCES:
            # 차단 중인 소스 건너뜀
            if curr_t < self._index_src_disable_until.get(src_name, 0):
                continue
            try:
                result = fetch_fn(iscd)
                if result is None:
                    continue  # 해당 소스가 이 지수를 지원하지 않음 → 다음 소스로
                # 성공 처리
                self._index_src_fail_counts[src_name] = 0
                self._index_cache[iscd] = (curr_t, result)
                if src_name != prev_src:
                    self._index_src = src_name
                    log_error(f"[INDEX_SRC_SWITCH] {iscd}: {prev_src} → {src_name} 로 전환 성공")
                return result
            except ConnectionError as ce:
                # 429 전용 로그
                log_error(f"[INDEX_429] {src_name} | {iscd} | {ce}")
                self._index_src_fail_counts[src_name] = self._index_src_fail_counts.get(src_name, 0) + 1
                if self._index_src_fail_counts[src_name] >= 3:
                    self._index_src_disable_until[src_name] = curr_t + 600  # 10분 차단
                    log_error(f"[INDEX_SRC_BLOCK] {src_name} 3회 연속 실패 → 10분 차단")
            except Exception as e:
                log_error(f"[INDEX_ERR] {src_name} | {iscd} | {type(e).__name__}: {e}")
                self._index_src_fail_counts[src_name] = self._index_src_fail_counts.get(src_name, 0) + 1
                if self._index_src_fail_counts[src_name] >= 3:
                    self._index_src_disable_until[src_name] = curr_t + 600
                    log_error(f"[INDEX_SRC_BLOCK] {src_name} 3회 연속 실패 → 10분 차단")

        # 모든 소스 실패 → 만료된 캐시라도 반환
        if cached:
            log_error(f"[INDEX_CACHE_FALLBACK] {iscd}: 모든 소스 실패, 만료 캐시 반환")
            return cached[1]
        return None

    def get_multiple_index_prices(self, symbol_map: dict) -> dict:
        """여러 지수를 한 번에 효율적으로 조회 (Bulk). 야후 Bulk 및 업비트 멀티 티커 활용."""
        results = {}
        curr_t = time.time()
        
        # 1. 캐시 먼저 확인
        to_fetch = []
        for s, code in symbol_map.items():
            cached = self._index_cache.get(code)
            if cached and (curr_t - cached[0]) < 120:
                results[s] = cached[1]
            else:
                to_fetch.append((s, code))
        
        if not to_fetch: return results

        # 2. 업비트 코인 일괄 조회 (UPBIT)
        coins = [code for s, code in to_fetch if code in ["BTC_USD", "BTC_KRW"]]
        if coins:
            try:
                # 묻지마 조회 대신 필요한 마켓만 조합
                markets = []
                if "BTC_KRW" in coins: markets.append("KRW-BTC")
                if "BTC_USD" in coins: markets.append("USDT-BTC")
                
                url = f"https://api.upbit.com/v1/ticker?markets={','.join(markets)}"
                self._wait_for_domain_delta(url)
                res = requests.get(url, timeout=5)
                data = res.json()
                for item in data:
                    is_usd = item['market'] == "USDT-BTC"
                    key = "BTC_USD" if is_usd else "BTC_KRW"
                    val = {"name": key, "price": float(item['trade_price']), "rate": float(item['signed_change_rate']) * 100}
                    self._index_cache[key] = (curr_t, val)
                    # Mapping back to original symbols
                    for s, code in to_fetch:
                        if code == key: results[s] = val
            except Exception as e:
                log_error(f"UPBIT Bulk Error: {e}")

        # 3. 야후 벌크 조회 (Yahoo Quote V7)
        yahoo_codes = [code for s, code in to_fetch if code not in coins]
        if yahoo_codes and self._index_src == "yahoo":
            try:
                # Yahoo 심볼 맵핑
                yahoo_symbol_map = {
                    "KOSPI": "^KS11", "KOSDAQ": "^KQ11", "KPI200": "^KS200", "VOSPI": "^VIX",
                    "FX_USDKRW": "USDKRW=X", "DOW": "^DJI", "NASDAQ": "^IXIC", "S&P500": "^GSPC",
                    "NAS_FUT": "NQ=F", "SPX_FUT": "ES=F"
                }
                targets = [yahoo_symbol_map.get(c, c) for c in yahoo_codes if c in yahoo_symbol_map]
                if targets:
                    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={','.join(targets)}"
                    self._wait_for_domain_delta(url)
                    res = requests.get(url, headers=self.headers, timeout=7)
                    data = res.json()
                    for quote in data.get('quoteResponse', {}).get('result', []):
                        y_sym = quote.get('symbol')
                        # 역맵핑
                        found_code = next((k for k, v in yahoo_symbol_map.items() if v == y_sym), None)
                        if found_code:
                            val = {"name": found_code, "price": quote.get('regularMarketPrice', 0), 
                                   "rate": quote.get('regularMarketChangePercent', 0)}
                            self._index_cache [found_code] = (curr_t, val)
                            for s, code in to_fetch:
                                if code == found_code: results[s] = val
            except Exception as e:
                log_error(f"Yahoo Bulk Error: {e}")

        # 4. 여전히 누락된 것들 (실패했거나 지원 종료된 소스) 개별 조회
        for s, code in to_fetch:
            if s not in results:
                results[s] = self.get_index_price(code)
                
        return results

    def get_naver_stock_detail(self, code: str) -> dict:
        """네이버 금융 상세 페이지에서 핵심 시세 정보 및 펀더멘털 지표 수집 (캐시 적용)"""
        now = datetime.now()
        # 장 시작 3분 전(08:57 ~ 08:59)에는 캐시를 무조건 무효화하여 장 시작 시점의 실시간성에 대비
        if now.hour == 8 and 57 <= now.minute <= 59:
            self._detail_cache.clear()

        curr_t = time.time()
        if code in self._detail_cache:
            ts, data = self._detail_cache[code]
            if curr_t - ts < self._detail_cache_duration: return data

        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            self._wait_for_domain_delta(url)
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
                # 단일 find()는 첫 번째 p(보통 가격/차액)만 가져올 수 있으므로 전체 탐색
                all_ps = today.find_all('p')
                rate_area = None
                for p in all_ps:
                    if '%' in p.text:
                        rate_area = p
                        break
                
                if rate_area:
                    try:
                        # 퍼센트 기호 앞의 숫자 추출 (예: "+ 1.23 %" -> 1.23)
                        val_match = re.search(r'([\d.]+)\s*%', rate_area.text)
                        if val_match:
                            val = float(val_match.group(1))
                            # 클래스명 또는 텍스트 기반으로 부호 결정
                            cls_str = str(rate_area.get('class', []))
                            if 'no_up' in cls_str: detail["rate"] = val
                            elif 'no_down' in cls_str: detail["rate"] = -val
                            else:
                                blind_txt = rate_area.find('span', {'class': 'blind'})
                                r_txt = blind_txt.text.strip() if blind_txt else ""
                                detail["rate"] = val if "플러스" in r_txt or "+" in rate_area.text else -val if "마이너스" in r_txt or "-" in rate_area.text else 0.0
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
            
            # 가격이 0원인 경우는 일시적 오류(또는 장 시작 전)이므로 캐시하지 않음
            if detail["price"] != "0" and detail["price"] != "":
                self._detail_cache[code] = (curr_t, detail)
            return detail
        except: return {"name": "Error", "price": "0", "rate": 0.0, "per": "N/A", "pbr": "N/A", "yield": "N/A", "sector_per": "N/A", "market_cap": "N/A"}

    def get_naver_stock_news(self, code: str) -> List[str]:
        """네이버 금융 뉴스 섹션에서 최신 헤드라인 수집"""
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
            self._wait_for_domain_delta(url)
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
            # 네이버 금융 NXT 시스템 URL로 변경
            for sosok in ["0", "1"]:
                url = f"https://finance.naver.com/sise/nxt_sise_quant.naver?sosok={sosok}"
                self._wait_for_domain_delta(url)
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
            else:
                # 데이터가 없는 경우 (장 시작 전 등)
                pass
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
                self._wait_for_domain_delta(url)
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
