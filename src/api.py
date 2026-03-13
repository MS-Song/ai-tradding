import requests
from src.logger import logger

class KISAPI:
    def __init__(self, auth):
        self.auth = auth
        self.domain = auth.domain
        
    def get_balance(self):
        """계좌 잔고 및 종목별 수익률 확인"""
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "VTTC8434R" if self.auth.is_virtual else "TTTC8434R"
        
        params = {
            "CANO": self.auth.cano,
            "ACNT_PRDT_CD": "01",
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") == "0":
                return data.get("output1", [])
            else:
                logger.error(f"[Balance] 잔고 조회 실패: {data.get('msg1')} ({data.get('rt_cd')})")
                return []
        except Exception as e:
            logger.error(f"[Balance] 잔고 조회 시스템 에러: {e}")
            return []

    def get_deposit(self):
        """계좌 잔고 및 예수금 상세 정보 확인 (실시간 반영)"""
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "VTTC8434R" if self.auth.is_virtual else "TTTC8434R"
        
        params = {
            "CANO": self.auth.cano,
            "ACNT_PRDT_CD": "01",
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            output2 = data.get("output2", [{}])[0]
            
            # 예수금 총액 (D+2)
            deposit = int(output2.get("dnca_tot_amt", 0))
            
            # 실시간 주문 가능 금액 탐색 (우선순위 순)
            # 1. prvs_rcdl_exca_amt: 이전익일환급금포함현금 (실시간 매수금 차감됨)
            # 2. nll_amt: 실제 현금 잔액
            # 3. dnca_tot_amt: 최후의 보루 (이것마저 0이면 진짜 0원)
            actual_cash = int(output2.get("prvs_rcdl_exca_amt", 0))
            if actual_cash == 0:
                actual_cash = int(output2.get("nll_amt", 0))
            if actual_cash == 0:
                actual_cash = deposit

            return {
                "deposit": deposit,
                "cash": actual_cash,                               # 실시간 현금 잔액
                "total_asset": int(output2.get("tot_evlu_amt", 0)), # 총 평가금액
                "stock_eval": int(output2.get("scts_evlu_amt", 0)), # 주식 평가금액
                "pnl": int(output2.get("evlu_pfls_smtl_amt", 0)), # 총 평가 손익
            }
        except Exception as e:
            logger.error(f"[Deposit] 예수금 조회 실패: {e}")
            return {"deposit": 0, "cash": 0, "total_asset": 0, "stock_eval": 0, "pnl": 0}

    def order_market(self, stock_code, qty, is_buy=True):
        """시장가 주문 실행 (매수/매도)"""
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self.auth.get_auth_headers()
        
        if self.auth.is_virtual:
            headers["tr_id"] = "VTTC0802U" if is_buy else "VTTC0801U"
        else:
            headers["tr_id"] = "TTTC0802U" if is_buy else "TTTC0801U"
            
        body = {
            "CANO": self.auth.cano,
            "ACNT_PRDT_CD": "01",
            "PDNO": stock_code,
            "ORD_DVSN": "01",
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": "0"
        }
        
        action = "매수" if is_buy else "매도"
        try:
            res = requests.post(url, headers=headers, json=body, timeout=10)
            data = res.json()
            
            if data.get("rt_cd") == "0":
                logger.info(f"[{action} 성공] 종목코드: {stock_code} | 수량: {qty}주")
                return True
            else:
                logger.error(f"[{action} 거부] 사유: {data.get('msg1')}")
                return False
        except Exception as e:
            logger.error(f"[Order] 시장가 주문 API 에러: {e}")
            return False

    def get_inquire_price(self, stock_code):
        """현재가, 거래량 및 등락 정보 확인"""
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKST01010100"
        
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                return {
                    "price": int(output.get("stck_prpr", 0)),
                    "vol": int(output.get("acml_vol", 0)),
                    "prev_vol": int(output.get("prdy_vol", 0)),
                    "rate": float(output.get("prdy_ctrt", 0)),
                    "diff": float(output.get("prdy_vrss", 0))
                }
        except Exception as e:
            logger.error(f"[Price] 가격/거래량 조회 에러 ({stock_code}): {e}")
        return None

    def get_top_gainers(self):
        """상승률 상위 종목 조회 (공식 API: FHPST01700000 - MEGA 18 파라미터 적용)"""
        url = f"{self.domain}/uapi/domestic-stock/v1/ranking/fluctuation"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHPST01700000"
        
        # 검증된 18개 풀 파라미터 세트
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20170",
            "FID_INPUT_ISCD": "0000",
            "FID_RANK_SORT_CLS_CODE": "0",
            "FID_INPUT_CNT_1": "0",
            "FID_PRC_CLS_CODE": "0",
            "FID_INQR_RANGE_1": "0",
            "FID_INQR_RANGE_2": "0",
            "FID_VOL_CNT": "0",
            "FID_TRGT_CLS_CODE": "0",
            "FID_TRGT_EXLS_CLS_CODE": "0",
            "FID_PRC_RANGE_CLS_CODE": "0",
            "FID_RSFL_RATE1": "0",
            "FID_RSFL_RATE2": "0",
            "FID_DIV_CLS_CODE": "0",
            "FID_ETC_CLS_CODE": "0",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", [])
                    results = []
                    for item in output[:5]:
                        results.append({
                            "hts_kor_isnm": item.get("hts_kor_isnm"),
                            "mksc_shrn_iscd": item.get("stck_shrn_iscd"),
                            "data_rank_sort_val": item.get("prdy_ctrt")
                        })
                    return results
            return []
        except:
            return []

    def get_stock_news(self, stock_code):
        """종목 뉴스 조회 (최근 1건 제목)"""
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/stock-news"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKSW10100100"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_NEWS_SND_DATE": "",
            "FID_NEWS_SND_TIME": "",
            "FID_NEWS_SND_HMS": ""
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200 and res.text.strip():
                data = res.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", [])
                    if output:
                        return output[0].get("hts_news_titl", "최근 소식 없음")
            return "최근 소식 없음"
        except:
            return "정보 없음"

    def get_index_price(self, iscd="0001"):
        """KIS 공식 API 시도 후 외부 API 백업으로 지수 조회"""
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-index-price"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKUP01010100"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": iscd
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", {})
                    return {
                        "name": "KOSPI" if iscd == "0001" else "KOSDAQ",
                        "price": float(output.get("bstp_nmix_prpr", 0)),
                        "rate": float(output.get("bstp_nmix_prni", 0)),
                        "diff": float(output.get("bstp_nmix_prdy_vrss", 0))
                    }
            return self._get_external_index(iscd)
        except:
            return self._get_external_index(iscd)

    def _get_external_index(self, iscd):
        """외부 API(네이버/야후) 실시간 지수 조회 및 수치 보정"""
        try:
            if iscd in ["0001", "1001"]:
                target = "KOSPI" if iscd == "0001" else "KOSDAQ"
                url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:{target}"
                res = requests.get(url, timeout=5)
                data = res.json()
                result = data['result']['areas'][0]['datas'][0]
                
                # 네이버 nv값은 소수점 없이 정수로 올 때가 많음 (예: 265012 -> 2650.12)
                raw_price = float(result['nv'])
                # 코스피가 10,000을 넘을 리 없으므로(현재 기준) 비정상적으로 크면 100으로 나눔
                if raw_price > 10000:
                    price = raw_price / 100
                else:
                    price = raw_price
                    
                # 대비(cv)와 등락율(cr)도 동일하게 보정
                raw_diff = float(result['cv'])
                diff = raw_diff / 100 if abs(raw_diff) > 500 else raw_diff
                
                return {
                    "name": target,
                    "price": price,
                    "rate": float(result['cr']),
                    "diff": diff
                }
            else:
                # 해외 지수 (야후는 소수점이 포함되어 오므로 그대로 사용)
                symbol = "^IXIC" if iscd == "NAS" else "^GSPC"
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
                headers = {"User-Agent": "Mozilla/5.0"}
                res = requests.get(url, headers=headers, timeout=5)
                data = res.json()
                meta = data['chart']['result'][0]['meta']
                curr_price = meta['regularMarketPrice']
                prev_close = meta['previousClose']
                return {
                    "name": "NASDAQ" if iscd == "NAS" else "S&P 500",
                    "price": curr_price,
                    "rate": ((curr_price - prev_close) / prev_close) * 100,
                    "diff": curr_price - prev_close
                }
        except:
            return None
