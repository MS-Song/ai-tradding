import os
import sys
import yaml
import math
# 상위 디렉토리를 path에 추가하여 src 모듈 임포트 가능하게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.logger import logger
from src.auth import KISAuth
from src.api import KISAPI
from src.config_init import get_config

def run_starter_kit():
    # 1. 초기화 및 설정 로드
    config = get_config()
    kit_config = config.get("vibe_strategy", {}).get("starter_kit", {})
    
    budget = kit_config.get("budget_per_stock", 1000000)
    stocks_to_buy = kit_config.get("stocks", [])
    
    # 2. 인증 및 API 클라이언트 생성 (환경변수 설정에 따름)
    auth = KISAuth()
    if not auth.generate_token():
        logger.error("❌ 인증 실패: 토큰을 발급할 수 없습니다.")
        return

    api = KISAPI(auth)
    
    print("\n" + "="*50)
    print("   🛒 [Vibe Trader] 기초 종목 일괄 매수 (Starter Kit)")
    print(f"   - 종목당 예산: {budget:,}원")
    print(f"   - 대상 종목 수: {len(stocks_to_buy)}개")
    print("="*50 + "\n")
    sys.stdout.flush()

    # 3. 현재 잔고 확인 (안내용)
    holdings = api.get_balance()
    if len(holdings) > 0:
        logger.warning(f"⚠️ 이미 {len(holdings)}개의 종목을 보유 중입니다. 추가 매수를 계속하시겠습니까?")
        # CLI에서 직접 실행 시 중단 여부를 묻는 대신, 로그로 알림만 줍니다.

    # 4. 종목별 매수 실행
    for stock_code in stocks_to_buy:
        # 현재가 조회
        current_price = api.get_inquire_price(stock_code)
        if not current_price:
            logger.error(f"❌ [{stock_code}] 현재가 조회 실패. 매수를 건너뜁니다.")
            continue
            
        # 매수 가능 수량 계산
        qty = math.floor(budget / current_price)
        
        if qty > 0:
            logger.info(f"💎 [{stock_code}] 분석 완료 - 현재가: {current_price:,}원 -> {qty}주 매수 시도 중...")
            success = api.order_market(stock_code, qty, is_buy=True)
            if success:
                logger.info(f"✅ [{stock_code}] 일괄 매수 완료!")
            else:
                logger.error(f"❌ [{stock_code}] 매수 주문 실패.")
        else:
            logger.warning(f"⚠️ [{stock_code}] 가격({current_price:,}원)이 예산({budget:,}원)을 초과하여 매수 불가.")
            
    print("\n" + "="*50)
    print("   ✨ 기초 종목 매수 작업이 완료되었습니다.")
    print("   이제 'main.py'를 실행하여 자동 매매를 시작하세요!")
    print("="*50 + "\n")
    sys.stdout.flush()

if __name__ == "__main__":
    run_starter_kit()
