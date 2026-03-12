import os
import yaml
from dotenv import load_dotenv

from src.logger import logger
from src.auth import KISAuth
from src.api import KISAPI
from src.strategy import VibeStrategy

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    # 환경변수 로드
    load_dotenv()
    
    # 설정 로드
    config = load_config()
    
    # 1. 인증 객체 생성 (기본값: 모의투자 Simulation First)
    # 실제 환경 전환 시 is_virtual=False 로 변경
    auth = KISAuth(is_virtual=True)
    if not auth.generate_token():
        logger.error("토큰 발급에 실패하여 프로그램을 종료합니다.")
        return

    # 2. API 클라이언트 생성
    api = KISAPI(auth)
    
    # 3. 전략 객체 생성
    strategy = VibeStrategy(api, config)
    
    # 4. 실시간 시장 트렌드 판별 및 실행
    logger.info("--- [실시간 Vibe Trading 시작] ---")
    current_trend = strategy.determine_market_trend()
    strategy.run_cycle(market_trend=current_trend)

if __name__ == "__main__":
    main()
