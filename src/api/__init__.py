from typing import Optional, Dict
from src.api.kis import KISAPIClient
from src.api.naver import NaverAPIClient
from src.api.yahoo import YahooAPIClient

class KISAPI(KISAPIClient, NaverAPIClient, YahooAPIClient):
    """KIS, Naver, Yahoo API를 통합하여 제공하는 메인 API 클래스."""
    
    def __init__(self, auth):
        # 다중 상속 구조에서 super().__init__()을 통해 계층별 초기화를 순차적으로 수행합니다.
        # KISAPIClient -> NaverAPIClient -> YahooAPIClient -> BaseAPI 순으로 초기화됩니다.
        super().__init__(auth)
        
    def clear_cache(self):
        """시스템의 모든 API 캐시를 초기화합니다."""
        self._chart_cache = {}  # BaseAPI
        self._detail_cache = {} # NaverAPIClient
        self._index_cache = {}  # YahooAPIClient

    def get_investor_trading_trend(self, code: str) -> Optional[dict]:
        """네이버와 KIS API를 결합하여 최적의 수급 데이터를 도출합니다 (네이버 우선)."""
        # 1. 네이버에서 상세 이력(Cycle 분석용) 포함 데이터 수집
        naver_data = NaverAPIClient.get_investor_trading_trend(self, code)
        
        # 2. KIS에서 실시간 데이터 및 연기금/투신 세부 데이터 수집
        kis_data = KISAPIClient.get_investor_trading_trend(self, code)
        
        if not naver_data:
            return kis_data
            
        if kis_data:
            # 네이버 데이터에 부족한 연기금/투신 정보를 KIS 데이터로 보충
            naver_data["pnsn_net_buy"] = kis_data.get("pnsn_net_buy", 0)
            naver_data["thst_net_buy"] = kis_data.get("thst_net_buy", 0)
            # 수치 불일치 시 KIS 데이터를 실시간 신뢰도로 활용 (선택적)
            # naver_data["frgn_net_buy"] = kis_data["frgn_net_buy"] 
            
        return naver_data
