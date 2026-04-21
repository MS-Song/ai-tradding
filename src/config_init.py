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
                "auto_sell": env_data.get("AI_AUTO_SELL_MODE", "FALSE") == "TRUE",
                "auto_apply": env_data.get("AUTO_APPLY_AI_STRATEGY", "FALSE") == "TRUE",
                "debug_mode": env_data.get("AI_DEBUG_MODE", "FALSE") == "TRUE",
                "preferred_model": env_data.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
                "llm_sequence": [tuple(item.split(":")) for item in env_data.get("LLM_SEQUENCE", "GEMINI:gemini-3.1-flash-lite-preview").split(",") if ":" in item]
            },
            "starter_kit": {
                "budget_per_stock": int(env_data.get("STARTER_KIT_BUDGET", 1000000)),
                "stocks": env_data.get("STARTER_KIT_STOCKS", "005930,000660,035420,005380").split(",")
            },
            "base_seed_money": int(env_data.get("BASE_SEED_MONEY", 0))
        }
    }

def ensure_env(force=False):
    """.env 파일 설정을 관리하고, 멀티 LLM 환경 구성을 포함"""
    env_path = ".env"
    bak_path = ".env.bak"
    
    if force and os.path.exists(env_path):
        shutil.copy(env_path, bak_path)
        print(f"\n 📂 기존 설정이 {bak_path}에 백업되었습니다.")

    env_data = dotenv_values(env_path) if os.path.exists(env_path) else {}
    
    required_keys = ["KIS_APPKEY", "KIS_SECRET", "KIS_CANO", "TAKE_PROFIT_THRESHOLD", "STOP_LOSS_THRESHOLD", "AI_AMOUNT_PER_TRADE"]
    missing = [key for key in required_keys if not env_data.get(key)]
    
    if missing or force:
        print("\n" + "="*60)
        print(" 🛠️  KIS-Vibe-Trader 환경 설정")
        print(" 엔터를 치면 [괄호] 안의 기존 값이 유지됩니다.")
        print("="*60)
        
        # 1. 기본 KIS 설정 및 전략 설정
        general_keys = [
            ("KIS_APPKEY", "앱 키 (App Key)", None, "text"),
            ("KIS_SECRET", "시크릿 키 (Secret Key)", None, "text"),
            ("KIS_CANO", "계좌번호 8자리 (CANO)", None, "text"),
            ("KIS_ACNT_PRDT_CD", "계좌상품코드 (보통 01)", "01", "text"),
            ("KIS_IS_VIRTUAL", "투자 모드 (1: 모의투자, 2: 실전투자)", "TRUE", "mode"),
            ("TAKE_PROFIT_THRESHOLD", "기본 익절 기준 (%)", "5.0", "text"),
            ("STOP_LOSS_THRESHOLD", "기본 손절 기준 (%)", "-5.0", "text"),
            ("AVERAGE_DOWN_AMOUNT", "물타기 1회 추가 매수 금액 (원)", "500000", "text"),
            ("MIN_LOSS_TO_BUY", "물타기 시작 수익률 (%)", "-3.0", "text"),
            ("MAX_INVESTMENT_PER_STOCK", "종목당 최대 투자 한도 (원)", "2000000", "text"),
            ("RECOVERY_AUTO_MODE", "물타기 자동 실행 여부 (Y/N)", "FALSE", "bool"),
            ("BULL_AVERAGE_DOWN_AMOUNT", "불타기 1회 추가 매수 금액 (원)", "500000", "text"),
            ("MIN_PROFIT_TO_PYRAMID", "불타기 시작 수익률 (%)", "3.0", "text"),
            ("BULL_MAX_INVESTMENT", "종목당 최대 불타기 한도 (원)", "25000000", "text"),
            ("PYRAMID_AUTO_MODE", "불타기 자동 실행 여부 (Y/N)", "FALSE", "bool"),
            ("AI_AMOUNT_PER_TRADE", "AI 추천 1회 매수 금액 (원)", "500000", "text"),
            ("AI_MIN_SCORE", "AI 추천 진입 최소 점수 (0-100)", "60.0", "text"),
            ("AI_MAX_INVESTMENT_PER_STOCK", "AI 추천 종목당 최대 투자액 (원)", "2000000", "text"),
            ("AI_AUTO_MODE", "AI 자율 매수(AUTO) 모드 사용 (Y/N)", "FALSE", "bool"),
            ("AI_AUTO_SELL_MODE", "AI 자율 매도(AUTO) 모드 사용 (Y/N)", "FALSE", "bool"),
            ("AI_DEBUG_MODE", "AI 디버그 모드 (장외 AI 강제실행) (Y/N)", "FALSE", "bool"),
            ("AUTO_APPLY_AI_STRATEGY", "AI 시황 분석 전략 자동 반영 여부 (Y/N)", "FALSE", "bool"),
            ("BASE_SEED_MONEY", "총 누적 입금액(초기 시드 + 추가 입금액) (원)", "0", "text")
        ]

        def handle_input(key, label, default, input_type, current_env):
            old_val = current_env.get(key, "")
            if input_type == "mode":
                current_disp = "모의투자" if old_val != "FALSE" else "실전투자"
                val = input(f" > {label} [{current_disp}]: ").strip()
                final = old_val if not val else ("FALSE" if val == '2' else "TRUE")
                return final or "TRUE"
            elif input_type == "bool":
                current_disp = "ON" if old_val == "TRUE" else "OFF"
                val = input(f" > {label} [{current_disp}]: ").strip().upper()
                if not val: return old_val if old_val else default
                return "TRUE" if val in ['Y', 'YES', 'ON', '1'] else "FALSE"
            else:
                if old_val and (key.endswith("KEY") or "SECRET" in key or "CANO" in key):
                    if len(old_val) <= 8:
                        display_val = f"{old_val[:2]}****{old_val[-2:]}"
                    else:
                        display_val = f"{old_val[:4]}****{old_val[-4:]}"
                else:
                    display_val = old_val or (default or "")
                val = input(f" > {label} [{display_val}]: ").strip()
                final = val if val else old_val
                if not final and key not in ["GOOGLE_API_KEY", "GROQ_API_KEY"]:
                    final = default or ""
                    while not final: final = input(f" ! {label}는 필수입니다: ").strip()
                return final

        def fetch_gemini_models(api_key):
            import requests
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    models = [m['name'].replace('models/', '') for m in resp.json().get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
                    return sorted(models)
            except: pass
            return ["gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"]

        def fetch_groq_models(api_key):
            import requests
            try:
                url = "https://api.groq.com/openai/v1/models"
                resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=5)
                if resp.status_code == 200:
                    models = [m['id'] for m in resp.json().get('data', [])]
                    return sorted(models)
            except: pass
            return ["llama-3.1-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"]

        results = {}
        for k, l, d, t in general_keys:
            results[k] = handle_input(k, l, d, t, env_data)

        # 2. 멀티 LLM 상세 설정
        print("\n" + "-"*30)
        print(" 🤖 AI 멀티 LLM 설정")
        print("-"*30)

        # 2-1. Google Gemini 설정
        gemini_key = handle_input("GOOGLE_API_KEY", "Google Gemini API Key (없으면 엔터)", None, "text", env_data)
        results["GOOGLE_API_KEY"] = gemini_key
        selected_llm_options = []

        if gemini_key:
            print("  > Gemini 모델 목록을 가져오는 중...")
            gemini_models = fetch_gemini_models(gemini_key)
            print("  [Gemini 모델 리스트]")
            for i, m in enumerate(gemini_models):
                print(f"   {i+1}: {m}")
            
            # 기존 값 찾기 (개별 설정값 우선, 없으면 시퀀스에서 추출)
            curr_p = env_data.get("GEMINI_MODEL", "")
            curr_s = env_data.get("GEMINI_SECONDARY_MODEL", "")
            
            if not curr_p or not curr_s:
                curr_seq = env_data.get("LLM_SEQUENCE", "")
                gemini_entries = [entry.split(":")[1] for entry in curr_seq.split(",") if entry.startswith("GEMINI:")]
                if not curr_p: curr_p = gemini_entries[0] if gemini_entries else gemini_models[0]
                if not curr_s: curr_s = gemini_entries[1] if len(gemini_entries) > 1 else (gemini_models[1] if len(gemini_models) > 1 else curr_p)
            
            p_model, s_model = curr_p, curr_s

            m1 = input(f"  > Gemini 주 모델 (Primary) 선택 (번호/이름) [{curr_p}]: ").strip()
            if not m1: p_model = curr_p
            elif m1.isdigit() and 1 <= int(m1) <= len(gemini_models): p_model = gemini_models[int(m1)-1]
            else: p_model = m1

            m2 = input(f"  > Gemini 부 모델 (Secondary) 선택 (번호/이름) [{curr_s}]: ").strip()
            if not m2: s_model = curr_s
            elif m2.isdigit() and 1 <= int(m2) <= len(gemini_models): s_model = gemini_models[int(m2)-1]
            else: s_model = m2
            
            selected_llm_options.append(("GEMINI", p_model, "Gemini Primary"))
            selected_llm_options.append(("GEMINI", s_model, "Gemini Secondary"))
            results["GEMINI_MODEL"] = p_model
            results["GEMINI_SECONDARY_MODEL"] = s_model
            
            # Gemini CPS 설정
            results["GEMINI_MAX_CPS"] = handle_input("GEMINI_MAX_CPS", "  > Gemini 초당 최대 호출 횟수 (기본 1.0)", "1.0", "text", env_data)

        # 2-2. Groq 설정
        groq_key = handle_input("GROQ_API_KEY", "Groq API Key (없으면 엔터)", None, "text", env_data)
        results["GROQ_API_KEY"] = groq_key
        if groq_key:
            print("  > Groq 모델 목록을 가져오는 중...")
            groq_models = fetch_groq_models(groq_key)
            print("  [Groq 모델 리스트]")
            for i, m in enumerate(groq_models):
                print(f"   {i+1}: {m}")
            
            # 기존 값 찾기 (개별 설정값 우선, 없으면 시퀀스에서 추출)
            curr_p = env_data.get("GROQ_MODEL", "")
            curr_s = env_data.get("GROQ_SECONDARY_MODEL", "")

            if not curr_p or not curr_s:
                curr_seq = env_data.get("LLM_SEQUENCE", "")
                groq_entries = [entry.split(":")[1] for entry in curr_seq.split(",") if entry.startswith("GROQ:")]
                if not curr_p: curr_p = groq_entries[0] if groq_entries else groq_models[0]
                if not curr_s: curr_s = groq_entries[1] if len(groq_entries) > 1 else (groq_models[1] if len(groq_models) > 1 else curr_p)

            p_model, s_model = curr_p, curr_s

            m1 = input(f"  > Groq 주 모델 (Primary) 선택 (번호/이름) [{curr_p}]: ").strip()
            if not m1: p_model = curr_p
            elif m1.isdigit() and 1 <= int(m1) <= len(groq_models): p_model = groq_models[int(m1)-1]
            else: p_model = m1

            m2 = input(f"  > Groq 부 모델 (Secondary) 선택 (번호/이름) [{curr_s}]: ").strip()
            if not m2: s_model = curr_s
            elif m2.isdigit() and 1 <= int(m2) <= len(groq_models): s_model = groq_models[int(m2)-1]
            else: s_model = m2
            
            selected_llm_options.append(("GROQ", p_model, "Groq Primary"))
            selected_llm_options.append(("GROQ", s_model, "Groq Secondary"))
            results["GROQ_MODEL"] = p_model
            results["GROQ_SECONDARY_MODEL"] = s_model

            # Groq CPS 설정
            results["GROQ_MAX_CPS"] = handle_input("GROQ_MAX_CPS", "  > Groq 초당 최대 호출 횟수 (무료 0.1~0.2 권장)", "0.5", "text", env_data)

        # 2-3. 최종 우선순위(Fail-over) 설정
        if not selected_llm_options:
            print(" ! 경고: 활성화된 LLM 서비스가 없습니다. 기본 Gemini 모델로 설정합니다.")
            results["LLM_SEQUENCE"] = "GEMINI:gemini-3.1-flash-lite-preview"
        else:
            print("\n  [선택된 모델 목록]")
            for i, opt in enumerate(selected_llm_options):
                print(f"   {i+1}. {opt[2]} ({opt[1]})")
            
            curr_seq_raw = env_data.get("LLM_SEQUENCE", "")
            existing_indices = []
            if curr_seq_raw:
                for entry in curr_seq_raw.split(","):
                    for idx, opt in enumerate(selected_llm_options):
                        if f"{opt[0]}:{opt[1]}" == entry:
                            existing_indices.append(str(idx + 1))
                            break
            
            default_indices = []
            seen_providers = set()
            # 1. 기존에 쓰던 모델이 있다면 우선순위 유지
            for idx_str in existing_indices:
                try:
                    idx = int(idx_str) - 1
                    if 0 <= idx < len(selected_llm_options):
                        provider = selected_llm_options[idx][0]
                        default_indices.append(idx_str)
                        seen_providers.add(provider)
                except: pass
            
            # 2. 새롭게 활성화된 서비스(Gemini 등)가 리스트에 없으면 추가
            for idx, opt in enumerate(selected_llm_options):
                provider = opt[0]
                idx_str = str(idx + 1)
                if provider not in seen_providers and idx_str not in default_indices:
                    default_indices.append(idx_str)
                    seen_providers.add(provider)
            
            default_seq_str = ",".join(default_indices[:3]) if default_indices else "1"
            
            print(f"\n  [우선순위 설정] 번호를 순서대로 입력하세요 (최대 3개, 예: 1,3,2)")
            while True:
                p_input = input(f"  > Fail-over 순서 (Enter 시 유지) [{default_seq_str}]: ").strip().replace(" ", "")
                if not p_input:
                    p_input = default_seq_str
                
                try:
                    p_indices = [int(i)-1 for i in p_input.split(",") if i.isdigit()]
                except: p_indices = [0]
                
                valid_indices = [i for i in p_indices if 0 <= i < len(selected_llm_options)][:3]
                if not valid_indices:
                    print("  ! 최소 1개 이상의 모델을 지정해야 합니다.")
                else:
                    seen = set()
                    final_seq = []
                    for idx in valid_indices:
                        if idx not in seen:
                            final_seq.append(f"{selected_llm_options[idx][0]}:{selected_llm_options[idx][1]}")
                            seen.add(idx)
                    results["LLM_SEQUENCE"] = ",".join(final_seq)
                    break

        # 3. 파일 저장 및 정리
        if not os.path.exists(env_path):
            with open(env_path, "w", encoding="utf-8") as f: f.write("")
        
        # KIS 키 변동 시 토큰 캐시 삭제
        if results.get("KIS_APPKEY") != env_data.get("KIS_APPKEY") or results.get("KIS_SECRET") != env_data.get("KIS_SECRET"):
            if os.path.exists(".token_cache.json"):
                try: os.remove(".token_cache.json")
                except: pass
        
        for key, val in results.items():
            set_key(env_path, key, str(val))
            
        # Rate Limit 캐시 초기화 (변경 즉시 반영)
        from src.strategy.advisors.base import BaseLLMAdvisor
        BaseLLMAdvisor._last_call_times = {}

        print("\n ✅ 모든 설정이 안전하게 저장되었습니다.")
        print("="*60 + "\n")
        load_dotenv(env_path, override=True)
    
    return True
