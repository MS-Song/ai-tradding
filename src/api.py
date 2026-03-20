import requests
import time
import threading
import re
from bs4 import BeautifulSoup
from src.logger import logger

class KISAPI:
    def __init__(self, auth):
        self.auth = auth
        self.domain = auth.domain
        self._balance_cache = None
        self._last_balance_time = 0
        self._hot_cache = []
        self._last_hot_time = 0
        self._vol_cache = []
        self._last_vol_time = 0
        self._cache_duration = 120.0 
        
        # KIS API 호출 제한 관리 (초당 1~2건)
        self._last_request_time = 0
        self._request_lock = threading.Lock()

    def _safe_int(self, val):
        """숫자 변환 유틸리티: 콤마 제거 및 예외 처리"""
        try:
            if not val or str(val).strip() == "": return 0
            return int(float(str(val).replace(',', '')))
        except: return 0
        
    def get_overseas_balance(self):
        """해외 주식 조회 제외 (속도 최우선)"""
        return []

    def _request(self, method, url, **kwargs):
        """네트워크/SSL 오류 대응 및 초당 호출 제한(Rate Limit)을 보장하는 내부 요청 함수"""
        with self._request_lock:
            curr_t = time.time()
            elapsed = curr_t - self._last_request_time
            # KIS API 안전을 위해 최소 1.1초 간격 유지
            if elapsed < 1.1:
                wait_t = 1.1 - elapsed
                time.sleep(wait_t)
            
            max_retries = 3
            for i in range(max_retries):
                try:
                    # SSL EOF 오류 방지를 위해 Connection: close 헤더 권장
                    if "headers" not in kwargs: kwargs["headers"] = {}
                    kwargs["headers"]["Connection"] = "close"
                    
                    res = requests.request(method, url, **kwargs)
                    self._last_request_time = time.time()
                    return res
                except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                    if i < max_retries - 1:
                        time.sleep(1.0 * (i + 1))
                        continue
                    raise e
                except Exception as e:
                    raise e
        return None

    def get_orderable_cash(self):
        """매수가능조회 API를 통해 앱(MTS) 주문창과 동일한 실제 구매 가능 금액 추출"""
        if self.auth.is_virtual: time.sleep(1.3)
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "VTTC8908R" if self.auth.is_virtual else "TTTC8908R"
        
        params = {
            "CANO": self.auth.cano, "ACNT_PRDT_CD": "01", "PDNO": "005930",
            "ORD_UNPR": "0", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
        }
        
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") == "0":
                return self._safe_int(data.get("output", {}).get("ord_psbl_cash", 0))
        except Exception as e:
            logger.error(f"매수 가능 금액 조회 API 오류: {e}")
        return 0

    def get_full_balance(self, force=False):
        """국내 주식 잔고 및 공식 총 자산 정보 조회 (주문가능금액 제외)"""
        curr_t = time.time()
        if not force and self._balance_cache and (curr_t - self._last_balance_time < self._cache_duration):
            return self._balance_cache
            
        if self.auth.is_virtual: time.sleep(1.3)
        url_kr = f"{self.domain}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers_kr = self.auth.get_auth_headers()
        headers_kr["tr_id"] = "VTTC8434R" if self.auth.is_virtual else "TTTC8434R"
        params_kr = {
            "CANO": self.auth.cano, "ACNT_PRDT_CD": "01", "AFHR_FLPR_YN": "N", "OFL_YN": "",
            "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        
        holdings_kr, summary_kr = [], {}
        try:
            res_kr = self._request("GET", url_kr, headers=headers_kr, params=params_kr, timeout=10)
            data_kr = res_kr.json()
            if data_kr.get("rt_cd") == "0":
                holdings_kr = data_kr.get("output1", [])
                summary_kr = data_kr.get("output2", [{}])[0]
            else:
                # 화면 노출 방지를 위해 파일 로그만 남김
                logger.warning(f"KR Balance API Resp: {data_kr.get('rt_cd')} - {data_kr.get('msg1')}")
        except Exception as e:
            logger.error(f"KR Balance Connection Error: {e}")

        combined, total_eval = [], 0
        if holdings_kr:
            # logger.debug(f"Balance Item Sample: {holdings_kr[0]}")
            pass
            
        for h in holdings_kr:
            qty = self._safe_int(h.get('hldg_qty', 0))
            if qty <= 0: continue
            ev = self._safe_int(h.get('evlu_amt', 0))
            total_eval += ev
            p_cu = float(h.get('prpr', 0))
            
            # API 분석 결과: fltt_rt(등락률)는 부호를 포함하지만, bfdy_cprs_icdc(금액)는 양수로 오는 경우가 있음
            d_r = float(h.get('fltt_rt', 0))
            d_v = float(h.get('bfdy_cprs_icdc', 0))
            
            # 등락률이 음수이면 금액도 음수로 처리 (부호 동기화)
            if d_r < 0:
                d_v = -abs(d_v)
            elif d_r > 0:
                d_v = abs(d_v)
                
            # prdy_vrss_sign 필드가 존재할 경우 추가 보정 (하한/하락)
            sign = h.get('prdy_vrss_sign')
            if sign in ['4', '5']:
                d_v = -abs(d_v)
                d_r = -abs(d_r)

            combined.append({
                "pdno": h.get('pdno'), "prdt_name": h.get('prdt_name'), "hldg_qty": qty,
                "pchs_avg_pric": float(h.get('pchs_avg_pric', 0)), "prpr": p_cu,
                "evlu_amt": ev, "evlu_pfls_rt": h.get('evlu_pfls_rt', "0.00"), 
                "evlu_pfls_amt": self._safe_int(h.get('evlu_pfls_amt', 0)), 
                "prdy_vrss": d_v, "prdy_ctrt": d_r,
                "currency": "KRW"
            })
            
        # 총 자산 및 평가 금액 정밀 매핑
        asset_info = {
            "cash": self._safe_int(summary_kr.get("prvs_rcdl_exca_amt", summary_kr.get("dnca_tot_amt", 0))),
            "total_asset": self._safe_int(summary_kr.get("tot_evlu_amt", 0)),
            "stock_eval": self._safe_int(summary_kr.get("evlu_amt_smtl_amt", total_eval)),
            "pnl": self._safe_int(summary_kr.get("evlu_pfls_smtl_amt", 0)),
            "deposit": self._safe_int(summary_kr.get("nll_amt", summary_kr.get("dnca_tot_amt", 0)))
        }
        
        self._balance_cache = (combined, asset_info)
        self._last_balance_time = curr_t
        return self._balance_cache

    def get_balance(self): return self.get_full_balance()[0]
    def get_deposit(self): return self.get_full_balance()[1]

    def order_market(self, code, qty, is_buy=True, price=0):
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = ("VTTC0802U" if is_buy else "VTTC0801U") if self.auth.is_virtual else ("TTTC0802U" if is_buy else "TTTC0801U")
        
        # 가격이 0보다 크면 지정가(00), 아니면 시장가(01)
        dvsn = "00" if price > 0 else "01"
        unpr = str(int(price)) if price > 0 else "0"
        
        body = {
            "CANO": self.auth.cano, 
            "ACNT_PRDT_CD": "01", 
            "PDNO": code, 
            "ORD_DVSN": dvsn, 
            "ORD_QTY": str(int(qty)), 
            "ORD_UNPR": unpr
        }
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=5)
            data = res.json()
            p_desc = f"{price:,}원 지정가" if price > 0 else "시장가"
            if data.get("rt_cd") == "0": 
                return True, f"[{'매수' if is_buy else '매도'} 성공] {code} {qty}주 ({p_desc})"
            return False, data.get("msg1", "오류")
        except Exception as e:
            return False, f"API 오류: {e}"

    def get_index_price(self, iscd="0001"):
        """국내/해외 지수 및 보조 지표 조회 (야후 파이낸스 통합)"""
        # 심볼 매핑
        symbol_map = {
            "0001": "^KS11", "KOSPI": "^KS11",
            "1001": "^KQ11", "KOSDAQ": "^KQ11",
            "KPI200": "069500.KS", # KODEX 200 (선물 대신 현물 ETF로 추종)
            "VOSPI": "^VIX",       # 한국 VKOSPI 대신 글로벌 VIX로 대체 (안정성)
            "FX_USDKRW": "USDKRW=X",
            "DOW": "^DJI", "NAS": "^IXIC", "NASDAQ": "^IXIC", "SPX": "^GSPC", "S&P500": "^GSPC",
            "NAS_FUT": "NQ=F", "SPX_FUT": "ES=F"
        }
        
        symbol = symbol_map.get(iscd)
        if not symbol: return None
        
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            data = res.json()
            
            if 'chart' in data and data['chart']['result']:
                meta = data['chart']['result'][0]['meta']
                curr_price = meta.get('regularMarketPrice', 0)
                prev_close = meta.get('previousClose', 0)
                
                # 야후 API는 종종 regularMarketPrice가 없을 때가 있으므로 종가 확인
                if curr_price == 0:
                    curr_price = meta.get('chartPreviousClose', 0)
                
                rate = ((curr_price - prev_close) / prev_close * 100) if prev_close != 0 else 0
                diff = curr_price - prev_close
                
                return {"name": iscd, "price": curr_price, "rate": rate, "diff": diff, "status": "02"}
        except Exception as e:
            # logger.debug(f"Yahoo Index Error ({iscd}): {e}")
            pass
        return None

    def _filter_risky_stocks(self, name):
        """관리종목, 정지, 환기, 정리매매, 단기과열 및 우선주 필터링"""
        risky_keywords = ["관리", "정지", "환기", "정리매매", "단기과열", "투자위험", "투자경고"]
        if any(kw in name for kw in risky_keywords): return True
        if name.endswith(('우', '우A', '우B')) or name.find(' (우)') != -1: return True
        return False

    def get_naver_hot_stocks(self):
        """네이버 인기검색종목 수집 (모바일 JSON API 활용)"""
        curr_t = time.time()
        if self._hot_cache and (curr_t - self._last_hot_time < self._cache_duration):
            return self._hot_cache
        
        results = []
        try:
            # 모바일 웹 API (인기 검색어)
            url = "https://m.stock.naver.com/api/stock/ranking/popularSearch"
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"}, timeout=5)
            data = res.json()
            
            if data and isinstance(data, list):
                for item in data:
                    name = item.get('stockName')
                    if self._filter_risky_stocks(name): continue
                    
                    code = item.get('itemCode')
                    price = self._safe_int(item.get('closePrice'))
                    rate = float(item.get('fluctuationRate', 0))
                    
                    results.append({
                        "mkt": "HOT", "name": name, "code": code,
                        "price": price, "rate": rate
                    })
        except Exception as e:
            # 모바일 API 실패 시 메인 페이지 파싱 시도 (백업)
            logger.error(f"Naver Hot Stocks API Error: {e}")
            
        if results:
            self._hot_cache = results[:100]
            self._last_hot_time = curr_t
        return self._hot_cache

    def get_naver_volume_stocks(self):
        """네이버 거래량 상위 종목 수집 (KOSPI & KOSDAQ 통합 Top 100)"""
        curr_t = time.time()
        if self._vol_cache and (curr_t - self._last_vol_time < self._cache_duration):
            return self._vol_cache
            
        all_results = []
        # 코스피(sosok=0), 코스닥(sosok=1) 각각 조회
        for sosok in ["0", "1"]:
            try:
                url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                res.encoding = 'euc-kr'
                soup = BeautifulSoup(res.text, 'html.parser')
                
                table = soup.find('table', {'class': 'type_2'})
                if table:
                    rows = table.find_all('tr')
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 6:
                            a_tag = cols[1].find('a')
                            if not a_tag: continue
                            
                            name = a_tag.text.strip()
                            if self._filter_risky_stocks(name): continue
                            
                            code = a_tag['href'].split('=')[-1]
                            price = self._safe_int(cols[2].text)
                            vol = self._safe_int(cols[5].text)
                            
                            # 등락률 파싱 (cols[4])
                            rate_td = cols[4].find('span')
                            rate_text = rate_td.text.strip().replace('%', '') if rate_td else "0"
                            rate = float(rate_text)
                            if rate_td and 'tah' in rate_td.get('class', []) and 'nv01' in rate_td.get('class', []):
                                rate = -abs(rate)
                                
                            all_results.append({
                                "mkt": "KSP" if sosok == "0" else "KDQ",
                                "name": name, "code": code,
                                "price": price, "rate": rate, "vol": vol
                            })
            except Exception as e:
                logger.error(f"Naver Volume Stocks Error ({sosok}): {e}")
        
        # 거래량 순으로 재정렬 및 상위 100개 추출
        all_results.sort(key=lambda x: x.get('vol', 0), reverse=True)
        final_res = all_results[:100]
        
        if final_res:
            self._vol_cache = final_res
            self._last_vol_time = curr_t
        return self._vol_cache

    def get_inquire_price(self, code):
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKST01010100"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=3)
            data = res.json()
            if data.get("rt_cd") == "0":
                out = data.get("output", {})
                return {"price": int(out.get("stck_prpr", 0)), "rate": float(out.get("prdy_ctrt", 0)), "vol": int(out.get("acml_vol", 0)), "prev_vol": int(out.get("prdy_vol", 0))}
        except: pass
        return None
