import json
import os
from datetime import datetime

USAGE_FILE = "ai_usage.json"

class AIUsageTracker:
    """AI API 호출 횟수 및 모델별 사용량을 추적하는 유틸리티 클래스.
    
    월별 총 호출 횟수와 모델별 상세 사용량을 `ai_usage.json` 파일에 기록하여 
    API 비용 관리 및 사용 패턴 분석을 지원합니다.
    """
    @staticmethod
    def log_call(model_id: str):
        """AI API 호출 성공 시 기록을 남깁니다.

        Args:
            model_id (str): 사용된 AI 모델 식별자 (예: 'Gemini-1.5-Flash').
        """
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
        """현재 월의 총 AI API 호출 횟수를 반환합니다.

        Returns:
            int: 총 호출 횟수.
        """
        usage = AIUsageTracker._load()
        month_key = datetime.now().strftime("%Y-%m")
        return usage.get(month_key, {}).get("total_calls", 0)

    @staticmethod
    def get_monthly_breakdown() -> dict:
        """현재 월의 모델별 상세 호출 횟수를 반환합니다.

        Returns:
            dict: 모델 ID를 키로 하고 호출 횟수를 값으로 하는 딕셔너리.
        """
        usage = AIUsageTracker._load()
        month_key = datetime.now().strftime("%Y-%m")
        return usage.get(month_key, {}).get("models", {})

    @staticmethod
    def _load():
        """기존 사용량 데이터를 파일로부터 불러옵니다."""
        if not os.path.exists(USAGE_FILE):
            return {}
        try:
            with open(USAGE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    @staticmethod
    def _save(data):
        """사용량 데이터를 파일에 저장합니다."""
        with open(USAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
