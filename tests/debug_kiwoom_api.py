import os
import sys
import json
from dotenv import load_dotenv

# 상위 폴더(src)를 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config_init import ensure_env
from src.auth import get_auth
from src.api.kiwoom import KiwoomAPIClient

def main():
    print("=== Kiwoom API Debugger ===")
    
    # 1. 환경변수 로드
    load_dotenv()
    if os.getenv("BROKER_TYPE", "KIS").upper() != "KIWOOM":
        print("경고: .env 파일의 BROKER_TYPE이 KIWOOM이 아닙니다.")
        print("테스트를 위해 임시로 BROKER_TYPE='KIWOOM' 환경을 적용합니다.")
        os.environ["BROKER_TYPE"] = "KIWOOM"

    # 2. 인증 객체 생성
    print("\n[1] 인증 객체 생성 중...")
    auth = get_auth()
    if not auth.is_token_valid():
        print("토큰 발급 중...")
        if not auth.generate_token():
            print("❌ 토큰 발급 실패! 환경변수 (KIWOOM_APPKEY, KIWOOM_SECRET) 확인 바랍니다.")
            return
    print("✅ 토큰 유효함")

    # 3. API 클라이언트 생성
    api = KiwoomAPIClient(auth)

    # 4. 잔고 조회 테스트
    print("\n[2] 잔고 및 자산 조회 테스트 (get_full_balance)")
    try:
        holdings, asset_info = api.get_full_balance()
        print("\n--- 자산 요약 ---")
        for k, v in asset_info.items():
            print(f"  {k}: {v:,}" if isinstance(v, (int, float)) else f"  {k}: {v}")
            
        print("\n--- 보유 종목 ---")
        if not holdings:
            print("  보유 종목이 없습니다.")
        else:
            for h in holdings:
                print(f"  [{h['pdno']}] {h['prdt_name']} - 수량: {h['hldg_qty']} / 평가금: {h['evlu_amt']} / 수익률: {h['evlu_pfls_rt']}%")
    except Exception as e:
        print(f"❌ 잔고 조회 실패: {e}")

    # 5. 시세 조회 테스트 (삼성전자)
    test_code = "005930"
    print(f"\n[3] 주식기본정보요청 테스트 (종목: {test_code})")
    try:
        price_info = api.get_inquire_price(test_code)
        if price_info:
            print(f"  현재가: {price_info['price']:,}원")
            print(f"  전일대비: {price_info['vrss']:,}원 ({price_info['ctrt']:.2f}%)")
            print(f"  거래량: {price_info['vol']:,}주")
        else:
            print(f"❌ 시세 조회 실패 또는 결과 없음")
    except Exception as e:
        print(f"❌ 시세 조회 예외 발생: {e}")

    print("\n테스트가 완료되었습니다.")

if __name__ == "__main__":
    main()
