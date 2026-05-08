import requests
import time
import os
from typing import Optional
from src.strategy.advisors.base import BaseLLMAdvisor
from src.logger import log_error

class GroqAdvisor(BaseLLMAdvisor):
    """Groq Llama-3 모델을 사용하는 AI 어드바이저 클래스.
    
    `BaseLLMAdvisor`를 상속받아 Groq의 OpenAI 호환 Chat Completions API와의 통신을 구현합니다.
    매우 빠른 추론 속도를 활용하여 Gemini 장애 시의 주요 Fallback 엔진으로 동작합니다.
    """

    def _call_api(self, prompt: str, timeout: int = 60) -> Optional[str]:
        """Groq API에 텍스트 생성을 요청합니다.

        Args:
            prompt (str): 모델에 전달할 프롬프트 문자열.
            timeout (int, optional): API 응답 대기 시간(초). 기본값 60.

        Returns:
            Optional[str]: 생성된 응답 텍스트. 실패 시 None 반환.
        """
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return None
            
        # Rate Limit 대기 (BaseLLMAdvisor에서 상속받은 CPS 제어 로직)
        self._wait_for_rate_limit(api_key)
            
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2 # 답변의 일관성을 위해 낮은 창의성 설정
        }
        
        for attempt in range(2):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if response.status_code == 200:
                    res_json = response.json()
                    # 사용량 트래킹 기록
                    from src.usage_tracker import AIUsageTracker
                    AIUsageTracker.log_call(self.model_id)
                    return res_json['choices'][0]['message']['content']
                else:
                    log_error(f"Groq API Error ({self.model_id}): {response.status_code} - {response.text}")
                    # 429(Rate Limit), 500/503(Server Error) 발생 시 지수 백오프 후 재시도
                    if response.status_code in [429, 500, 503]:
                        time.sleep(2 ** attempt)
                        continue
                    break
            except Exception as e:
                log_error(f"Groq API Exception ({self.model_id}): {e}")
                time.sleep(1)
        return None
