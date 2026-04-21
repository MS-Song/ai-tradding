import json
import os
from datetime import datetime

USAGE_FILE = "ai_usage.json"

class AIUsageTracker:
    @staticmethod
    def log_call(model_id: str):
        """AI API 호출 성공 시 기록을 남깁니다."""
        try:
            usage = AIUsageTracker._load()
            month_key = datetime.now().strftime("%Y-%m")
            
            if month_key not in usage:
                usage[month_key] = {"total_calls": 0, "models": {}}
                
            usage[month_key]["total_calls"] += 1
            usage[month_key]["models"][model_id] = usage[month_key]["models"].get(model_id, 0) + 1
            
            AIUsageTracker._save(usage)
        except: pass

    @staticmethod
    def get_monthly_calls() -> int:
        """이번 달 총 호출 횟수를 반환합니다."""
        usage = AIUsageTracker._load()
        month_key = datetime.now().strftime("%Y-%m")
        return usage.get(month_key, {}).get("total_calls", 0)

    @staticmethod
    def get_monthly_breakdown() -> dict:
        """이번 달 모델별 상세 호출 횟수를 반환합니다."""
        usage = AIUsageTracker._load()
        month_key = datetime.now().strftime("%Y-%m")
        return usage.get(month_key, {}).get("models", {})

    @staticmethod
    def _load():
        if not os.path.exists(USAGE_FILE):
            return {}
        try:
            with open(USAGE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    @staticmethod
    def _save(data):
        with open(USAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
