import requests
import time
from src.logger import logger

class KISAPI:
    def __init__(self, auth):
        self.auth = auth
        self.domain = auth.domain
        # TPS 방어를 위한 캐시 변수
        self._balance_cache = None
        self._last_balance_time = 0
        self._gainers_cache = None
        self._last_gainers_time = 0
        self._losers_cache = None
        self._last_losers_time = 0
        self._news_cache = {} # 종목별 뉴스 캐시
        self._cache_duration = 0.5 # 0.5초 캐시
        
    def get_full_balance(self):
        """계좌 잔고(종목)와 예수금/자산 요약을 한 번에 조회 (TPS 최적화 및 캐싱)"""
        current_time = time.time()
        if self._balance_cache and (current_time - self._last_balance_time < self._cache_duration):
            return self._balance_cache
            
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
            time.sleep(0.5) # 강제 TPS 방어 (초당 2회 제한)
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            
            if data.get("rt_cd") != "0":
                logger.error(f"[Balance] 조회 실패: {data.get('msg1')} ({data.get('rt_cd')})")
                return [], {"deposit": 0, "cash": 0, "total_asset": 0, "stock_eval": 0, "pnl": 0}

            # 1. 종목 리스트 (output1)
            holdings = data.get("output1", [])
            
            # 2. 계좌 요약 (output2)
            summary = data.get("output2", [{}])[0]
            
            deposit = int(summary.get("dnca_tot_amt", 0))        # 예수금 (D+2)
            actual_cash = int(summary.get("prvs_rcdl_exca_amt", 0)) # 주문 가능 현금
            if actual_cash == 0:
                actual_cash = int(summary.get("nll_amt", 0))
            if actual_cash == 0:
                actual_cash = deposit

            stock_eval = int(summary.get("scts_evlu_amt", 0))    # 주식 평가액 합계
            
            # 직접 합산 로직 (정합성 강화)
            calculated_pnl = 0
            calculated_stock_eval = 0
            for h in holdings:
                curr_price = float(h.get('prpr', 0))
                avg_price = float(h.get('pchs_avg_pric', 0))
                h_qty = float(h.get('hldg_qty', 0))
                
                calculated_pnl += int((curr_price - avg_price) * h_qty)
                calculated_stock_eval += int(float(h.get('evlu_amt', 0)))
            
            # API 제공 데이터와 직접 계산 데이터 중 더 신뢰할 수 있는 쪽 선택 (보통 직접 계산이 정확)
            asset_info = {
                "deposit": deposit,
                "cash": actual_cash,
                "total_asset": deposit + calculated_stock_eval, # 예수금 + 실제 종목 평가액 합계
                "stock_eval": calculated_stock_eval,
                "pnl": calculated_pnl,
            }
            
            # 캐시 업데이트
            self._balance_cache = (holdings, asset_info)
            self._last_balance_time = time.time()
            
            return holdings, asset_info
            
        except Exception as e:
            logger.error(f"[Balance] 통합 조회 시스템 에러: {e}")
            return [], {"deposit": 0, "cash": 0, "total_asset": 0, "stock_eval": 0, "pnl": 0}

    def get_balance(self):
        """하위 호환성을 위해 유지"""
        holdings, _ = self.get_full_balance()
        return holdings

    def get_deposit(self):
        """하위 호환성을 위해 유지"""
        _, asset_info = self.get_full_balance()
        return asset_info

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
            time.sleep(0.5)
            res = requests.post(url, headers=headers, json=body, timeout=10)
            data = res.json()

            if data.get("rt_cd") == "0":
                msg = f"[{action} 성공] 종목코드: {stock_code} | 수량: {qty}주"
                logger.info(msg)
                return True, msg
            else:
                err_msg = data.get("msg1", "알 수 없는 에러")
                logger.error(f"[{action} 거부] 사유: {err_msg}")
                return False, err_msg
        except Exception as e:
            logger.error(f"[{action} 에러] 시스템 문제: {e}")
            return False, str(e)


    def get_inquire_price(self, stock_code):
        """현재가, 거래량 및 등락 정보 확인"""
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKST01010100"
        
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code}
        
        try:
            time.sleep(0.5) # 강제 TPS 방어 (초당 2회 제한)
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

    def _get_ranking(self, is_gainer=True):
        """상승률(0) 또는 하락률(1) 순위 조회 공통 함수 (1분 캐시)"""
        current_time = time.time()
        cache = self._gainers_cache if is_gainer else self._losers_cache
        last_time = self._last_gainers_time if is_gainer else self._last_losers_time
        
        if cache and (current_time - last_time < 60):
            return cache

        url = f"{self.domain}/uapi/domestic-stock/v1/ranking/fluctuation"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHPST01700000"
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20170",
            "FID_INPUT_ISCD": "0000",
            "FID_RANK_SORT_CLS_CODE": "0" if is_gainer else "1",
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
            time.sleep(0.5)
            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", [])
                    results = []
                    # 로컬 필터링을 위해 충분한 데이터(상위 50개)를 확보
                    for item in output[:50]: 
                        code = item.get("stck_shrn_iscd")
                        mkt_name = "KSP" if code.startswith(('00', '01', '02', '03', '05', '06')) else "KDQ"
                        results.append({
                            "mkt": mkt_name,
                            "name": item.get("hts_kor_isnm"),
                            "code": code,
                            "price": item.get("stck_prpr"),
                            "rate": item.get("prdy_ctrt")
                        })
                    if is_gainer:
                        self._gainers_cache = results
                        self._last_gainers_time = current_time
                    else:
                        self._losers_cache = results
                        self._last_losers_time = current_time
                    return results
            return []
        except:
            return []

    def get_top_gainers(self):
        return self._get_ranking(is_gainer=True)

    def get_top_losers(self):
        return self._get_ranking(is_gainer=False)

    def get_stock_news(self, stock_code):
        """종목 뉴스 조회 (최근 1건 제목, 10분 캐시)"""
        current_time = time.time()
        if stock_code in self._news_cache:
            news_data, last_time = self._news_cache[stock_code]
            if current_time - last_time < 600: # 10분 캐시
                return news_data

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
                    news_title = output[0].get("hts_news_titl", "최근 소식 없음") if output else "최근 소식 없음"
                    self._news_cache[stock_code] = (news_title, current_time)
                    return news_title
            return "최근 소식 없음"
        except Exception:
            return "정보 없음"

    def get_index_price(self, iscd="0001"):
        """KIS 공식 API 시도 후 외부 API 백업으로 지수 조회"""
        url = f"{self.domain}/uapi/domestic-stock/v1/quotations/inquire-index-price"
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "FHKUP01010100"
        
        params = {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": iscd}
        
        try:
            # 해외 지수 코드(NAS, SPX, NQF)는 즉시 외부 API로 분기
            if iscd in ["NAS", "SPX", "NQF", "USD"]:
                return self._get_external_index(iscd)

            res = requests.get(url, headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", {})
                    return {
                        "name": "KOSPI" if iscd == "0001" else "KOSDAQ",
                        "price": float(output.get("bstp_nmix_prpr", 0)),
                        "rate": float(output.get("bstp_nmix_prni", 0)),
                        "diff": float(output.get("bstp_nmix_prdy_vrss", 0)),
                        "status": output.get("bstp_nmix_prpr_stat_cls_code", "00")
                    }
            return self._get_external_index(iscd)
        except:
            return self._get_external_index(iscd)

    def _get_external_index(self, iscd):
        """외부 API(네이버/야후) 실시간 지수 및 환율 조회"""
        try:
            # 1. 환율 전용 (네이버 모바일 API가 가장 정확함)
            if iscd == "USD":
                url = "https://m.stock.naver.com/front-api/v1/marketIndex/prices?category=exchange&re_id=FX_USDKRW&size=1"
                res = requests.get(url, timeout=5)
                data = res.json()
                result = data['result'][0]
                return {
                    "name": "USD",
                    "price": float(result['closePrice'].replace(',', '')),
                    "rate": float(result['fluctuationsRatio']),
                    "diff": float(result['fluctuationsPrice'].replace(',', ''))
                }

            # 2. 국내 지수 (네이버 폴링 API)
            elif iscd in ["0001", "1001"]:
                target = "KOSPI" if iscd == "0001" else "KOSDAQ"
                url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_INDEX:{target}"
                res = requests.get(url, timeout=5)
                data = res.json()
                item = data['result']['areas'][0]['datas'][0]
                price = float(item['nv'])
                if price > 10000: price /= 100
                return {
                    "name": "KSP" if iscd=="0001" else "KDQ",
                    "price": price,
                    "rate": float(item['cr']),
                    "diff": float(item['cv'])
                }
            
            # 3. 해외 지수 및 선물 (야후 파이낸스)
            else:
                symbol = "^IXIC" if iscd == "NAS" else "^GSPC" if iscd == "SPX" else "NQ=F"
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
                headers = {"User-Agent": "Mozilla/5.0"}
                res = requests.get(url, headers=headers, timeout=5)
                data = res.json()
                meta = data['chart']['result'][0]['meta']
                curr_price = meta.get('regularMarketPrice', 0)
                prev_close = meta.get('previousClose', 0)
                rate = ((curr_price - prev_close) / prev_close * 100) if prev_close != 0 else 0
                return {
                    "name": "NAS" if iscd=="NAS" else "SPX" if iscd=="SPX" else "NAS.F",
                    "price": curr_price,
                    "rate": rate,
                    "diff": curr_price - prev_close
                }
        except:
            return None
