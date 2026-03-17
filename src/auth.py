import os
import requests
import time
import json
from src.logger import logger

class KISAuth:
    def __init__(self, is_virtual=None):
        self.appkey = os.getenv("KIS_APPKEY")
        self.secret = os.getenv("KIS_SECRET")
        self.cano = os.getenv("KIS_CANO")
        
        # 인자로 명시적 지정이 없으면 환경변수 사용, 환경변수도 없으면 True(모의)
        if is_virtual is None:
            env_val = os.getenv("KIS_IS_VIRTUAL", "TRUE").upper()
            self.is_virtual = (env_val != "FALSE")
        else:
            self.is_virtual = is_virtual
        
        self.domain = (
            "https://openapivts.koreainvestment.com:29443" 
            if self.is_virtual else 
            "https://openapi.koreainvestment.com:9443"
        )
        
        self.cache_file = ".token_cache.json"
        self.access_token = None
        self.token_issued_at = 0
        self.token_expiry_sec = 600 # 10분간 공유

    def _load_token_cache(self):
        """파일에서 저장된 토큰 정보 로드"""
        if not os.path.exists(self.cache_file):
            return False
        
        try:
            with open(self.cache_file, "r") as f:
                cache = json.load(f)
                # 현재 설정(모의/실전)과 같은 경우만 로드
                if cache.get("is_virtual") == self.is_virtual:
                    self.access_token = cache.get("access_token")
                    self.token_issued_at = cache.get("token_issued_at", 0)
                    return True
        except Exception:
            pass
        return False

    def _save_token_cache(self):
        """새로 발급받은 토큰 정보를 파일에 저장"""
        try:
            cache = {
                "access_token": self.access_token,
                "token_issued_at": self.token_issued_at,
                "is_virtual": self.is_virtual
            }
            with open(self.cache_file, "w") as f:
                json.dump(cache, f)
        except Exception as e:
            logger.error(f"토큰 캐시 저장 실패: {e}")

    def is_token_valid(self):
        """현재 토큰이 유효한지(10분 이내) 확인"""
        # 메모리에 없으면 파일에서 먼저 읽어옴
        if not self.access_token:
            self._load_token_cache()
            
        if not self.access_token:
            return False
        
        elapsed = time.time() - self.token_issued_at
        return elapsed < self.token_expiry_sec

    def generate_token(self):
        """OAuth 2.0 토큰 발급 (파일 기반 10분 공유)"""
        # 1. 파일/메모리에 유효한 토큰이 있다면 즉시 사용
        if self.is_token_valid():
            return True

        url = f"{self.domain}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.appkey,
            "appsecret": self.secret
        }
        
        try:
            res = requests.post(url, headers=headers, json=body, timeout=10)
            if res.status_code != 200:
                logger.error(f"❌ 토큰 발급 실패 (HTTP {res.status_code}): {res.text}")
                return False
            
            data = res.json()
            self.access_token = data.get("access_token")
            self.token_issued_at = time.time()
            
            # 2. 새로 발급받은 토큰을 파일에 저장 (다른 프로세스와 공유)
            self._save_token_cache()
            
            return True
        except Exception as e:
            logger.error(f"❌ 토큰 발급 에러: {e}")
            return False

    def get_auth_headers(self):
        # 헤더 요청 시 토큰이 유효하지 않으면 자동 갱신 시도
        if not self.is_token_valid():
            self.generate_token()
            
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.appkey,
            "appsecret": self.secret,
            "tr_id": "",
            "custtype": "P"
        }
