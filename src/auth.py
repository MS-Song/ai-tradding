import os
import requests
import time
import json
import threading
from src.logger import logger

class KISAuth:
    def __init__(self, is_virtual=None):
        self.appkey = os.getenv("KIS_APPKEY")
        self.secret = os.getenv("KIS_SECRET")
        self.cano = os.getenv("KIS_CANO")
        self.acnt_prdt_cd = os.getenv("KIS_ACNT_PRDT_CD", "01") # 기본값 01
        
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
        self.token_expiry_sec = 43200 # 12시간 (KIS 토큰은 최대 24시간 유효)
        self._lock = threading.Lock()
        self._is_handling_error = False

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
        """OAuth 2.0 토큰 발급 (쓰레드 세이프, 파일 기반 공유)"""
        # 1. 먼저 락 없이 현재 메모리/캐시가 유효한지 확인 (Fast path)
        if self.is_token_valid():
            return True

        # 2. 유효하지 않다면 락을 획득하고 다시 확인 (Double-checked locking)
        with self._lock:
            # 락 획득 후 다른 쓰레드가 이미 필드를 업데이트했을 수 있으므로 재로드
            if self._load_token_cache() and self.is_token_valid():
                return True

            # 실제 API 호출
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
                    err_msg = ""
                    try: err_msg = res.json().get("error_description", res.text)
                    except: err_msg = res.text
                    
                    # 1분당 1회 초과 등의 에러면 추가 가공
                    logger.error(f"❌ 토큰 발급 실패 (HTTP {res.status_code}): {err_msg}")
                    
                    if hasattr(self, 'on_error_message') and self.on_error_message:
                        self.on_error_message(f"토큰 발급 에러: {err_msg}")
                    
                    # 1분 제한 에러면 즉시 재시도하지 않고 실패 처리 (다음 사이클에서 시도)
                    return False
                
                data = res.json()
                self.access_token = data.get("access_token")
                # KIS 토큰은 보통 86400초(24시간) 유효하지만 안전하게 현재 시각 저장
                self.token_issued_at = time.time()
                
                if not self.access_token:
                    logger.error("❌ 토큰 발급 성공했으나 access_token이 비어있음")
                    return False

                # 3. 새로 발급받은 토큰을 파일에 저장 (다른 프로세스와 공유)
                self._save_token_cache()
                logger.info("✅ KIS API 접근 토큰 발급/갱신 완료")
                
                return True
            except Exception as e:
                logger.error(f"❌ 토큰 발급 에러: {e}")
                if hasattr(self, 'on_error_message') and self.on_error_message:
                    self.on_error_message(f"토큰 발급 예외: {str(e)}")
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
