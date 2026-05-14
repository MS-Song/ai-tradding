import os
import requests
import time
import json
import threading
from src.logger import logger

class KISAuth:
    """한국투자증권(KIS) API 인증 및 토큰 관리를 담당하는 클래스.

    OAuth 2.0 기반의 접근 토큰(Access Token) 발급 및 갱신을 처리하며,
    파일 캐싱(.token_cache.json)을 통해 여러 프로세스 간 토큰을 공유합니다.
    쓰레드 세이프(Thread-safe)한 토큰 발급 로직을 포함합니다.

    Attributes:
        appkey (str): KIS 앱 키.
        secret (str): KIS 앱 시크릿.
        cano (str): 계좌 번호 (체계번호 8자리).
        acnt_prdt_cd (str): 계좌 상품 코드 (보통 '01').
        is_virtual (bool): 모의투자 계좌 여부.
        domain (str): API 접속 도메인 (모의/실전 구분).
        access_token (str): 현재 유효한 접근 토큰.
    """
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
        """로컬 파일 캐시에서 토큰 정보를 로드합니다.

        Returns:
            bool: 로드 성공 여부.
        """
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
        """새로 발급받은 토큰 정보를 로컬 파일 캐시에 저장합니다."""
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
        """현재 보유한 토큰이 시간상 유효한지 확인합니다.

        Returns:
            bool: 유효하면 True, 만료되었거나 없으면 False.
        """
        # 메모리에 없으면 파일에서 먼저 읽어옴
        if not self.access_token:
            self._load_token_cache()
            
        if not self.access_token:
            return False
        
        elapsed = time.time() - self.token_issued_at
        return elapsed < self.token_expiry_sec

    def generate_token(self):
        """OAuth 2.0 토큰을 발급받거나 갱신합니다.

        Double-checked locking 패턴을 사용하여 멀티쓰레드 환경에서
        중복 발급 요청을 방지하고 성능을 최적화합니다.

        Returns:
            bool: 토큰 확보 성공 여부.
        """
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
        """API 호출에 필요한 인증 헤더를 생성하여 반환합니다.

        Returns:
            dict: Authorization Bearer 토큰 및 앱 키 정보가 포함된 헤더.
        """
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

class KiwoomAuth:
    """키움증권 REST API 인증 및 토큰 관리를 담당하는 클래스."""
    def __init__(self, is_virtual=None):
        self.appkey = os.getenv("KIWOOM_APPKEY")
        self.secret = os.getenv("KIWOOM_SECRET")
        self.account = os.getenv("KIWOOM_ACCOUNT")
        
        if is_virtual is None:
            env_val = os.getenv("KIWOOM_IS_VIRTUAL", "TRUE").upper()
            self.is_virtual = (env_val != "FALSE")
        else:
            self.is_virtual = is_virtual
        
        self.domain = (
            "https://mockapi.kiwoom.com" 
            if self.is_virtual else 
            "https://api.kiwoom.com"
        )
        self.ws_domain = (
            "wss://mockapi.kiwoom.com:10000"
            if self.is_virtual else
            "wss://api.kiwoom.com:10000"
        )
        
        self.cache_file = ".token_cache_kiwoom.json"
        self.access_token = None
        self.token_issued_at = 0
        self.token_expiry_sec = 43200
        self._lock = threading.Lock()

    def _load_token_cache(self):
        if not os.path.exists(self.cache_file): return False
        try:
            with open(self.cache_file, "r") as f:
                cache = json.load(f)
                if cache.get("is_virtual") == self.is_virtual:
                    self.access_token = cache.get("access_token")
                    self.token_issued_at = cache.get("token_issued_at", 0)
                    return True
        except: pass
        return False

    def _save_token_cache(self):
        try:
            cache = {
                "access_token": self.access_token,
                "token_issued_at": self.token_issued_at,
                "is_virtual": self.is_virtual
            }
            with open(self.cache_file, "w") as f: json.dump(cache, f)
        except Exception as e:
            logger.error(f"키움 토큰 캐시 저장 실패: {e}")

    def is_token_valid(self):
        if not self.access_token: self._load_token_cache()
        if not self.access_token: return False
        elapsed = time.time() - self.token_issued_at
        return elapsed < self.token_expiry_sec

    def invalidate_token(self):
        """현재 토큰을 무효화하고 로컬 캐시 파일을 삭제합니다."""
        with self._lock:
            self.access_token = None
            self.token_issued_at = 0
            if os.path.exists(self.cache_file):
                try:
                    os.remove(self.cache_file)
                    logger.info(f"🗑️ 키움 토큰 캐시 파일 삭제 완료 ({self.cache_file})")
                except Exception as e:
                    logger.error(f"키움 토큰 캐시 파일 삭제 실패: {e}")

    def generate_token(self):
        if self.is_token_valid(): return True
        with self._lock:
            if self._load_token_cache() and self.is_token_valid(): return True
            url = f"{self.domain}/oauth2/token"
            headers = {"content-type": "application/json"}
            body = {"grant_type": "client_credentials", "appkey": self.appkey, "secretkey": self.secret}
            try:
                res = requests.post(url, headers=headers, json=body, timeout=10)
                if res.status_code != 200:
                    logger.error(f"❌ 키움 토큰 발급 실패: {res.text}")
                    return False
                data = res.json()
                self.access_token = data.get("token")
                self.token_issued_at = time.time()
                if not self.access_token: return False
                self._save_token_cache()
                logger.info("✅ 키움 API 접근 토큰 발급 완료")
                return True
            except Exception as e:
                logger.error(f"❌ 키움 토큰 발급 예외: {e}")
                return False

    def get_auth_headers(self):
        if not self.is_token_valid(): self.generate_token()
        return {
            "content-type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.appkey,
            "appsecret": self.secret
        }

def get_auth():
    """현재 BROKER_TYPE 설정에 맞는 인증 객체를 반환합니다."""
    broker_type = os.getenv("BROKER_TYPE", "KIS").upper()
    if broker_type == "KIWOOM":
        return KiwoomAuth()
    return KISAuth()

