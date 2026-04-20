import requests
import time
import os
from typing import Optional
from src.strategy.advisors.base import BaseLLMAdvisor
from src.logger import log_error

class GroqAdvisor(BaseLLMAdvisor):
    def _call_api(self, prompt: str, timeout: int = 60) -> Optional[str]:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return None
            
        # Rate Limit 대기
        self._wait_for_rate_limit(api_key)
            
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2
        }
        
        for attempt in range(2):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if response.status_code == 200:
                    res_json = response.json()
                    return res_json['choices'][0]['message']['content']
                else:
                    log_error(f"Groq API Error ({self.model_id}): {response.status_code} - {response.text}")
                    if response.status_code in [429, 500, 503]:
                        time.sleep(2 ** attempt)
                        continue
                    break
            except Exception as e:
                log_error(f"Groq API Exception ({self.model_id}): {e}")
                time.sleep(1)
        return None
