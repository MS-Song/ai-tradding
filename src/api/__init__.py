import os
from typing import Optional, Dict
from src.api.kis import KISAPIClient
from src.api.kiwoom import KiwoomAPIClient
from src.api.naver import NaverAPIClient
from src.api.yahoo import YahooAPIClient

def get_base_broker_class():
    broker = os.getenv("BROKER_TYPE", "KIS").upper()
    return KiwoomAPIClient if broker == "KIWOOM" else KISAPIClient

BaseBrokerClass = get_base_broker_class()

class KISAPI(BaseBrokerClass, NaverAPIClient, YahooAPIClient):
    """설정된 증권사(KIS 또는 KIWOOM), Naver, Yahoo API를 통합하여 제공하는 메인 API 클래스."""
    
    def __init__(self, auth):
        super().__init__(auth)
        
    def clear_cache(self):
        """시스템의 모든 API 캐시를 초기화합니다."""
        self._chart_cache = {}  # BaseAPI
        self._detail_cache = {} # NaverAPIClient
        self._index_cache = {}  # YahooAPIClient

    def get_investor_trading_trend(self, code: str) -> Optional[dict]:
        """네이버와 증권사 API를 결합하여 최적의 수급 데이터를 도출합니다.
        
        실거래(Real) 환경에서는 증권사 공식 데이터를 우선하며, 
        모의투자(Virtual) 환경에서는 네이버 크롤링 데이터를 우선하되 증권사 데이터를 보강합니다.
        """
        is_v = getattr(self.auth, 'is_virtual', True)
        
        # 1. 데이터 수집
        naver_data = NaverAPIClient.get_investor_trading_trend(self, code)
        broker_data = BaseBrokerClass.get_investor_trading_trend(self, code)
        
        # 2. 실거래 모드: 증권사 데이터 우선
        if not is_v and broker_data:
            if naver_data:
                # 네이버의 히스토리 데이터가 있다면 보강용으로 활용 가능 (필요 시)
                broker_data["history"] = naver_data.get("history", [])
            return broker_data
            
        # 3. 모의투자 또는 증권사 데이터 부재 시: 네이버 데이터 우선
        if not naver_data:
            return broker_data
            
        if broker_data:
            # 네이버 데이터에 증권사 전용 필드(연기금, 투신 등) 보강
            naver_data["pnsn_net_buy"] = broker_data.get("pnsn_net_buy", 0)
            naver_data["thst_net_buy"] = broker_data.get("thst_net_buy", 0)
            
        return naver_data

    def get_naver_stock_detail(self, code: str, force: bool = False, **kwargs) -> dict:
        """종목 상세 정보를 수집합니다. 실거래 모드에서는 증권사 공식 데이터를 우선합니다.
        
        증권사 API의 현재가 조회 데이터를 기반으로 PER, PBR, 시가총액 등을 구성하며,
        종목명이나 업종 지표 등 증권사 API에서 누락된 정보만 네이버에서 보강합니다.
        """
        is_v = getattr(self.auth, 'is_virtual', True)
        
        # 1. 실거래 모드: 증권사 데이터 우선 시도
        if not is_v:
            broker_data = self.get_inquire_price(code)
            if broker_data:
                # 증권사 데이터를 기본으로 설정
                detail = {
                    "name": "Unknown",
                    "price": broker_data.get("price", 0),
                    "rate": broker_data.get("ctrt", 0.0),
                    "cv": broker_data.get("vrss", 0),
                    "market_cap": f"{broker_data.get('market_cap', 0) / 100000000:,.0f}억원" if broker_data.get('market_cap') else "N/A",
                    "per": str(broker_data.get("per", "N/A")),
                    "pbr": str(broker_data.get("pbr", "N/A")),
                    "yield": "N/A",
                    "sector_per": "N/A"
                }
                
                # 부족한 필드(이름, 배당, 업종PER 등)를 네이버에서 보강 (크롤링 최소화)
                naver_data = NaverAPIClient.get_naver_stock_detail(self, code, force=force)
                if naver_data:
                    detail["name"] = naver_data.get("name", "Unknown")
                    detail["yield"] = naver_data.get("yield", "N/A")
                    detail["sector_per"] = naver_data.get("sector_per", "N/A")
                    # 증권사에서 N/A인 경우 네이버 데이터로 보강
                    if detail["per"] == "N/A": detail["per"] = naver_data.get("per", "N/A")
                    if detail["pbr"] == "N/A": detail["pbr"] = naver_data.get("pbr", "N/A")
                
                return detail

        # 2. 모의투자 또는 증권사 데이터 부재 시: 기존 네이버 로직 활용
        return NaverAPIClient.get_naver_stock_detail(self, code, force=force, **kwargs)

