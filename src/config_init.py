import os
from dotenv import load_dotenv, set_key

def ensure_env():
    """.env 파일이 없거나 필수 환경 변수가 없으면 사용자로부터 입력받아 생성/업데이트"""
    env_path = ".env"
    required_keys = ["KIS_APPKEY", "KIS_SECRET", "KIS_CANO", "KIS_IS_VIRTUAL"]
    
    # 1. 먼저 기존 .env 로드
    load_dotenv(env_path)
    
    missing_keys = [key for key in required_keys if not os.getenv(key)]
    
    if missing_keys:
        print("\n" + "="*50)
        print(" 🛠️  환경 설정 (.env) 이 누락되었습니다.")
        print(" 한국투자증권 Open API 정보를 입력해주세요.")
        print("="*50)
        
        for key in missing_keys:
            val = ""
            if key == "KIS_IS_VIRTUAL":
                val = input(" > 투자 모드 선택 (1: 모의투자[기본], 2: 실전투자): ").strip()
                if val == '2':
                    val = "FALSE"
                else:
                    val = "TRUE"
            else:
                while not val:
                    prompt = {
                        "KIS_APPKEY": "앱 키 (App Key)",
                        "KIS_SECRET": "시크릿 키 (Secret Key)",
                        "KIS_CANO": "계좌번호 8자리 (CANO)"
                    }.get(key, key)
                    
                    val = input(f" > {prompt} 입력: ").strip()
                    if not val:
                        print(f" ⚠️ {prompt}는 필수 입력 항목입니다.")
            
            # .env 파일에 저장
            if not os.path.exists(env_path):
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("")
            
            set_key(env_path, key, val)
        
        print("\n ✅ .env 파일이 업데이트 되었습니다.")
        print("="*50 + "\n")
        
        # 다시 로드하여 os.environ 업데이트
        load_dotenv(env_path, override=True)
    
    return True
