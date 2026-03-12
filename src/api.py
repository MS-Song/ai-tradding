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
        # 잔고 조회 TR ID: 실전(TTTC8434R), 모의(VTTC8434R)
        headers["tr_id"] = "VTTC8434R" if self.auth.is_virtual else "TTTC8434R"
        
        params = {
            "CANO": self.auth.cano,
            "ACNT_PRDT_CD": "01", # 상품코드 (보통 01)
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
            res.raise_for_status()
            data = res.json()
            
            # 보유 종목 리스트 반환 (output1)
            # 보유수량: hldg_qty, 매입평균가: pchs_avg_pric, 현재가: prpr, 수익률: evlu_pfls_rt
            return data.get("output1", [])
            
        except Exception as e:
            logger.error(f"[Balance] 잔고 조회 실패: {e}")
            return []

    def order_market(self, stock_code, qty, is_buy=True):
        """시장가 주문 실행 (매수/매도)"""
        url = f"{self.domain}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self.auth.get_auth_headers()
        
        # TR_ID 세팅
        if self.auth.is_virtual:
            headers["tr_id"] = "VTTC0802U" if is_buy else "VTTC0801U"
        else:
            headers["tr_id"] = "TTTC0802U" if is_buy else "TTTC0801U"
            
        body = {
            "CANO": self.auth.cano,
            "ACNT_PRDT_CD": "01",
            "PDNO": stock_code,
            "ORD_DVSN": "01", # 01: 시장가
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": "0" # 시장가 주문시 단가는 0
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
        """현재가 확인"""
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKST01010100"
        
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") == "0":
                return int(data["output"]["stck_prpr"])
        except Exception as e:
            logger.error(f"[Price] 가격 조회 에러 ({stock_code}): {e}")
        return None

    def get_index_price(self, iscd="0001"):
        """지수 정보 조회 (0001: 코스피, 1001: 코스닥)"""
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-index-price"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKST03010100"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "U",
            "FID_INPUT_ISCD": iscd
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") == "0":
                output = data.get("output", {})
                return {
                    "price": float(output.get("bstp_nmix_prpr", 0)), # 현재 지수
                    "rate": float(output.get("bstp_nmix_prni", 0)), # 전일 대비 등락율
                    "diff": float(output.get("bstp_nmix_prdy_vrss", 0)) # 전일 대비 등락폭
                }
        except Exception as e:
            logger.error(f"[Index] 지수 조회 에러: {e}")
        return None
