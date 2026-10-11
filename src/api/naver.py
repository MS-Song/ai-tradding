import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import random
from typing import List, Dict, Optional, Any
from src.api.base import BaseAPI
from src.utils import safe_cast_float
from src.utils import retry_api
from src.logger import log_error
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

class NaverAPIClient(BaseAPI):
    """네이버 금융(Finance) 데이터를 수집하는 클라이언트.

    실시간 시세(polling API), 인기 검색 종목, 거래량 급증 종목, 종목 상세 정보(PER/PBR), 
    뉴스, 테마 데이터 등을 크롤링 또는 API를 통해 수집합니다.

    Attributes:
        _detail_cache (dict): 종목 상세 정보 캐시.
        _cache_duration (int): 캐시 유효 기간 (초).
    """
    def __init__(self):
        super().__init__()
        self._detail_cache = {}
        self._cache_duration = 120
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        # [v2.0.1] ConnectionResetError(10054) 등 서버 측 연결 끊김에 대한 자동 재시도 설정
        retry_strategy = Retry(
            total=3,                          # 최대 3회 재시도
            backoff_factor=0.5,               # 0.5초, 1초, 2초 백오프
            status_forcelist=[500, 502, 503, 504],  # 서버 에러 시에도 재시도
            allowed_methods=["GET", "POST"],   # GET/POST 모두 재시도 허용
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get_naver_stocks_realtime(self, codes: List[str]) -> Dict[str, dict]:
        """여러 종목의 실시간 시세를 한 번에 조회합니다.

        네이버 polling API를 사용하며, 등락률 부호(rf 필드)를 보정하여 반환합니다.

        Args:
            codes (List[str]): 종목 코드 리스트.

        Returns:
            Dict[str, dict]: 종목 코드를 키로 하는 시세 정보 맵.
        """
        if not codes: return {}
        try:
            codes_str = ",".join(codes)
            api_url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{codes_str}"
            res = self._session.get(api_url, timeout=5)
            results = {}
            if res.status_code == 200:
                data = res.json()
                for area in data.get('result', {}).get('areas', []):
                    for item in area.get('datas', []):
                        code = item.get('cd')
                        if not code: continue
                        price = float(item.get('nv', 0))
                        # [Fix] Naver 실시간 API는 등락률(cr), 등락폭(cv)이 절대값으로 올 때가 많음 -> rf 필드로 부호 결정
                        sign = item.get('rf') # 1: 상한, 2: 상승, 3: 보합, 4: 하한, 5: 하락
                        rate = float(item.get('cr', 0.0))
                        cv = float(item.get('cv', 0))
                        if sign in ['4', '5']:
                            rate = -abs(rate)
                            cv = -abs(cv)
                        
                        results[code] = {
                            "name": item.get('nm'), "price": price,
                            "rate": rate,
                            "cv": cv,
                            "aq": float(item.get('aq', 0)),
                            "amt": float(item.get('aa', 0)), # [추가] 거래대금 (백만 단위)
                            "hv": float(item.get('hv', price)),
                            "lv": float(item.get('lv', price)),
                            "ov": float(item.get('ov', price))
                        }
                        # [추가] 실시간 캐시 업데이트
                        if not hasattr(self, '_realtime_cache'): self._realtime_cache = {}
                        self._realtime_cache[code] = (time.time(), results[code])
            return results
        except: return {}

    def _parse_mobile_stock_item(self, s: dict) -> dict:
        """네이버 모바일 증권 API 종목 객체를 공통 포맷으로 파싱합니다."""
        code = str(s.get("itemCode", "")).strip()
        name = str(s.get("stockName", "")).strip()
        price = safe_cast_float(s.get("closePriceRaw", s.get("closePrice", 0)))
        rate = safe_cast_float(s.get("fluctuationsRatio", 0.0))
        sosok = str(s.get("sosok", "0"))
        mkt = "KSP" if sosok == "0" else "KDQ"
        vol = safe_cast_float(s.get("accumulatedTradingVolumeRaw", s.get("accumulatedTradingVolume", 0)))
        amt_raw = safe_cast_float(s.get("accumulatedTradingValueRaw", 0))
        amt = amt_raw / 1_000_000.0 if amt_raw > 0 else safe_cast_float(s.get("accumulatedTradingValue", 0))
        return {
            "code": code, "name": name, "price": price,
            "rate": rate, "vol": vol, "amt": amt, "mkt": mkt
        }

    def get_naver_hot_stocks(self) -> List[dict]:
        """네이버 모바일 증권 '인기 검색 종목' TOP 20을 수집합니다.

        Returns:
            List[dict]: 인기 종목 리스트 (코드, 이름, 가격, 등락률 등 포함).
        """
        results = []
        try:
            url = "https://m.stock.naver.com/api/stocks/searchTop/all?page=1&pageSize=30"
            res = self._session.get(url, timeout=5)
            if res.status_code == 200:
                stocks = res.json().get("stocks", [])
                for s in stocks:
                    item = self._parse_mobile_stock_item(s)
                    if item["code"]:
                        results.append(item)
            return results[:20]
        except Exception as e:
            log_error(f"get_naver_hot_stocks 실패: {e}")
            return []

    def get_naver_stock_detail(self, code: str, force: bool = False, **kwargs) -> dict:
        """종목의 상세 정보(시총, PER, PBR 등)를 수집합니다.

        실시간 API와 모바일 integration API를 결합하여 데이터를 구성하며, 
        단기 캐싱을 통해 불필요한 네트워크 요청을 방지합니다.

        Args:
            code (str): 종목 코드.
            force (bool): 캐시를 무시하고 새로 수집할지 여부.

        Returns:
            dict: 종목 상세 정보 딕셔너리.
        """
        curr_t = time.time()
        if not force and code in self._detail_cache:
            ts, data = self._detail_cache[code]
            if curr_t - ts < self._cache_duration: return data
        
        detail = {
            "name": "Unknown", "price": 0, "rate": 0.0, "cv": 0, 
            "market_cap": "N/A", "per": "N/A", "pbr": "N/A", 
            "yield": "N/A", "sector_per": "N/A",
            "vol": 0, "amt": 0
        }
        
        # 1. 실시간 시세 및 기본 정보 (캐시 확인 후 polling API 활용)
        try:
            item = None
            if hasattr(self, '_realtime_cache') and code in self._realtime_cache:
                ts, rt_item = self._realtime_cache[code]
                if curr_t - ts < 10:
                    item = rt_item
            
            if not item:
                rt_data = self.get_naver_stocks_realtime([code])
                if code in rt_data: item = rt_data[code]
            
            if item:
                detail["name"] = item.get("name", "Unknown")
                detail["price"] = item.get("price", 0)
                detail["rate"] = item.get("rate", 0.0)
                detail["cv"] = item.get("cv", 0)
                detail["vol"] = item.get("aq", 0)
                detail["amt"] = item.get("amt", 0)
        except: pass

        # 2. 펀더멘털 및 상세 정보 (모바일 통합 API 활용)
        try:
            url = f"https://m.stock.naver.com/api/stock/{code}/integration"
            res = self._session.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if detail["name"] == "Unknown":
                    detail["name"] = data.get("stockName", "Unknown")
                for info in data.get("totalInfos", []):
                    k = str(info.get("key", "")).strip()
                    v = str(info.get("value", "")).strip()
                    if "시총" in k or "시가총액" in k:
                        detail["market_cap"] = v
                    elif k == "PER":
                        detail["per"] = v.replace("배", "").strip()
                    elif k == "PBR":
                        detail["pbr"] = v.replace("배", "").strip()
                    elif "배당수익률" in k:
                        detail["yield"] = v
                    elif "업종PER" in k:
                        detail["sector_per"] = v.replace("배", "").strip()
            
            self._detail_cache[code] = (curr_t, detail)
            return detail
        except: return detail

    def get_naver_volume_stocks(self) -> List[dict]:
        """네이버 모바일 증권 '거래량 상위 종목' 리스트를 수집합니다.

        Returns:
            List[dict]: 거래량 상위 종목 리스트 (코스피/코스닥 통합 최대 40개).
        """
        results = []
        try:
            url = "https://m.stock.naver.com/api/stocks/quantTop/all?page=1&pageSize=40"
            res = self._session.get(url, timeout=5)
            if res.status_code == 200:
                stocks = res.json().get("stocks", [])
                for s in stocks:
                    item = self._parse_mobile_stock_item(s)
                    if item["code"]:
                        results.append(item)
            results.sort(key=lambda x: x.get('vol', 0), reverse=True)
            return results[:40]
        except Exception as e:
            log_error(f"get_naver_volume_stocks 실패: {e}")
            return []

    def get_naver_amount_stocks(self) -> List[dict]:
        """네이버 모바일 증권 '거래대금 상위 종목' 리스트를 수집합니다.

        Returns:
            List[dict]: 거래대금 상위 종목 리스트 (코스피/코스닥 통합 최대 40개).
        """
        results = []
        try:
            url = "https://m.stock.naver.com/api/stocks/priceTop/all?page=1&pageSize=40"
            res = self._session.get(url, timeout=5)
            if res.status_code == 200:
                stocks = res.json().get("stocks", [])
                for s in stocks:
                    item = self._parse_mobile_stock_item(s)
                    if item["code"]:
                        results.append(item)
            results.sort(key=lambda x: x.get('amt', 0), reverse=True)
            return results[:40]
        except Exception as e:
            log_error(f"get_naver_amount_stocks 실패: {e}")
            return []

    def get_naver_stock_news(self, code: str) -> List[str]:
        """특정 종목의 최신 뉴스 헤드라인을 수집합니다.

        Args:
            code (str): 종목 코드.

        Returns:
            List[str]: 뉴스 헤드라인 리스트 (최대 3개).
        """
        try:
            url = f"https://m.stock.naver.com/api/news/stock/{code}?page=1&pageSize=3"
            res = self._session.get(url, timeout=5)
            news_list = []
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and data:
                    items = data[0].get("items", [])
                    import html
                    for it in items[:3]:
                        title = html.unescape(it.get("title", "").strip())
                        if title:
                            news_list.append(f"[뉴스] {title}")
            return news_list
        except Exception as e:
            log_error(f"get_naver_stock_news 실패: {e}")
            return []

    def get_naver_theme_data(self) -> dict:
        """네이버 모바일 증권 테마 API 데이터를 수집하여 테마-종목 맵을 구축합니다.

        기존 HTML 스크래핑 방식에서 모바일 증권 공식 JSON API 연동으로 전환하여,
        웹 UI 개편에 영향을 받지 않고 고속 병렬 수집(ThreadPoolExecutor)을 지원합니다.

        Returns:
            dict: {테마명: [{"name": 종목명, "code": 종목코드}, ...]} 형식의 데이터.
        """
        theme_map = {}
        try:
            # 1. 테마 그룹 목록 수집 (모바일 API)
            groups = []
            for page in range(1, 20):
                url = f"https://m.stock.naver.com/api/stocks/theme?page={page}&pageSize=100"
                res = self._session.get(url, timeout=10)
                if res.status_code != 200:
                    break
                data = res.json()
                page_groups = data.get("groups", [])
                if not page_groups:
                    break
                groups.extend(page_groups)
                total_count = data.get("totalCount", 0)
                if total_count and len(groups) >= total_count:
                    break

            if not groups:
                return {}

            # 2. 각 테마 그룹별 편입 종목 수집 (동시성 5개로 안정적 병렬 처리)
            from concurrent.futures import ThreadPoolExecutor

            def _fetch_group_stocks(group: dict):
                group_no = group.get("no")
                group_name = group.get("name")
                if not group_no or not group_name:
                    return None, []
                total_cnt = group.get("totalCount", 0)
                max_page = (total_cnt + 99) // 100 if total_cnt > 0 else 1
                group_stocks = []
                for p in range(1, max_page + 1):
                    detail_url = f"https://m.stock.naver.com/api/stocks/theme/{group_no}?page={p}&pageSize=100"
                    try:
                        r = self._session.get(detail_url, timeout=10)
                        if r.status_code == 200:
                            for item in r.json().get("stocks", []):
                                code = item.get("itemCode")
                                name = item.get("stockName")
                                if code and name:
                                    group_stocks.append({"name": name, "code": code})
                    except Exception:
                        pass
                return group_name, group_stocks

            with ThreadPoolExecutor(max_workers=5) as executor:
                for name, stocks in executor.map(_fetch_group_stocks, groups):
                    if name and stocks:
                        theme_map[name] = stocks

            return theme_map
        except Exception as e:
            log_error(f"get_naver_theme_data 오류 발생: {e}")
            return {}

    def get_naver_minute_chart(self, code: str, count: int = 40) -> List[dict]:
        """네이버 F-Chart XML API를 통해 분봉 데이터를 가져옵니다.

        한국투자증권 API 장애 시 지표 분석을 위한 Fallback용으로 사용됩니다.

        Args:
            code (str): 종목 코드.
            count (int): 가져올 봉 개수.

        Returns:
            List[dict]: 분봉 캔들 리스트.
        """
        try:
            url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=minute&count={count}&requestType=0"
            res = self._session.get(url, timeout=5)
            if res.status_code != 200: return []
            
            import re
            pattern = re.compile(r'<item data="([^"]+)" />')
            items = pattern.findall(res.text)
            
            candles = []
            for item in items:
                parts = item.split('|')
                if len(parts) >= 6:
                    candles.append({
                        "stck_cntg_hour": parts[0][-6:], 
                        "stck_prpr": parts[4], 
                        "stck_clpr": parts[4]
                    })
            return list(reversed(candles))
        except:
            return []

    def get_naver_daily_chart(self, code: str, count: int = 100) -> List[dict]:
        """네이버 F-Chart XML API를 통해 일봉 데이터를 가져옵니다.

        한국투자증권 API 장애 시 지표 분석을 위한 Fallback용으로 사용됩니다.

        Args:
            code (str): 종목 코드.
            count (int): 가져올 봉 개수 (기본 100개).

        Returns:
            List[dict]: 일봉 캔들 리스트.
        """
        try:
            url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0"
            res = self._session.get(url, timeout=5)
            if res.status_code != 200: return []
            
            import re
            pattern = re.compile(r'<item data="([^"]+)" />')
            items = pattern.findall(res.text)
            
            candles = []
            for item in items:
                parts = item.split('|')
                if len(parts) >= 6:
                    candles.append({
                        "stck_bsop_date": parts[0],
                        "stck_oprc": parts[1],
                        "stck_hgpr": parts[2],
                        "stck_lwpr": parts[3],
                        "stck_clpr": parts[4],
                        "stck_prpr": parts[4]
                    })
            return list(reversed(candles))
        except:
            return []

    @retry_api(max_retries=2, delay=1.0)
    def get_investor_trading_trend(self, code: str) -> Optional[dict]:
        """네이버 금융에서 특정 종목의 투자자별 매매동향(외인, 기관)을 수집합니다.

        기존 KIS API 대비 과거 이력을 포함하여 상세히 분석할 수 있습니다.

        Args:
            code (str): 종목 코드.

        Returns:
            Optional[dict]: 최신 수급 정보 및 과거 5거래일 이력.
        """
        try:
            url = f"https://finance.naver.com/item/frgn.naver?code={code}"
            self._wait_for_domain_delta(url)
            
            # [수정] 웹페이지 크롤링 시에는 JSON 헤더가 오해를 살 수 있으므로 User-Agent만 포함된 클린 헤더 사용
            clean_headers = {"User-Agent": self.headers.get("User-Agent")}
            res = self._session.get(url, headers=clean_headers, timeout=5)
            if not BeautifulSoup: return None
            
            soup = BeautifulSoup(res.content, 'html.parser', from_encoding='cp949')
            tables = soup.find_all('table', {'class': 'type2'})
            table = None
            for t in tables:
                th = t.find('th')
                if th and '날짜' in th.text:
                    table = t
                    break
            
            if not table: return None
            
            rows = table.find_all('tr')
            history = []
            for row in rows:
                cols = row.find_all('td')
                if len(cols) > 8:
                    date = cols[0].text.strip()
                    if not date or '.' not in date: continue
                    
                    # 기관, 외인 순매수 (주 단위)
                    inst = safe_cast_float(cols[5].text.strip().replace(',', ''))
                    frgn = safe_cast_float(cols[6].text.strip().replace(',', ''))
                    hold_rt = safe_cast_float(cols[8].text.strip().replace(',', '').replace('%', ''))
                    
                    history.append({
                        "date": date,
                        "inst_net_buy": inst,
                        "frgn_net_buy": frgn,
                        "frgn_hold_rt": hold_rt
                    })
                    if len(history) >= 10: break # 최근 10거래일 수집
            
            if not history: return None
            
            # 최신 데이터 (오늘)
            latest = history[0]
            return {
                "frgn_net_buy": latest["frgn_net_buy"],
                "inst_net_buy": latest["inst_net_buy"],
                "frgn_hold_rt": latest["frgn_hold_rt"],
                "pnsn_net_buy": 0, # 네이버 상세 페이지에선 연기금 분리 불가 (KIS Fallback 필요)
                "history": history, # 과거 이력 전달 (사이클 분석용)
                "source": "naver"
            }
        except Exception as e:
            log_error(f"Naver Investor Fetch Error (Code: {code}): {e}")
            return None

    def get_market_open_status(self) -> Optional[bool]:
        """네이버 모바일 API를 통해 국내 증시의 실시간 개장 상태를 확인합니다.

        Returns:
            Optional[bool]: 개장 시 True, 마감 시 False, 확인 불가 시 None.
        """
        try:
            url = "https://m.stock.naver.com/api/index/KOSPI/basic"
            self._wait_for_domain_delta(url)
            res = self._session.get(url, timeout=5)
            if res.status_code == 200:
                status = res.json().get('marketStatus')
                if status:
                    return status == "OPEN"
        except Exception as e:
            from src.logger import log_error
            log_error(f"⚠️ 시장 상태 조회 오류: {e}")
        return None
