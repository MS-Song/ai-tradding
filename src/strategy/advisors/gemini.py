import requests
import time
import os
from typing import Optional
from src.strategy.advisors.base import BaseLLMAdvisor
from src.logger import log_error

class GeminiAdvisor(BaseLLMAdvisor):
    """Google Gemini Pro/Flash 모델을 사용하는 AI 어드바이저 클래스.
    
    `BaseLLMAdvisor`를 상속받아 Gemini REST API와의 통신을 구현합니다.
    초당 호출 횟수 제한(Rate Limit)을 준수하며, 일시적 오류에 대한 재시도 로직을 포함합니다.
    """

    def _call_api(self, prompt: str, timeout: int = 60) -> Optional[str]:
        """Gemini API에 텍스트 생성을 요청합니다.

        Args:
            prompt (str): 모델에 전달할 프롬프트 문자열.
            timeout (int, optional): API 응답 대기 시간(초). 기본값 60.

        Returns:
            Optional[str]: 생성된 응답 텍스트. 실패 시 None 반환.
        """
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return None
            
        # Rate Limit 대기 (BaseLLMAdvisor에서 상속받은 CPS 제어 로직)
        self._wait_for_rate_limit(api_key)
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_id}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        for attempt in range(2):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if response.status_code == 200:
                    res_json = response.json()
                    # 사용량 트래킹 기록
                    from src.usage_tracker import AIUsageTracker
                    AIUsageTracker.log_call(self.model_id)
                    return res_json['candidates'][0]['content']['parts'][0]['text']
                else:
                    log_error(f"Gemini API Error ({self.model_id}): {response.status_code} - {response.text}")
                    # 429(Rate Limit), 500/503(Server Error) 발생 시 지수 백오프 후 재시도
                    if response.status_code in [429, 500, 503]:
                        time.sleep(2 ** attempt)
                        continue
                    break
            except Exception as e:
                log_error(f"Gemini API Exception ({self.model_id}): {e}")
                time.sleep(1)
        return None
