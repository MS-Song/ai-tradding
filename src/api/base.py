import time
import threading
import requests
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

class BaseAPI:
    def __init__(self):
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self._domain_lock = threading.Lock()
        self._last_request_times = {}
        self._min_interval = 0.33
        self._chart_cache = {}

    def _wait_for_domain_delta(self, url: str):
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
        try:
            if val is None or str(val).strip() == "": return 0.0
            return float(str(val).replace(',', '').strip())
        except: return 0.0

    def _get_cached_chart(self, key: str, ttl: int = 300) -> Optional[List[dict]]:
        if key in self._chart_cache:
            ts, data = self._chart_cache[key]
            if time.time() - ts < ttl: return data
        return None

    def _set_cached_chart(self, key: str, data: List[dict]):
        self._chart_cache[key] = (time.time(), data)
