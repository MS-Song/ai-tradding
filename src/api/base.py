import time
import threading
import requests
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse
from src.logger import logger


class BrokerRateLimiter:
    """증권사 API 요청의 중앙화된 레이트 리미터 (Token Bucket 알고리즘).

    모의투자와 실거래 환경에서 서로 다른 처리량(RPS)을 적용하여
    API 호출 빈도를 체계적으로 제어합니다. 싱글톤(Singleton) 패턴으로
    프로세스 전체에서 하나의 큐만 유지됩니다.

    Attributes:
        _instances (dict): 증권사별 싱글톤 인스턴스 맵.
        _rps (float): 초당 허용 요청 수 (Requests Per Second).
        _max_tokens (int): 버킷의 최대 토큰 수 (버스트 허용량).
        _tokens (float): 현재 사용 가능한 토큰 수.
        _last_refill (float): 마지막 토큰 보충 시각(epoch).
    """

    _instances: Dict[str, 'BrokerRateLimiter'] = {}
    _creation_lock = threading.Lock()

    # 증권사별 권장 RPS 설정값 (실거래 기준)
    BROKER_RPS_CONFIG = {
        "KIS": 15.0,       # KIS 실전: 초당 20건 공식이나 안전 마진 확보
        "KIWOOM": 5.0,     # 키움 실전: 초당 5건 (REST API 기준)
    }

    # 모의투자 공통 RPS (증권사 무관)
    VIRTUAL_RPS = 0.8      # 모의: 초당 0.8건 (1.25초 간격)

    @classmethod
    def get_instance(cls, broker_type: str, is_virtual: bool) -> 'BrokerRateLimiter':
        """증권사/환경별 싱글톤 레이트 리미터 인스턴스를 반환합니다.

        Args:
            broker_type (str): 증권사 타입 ("KIS" 또는 "KIWOOM").
            is_virtual (bool): 모의투자 여부.

        Returns:
            BrokerRateLimiter: 해당 환경의 레이트 리미터 인스턴스.
        """
        key = f"{broker_type.upper()}_{'VIRTUAL' if is_virtual else 'REAL'}"
        if key not in cls._instances:
            with cls._creation_lock:
                if key not in cls._instances:
                    if is_virtual:
                        rps = cls.VIRTUAL_RPS
                    else:
                        rps = cls.BROKER_RPS_CONFIG.get(broker_type.upper(), 10.0)
                    cls._instances[key] = cls(rps=rps, broker_type=broker_type, is_virtual=is_virtual)
                    mode = "모의" if is_virtual else "실전"
                    logger.info(f"🚦 [{broker_type}] {mode}투자 레이트 리미터 초기화: {rps} req/s")
        return cls._instances[key]

    def __init__(self, rps: float, broker_type: str, is_virtual: bool):
        """Token Bucket 레이트 리미터를 초기화합니다.

        Args:
            rps (float): 초당 허용 요청 수.
            broker_type (str): 증권사 타입.
            is_virtual (bool): 모의투자 여부.
        """
        self._rps = rps
        self._broker_type = broker_type
        self._is_virtual = is_virtual
        # 버스트 허용: 실거래는 최대 3건까지 즉시 처리, 모의는 1건만
        self._max_tokens = 1 if is_virtual else min(3, int(rps))
        self._tokens = float(self._max_tokens)
        self._last_refill = time.time()
        self._lock = threading.Lock()
        # 통계 추적
        self._total_requests = 0
        self._total_wait_time = 0.0

    def acquire(self, timeout: float = 30.0) -> bool:
        """토큰을 1개 획득합니다. 토큰이 없으면 보충될 때까지 대기합니다.

        Token Bucket 알고리즘에 따라 시간이 경과하면 토큰이 자동 보충되며,
        보충 속도는 설정된 RPS에 비례합니다.

        Args:
            timeout (float): 최대 대기 시간 (초). 이를 초과하면 False 반환.

        Returns:
            bool: 토큰 획득 성공 여부.
        """
        deadline = time.time() + timeout
        wait_start = time.time()

        while True:
            with self._lock:
                now = time.time()
                # 경과 시간만큼 토큰 보충
                elapsed = now - self._last_refill
                self._tokens = min(self._max_tokens, self._tokens + elapsed * self._rps)
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_requests += 1
                    waited = now - wait_start
                    if waited > 0.01:
                        self._total_wait_time += waited
                    return True

                # 1토큰 보충까지 필요한 대기 시간 계산
                wait_needed = (1.0 - self._tokens) / self._rps

            if time.time() + wait_needed > deadline:
                return False  # 타임아웃 초과

            time.sleep(min(wait_needed, 0.1))  # 최대 0.1초 단위로 폴링

    def get_stats(self) -> dict:
        """레이트 리미터의 현재 상태 및 통계를 반환합니다.

        Returns:
            dict: 총 요청 수, 평균 대기 시간, 현재 RPS 설정 등.
        """
        with self._lock:
            avg_wait = (self._total_wait_time / self._total_requests) if self._total_requests > 0 else 0
            return {
                "broker": self._broker_type,
                "mode": "모의" if self._is_virtual else "실전",
                "rps": self._rps,
                "max_burst": self._max_tokens,
                "total_requests": self._total_requests,
                "avg_wait_sec": round(avg_wait, 4),
                "tokens_available": round(self._tokens, 2)
            }


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
