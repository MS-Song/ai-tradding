import time
import threading
import requests
import random
from typing import List, Tuple, Optional, Dict, Any
from src.api.base import BaseAPI
from src.utils import retry_api

class KISAPIClient(BaseAPI):
    def __init__(self, auth):
        super().__init__()
        self.auth = auth
        self.domain = auth.domain

    _last_req_time = 0
    _req_lock = threading.Lock()

    def _request(self, method, url, **kwargs):
        # [개선] 글로벌 레이트 리미터: 전 스레드 공통으로 초당 호출 제한 준수
        with self._req_lock:
            now = time.time()
            # 모의 투자는 초당 2회, 실전은 초당 5회(또는 10회)이나 안전을 위해 0.5s~1s 간격 유지
            interval = 0.51 if self.auth.is_virtual else 0.21
            elapsed = now - self._last_req_time
            if elapsed < interval:
                time.sleep(interval - elapsed)
            self._last_req_time = time.time()

        return requests.request(method, url, **kwargs)

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
            if data.get("rt_cd") != "0": return [], {"total_asset":0, "stock_eval":0, "cash":0, "pnl":0}
            
            raw_holdings = data.get("output1", [])
            holdings = []
            for h in raw_holdings:
                qty = int(self._safe_float(h.get('hldg_qty', 0)))
                if qty <= 0: continue
                
                prpr = self._safe_float(h.get('prpr', 0))
                vrss = self._safe_float(h.get('prdy_vrss', 0))
                ctrt = self._safe_float(h.get('prdy_ctrt', 0))
                
                # 부호 보정
                sign = h.get('prdy_vrss_sign', '3')
                if sign in ['4', '5']:
                    vrss = -abs(vrss)
                    ctrt = -abs(ctrt)
                elif sign in ['1', '2']:
                    vrss = abs(vrss)
                    ctrt = abs(ctrt)

                holdings.append({
                    "pdno": h.get("pdno"), "prdt_name": h.get("prdt_name"),
                    "hldg_qty": str(qty), "pchs_avg_pric": h.get("pchs_avg_pric"),
                    "prpr": str(prpr), "evlu_amt": h.get("evlu_amt"), 
                    "evlu_pfls_rt": h.get("evlu_pfls_rt"),
                    "evlu_pfls_amt": h.get("evlu_pfls_amt", "0"),
                    "prdy_vrss": str(vrss), "prdy_ctrt": str(ctrt)
                })
            
            raw_summary = data.get("output2", [{}])[0]
            d0_cash = self._safe_float(raw_summary.get("dnca_tot_amt"))
            # [수정] d2_cash는 'excc'(재사용/증거금포함)가 아닌 'exca'(실제 정산예정금)를 사용해야 함
            d2_cash = self._safe_float(raw_summary.get("prvs_rcdl_exca_amt"))
            if d2_cash <= 0: d2_cash = d0_cash # 데이터 부재 시 D+0으로 대체
            
            stock_eval = self._safe_float(raw_summary.get("evlu_amt_smtl_amt"))
            
            # [개선] 총자산 = 정산현금(D+2) + 주식평가금 (미결제 매도대금 포함)
            tot_asset = d2_cash + stock_eval
            
            asset_info = {
                "total_asset": tot_asset,
                "stock_eval": stock_eval,
                "d0_cash": d0_cash,
                "d2_cash": d2_cash,
                "cash": d2_cash, # 시스템 매수 가능 판단 기준 (정산금 기준)
                "pnl": self._safe_float(raw_summary.get("evlu_pfls_smtl_amt")),
                "prev_day_asset": self._safe_float(raw_summary.get("prdy_evlu_amt") or 0)
            }
            return holdings, asset_info
        except: return [], {}

    def get_balance(self, force=False) -> List[dict]:
        return self.get_full_balance(force=force)[0]

    def order_market(self, code: str, qty: int, is_buy: bool, price: int = 0) -> Tuple[bool, str]:
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self.auth.get_auth_headers()
        tr_id = "VTTC0802U" if is_buy else "VTTC0801U"
        if not self.auth.is_virtual: tr_id = "TTTC0802U" if is_buy else "TTTC0801U"
        headers.update({"tr_id": tr_id})
        dvsn = "01" if price == 0 else "00"
        body = {"CANO": self.auth.cano, "ACNT_PRDT_CD": "01", "PDNO": code, "ORD_DVSN": dvsn, "ORD_QTY": str(int(qty)), "ORD_UNPR": str(int(price))}
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=5)
            data = res.json()
            if data.get("rt_cd") == "0": return True, "성공"
            return False, data.get("msg1", "오류")
        except Exception as e: return False, f"API 오류: {e}"

    @retry_api(max_retries=2, delay=2.0)
    def get_daily_chart_price(self, code: str, start_date: str = "", end_date: str = "") -> List[dict]:
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        headers = self.auth.get_auth_headers(); headers.update({"tr_id": "FHKST03010100"})
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": start_date, "FID_INPUT_DATE_2": end_date, "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=10)
            data = res.json()
            return data.get("output2", [])
        except: return []

    @retry_api(max_retries=2, delay=1.5)
    def get_minute_chart_price(self, code: str, target_time: str = "") -> List[dict]:
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = self.auth.get_auth_headers(); headers.update({"tr_id": "FHKST03010200"})
        if not target_time:
            from datetime import datetime
            target_time = datetime.now().strftime('%H%M%S')
            if target_time > "153000": target_time = "153000"
        params = {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code, "FID_INPUT_TM_1": target_time, "FID_PW_RES_PRC": "0"}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=10)
            data = res.json()
            return data.get("output2", [])
        except: return []

    @retry_api(max_retries=2, delay=1.2)
    def get_index_chart_price(self, code: str, period_div: str = "D", start_date: str = "", end_date: str = "") -> List[dict]:
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
        headers = self.auth.get_auth_headers(); headers.update({"tr_id": "FHKUP03500100"})
        params = {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": start_date, "FID_INPUT_DATE_2": end_date, "FID_PERIOD_DIV_CODE": period_div}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=10)
            data = res.json()
            return data.get("output2", [])
        except: return []

    def calculate_atr(self, code: str, period: int = 14) -> float:
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=period + 10)).strftime('%Y%m%d')
        candles = self.get_daily_chart_price(code, start_date, end_date)
        if len(candles) < period: return 0.0
        tr_list = []
        for i in range(len(candles) - 1):
            curr, prev = candles[i], candles[i+1]
            h, l, pc = self._safe_float(curr.get('stck_hgpr', 0)), self._safe_float(curr.get('stck_lwpr', 0)), self._safe_float(prev.get('stck_clpr', 0))
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)
            if len(tr_list) >= period: break
        return sum(tr_list) / len(tr_list) if tr_list else 0.0

    def get_inquire_price(self, code: str) -> Optional[dict]:
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_auth_headers(); headers.update({"tr_id": "FHKST01010100"})
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=5)
            d = res.json().get("output", {})
            sign = d.get("prdy_vrss_sign", "3")
            vrss = self._safe_float(d.get("prdy_vrss"))
            ctrt = self._safe_float(d.get("prdy_ctrt"))
            
            if sign in ["4", "5"]:
                vrss = -abs(vrss)
                ctrt = -abs(ctrt)
            elif sign in ["1", "2"]:
                vrss = abs(vrss)
                ctrt = abs(ctrt)

            return {
                "price": self._safe_float(d.get("stck_prpr")),
                "vrss": vrss,
                "ctrt": ctrt,
                "vol": self._safe_float(d.get("acml_vol")),
                "prev_vol": self._safe_float(d.get("prdy_vol")),
                "high": self._safe_float(d.get("stck_hgpr")),
                "low": self._safe_float(d.get("stck_lwpr"))
            }
        except: return None
