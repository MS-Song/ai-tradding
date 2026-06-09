import os
import time
from typing import Optional
from src.strategy.advisors.base import BaseLLMAdvisor
from src.logger import log_error
from google import genai
from google.genai import types

class GeminiAdvisor(BaseLLMAdvisor):
    """Google Gemini 모델을 사용하는 AI 어드바이저 클래스.
    
    `BaseLLMAdvisor`를 상속받아 google-genai SDK와의 통신을 구현합니다.
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
            log_error("GOOGLE_API_KEY is not configured.")
            return None
            
        # Rate Limit 대기 (BaseLLMAdvisor에서 상속받은 CPS 제어 로직 - api_key를 키로 사용)
        self._wait_for_rate_limit(api_key)
            
        model_name = self.model_id
        if model_name.startswith("models/"):
            model_name = model_name.replace("models/", "")
        
        for attempt in range(2):
            try:
                # google-genai SDK 클라이언트 생성 (timeout 설정 포함)
                # timeout은 ms 단위이므로 seconds * 1000
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=int(timeout * 1000))
                )
                
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                
                if response:
                    try:
                        text = response.text
                        if text:
                            # 사용량 트래킹 기록
                            from src.usage_tracker import AIUsageTracker
                            AIUsageTracker.log_call(self.model_id)
                            return text
                    except ValueError as ve:
                        log_error(f"Gemini Response parse error (blocked by safety?): {ve}")
                        
                log_error(f"Gemini API returned empty or blocked response for {model_name}")
                if attempt < 1:
                    time.sleep(2 ** attempt)
                    continue
            except Exception as e:
                log_error(f"Gemini API Exception ({model_name}) on attempt {attempt + 1}: {e}")
                if attempt < 1:
                    time.sleep(2 ** attempt)
                    continue
        return None


