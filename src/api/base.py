import time
import threading
import requests
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

class BaseAPI:
    """모든 외부 API 통신 클래스의 기반이 되는 베이스 클래스.
    
    API 호출 시 도메인별 속도 제한(Rate Limit)을 준수하기 위한 대기 로직, 
    데이터 타입 안전 변환(Safe Float), 그리고 차트 데이터 캐싱 기능을 제공합니다.
    """
    def __init__(self):
        """BaseAPI를 초기화합니다.
        
        기본 HTTP 헤더 설정, 도메인별 호출 간격 제어 객체, 
        그리고 차트 데이터 캐시를 생성합니다.
        """
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self._domain_lock = threading.Lock()
        self._last_request_times = {}
        self._min_interval = 0.33
        self._chart_cache = {}

    def _wait_for_domain_delta(self, url: str):
        """도메인별 API 호출 간격을 조절하여 속도 제한 위반을 방지합니다.

        설정된 최소 간격(`_min_interval`)보다 빠르게 동일 도메인에 요청이 
        발생할 경우 필요한 시간만큼 `sleep`하여 실행을 지연시킵니다.
        단, 실시간 고빈도 호출이 필요한 Naver Polling API 등은 예외로 처리합니다.

        Args:
            url (str): 요청할 대상 URL.
        """
        try:
            domain = urlparse(url).netloc
            if not domain: return
            
            # [최적화] polling API는 고빈도 호출용이므로 레이트 리미트 면제
            if domain == "polling.finance.naver.com":
                return

            wait_time = 0
            with self._domain_lock:
                now = time.time()
                last_time = self._last_request_times.get(domain, 0)
                elapsed = now - last_time
                if elapsed < self._min_interval:
                    wait_time = self._min_interval - elapsed
                self._last_request_times[domain] = now + wait_time
            
            if wait_time > 0:
                time.sleep(wait_time)
        except: pass

    def _safe_float(self, val: Any) -> float:
        """문자열 등 다양한 형태의 데이터를 안전하게 부동 소수점(float)으로 변환합니다.

        쉼표(,) 제거 및 빈 문자열 처리를 포함하며, 변환 실패 시 0.0을 반환합니다.

        Args:
            val (Any): 변환할 값.

        Returns:
            float: 변환된 부동 소수점 값.
        """
        try:
            if val is None or str(val).strip() == "": return 0.0
            return float(str(val).replace(',', '').strip())
        except: return 0.0

    def _get_cached_chart(self, key: str, ttl: int = 300) -> Optional[List[dict]]:
        """캐시된 차트 데이터를 조회합니다.

        Args:
            key (str): 캐시 키.
            ttl (int): 캐시 유효 시간 (초). 기본값은 300초(5분).

        Returns:
            Optional[List[dict]]: 캐시된 데이터가 있고 유효하면 데이터 리스트를, 아니면 None을 반환.
        """
        if key in self._chart_cache:
            ts, data = self._chart_cache[key]
            if time.time() - ts < ttl: return data
        return None

    def _set_cached_chart(self, key: str, data: List[dict]):
        """차트 데이터를 캐시에 저장합니다.

        Args:
            key (str): 캐시 키.
            data (List[dict]): 저장할 데이터 리스트.
        """
        self._chart_cache[key] = (time.time(), data)
