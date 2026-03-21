import os
import requests
import json
from dotenv import load_dotenv

def list_available_models():
    load_dotenv(override=True)
    api_key = os.getenv("GOOGLE_API_KEY")
    
    if not api_key:
        print("❌ GOOGLE_API_KEY가 설정되지 않았습니다.")
        return

    # Google AI SDK 모델 목록 조회 엔드포인트
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    try:
        res = requests.get(url)
        if res.status_code == 200:
            data = res.json()
            print("\n✅ 접근 가능한 모델 목록:")
            print("="*60)
            for model in data.get('models', []):
                # 콘텐츠 생성(generateContent)을 지원하는 모델만 필터링
                if 'generateContent' in model.get('supportedGenerationMethods', []):
                    print(f"- ID: {model['name']}")
                    print(f"  Name: {model['displayName']}")
                    print(f"  Description: {model['description']}")
                    print("-" * 30)
            print("="*60)
        else:
            print(f"❌ 호출 실패 (Status: {res.status_code})")
            print(res.text)
    except Exception as e:
        print(f"❌ 오류 발생: {e}")

if __name__ == "__main__":
    list_available_models()
