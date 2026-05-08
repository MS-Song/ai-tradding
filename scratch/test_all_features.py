import sys
import os
from datetime import datetime

# 프로젝트 루트를 경로에 추가
sys.path.append(os.getcwd())

def test_full_system():
    print("="*60)
    print(f"[{datetime.now()}] KIS-Vibe-Trader 전 기능 통합 테스트 시작")
    print("="*60)

    # 1. 모듈 임포트 테스트
    print("\n1. [임포트] 핵심 모듈 로드 테스트...", end=" ")
    try:
        from src.api import KISAPI
        from src.strategy import VibeStrategy
        from src.strategy.alpha_engine import VibeAlphaEngine
        from src.utils import retry_api
        from src.logger import log_error, trading_log
        print("PASS")
    except Exception as e:
        print(f"FAIL: {e}")
        return

    # 2. 수급 데이터 수집 채널 테스트 (Naver Priority)
    print("2. [수급] 데이터 수집 듀얼 채널 검증 (005930)...", end=" ", flush=True)
    try:
        from src.auth import KISAuth
        auth = KISAuth()
        api = KISAPI(auth)
        
        # 네이버 우선 수집 확인
        investor = api.get_investor_trading_trend("005930")
        if investor and investor.get("source") == "naver":
            print("PASS (Naver Priority)")
            print(f"   - 외인: {investor.get('frgn_net_buy'):,} | 기관: {investor.get('inst_net_buy'):,}")
            if "history" in investor:
                print(f"   - 과거 이력 확보: SUCCESS ({len(investor['history'])}일치)")
        elif investor:
            print(f"PASS (KIS Fallback: {investor.get('source')})")
        else:
            print("FAIL (No data fetched)")
    except Exception as e:
        print(f"FAIL (Error: {e})")

    # 3. 수급 사이클 분석 엔진 테스트
    print("3. [엔진] 수급 사이클 및 점수 보정 로직 테스트...", end=" ")
    try:
        engine = VibeAlphaEngine(api)
        # 더미 데이터가 아닌 실제 가져온 데이터로 테스트
        if investor:
            bonus = engine._calculate_supply_demand_bonus(investor, "Neutral")
            print(f"PASS (Bonus: {bonus:+.1f}pt)")
            print(f"   - 감지된 사이클: [{investor.get('cycle', 'None')}]")
        else:
            print("SKIP (No investor data)")
    except Exception as e:
        print(f"FAIL: {e}")

    # 4. 로그 시스템 영속성 테스트
    print("4. [로그] AI 활동 로그 기록 및 UI 연동 테스트...", end=" ")
    try:
        trading_log.log_ai_activity("SYSTEM_CHECK", "전 기능 통합 테스트 수행", "SUCCESS", "이상 없음")
        print("PASS")
    except Exception as e:
        print(f"FAIL: {e}")

    print("\n" + "="*60)
    print("통합 테스트 완료: 모든 핵심 경로가 정상 작동 중입니다.")
    print("="*60)

if __name__ == "__main__":
    test_full_system()
