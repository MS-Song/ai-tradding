import time
import requests
import threading
from typing import List, Tuple, Optional, Dict, Any
from src.api.base import BaseAPI, BrokerRateLimiter
from src.utils import retry_api

class KiwoomAPIClient(BaseAPI):
    """키움증권 REST API 연동 클라이언트.

    BrokerRateLimiter를 통해 중앙 집중식 API 호출 빈도를 제어합니다.
    모의투자(0.8 req/s)와 실전투자(5 req/s)의 RPS가 자동 적용됩니다.

    Attributes:
        auth: 키움 인증 객체 (토큰 및 계좌 정보 포함).
        domain (str): 키움 API 접속 도메인.
        _rate_limiter (BrokerRateLimiter): 중앙 레이트 리미터 인스턴스.
    """
    def __init__(self, auth):
        super().__init__()
        self.auth = auth
        self.domain = auth.domain
        is_v = getattr(auth, 'is_virtual', True)
        self._rate_limiter = BrokerRateLimiter.get_instance("KIWOOM", is_v)

    def _request(self, method, url, **kwargs):
        """중앙 레이트 리미터를 통과한 후 HTTP 요청을 수행합니다.

        BrokerRateLimiter의 Token Bucket 알고리즘에 의해 모의투자(0.8 req/s)와
        실전투자(증권사별 권장 RPS)의 호출 빈도가 자동으로 제어됩니다.
        """
        self._rate_limiter.acquire()
        return requests.request(method, url, **kwargs)

    @retry_api(max_retries=3, delay=1.5)
    def get_full_balance(self, force=False, **kwargs) -> Tuple[List[dict], dict]:
        """계좌의 전체 잔고와 자산 요약 정보를 조회합니다."""
        url = f"{self.domain}/api/dostk/acnt"
        headers = self.auth.get_auth_headers()
        
        # 1. 예수금 (D+2) 조회
        headers["api-id"] = "kt00001"
        res_cash = self._request("POST", url, headers=headers, json={"qry_tp": "2"}, timeout=10)
        data_cash = res_cash.json()
        if str(data_cash.get("return_code")) != "0":
            raise Exception(f"Kiwoom Cash API Error: {data_cash.get('return_msg')} (RT_CD:{data_cash.get('return_code')})")
        
        d2_cash = self._safe_float(data_cash.get("d2_entra", 0))
        d0_cash = self._safe_float(data_cash.get("entr", 0))
        
        # 2. 계좌평가잔고내역 조회
        headers["api-id"] = "kt00018"
        res_bal = self._request("POST", url, headers=headers, json={"qry_tp": "1", "dmst_stex_tp": "KRX"}, timeout=10)
        data_bal = res_bal.json()
        if str(data_bal.get("return_code")) != "0":
            raise Exception(f"Kiwoom Balance API Error: {data_bal.get('return_msg')} (RT_CD:{data_bal.get('return_code')})")
        
        raw_holdings = data_bal.get("acnt_evlt_remn_indv_tot", [])
        holdings = []
        for h in raw_holdings:
            qty = int(self._safe_float(h.get("rmnd_qty", 0)))
            if qty <= 0: continue
            
            code = h.get("stk_cd", "").replace("A", "") # 키움은 'A'가 붙어서 오는 경우가 많음
            cur_prc = self._safe_float(h.get("cur_prc", 0))
            pred_close = self._safe_float(h.get("pred_close_pric", 0))
            antc_prc = self._safe_float(h.get("antc_cntg_prc", 0))
            
            # [신규] 장전 동시호가 시 현재가가 0이면 예상가 사용
            display_prc = cur_prc
            if display_prc <= 0 and antc_prc > 0:
                display_prc = antc_prc
            
            vrss = display_prc - pred_close
            ctrt = (vrss / pred_close * 100) if pred_close else 0.0
            
            holdings.append({
                "pdno": code,
                "prdt_name": h.get("stk_nm", ""),
                "hldg_qty": str(qty),
                "pchs_avg_pric": str(self._safe_float(h.get("pur_pric", 0))),
                "prpr": str(display_prc),
                "evlu_amt": str(display_prc * qty), # 평가금액 재계산
                "evlu_pfls_rt": str(self._safe_float(h.get("prft_rt", 0))),
                "evlu_pfls_amt": str((display_prc - self._safe_float(h.get("pur_pric", 0))) * qty),
                "prdy_vrss": str(vrss),
                "prdy_ctrt": str(ctrt)
            })
        
        stock_eval = self._safe_float(data_bal.get("tot_evlt_amt", 0))
        stock_principal = self._safe_float(data_bal.get("tot_pur_amt", 0))
        tot_asset = self._safe_float(data_bal.get("prsm_dpst_aset_amt", 0))
        pnl = self._safe_float(data_bal.get("tot_evlt_pl", 0))
        
        if tot_asset <= 0:
            tot_asset = d2_cash + stock_eval
            
        cash = d2_cash if d2_cash > 0 else 0
        
        asset_info = {
            "total_asset": tot_asset,
            "total_principal": stock_principal + d2_cash,
            "stock_eval": stock_eval,
            "stock_principal": stock_principal,
            "cash": cash,
            "d0_cash": d0_cash,
            "d2_cash": d2_cash,
            "pnl": pnl,
            "deposit": 0,
            "prev_day_asset": tot_asset - pnl
        }
        return holdings, asset_info

    def get_balance(self, force=False, **kwargs) -> List[dict]:
        return self.get_full_balance(force=force)[0]

    def order_market(self, code: str, qty: int, is_buy: bool, price: int = 0) -> Tuple[bool, str]:
        """주식을 주문합니다."""
        url = f"{self.domain}/api/dostk/ordr"
        headers = self.auth.get_auth_headers()
        # 매수(kt10000) / 매도(kt10001)
        tr_id = "kt10000" if is_buy else "kt10001"
        headers["api-id"] = tr_id
        
        body = {
            "dmst_stex_tp": "KRX",  # 국내거래소구분 (KRX: 한국거래소)
            "stk_cd": code,
            "ord_qty": str(int(qty)),
            "ord_uv": str(int(price)),
            "trde_tp": "03" if price == 0 else "00" # 03: 시장가, 00: 보통(지정가)
        }
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=5)
            data = res.json()
            if str(data.get("return_code")) == "0": return True, "성공"
            return False, data.get("return_msg", "오류")
        except Exception as e: return False, f"API 오류: {e}"

    @retry_api(max_retries=2, delay=2.0)
    def get_daily_chart_price(self, code: str, start_date: str = "", end_date: str = "") -> List[dict]:
        """특정 기간의 일봉 차트 데이터를 가져옵니다. (ka10081)"""
        url = f"{self.domain}/api/dostk/chart"
        headers = self.auth.get_auth_headers()
        headers["api-id"] = "ka10081"
        body = {
            "stk_cd": code,
            "inq_strt_dt": start_date,
            "inq_end_dt": end_date,
            "adj_prc_inq_tp": "1" # 1:수정주가
        }
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=10)
            data = res.json()
            output = data.get("stk_d_chart_tot", [])
            # KIS 형식으로 변환: stck_hgpr, stck_lwpr, stck_clpr, stck_oprc, acml_vol, stck_bsop_date
            converted = []
            for item in output:
                converted.append({
                    "stck_bsop_date": item.get("bsns_dt"),
                    "stck_clpr": item.get("close_prc"),
                    "stck_oprc": item.get("opn_prc"),
                    "stck_hgpr": item.get("high_prc"),
                    "stck_lwpr": item.get("low_prc"),
                    "acml_vol": item.get("acml_trde_qty")
                })
            return converted
        except: return []

    @retry_api(max_retries=2, delay=1.5)
    def get_minute_chart_price(self, code: str, target_time: str = "") -> List[dict]:
        url = f"{self.domain}/api/dostk/chart"
        headers = self.auth.get_auth_headers()
        headers["api-id"] = "ka10080"
        body = {"stk_cd": code, "min_tp": "1", "adj_prc_inq_tp": "1"}
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=10)
            data = res.json()
            output = data.get("stk_min_chart_tot", [])
            converted = []
            for item in output:
                converted.append({
                    "stck_bsop_date": item.get("bsns_dt"),
                    "stck_cntg_hour": item.get("cntg_tm"),
                    "stck_clpr": item.get("close_prc"),
                    "stck_oprc": item.get("opn_prc"),
                    "stck_hgpr": item.get("high_prc"),
                    "stck_lwpr": item.get("low_prc"),
                    "cntg_vol": item.get("cntg_qty")
                })
            return converted
        except: return []

    @retry_api(max_retries=2, delay=1.2)
    def get_index_chart_price(self, code: str, period_div: str = "D", start_date: str = "", end_date: str = "") -> List[dict]:
        url = f"{self.domain}/api/dostk/chart"
        headers = self.auth.get_auth_headers()
        headers["api-id"] = "ka20006" # 업종일봉
        code_map = {"0001": "001", "1001": "101"} # KIS코스피:0001 -> 키움코스피:001
        kw_code = code_map.get(code, code)
        body = {"sect_cd": kw_code, "inq_strt_dt": start_date, "inq_end_dt": end_date}
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=10)
            data = res.json()
            output = data.get("sect_d_chart_tot", [])
            converted = []
            for item in output:
                converted.append({
                    "stck_bsop_date": item.get("bsns_dt"),
                    "bstp_nmix_prpr": item.get("close_prc")
                })
            return converted
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
        """주식기본정보요청 (ka10001)"""
        url = f"{self.domain}/api/dostk/stkinfo"
        headers = self.auth.get_auth_headers()
        headers["api-id"] = "ka10001"
        body = {"stk_cd": code}
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=5)
            data = res.json()
            if str(data.get("return_code")) != "0": return None
            
            cur_prc = self._safe_float(data.get("cur_prc", 0))
            pred_close = self._safe_float(data.get("pred_close_pric", 0))
            vrss = cur_prc - pred_close
            ctrt = (vrss / pred_close * 100) if pred_close else 0.0

            return {
                "price": cur_prc,
                "vrss": vrss,
                "ctrt": ctrt,
                "vol": self._safe_float(data.get("acml_trde_qty", 0)),
                "prev_vol": self._safe_float(data.get("pred_acml_trde_qty", 0)),
                "high": self._safe_float(data.get("high_prc", 0)),
                "low": self._safe_float(data.get("low_prc", 0)),
                "per": data.get("per"),
                "pbr": data.get("pbr"),
                "eps": data.get("eps"),
                "bps": data.get("bps"),
                "antc_price": self._safe_float(data.get("antc_cntg_prc", 0)),
                "antc_rate": self._safe_float(data.get("antc_cntg_prdy_ctrt", 0)),
                "market_cap": self._safe_float(data.get("total_eval_pric", 0)) * 1000000 
            }
        except: return None

    @retry_api(max_retries=2, delay=1.0)
    def get_investor_trading_trend(self, code: str) -> Optional[dict]:
        """종목별투자자기관별요청 (ka10059)"""
        url = f"{self.domain}/api/dostk/stkinfo"
        headers = self.auth.get_auth_headers()
        headers["api-id"] = "ka10059"
        body = {"stk_cd": code, "inq_tp": "2", "inq_strt_dt": "", "inq_end_dt": "", "amt_qty_tp": "2"}
        try:
            res = self._request("POST", url, headers=headers, json=body, timeout=5)
            data = res.json()
            if str(data.get("return_code")) != "0": return None
            
            d_list = data.get("stk_invst_istt_tot", [])
            if not d_list: return None
            
            d = d_list[0] # 가장 최근
            return {
                "frgn_net_buy": self._safe_float(d.get("frgn_ntby_qty", 0)),
                "inst_net_buy": self._safe_float(d.get("istt_ntby_qty", 0)),
                "pnsn_net_buy": self._safe_float(d.get("pnsn_ntby_qty", 0)),
                "thst_net_buy": self._safe_float(d.get("ivtr_ntby_qty", 0)),
                "frgn_hold_rt": self._safe_float(d.get("frgn_rt", 0))
            }
        except: return None
