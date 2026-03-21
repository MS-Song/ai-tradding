import os
import shutil
from dotenv import load_dotenv, set_key

def ensure_env(force=False):
    """.env 파일 설정을 관리하고, 엔터 입력 시 기존 값을 유지하는 기능 포함"""
    env_path = ".env"
    bak_path = ".env.bak"
    required_keys = ["KIS_APPKEY", "KIS_SECRET", "KIS_CANO", "KIS_ACNT_PRDT_CD", "KIS_IS_VIRTUAL", "GOOGLE_API_KEY"]
    
    # 1. 강제 재설정 시 백업 생성
    if force and os.path.exists(env_path):
        shutil.copy(env_path, bak_path)
        print(f"\n 📂 기존 설정이 {bak_path}에 백업되었습니다.")

    # 2. 기존 값 로드
    load_dotenv(env_path, override=True)
    
    # 설정이 필요한 상황(누락되었거나 강제 호출 시)
    # GOOGLE_API_KEY는 필수에서 제외하고 체크
    check_keys = ["KIS_APPKEY", "KIS_SECRET", "KIS_CANO", "KIS_ACNT_PRDT_CD", "KIS_IS_VIRTUAL"]
    missing = [key for key in check_keys if not os.getenv(key)]
    if missing or force:
        print("\n" + "="*60)
        print(" 🛠️  KIS-Vibe-Trader 환경 설정")
        print(" 엔터를 치면 기존 값이 유지됩니다.")
        print("="*60)
        
        for key in required_keys:
            old_val = os.getenv(key, "")
            
            if key == "KIS_IS_VIRTUAL":
                current_disp = "모의투자" if old_val != "FALSE" else "실전투자"
                prompt = f" > 투자 모드 선택 (1: 모의투자, 2: 실전투자) [{current_disp}]: "
                val = input(prompt).strip()
                if not val: 
                    final_val = old_val if old_val else "TRUE"
                else:
                    final_val = "FALSE" if val == '2' else "TRUE"
            else:
                label = {
                    "KIS_APPKEY": "앱 키 (App Key)",
                    "KIS_SECRET": "시크릿 키 (Secret Key)",
                    "KIS_CANO": "계좌번호 8자리 (CANO)",
                    "KIS_ACNT_PRDT_CD": "계좌상품코드 (보통 01)",
                    "GOOGLE_API_KEY": "Gemini API Key (선택사항)"
                }.get(key, key)
                
                # 민감 정보는 일부만 노출
                display_val = f"{old_val[:4]}****{old_val[-4:]}" if old_val and len(old_val) > 8 else old_val
                val = input(f" > {label} [{display_val}]: ").strip()
                final_val = val if val else old_val
                
                if not final_val and key != "GOOGLE_API_KEY":
                    print(f" ⚠️ {label}는 필수 입력 항목입니다.")
                    while not final_val:
                        val = input(f" > {label} 입력: ").strip()
                        final_val = val
            
            # .env 파일에 즉시 저장
            if not os.path.exists(env_path):
                with open(env_path, "w", encoding="utf-8") as f: f.write("")
            set_key(env_path, key, final_val)
        
        print("\n ✅ 설정이 안전하게 저장되었습니다.")
        print("="*60 + "\n")
        
        # 최신화된 값으로 다시 로드
        load_dotenv(env_path, override=True)
    
    return True
