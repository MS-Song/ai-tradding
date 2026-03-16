import requests
import time
from src.logger import logger

class KISAPI:
    def __init__(self, auth):
        self.auth = auth
        self.domain = auth.domain
        self._balance_cache = None
        self._last_balance_time = 0
        self._gainers_cache = []
        self._last_gainers_time = 0
        self._losers_cache = []
        self._last_losers_time = 0
        self._cache_duration = 5.0 

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
        """네트워크/SSL 오류 대응을 위한 재시도 로직이 포함된 내부 요청 함수"""
        max_retries = 3
        for i in range(max_retries):
            try:
                # SSL EOF 오류 방지를 위해 Connection: close 헤더 권장
                if "headers" not in kwargs: kwargs["headers"] = {}
                kwargs["headers"]["Connection"] = "close"
                
                res = requests.request(method, url, **kwargs)
                return res
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                if i < max_retries - 1:
                    time.sleep(1.5 * (i + 1)) # 재시도 간격 점진적 증가
                    continue
                raise e
            except Exception as e:
                raise e

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
        for h in holdings_kr:
            qty = self._safe_int(h.get('hldg_qty', 0))
            if qty <= 0: continue
            ev = self._safe_int(h.get('evlu_amt', 0))
            total_eval += ev
            combined.append({
                "pdno": h.get('pdno'), "prdt_name": h.get('prdt_name'), "hldg_qty": qty,
                "pchs_avg_pric": float(h.get('pchs_avg_pric', 0)), "prpr": float(h.get('prpr', 0)),
                "evlu_amt": ev, "evlu_pfls_rt": h.get('evlu_pfls_rt', "0.00"), 
                "evlu_pfls_amt": self._safe_int(h.get('evlu_pfls_amt', 0)), "currency": "KRW"
            })
            
        # 총 자산 및 평가 금액 정밀 매핑
        asset_info = {
            "cash": 0, # 외부(get_orderable_cash)에서 주입 예정
            "total_asset": self._safe_int(summary_kr.get("tot_evlu_amt", 0)),
            "stock_eval": self._safe_int(summary_kr.get("evlu_amt_smtl_amt", total_eval)),
            "pnl": self._safe_int(summary_kr.get("evlu_pfls_smtl_amt", 0)),
            "deposit": self._safe_int(summary_kr.get("nll_amt", summary_kr.get("dnca_tot_amt", 0)))
        }
        
        # 이전 캐시의 Cash 값이 있다면 유지 (로테이션 갱신 대응)
        if self._balance_cache and asset_info["cash"] == 0:
            asset_info["cash"] = self._balance_cache[1].get("cash", 0)

        self._balance_cache = (combined, asset_info)
        self._last_balance_time = curr_t
        return self._balance_cache

    def get_balance(self): return self.get_full_balance()[0]
    def get_deposit(self): return self.get_full_balance()[1]

    def order_market(self, code, qty, is_buy=True):
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = ("VTTC0802U" if is_buy else "VTTC0801U") if self.auth.is_virtual else ("TTTC0802U" if is_buy else "TTTC0801U")
        body = {"CANO": self.auth.cano, "ACNT_PRDT_CD": "01", "PDNO": code, "ORD_DVSN": "01", "ORD_QTY": str(int(qty)), "ORD_UNPR": "0"}
        try:
            res = requests.post(url, headers=headers, json=body, timeout=5)
            data = res.json()
            if data.get("rt_cd") == "0": return True, f"[{'매수' if is_buy else '매도'} 성공] {code} {qty}주"
            return False, data.get("msg1", "오류")
        except: return False, "API 오류"

    def get_index_price(self, iscd="0001"):
        """국내/해외 지수 조회 (네이버/야후 백업 포함)"""
        if iscd in ["0001", "1001", "KOSPI", "KOSDAQ"]:
            try:
                target = "KOSPI" if iscd in ["0001", "KOSPI"] else "KOSDAQ"
                url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:{target}"
                res = requests.get(url, timeout=3)
                data = res.json()
                item = data['result']['areas'][0]['datas'][0]
                return {"name": target, "price": float(item['nv']), "rate": float(item['cr']), "diff": float(item['cv']), "status": "02"}
            except: pass
            
        if iscd in ["NAS", "NASDAQ", "SPX", "S&P500"]:
            try:
                symbol = "^IXIC" if iscd in ["NAS", "NASDAQ"] else "^GSPC"
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
                res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
                data = res.json()
                meta = data['chart']['result'][0]['meta']
                curr_price = meta.get('regularMarketPrice', 0)
                prev_close = meta.get('previousClose', 0)
                rate = ((curr_price - prev_close) / prev_close * 100) if prev_close != 0 else 0
                return {"name": iscd, "price": curr_price, "rate": rate, "diff": curr_price - prev_close}
            except: pass
        return None

    def get_top_gainers(self): return self._get_ranking(True)
    def get_top_losers(self): return self._get_ranking(False)

    def _get_ranking(self, is_gainer=True):
        if self.auth.is_virtual: time.sleep(1.3)
        curr_t = time.time()
        cache = self._gainers_cache if is_gainer else self._losers_cache
        last_t = self._last_gainers_time if is_gainer else self._last_losers_time
        if cache and (curr_t - last_t < 60): return cache
        
        url = f"{self.domain}/uapi/domestic-stock/v1/ranking/fluctuation"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHPST01700000"
        # 0: 상승율순, 1: 하락율순
        sort_code = "0" if is_gainer else "1"
        
        # 제외 구분 (10자리): 1:투자유의, 2:관리종목, 3:결산월미도래, 4:우선주, 5:신주인수권, 6:증권투자회사, 7:수익증권, 8:종목조건, 9:ETF, 10:ETN
        # 전부 제외(1) 처리하여 순수 보통주만 추출
        exls_code = "1111111111"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J", 
            "FID_COND_SCR_DIV_CODE": "20170", 
            "FID_INPUT_ISCD": "0000", 
            "FID_RANK_SORT_CLS_CODE": sort_code, 
            "FID_INPUT_CNT_1": "0", 
            "FID_PRC_CLS_CODE": "0", 
            "FID_INQR_RANGE_1": "0", 
            "FID_INQR_RANGE_2": "0", 
            "FID_VOL_CNT": "0", 
            "FID_TRGT_CLS_CODE": "0", 
            "FID_TRGT_EXLS_CLS_CODE": exls_code, 
            "FID_PRC_RANGE_CLS_CODE": "0", 
            "FID_RSFL_RATE1": "0", 
            "FID_RSFL_RATE2": "0", 
            "FID_DIV_CLS_CODE": "0", 
            "FID_ETC_CLS_CODE": "0", 
            "FID_INPUT_PRICE_1": "0", 
            "FID_INPUT_PRICE_2": "0"
        }
        
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=5)
            data = res.json()
            if data.get("rt_cd") == "0":
                out = data.get("output", [])
                if not out: out = data.get("output1", [])
                
                results = []
                for item in out:
                    code = item.get("stck_shrn_iscd")
                    name = item.get("hts_kor_isnm", "Unknown")
                    if not code: continue
                    
                    # [필터링 강화]
                    # 1. 6자리가 아닌 종목코드(증권, 신주인수권 등) 제외
                    if len(code) != 6: continue
                    # 2. 우선주 제외 (이름에 '우'가 들어가거나 코드가 특정 숫자로 끝나는 경우 등 - API에서 이미 걸렀을 수 있지만 2중 체크)
                    if name.endswith(('우', '우A', '우B')) or name.find(' (우)') != -1: continue
                    
                    try:
                        rate = float(item.get("prdy_ctrt", 0))
                        results.append({
                            "mkt": "KSP" if code.startswith(('00', '01', '02', '03', '05', '06', '07')) else "KDQ", 
                            "name": name, 
                            "code": code, 
                            "price": item.get("stck_prpr", "0"), 
                            "rate": rate
                        })
                    except: continue
                
                # 수익률 기준 내부 재정렬
                if is_gainer:
                    results.sort(key=lambda x: x['rate'], reverse=True)
                    results = [r for r in results if r['rate'] > 0]
                else:
                    results.sort(key=lambda x: x['rate'])
                    results = [r for r in results if r['rate'] < 0]

                final_res = results[:20]
                if is_gainer: self._gainers_cache, self._last_gainers_time = final_res, curr_t
                else: self._losers_cache, self._last_losers_time = final_res, curr_t
                return final_res
        except Exception as e:
            logger.error(f"Ranking API Parse Error: {e}")
        return []

    def get_inquire_price(self, code):
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKST01010100"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=3)
            data = res.json()
            if data.get("rt_cd") == "0":
                out = data.get("output", {})
                return {"price": int(out.get("stck_prpr", 0)), "rate": float(out.get("prdy_ctrt", 0)), "vol": int(out.get("acml_vol", 0)), "prev_vol": int(out.get("prdy_vol", 0))}
        except: pass
        return None
