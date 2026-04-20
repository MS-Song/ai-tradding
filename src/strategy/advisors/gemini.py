import requests
import time
import os
from typing import Optional
from src.strategy.advisors.base import BaseLLMAdvisor
from src.logger import log_error

class GeminiAdvisor(BaseLLMAdvisor):
    def _call_api(self, prompt: str, timeout: int = 60) -> Optional[str]:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return None
            
        # Rate Limit 대기
        self._wait_for_rate_limit(api_key)
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_id}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        for attempt in range(2):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
                if response.status_code == 200:
                    res_json = response.json()
                    return res_json['candidates'][0]['content']['parts'][0]['text']
                else:
                    log_error(f"Gemini API Error ({self.model_id}): {response.status_code} - {response.text}")
                    if response.status_code in [429, 500, 503]:
                        time.sleep(2 ** attempt)
                        continue
                    break
            except Exception as e:
                log_error(f"Gemini API Exception ({self.model_id}): {e}")
                time.sleep(1)
        return None
