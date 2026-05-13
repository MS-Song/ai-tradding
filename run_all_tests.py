import pytest
import sys
import os

def main():
    """
    프로젝트 내의 모든 자동화된 단위 테스트를 한번에 실행합니다.
    - tests/test_*.py 패턴의 모든 파일을 탐색합니다.
    - pytest.ini의 설정(출력 캡처 비활성화 등)을 기본적으로 따릅니다.
    """
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ["PYTHONUTF8"] = "1"
    
    print("=" * 60)
    print(" AI-Vibe-Trader 통합 테스트 러너 (All Tests)")
    print("=" * 60)
    
    # 루트 디렉토리를 경로에 추가
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    # pytest 실행 (tests 폴더 대상)
    # 인자를 추가하여 테스트를 상세히 출력 (-v)
    exit_code = pytest.main(["-v", "tests/"])
    
    print("=" * 60)
    if exit_code == 0:
        print(" [SUCCESS] 모든 테스트가 성공적으로 통과되었습니다!")
    else:
        print(" [FAIL] 일부 테스트가 실패했습니다. 위 로그를 확인하세요.")
        
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
