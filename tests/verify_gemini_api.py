import os
import sys
from dotenv import load_dotenv

# 표준 출력 인코딩을 UTF-8로 강제 설정 (한글 깨짐 방지)
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def verify_vertex_gemini():
    load_dotenv(override=True)
    project_id = os.getenv("VERTEX_PROJECT_ID")
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    location = os.getenv("VERTEX_LOCATION", "us-central1")
    
    print("\n" + "="*80)
    print("🚀 [Vertex AI Gemini API 통합 검증 도구] 실행")
    print("="*80)
    
    if not project_id:
        print("❌ VERTEX_PROJECT_ID가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return

    print(f"🔹 GCP Project ID: {project_id}")
    print(f"🔹 GCP Region: {location}")
    print(f"🔹 Service Account Key Path: {credentials_path or '지정되지 않음 (기본 Application Default Credentials 사용)'}")
    
    if credentials_path:
        if os.path.exists(credentials_path):
            print(f"✅ Service Account Key JSON 파일이 존재합니다: {os.path.abspath(credentials_path)}")
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(credentials_path)
        else:
            print(f"❌ Service Account Key JSON 파일이 해당 경로에 존재하지 않습니다: {credentials_path}")
            return
            
    # Initialize Vertex AI
    print("\n[1] Vertex AI SDK 초기화 중...")
    try:
        import vertexai
        vertexai.init(project=project_id, location=location)
        print("✅ Vertex AI SDK 초기화 완료.")
    except Exception as e:
        print(f"❌ Vertex AI SDK 초기화 실패: {e}")
        return

    # Try generating content using different models
    print("\n" + "-"*80)
    print(f"[2] Vertex AI Gemini 모델 통신 테스트 (60초 타임아웃 적용)")
    
    test_targets = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]
    
    for model_id in test_targets:
        print(f"📡 시도 중: {model_id:30} ...", end=" ", flush=True)
        try:
            from vertexai.generative_models import GenerativeModel
            model = GenerativeModel(model_id)
            response = model.generate_content(
                "Hello! Confirm model access by saying 'Hello from Vertex AI'.",
                request_options={"timeout": 60.0}
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
    verify_vertex_gemini()

