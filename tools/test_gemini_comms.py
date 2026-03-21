import os
import requests
from dotenv import load_dotenv

def find_working_model():
    load_dotenv(override=True)
    api_key = os.getenv("GOOGLE_API_KEY")
    
    if not api_key:
        print("❌ API KEY 없음")
        return

    # 구글 최신 2.0 이상 및 2.5 라인업 총망라
    candidate_models = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-pro-exp-0205",
        "gemini-2.0-flash-thinking-exp-0121",
        "gemini-2.0-flash-001",
        "gemini-2.0-flash-lite-preview-02-27",
        "gemini-2.5-flash-preview-tts",
        "gemini-2.0-pro-exp"
    ]

    print("\n🚀 [Gemini 2.0+] 통신 가능한 모델 발굴 시작...\n")
    
    for model in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": "Hi"}]}]}
        
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                print(f"✅ 빙고! 찾았습니다: {model} (Status: 200)")
                return model
            else:
                msg = res.json().get('error', {}).get('message', '알수없는 에러')
                print(f"❌ 실패: {model} -> {msg[:50]}...")
        except Exception as e:
            print(f"❌ 예외: {model} -> {e}")
            
    print("\n⚠️ 2.0 이상 모델 중 사용 가능한 것을 찾지 못했습니다.")
    return None

if __name__ == "__main__":
    find_working_model()
