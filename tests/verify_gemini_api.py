import os
import requests
import json
import sys
from dotenv import load_dotenv

# 표준 출력 인코딩을 UTF-8로 강제 설정 (한글 깨짐 방지)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def verify_gemini():
    load_dotenv(override=True)
    api_key = os.getenv("GOOGLE_API_KEY")
    
    if not api_key:
        print("❌ GOOGLE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return

    print("\n" + "="*80)
    print("🚀 [Gemini API 통합 검증 도구] 실행")
    print("="*80)

    # 1. 모델 리스트 조회
    print("\n[1] 접근 가능한 모델 리스트 조회 중...")
    url_list = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    available_models = []
    try:
        res = requests.get(url_list, timeout=15)
        if res.status_code == 200:
            data = res.json()
            models = data.get('models', [])
            for m in models:
                m_id = m.get('name', '').replace('models/', '')
                if 'generateContent' in m.get('supportedGenerationMethods', []):
                    available_models.append(m_id)
                    print(f"✅ ID: {m_id:30} | Name: {m.get('displayName', 'N/A')}")
        else:
            print(f"❌ 모델 리스트 조회 실패 (Status: {res.status_code})")
    except Exception as e:
        print(f"❌ 예외 발생 (리스트 조회): {e}")

    # 2. 통신 테스트 (60초 타임아웃 적용)
    if not available_models:
        print("\n⚠️ 테스트할 수 있는 모델이 없습니다.")
        return

    print("\n" + "-"*80)
    print(f"[2] 상위 모델 통신 테스트 (60초 타임아웃 적용)")
    
    # 테스트 우선순위: 사용자가 지정한 3.1, 3.0, 2.5 순
    test_targets = [
        "gemini-3.1-pro-preview", 
        "gemini-3.1-flash-lite-preview",
        "gemini-2.5-pro",
        "gemini-1.5-pro" # 대안
    ]
    
    # 실제 존재하는 모델만 필터링
    actual_targets = [m for m in test_targets if m in available_models]
    if not actual_targets:
        actual_targets = [available_models[0]] # 없으면 첫 번째 모델이라도 테스트

    for model_id in actual_targets:
        print(f"📡 시도 중: {model_id:30} ...", end=" ", flush=True)
        url_test = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": "Hello, confirm your model version."}]}]}
        
        try:
            res = requests.post(url_test, json=payload, timeout=60)
            if res.status_code == 200:
                print("✅ 성공 (200 OK)")
            else:
                print(f"❌ 실패 (Status: {res.status_code})")
        except requests.exceptions.Timeout:
            print("⏳ 타임아웃 (60초 초과)")
        except Exception as e:
            print(f"❌ 에외: {e}")

    print("\n" + "="*80)
    print("🏁 검증 종료.")
    print("="*80)

if __name__ == "__main__":
    verify_gemini()
