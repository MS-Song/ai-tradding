import os
import sys
# 상위 디렉토리를 path에 추가하여 src 모듈 임포트 가능하게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.logger import logger
from src.auth import KISAuth
from src.api import KISAPI

def test_buy_stocks():
    # 환경변수 로드
    load_dotenv()
    
    # 1. 인증 및 API 객체 생성 (환경변수 설정에 따름)
    auth = KISAuth()
    if not auth.generate_token():
        logger.error("인증 실패")
        return

    api = KISAPI(auth)
    
    # 매수 대상 종목
    stocks_to_buy = [
        {"code": "005930", "name": "삼성전자"},
        {"code": "000660", "name": "SK하이닉스"}
    ]
    
    logger.info("=== 1주 매입 테스트 시작 ===")
    
    for stock in stocks_to_buy:
        code = stock["code"]
        name = stock["name"]
        
        logger.info(f"[{name}({code})] 1주 시장가 매수 주문 시도...")
        success = api.order_market(code, 1, is_buy=True)
        
        if success:
            logger.info(f"[{name}] 매수 주문 전송 완료!")
        else:
            logger.error(f"[{name}] 매수 주문 실패 (로그 확인 필요)")
            
    logger.info("=== 테스트 종료 ===")

if __name__ == "__main__":
    test_buy_stocks()
