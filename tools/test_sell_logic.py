import os
import sys
import json
from dotenv import load_dotenv

# 상위 디렉토리를 path에 추가하여 src 모듈 임포트 가능하게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import KISAuth
from src.api import KISAPI

def test_sell_api():
    load_dotenv()
    auth = KISAuth()
    if not auth.generate_token():
        print("❌ 인증 실패")
        return

    api = KISAPI(auth)
    
    # 1. 잔고 조회하여 매도할 종목 찾기
    holdings, asset = api.get_full_balance(force=True)
    if not holdings:
        print("ℹ️ 매도할 보유 종목이 없습니다. 가상의 매도 테스트를 진행합니다 (실제 전송은 하지 않음).")
        # 실제 계좌에 종목이 없으면 테스트가 어려우므로, 
        # 여기서는 order_market 함수 내부의 tr_id와 body 구성을 다시 확인하는 수준으로 진행하거나
        # 사용자에게 실제 종목이 있을 때 실행해달라고 요청해야 함.
        return

    target = holdings[0]
    code = target['pdno']
    name = target['prdt_name']
    qty = 1 # 테스트로 1주만
    
    print(f"[*] 테스트 매도 시도: {name} ({code}) {qty}주, 시장가")
    
    # 실제 매도 주문을 내기 전에 body를 출력해보기 위해 api.py의 order_market을 잠시 수정해서 로그를 찍게 할 수도 있음.
    # 여기서는 직접 호출해봅니다.
    success, msg = api.order_market(code, qty, is_buy=False)
    
    if success:
        print(f"✅ 매도 주문 성공!")
    else:
        print(f"❌ 매도 주문 실패: {msg}")

if __name__ == "__main__":
    test_sell_api()
