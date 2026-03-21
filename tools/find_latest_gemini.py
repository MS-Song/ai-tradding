import os
import requests
import json
from dotenv import load_dotenv

def find_actual_latest_model():
    load_dotenv(override=True)
    api_key = os.getenv("GOOGLE_API_KEY")
    
    if not api_key:
        print("❌ GOOGLE_API_KEY가 없습니다.")
        return

    # 1단계: 모델 목록 조회 (v1beta 엔드포인트)
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    try:
        res = requests.get(url)
        if res.status_code == 200:
            models_data = res.json().get('models', [])
            print("\n🔍 [Step 2] 가용 모델 분석 결과:")
            print("="*70)
            
            valid_models = []
            for m in models_data:
                # generateContent를 지원하는지 확인
                if 'generateContent' in m.get('supportedGenerationMethods', []):
                    name = m['name']
                    display_name = m.get('displayName', '')
                    # 2단계: 최신 모델 선별 (이름에 flash나 pro 포함)
                    if 'flash' in name.lower() or 'pro' in name.lower():
                        valid_models.append(name)
                        print(f"✅ 발견: {name} ({display_name})")
            
            print("="*70)
            if valid_models:
                # 가장 마지막에 위치한 모델이 보통 최신 버전임
                latest = valid_models[-1]
                print(f"\n🚀 [Result] 선정된 최신 모델명: {latest}")
                return latest
            else:
                print("❌ 'flash' 또는 'pro'를 포함한 적합한 모델을 찾지 못했습니다.")
        else:
            print(f"❌ 목록 조회 실패 (Code: {res.status_code})")
            print(res.text)
    except Exception as e:
        print(f"❌ 시스템 오류: {e}")

if __name__ == "__main__":
    find_actual_latest_model()
