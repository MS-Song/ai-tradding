import os
import sys
# 상위 디렉토리를 path에 추가하여 src 모듈 임포트 가능하게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from src.logger import logger
from src.auth import KISAuth
from src.api import KISAPI

def run_manual_sell():
    # 1. 초기화 및 인증
    load_dotenv()
    # 환경변수 설정에 따름
    auth = KISAuth()
    if not auth.generate_token():
        logger.error("인증 실패: 토큰을 발급할 수 없습니다.")
        return

    api = KISAPI(auth)
    
    print("\n" + "═"*60)
    print("   📉 [Vibe Trader] 수동 매도 시스템 (시장가)")
    print("═"*60)

    # 2. 현재 보유 종목 조회
    holdings = api.get_balance()
    if not holdings:
        print("\n   ℹ️ 현재 보유 중인 종목이 없습니다.")
        return

    print("\n   [현재 보유 종목 리스트]")
    print(f"   {'번호':<3} | {'종목명':<12} | {'종목코드':<8} | {'보유수량':>6} | {'수익률':>8}")
    print("   " + "─"*55)
    
    holding_list = []
    for i, h in enumerate(holdings, 1):
        name = h.get("prdt_name", "Unknown")
        code = h.get("pdno", "")
        qty = int(h.get("hldg_qty", 0))
        rt = h.get("evlu_pfls_rt", "0.0")
        holding_list.append({"name": name, "code": code, "qty": qty})
        print(f"   {i:<4} | {name:<12} | {code:<8} | {qty:>8} | {rt:>8}%")

    print("═"*60)

    # 3. 사용자 입력 처리
    try:
        choice = input("\n   👉 매도할 종목의 번호를 입력하세요 (취소: Enter): ")
        if not choice:
            print("   매도를 취소합니다.")
            return
        
        idx = int(choice) - 1
        if idx < 0 or idx >= len(holding_list):
            print("   ❌ 잘못된 번호입니다.")
            return
        
        target = holding_list[idx]
        print(f"\n   선택 종목: {target['name']} ({target['code']})")
        print(f"   매도 가능 수량: {target['qty']}주")
        
        qty_input = input(f"   👉 매도할 수량을 입력하세요 (전량: Enter): ")
        if not qty_input:
            sell_qty = target['qty']
        else:
            sell_qty = int(qty_input)
            
        if sell_qty <= 0:
            print("   ❌ 수량은 1주 이상이어야 합니다.")
            return
        if sell_qty > target['qty']:
            print(f"   ❌ 보유 수량({target['qty']}주)을 초과할 수 없습니다.")
            return

        # 4. 매도 실행 확인
        confirm = input(f"\n   ⚠️ 정말로 {target['name']} {sell_qty}주를 [시장가]에 매도할까요? (y/n): ")
        if confirm.lower() != 'y':
            print("   매도를 중단합니다.")
            return

        # 5. API 호출
        success = api.order_market(target['code'], sell_qty, is_buy=False)
        if success:
            print(f"\n   ✅ {target['name']} {sell_qty}주 시장가 매도 주문 성공!")
        else:
            print(f"\n   ❌ 매도 주문에 실패했습니다.")

    except ValueError:
        print("   ❌ 숫자만 입력 가능합니다.")
    except Exception as e:
        print(f"   ❌ 오류 발생: {e}")

if __name__ == "__main__":
    run_manual_sell()
