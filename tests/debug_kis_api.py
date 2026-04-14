import os
import sys
import json
from dotenv import load_dotenv

# 프로젝트 루트를 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.auth import KISAuth
from src.api import KISAPI

def debug_kis():
    print("\n" + "="*60)
    print(" 🔍 KIS API 정밀 진단 시스템 기동")
    print("="*60)
    
    load_dotenv(override=True)
    auth = KISAuth()
    api = KISAPI(auth)
    
    print(f"\n1. 접속 정보 확인:")
    print(f"   - 모의투자 여부: {auth.is_virtual}")
    print(f"   - 도메인: {auth.domain}")
    print(f"   - 계좌번호: {auth.cano}")
    
    print(f"\n2. 토큰 발급 테스트:")
    success = auth.generate_token()
    if success:
        print(f"   ✅ 토큰 발급 성공 (Token: {auth.access_token[:10]}...)")
    else:
        print(f"   ❌ 토큰 발급 실패")
        return

    print(f"\n3. 잔고 조회 API 원문 분석 (inquire-balance):")
    url = f"{auth.domain}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = auth.get_auth_headers()
    headers.update({"tr_id": "VTTC8434L" if auth.is_virtual else "TTTC8434L"})
    params = {
        "CANO": auth.cano, "ACNT_PRDT_CD": "01",
        "AFHR_FLG": "N", "OVRZ_SEARCH_FLG": "N", "PRDT_TYPE_CD": "01",
        "TRADE_DVSN_CD": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    try:
        import requests
        res = requests.get(url, headers=headers, params=params, timeout=10)
        print(f"   - HTTP 상태 코드: {res.status_code}")
        data = res.json()
        
        print("\n   [응답 데이터 원문 (일부)]")
        # 보안을 위해 계좌번호 등은 마스킹 처리할 수 있으나, 여기선 전체 키 구조 파악을 위해 출력
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        if "output1" in data:
            print(f"\n   ✅ output1(보유종목) 발견: {len(data['output1'])}개 종목")
            if data['output1']:
                print(f"      - 첫 번째 종목 키 리스트: {list(data['output1'][0].keys())}")
        
        if "output2" in data:
            print(f"\n   ✅ output2(자산요약) 발견")
            if data['output2']:
                print(f"      - 요약 데이터 키 리스트: {list(data['output2'][0].keys())}")
                
    except Exception as e:
        print(f"   ❌ API 호출 중 예외 발생: {e}")

    print(f"\n4. 종목 시세 조회 테스트 (삼성전자 005930):")
    price_data = api.get_inquire_price("005930")
    if price_data:
        print(f"   ✅ 시세 조회 성공: {price_data}")
    else:
        print(f"   ❌ 시세 조회 실패")

    print("\n" + "="*60)
    print(" 🏁 진단 완료")
    print("="*60)

if __name__ == "__main__":
    debug_kis()
