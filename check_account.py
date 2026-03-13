import os
from dotenv import load_dotenv
from src.logger import logger
from src.auth import KISAuth
from src.api import KISAPI

def check_account():
    # 환경변수 로드
    load_dotenv()
    
    # 1. 인증 객체 생성 (모의투자)
    auth = KISAuth(is_virtual=True)
    if not auth.generate_token():
        logger.error("인증 실패: .env 파일의 API KEY를 확인하세요.")
        return

    # 2. API 클라이언트 생성
    api = KISAPI(auth)
    
    logger.info("--- [계좌 상태 점검 시작] ---")
    
    # 3. 지수 정보 확인 (수정된 로직 검증)
    index_data = api.get_index_price("0001")
    if index_data:
        logger.info(f"📊 현재 시장 지수 (KOSPI): {index_data['price']} ({index_data['diff']}{index_data['rate']}%)")
    else:
        logger.error("❌ 지수 정보 조회 실패. API 연결 상태를 확인하세요.")

    # 4. 예수금 조회
    deposit = api.get_deposit()
    logger.info(f"💰 계좌 예수금 (주문 가능 금액): {deposit:,}원")
    
    # 5. 보유 종목 조회
    holdings = api.get_balance()
    holdings_count = len(holdings)
    logger.info(f"📋 현재 보유 종목 수: {holdings_count}개")
    
    if holdings_count > 0:
        for idx, item in enumerate(holdings, 1):
            name = item.get("prdt_name", "Unknown")
            rt = item.get("evlu_pfls_rt", "0")
            qty = item.get("hldg_qty", "0")
            logger.info(f"  {idx}. {name} ({item.get('pdno')}): {qty}주 | 수익률: {rt}%")
    
    # 5. 최종 판단
    if deposit > 0:
        logger.info(">>> [결과] 계좌에 자산이 확인되었습니다. 자동 매매를 시작할 수 있는 상태입니다.")
    else:
        logger.warning(">>> [결과] 예수금이 0원입니다. 모의투자 계좌에 사이버 머니를 충전했는지 확인해주세요.")
    
    logger.info("--- [계좌 상태 점검 완료] ---")

if __name__ == "__main__":
    check_account()
