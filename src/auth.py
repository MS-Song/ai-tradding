import os
import requests
from src.logger import logger

class KISAuth:
    def __init__(self, is_virtual=True):
        self.appkey = os.getenv("KIS_APPKEY")
        self.secret = os.getenv("KIS_SECRET")
        self.cano = os.getenv("KIS_CANO")
        self.is_virtual = is_virtual
        
        # Domain: Simulation First 설정 적용
        self.domain = (
            "https://openapivts.koreainvestment.com:29443" 
            if is_virtual else 
            "https://openapi.koreainvestment.com:9443"
        )
        
        self.access_token = None
        
    def generate_token(self):
        """OAuth 2.0 토큰 발급"""
        logger.info(f"발급 도메인: {self.domain} (모의투자: {self.is_virtual})")
        
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
                logger.error(f"토큰 발급 실패 (HTTP {res.status_code}): {res.text}")
                return False
            
            data = res.json()
            self.access_token = data.get("access_token")
            logger.info("토큰 발급 완료 (성공)")
            return True
        except requests.exceptions.RequestException as e:
            # Strict Error Handling
            logger.error(f"토큰 발급 실패 (네트워크/인증 오류): {e}")
            return False

    def get_auth_headers(self):
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.appkey,
            "appsecret": self.secret,
            "tr_id": "" # API 호출 시 오버라이드 됨
        }
