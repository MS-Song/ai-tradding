import os
import sys
from dotenv import load_dotenv

# 표준 출력 인코딩을 UTF-8로 강제 설정 (한글 깨짐 방지)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def verify_gemini():
    load_dotenv(override=True)
    api_key = os.getenv("GOOGLE_API_KEY")
    
    print("\n" + "="*80)
    print("🚀 [Gemini API 통합 검증 도구] 실행")
    print("="*80)
    
    if not api_key:
        print("❌ GOOGLE_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return

    print(f"🔹 Google API Key: {api_key[:4]}...{api_key[-4:] if len(api_key) > 8 else ''}")
    
    # google-genai SDK로 API 연결 시도
    print("\n[1] google-genai SDK 클라이언트 생성 중...")
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=60000)
        )
        print("✅ google-genai SDK 클라이언트 생성 완료.")
    except Exception as e:
        print(f"❌ SDK 로딩/클라이언트 생성 실패: {e}")
        return

    # 모델 통신 테스트
    print("\n" + "-"*80)
    print(f"[2] Gemini 모델 통신 테스트 (60초 타임아웃 적용)")
    
    test_targets = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]
    
    for model_id in test_targets:
        print(f"📡 시도 중: {model_id:30} ... ", end="", flush=True)
        try:
            response = client.models.generate_content(
                model=model_id,
                contents="Hello! Confirm model access by saying 'Hello from Gemini'."
            )
            if response and response.text:
                print(f"✅ 성공 (응답: {response.text.strip()})")
            else:
                print("❌ 실패 (빈 응답)")
        except Exception as e:
            print(f"❌ 에러: {e}")

    print("\n" + "="*80)
    print("🏁 검증 종료.")
    print("="*80)

if __name__ == "__main__":
    verify_gemini()


