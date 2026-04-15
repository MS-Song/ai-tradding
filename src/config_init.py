import os
import shutil
import yaml
from dotenv import load_dotenv, set_key, dotenv_values

def get_config():
    """환경 변수(.env)에서 트레이딩 설정을 읽어와 딕셔너리로 반환"""
    # 매번 최신 .env를 반영하기 위해 dotenv_values() 활용
    env_data = dotenv_values(".env")
    return {
        "vibe_strategy": {
            "take_profit_threshold": float(env_data.get("TAKE_PROFIT_THRESHOLD", 5.0)),
            "stop_loss_threshold": float(env_data.get("STOP_LOSS_THRESHOLD", -5.0)),
            "take_profit_ratio": float(env_data.get("TAKE_PROFIT_RATIO", 0.3)),
            "stop_loss_ratio": float(env_data.get("STOP_LOSS_RATIO", 1.0)),
            "bull_market": {
                "take_profit_threshold": float(env_data.get("BULL_TAKE_PROFIT_THRESHOLD", 3.0)),
                "min_profit_to_pyramid": float(env_data.get("MIN_PROFIT_TO_PYRAMID", 3.0)),
                "average_down_amount": int(env_data.get("BULL_AVERAGE_DOWN_AMOUNT", 500000)),
                "max_investment_per_stock": int(env_data.get("BULL_MAX_INVESTMENT", 25000000)),
                "auto_mode": env_data.get("PYRAMID_AUTO_MODE", "FALSE") == "TRUE"
            },
            "bear_market": {
                "average_down_amount": int(env_data.get("AVERAGE_DOWN_AMOUNT", 500000)),
                "min_loss_to_buy": float(env_data.get("MIN_LOSS_TO_BUY", -3.0)),
                "max_investment_per_stock": int(env_data.get("MAX_INVESTMENT_PER_STOCK", 2000000)),
                "auto_mode": env_data.get("RECOVERY_AUTO_MODE", "FALSE") == "TRUE"
            },
            "ai_config": {
                "amount_per_trade": int(env_data.get("AI_AMOUNT_PER_TRADE", 500000)),
                "min_score": float(env_data.get("AI_MIN_SCORE", 60.0)),
                "max_investment_per_stock": int(env_data.get("AI_MAX_INVESTMENT_PER_STOCK", 2000000)),
                "auto_mode": env_data.get("AI_AUTO_MODE", "FALSE") == "TRUE",
                "auto_apply": env_data.get("AUTO_APPLY_AI_STRATEGY", "FALSE") == "TRUE"
            },
            "starter_kit": {
                "budget_per_stock": int(env_data.get("STARTER_KIT_BUDGET", 1000000)),
                "stocks": env_data.get("STARTER_KIT_STOCKS", "005930,000660,035420,005380").split(",")
            }
        }
    }

def ensure_env(force=False):
    """.env 파일 설정을 관리하고, 엔터 입력 시 기존 값을 유지하는 기능 포함"""
    env_path = ".env"
    bak_path = ".env.bak"
    
    # 1. 강제 재설정 시 백업 생성
    if force and os.path.exists(env_path):
        shutil.copy(env_path, bak_path)
        print(f"\n 📂 기존 설정이 {bak_path}에 백업되었습니다.")

    # 2. 기존 값 로드 (dict 형태로 직접 로드)
    env_data = dotenv_values(env_path) if os.path.exists(env_path) else {}
    
    # 필수 설정 체크 (주요 항목 위주)
    required_keys = [
        "KIS_APPKEY", "KIS_SECRET", "KIS_CANO", "TAKE_PROFIT_THRESHOLD", 
        "STOP_LOSS_THRESHOLD", "AI_AMOUNT_PER_TRADE"
    ]
    
    missing = [key for key in required_keys if not env_data.get(key)]
    if missing or force:
        print("\n" + "="*60)
        print(" 🛠️  KIS-Vibe-Trader 환경 설정")
        print(" 엔터를 치면 [괄호] 안의 기존 값이 유지됩니다.")
        print("="*60)
        
        setup_keys = [
            # [Key, Label, Default, Type(text/bool/mode)]
            ("KIS_APPKEY", "앱 키 (App Key)", None, "text"),
            ("KIS_SECRET", "시크릿 키 (Secret Key)", None, "text"),
            ("KIS_CANO", "계좌번호 8자리 (CANO)", None, "text"),
            ("KIS_ACNT_PRDT_CD", "계좌상품코드 (보통 01)", "01", "text"),
            ("KIS_IS_VIRTUAL", "투자 모드 (1: 모의투자, 2: 실전투자)", "TRUE", "mode"),
            ("GOOGLE_API_KEY", "Gemini API Key (선택사항)", None, "text"),
            
            # 기본 전략
            ("TAKE_PROFIT_THRESHOLD", "기본 익절 기준 (%)", "5.0", "text"),
            ("STOP_LOSS_THRESHOLD", "기본 손절 기준 (%)", "-5.0", "text"),
            
            # 물타기(Recovery)
            ("AVERAGE_DOWN_AMOUNT", "물타기 1회 추가 매수 금액 (원)", "500000", "text"),
            ("MIN_LOSS_TO_BUY", "물타기 시작 수익률 (%)", "-3.0", "text"),
            ("MAX_INVESTMENT_PER_STOCK", "종목당 최대 투자 한도 (원)", "2000000", "text"),
            ("RECOVERY_AUTO_MODE", "물타기 자동 실행 여부 (Y/N)", "FALSE", "bool"),
            
            # AI 추천(Vibe-Alpha)
            ("AI_AMOUNT_PER_TRADE", "AI 추천 1회 매수 금액 (원)", "500000", "text"),
            ("AI_MIN_SCORE", "AI 추천 진입 최소 점수 (0-100)", "60.0", "text"),
            ("AI_MAX_INVESTMENT_PER_STOCK", "AI 추천 종목당 최대 투자액 (원)", "2000000", "text"),
            ("AI_AUTO_MODE", "AI 자율 매수(AUTO) 모드 사용 (Y/N)", "FALSE", "bool"),
            ("AUTO_APPLY_AI_STRATEGY", "AI 시황 분석 전략 자동 반영 여부 (Y/N)", "FALSE", "bool")
        ]
        
        for key, label, default, input_type in setup_keys:
            old_val = env_data.get(key, "")
            
            # 1. 투자 모드 특수 처리
            if input_type == "mode":
                current_disp = "모의투자" if old_val != "FALSE" else "실전투자"
                val = input(f" > {label} [{current_disp}]: ").strip()
                final_val = old_val if not val else ("FALSE" if val == '2' else "TRUE")
                if not final_val: final_val = "TRUE"
                
            # 2. 불리언(Y/N) 특수 처리
            elif input_type == "bool":
                current_disp = "ON" if old_val == "TRUE" else "OFF"
                val = input(f" > {label} [{current_disp}]: ").strip().upper()
                if not val:
                    final_val = old_val if old_val else default
                else:
                    final_val = "TRUE" if val in ['Y', 'YES', 'ON', '1'] else "FALSE"
            
            # 3. 일반 텍스트 및 마스킹
            else:
                if old_val and len(old_val) > 20:
                    display_val = f"{old_val[:4]}****{old_val[-4:]}"
                else:
                    display_val = old_val if old_val else (default if default else "")
                
                val = input(f" > {label} [{display_val}]: ").strip()
                final_val = val if val else old_val
                
                if not final_val and key not in ["GOOGLE_API_KEY"]:
                    final_val = default if default else ""
                    if not final_val:
                        while not final_val:
                            final_val = input(f" ! {label}는 필수입니다: ").strip()
            
            if not os.path.exists(env_path):
                with open(env_path, "w", encoding="utf-8") as f: f.write("")
            set_key(env_path, key, str(final_val))
        
        print("\n ✅ 모든 설정이 안전하게 저장되었습니다.")
        print("="*60 + "\n")
        load_dotenv(env_path, override=True)
    
    return True
