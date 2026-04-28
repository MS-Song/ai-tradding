from src.api.kis import KISAPIClient
from src.api.naver import NaverAPIClient
from src.api.yahoo import YahooAPIClient

class KISAPI(KISAPIClient, NaverAPIClient, YahooAPIClient):
    def __init__(self, auth):
        KISAPIClient.__init__(self, auth)
        NaverAPIClient.__init__(self)
        YahooAPIClient.__init__(self)
        
    def clear_cache(self):
        self._chart_cache = {}
        self._detail_cache = {}
        self._index_cache = {}
