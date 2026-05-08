import time
import threading
import requests
import random
from typing import List, Tuple, Optional, Dict, Any
from src.api.base import BaseAPI
from src.utils import retry_api

class KISAPIClient(BaseAPI):
    """한국투자증권(KIS) API 연동 클라이언트.

    국내 주식 주문(현금 주문), 잔고 조회, 실시간 시세 조회, 차트 데이터 수집 등을 수행합니다.
    모의투자와 실전투자 환경에 따라 자동으로 호출 tr_id를 전환하며, 
    API 레이트 리밋(Rate Limit)을 준수하기 위한 요청 큐 제어 기능을 포함합니다.

    Attributes:
        auth: KIS 인증 객체 (토큰 및 계좌 정보 포함).
        domain (str): KIS API 접속 도메인.
    """
    def __init__(self, auth):
        super().__init__()
        self.auth = auth
        self.domain = auth.domain

    _last_req_time = 0
    _req_lock = threading.Lock()

    def _request(self, method, url, **kwargs):
        """글로벌 레이트 리미터가 적용된 HTTP 요청을 수행합니다.

        모의투자의 경우 초당 호출 제한이 엄격하므로(1.8초 간격), 
        인스턴스 간 공유되는 락(_req_lock)을 통해 요청 간격을 제어합니다.

        Args:
            method (str): HTTP 메서드 (GET, POST 등).
            url (str): 요청 URL.
            **kwargs: requests.request에 전달될 추가 인자.

        Returns:
            requests.Response: API 응답 객체.
        """
        # [개선] 글로벌 레이트 리미터: 모의투자는 초당 1회 미만 엄격 제한, 실전은 제한 해제
        is_v = getattr(self.auth, 'is_virtual', True)
        if is_v:
            # 클래스 변수를 직접 참조하여 인스턴스에 상관없이 단일 큐 보장
            with KISAPIClient._req_lock:
                now = time.time()
                interval = 1.8 # 1.5 -> 1.8로 상향 (RT_CD:1 방어 강화)
                elapsed = now - KISAPIClient._last_req_time
                if elapsed < interval:
                    # 미세한 랜덤 지터 추가하여 동시성 충돌 완화
                    time.sleep(interval - elapsed + random.uniform(0.01, 0.05))
                KISAPIClient._last_req_time = time.time()
        # 실전 거래는 별도의 대기 없이 즉시 실행 (호출 큐 해제)

        return requests.request(method, url, **kwargs)

    @retry_api(max_retries=3, delay=1.5)
    def get_full_balance(self, force=False, **kwargs) -> Tuple[List[dict], dict]:
        """계좌의 전체 잔고와 자산 요약 정보를 조회합니다.

        Args:
            force (bool): 캐시 무시 여부 (현재 구현에서는 직접 조회).

        Returns:
            Tuple[List[dict], dict]: (보유 종목 리스트, 자산 요약 정보).
        """
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
            if data.get("rt_cd") != "0": 
                msg = data.get("msg1", "Unknown Error")
                raise Exception(f"KIS API Error: {msg} (RT_CD:{data.get('rt_cd')})")
            
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
            
            # output2가 비어있는 경우 대응 (종목은 없는데 예수금만 있는 경우 등)
            if not data.get("output2"):
                return holdings, {"total_asset": 0, "prev_day_asset": 0}
            
            raw_summary = data.get("output2", [{}])[0]
            d0_cash = self._safe_float(raw_summary.get("dnca_tot_amt"))            # D+0 예수금
            d2_cash = self._safe_float(raw_summary.get("prvs_rcdl_excc_amt"))      # D+2 정산예수금
            
            # 가용 현금(cash)은 주식 매도 대금을 즉시 매수 자금으로 활용할 수 있도록 D+2 정산예수금을 기준으로 합니다.
            # D+2 예수금이 마이너스인 경우(미수 발생) 추가 매수를 방지하기 위해 0으로 처리합니다.
            cash = d2_cash if d2_cash > 0 else 0
            
            stock_eval = self._safe_float(raw_summary.get("evlu_amt_smtl_amt"))
            stock_principal = self._safe_float(raw_summary.get("pchs_amt_smtl_amt"))
            
            # [복구] 메인 브랜치 표준 필드 사용
            tot_asset = self._safe_float(raw_summary.get("tot_evlu_amt"))
            if tot_asset <= 0:
                tot_asset = d2_cash + stock_eval
            
            # [복구] 메인 브랜치 표준 필드 사용 (prdy_evlu_amt)
            prev_day_asset = self._safe_float(raw_summary.get("prdy_evlu_amt") or 0)
            
            asset_info = {
                "total_asset": tot_asset,
                "total_principal": stock_principal + d2_cash,
                "stock_eval": stock_eval,
                "stock_principal": stock_principal,
                "cash": cash,
                "d0_cash": d0_cash,
                "d2_cash": d2_cash,
                "pnl": self._safe_float(raw_summary.get("evlu_pfls_smtl_amt")),
                "deposit": self._safe_float(raw_summary.get("prvs_rcdl_exca_amt") or 0),
                "prev_day_asset": prev_day_asset
            }
            return holdings, asset_info
        except Exception as e:
            # 예외를 상위로 던져서 SyncWorker가 구체적인 이유를 표시하게 함
            if "KIS API Error" in str(e): raise e
            raise Exception(f"Balance Fetch Fail: {e}")

    def get_balance(self, force=False, **kwargs) -> List[dict]:
        """보유 종목 리스트만 반환합니다."""
        return self.get_full_balance(force=force)[0]

    def order_market(self, code: str, qty: int, is_buy: bool, price: int = 0) -> Tuple[bool, str]:
        """주식을 시장가 또는 지정가로 주문합니다.

        Args:
            code (str): 종목 코드.
            qty (int): 주문 수량.
            is_buy (bool): 매수 여부 (True: 매수, False: 매도).
            price (int): 지정가 주문 시 가격 (0이면 시장가 주문).

        Returns:
            Tuple[bool, str]: (성공 여부, 메시지).
        """
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
        """특정 기간의 일봉 차트 데이터를 가져옵니다."""
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
        """특정 시점의 분봉 차트 데이터를 가져옵니다."""
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
        """국내 지수(코스피, 코스닥 등)의 차트 데이터를 가져옵니다."""
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice"
        headers = self.auth.get_auth_headers(); headers.update({"tr_id": "FHKUP03500100"})
        params = {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code, "FID_INPUT_DATE_1": start_date, "FID_INPUT_DATE_2": end_date, "FID_PERIOD_DIV_CODE": period_div}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=10)
            data = res.json()
            return data.get("output2", [])
        except: return []

    def calculate_atr(self, code: str, period: int = 14) -> float:
        """종목의 변동성 지표인 ATR(Average True Range)을 계산합니다."""
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
        """종목의 실시간 현재가 정보를 상세 조회합니다."""
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

    @retry_api(max_retries=2, delay=1.0)
    def get_investor_trading_trend(self, code: str) -> Optional[dict]:
        """종목별 투자자 매매동향(외인, 기관, 연기금, 투신 등)을 조회합니다.
        
        Args:
            code (str): 종목 코드.
            
        Returns:
            Optional[dict]: 외인/기관/연기금/투신 등의 순매수 정보.
        """
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-investor"
        headers = self.auth.get_auth_headers(); headers.update({"tr_id": "FHKST01010900"})
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code}
        try:
            res = self._request("GET", url, headers=headers, params=params, timeout=5)
            data = res.json()
            if data.get("rt_cd") != "0": return None
            
            # output은 현재 시점의 누적/요약 데이터
            d = data.get("output", {})
            # 순매수 수량 (단위: 주)
            return {
                "frgn_net_buy": self._safe_float(d.get("prdy_frgn_ntby_qty")), # 외인
                "inst_net_buy": self._safe_float(d.get("prdy_inst_ntby_qty")), # 기관 합계
                "pnsn_net_buy": self._safe_float(d.get("pnsn_net_buy_qty")),   # 연기금
                "thst_net_buy": self._safe_float(d.get("thst_net_buy_qty")),   # 투신
                "frgn_hold_rt": self._safe_float(d.get("frgn_lhld_rate"))      # 외인 보유율
            }
        except: return None
