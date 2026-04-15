
import os
import sys
from dotenv import load_dotenv

# 프로젝트 루트를 path에 추가
sys.path.append(os.getcwd())

load_dotenv()

from src.strategy import GeminiAdvisor

class MockAPI:
    def get_naver_stock_detail(self, code): return {"price": 10000}
    def get_naver_stock_news(self, code): return ["뉴스1", "뉴스2"]

def test_fallback():
    print("🚀 [Gemini Fallback 테스트] 시작")
    
    # 1순위를 존재하지 않는 모델로 설정하여 강제로 Fallback 유도
    ai_config = {
        "preferred_model": "invalid-model-id-12345",
        "fallback_sequence": [
            "invalid-model-id-12345",
            "gemini-3.1-flash-lite-preview" # 실제 작동하는 모델
        ]
    }
    
    advisor = GeminiAdvisor(MockAPI(), ai_config)
    
    print(f"1. 호출 시도 (Preferred: {ai_config['preferred_model']})")
    # 아주 간단한 프롬프트로 테스트
    result = advisor._safe_gemini_call("Say 'Fallback Success'")
    
    if result and "Fallback Success" in result:
        print(f"✅ 테스트 성공: Fallback이 작동하여 결과를 가져왔습니다. -> {result}")
    else:
        print(f"❌ 테스트 실패: 결과를 가져오지 못했습니다. -> {result}")

if __name__ == "__main__":
    test_fallback()
