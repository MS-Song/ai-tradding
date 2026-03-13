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
        
    def get_overseas_balance(self):
        """해외 주식 조회 제외 (속도 최우선)"""
        return []

    def get_full_balance(self):
        """국내 잔고 및 자산 정보 조회 (환율 제외)"""
        curr_t = time.time()
        if self._balance_cache and (curr_t - self._last_balance_time < self._cache_duration):
            return self._balance_cache
            
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
            res_kr = requests.get(url_kr, headers=headers_kr, params=params_kr, timeout=5)
            data_kr = res_kr.json()
            if data_kr.get("rt_cd") == "0":
                holdings_kr = data_kr.get("output1", [])
                summary_kr = data_kr.get("output2", [{}])[0]
        except: pass

        combined, total_eval, total_pnl = [], 0, 0
        for h in holdings_kr:
            qty = float(h.get('hldg_qty', 0))
            if qty <= 0: continue
            ev, pnl = int(float(h.get('evlu_amt', 0))), int(float(h.get('evlu_pfls_amt', 0)))
            total_eval += ev; total_pnl += pnl
            combined.append({
                "pdno": h.get('pdno'), "prdt_name": h.get('prdt_name'), "hldg_qty": qty,
                "pchs_avg_pric": float(h.get('pchs_avg_pric', 0)), "prpr": float(h.get('prpr', 0)),
                "evlu_amt": ev, "evlu_pfls_rt": h.get('evlu_pfls_rt', "0.00"), "evlu_pfls_amt": pnl, "currency": "KRW"
            })
            
        deposit = int(summary_kr.get("dnca_tot_amt", 0))
        asset_info = {
            "deposit": deposit, "cash": int(summary_kr.get("prvs_rcdl_exca_amt", deposit)),
            "total_asset": deposit + total_eval, "stock_eval": total_eval, "pnl": total_pnl
        }
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
        curr_t = time.time()
        cache = self._gainers_cache if is_gainer else self._losers_cache
        last_t = self._last_gainers_time if is_gainer else self._last_losers_time
        if cache and (curr_t - last_t < 60): return cache
        
        url = f"{self.domain}/uapi/domestic-stock/v1/ranking/fluctuation"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHPST01700000"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20170", "FID_INPUT_ISCD": "0000", "FID_RANK_SORT_CLS_CODE": "0" if is_gainer else "1", "FID_INPUT_CNT_1": "0", "FID_PRC_CLS_CODE": "0", "FID_INQR_RANGE_1": "0", "FID_INQR_RANGE_2": "0", "FID_VOL_CNT": "0", "FID_TRGT_CLS_CODE": "0", "FID_TRGT_EXLS_CLS_CODE": "0", "FID_PRC_RANGE_CLS_CODE": "0", "FID_RSFL_RATE1": "0", "FID_RSFL_RATE2": "0", "FID_DIV_CLS_CODE": "0", "FID_ETC_CLS_CODE": "0", "FID_INPUT_PRICE_1": "0", "FID_INPUT_PRICE_2": "0"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            if data.get("rt_cd") == "0":
                out = data.get("output", data.get("output1", []))
                if not out and "output2" in data: out = data["output2"]
                
                results = []
                if isinstance(out, list):
                    for item in out[:10]:
                        code = item.get("stck_shrn_iscd")
                        if not code: continue
                        results.append({
                            "mkt": "KSP" if code.startswith(('00', '01', '02', '03', '05', '06')) else "KDQ", 
                            "name": item.get("hts_kor_isnm", "Unknown"), 
                            "code": code, 
                            "price": item.get("stck_prpr", "0"), 
                            "rate": item.get("prdy_ctrt", "0")
                        })
                if is_gainer: self._gainers_cache, self._last_gainers_time = results, curr_t
                else: self._losers_cache, self._last_losers_time = results, curr_t
                return results
        except: pass
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
