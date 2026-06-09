import os
import time
from typing import Optional
from src.strategy.advisors.base import BaseLLMAdvisor
from src.logger import log_error

# Lazy loading flag for Vertex AI initialization
_vertex_initialized = False

def init_vertex_ai() -> bool:
    """Initialize Google Cloud Vertex AI SDK.
    
    Reads GCP project credentials and settings from environment variables.
    """
    global _vertex_initialized
    if _vertex_initialized:
        return True
        
    project_id = os.getenv("VERTEX_PROJECT_ID")
    if not project_id:
        return False
        
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path and os.path.exists(credentials_path):
        # Resolve absolute path to ensure SDK finds it correctly
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(credentials_path)
        
    location = os.getenv("VERTEX_LOCATION", "us-central1")
    
    try:
        import vertexai
        vertexai.init(project=project_id, location=location)
        _vertex_initialized = True
        return True
    except Exception as e:
        log_error(f"Failed to initialize Vertex AI: {e}")
        return False

class GeminiAdvisor(BaseLLMAdvisor):
    """Google Cloud Vertex AI Gemini 모델을 사용하는 AI 어드바이저 클래스.
    
    `BaseLLMAdvisor`를 상속받아 Vertex AI SDK와의 통신을 구현합니다.
    초당 호출 횟수 제한(Rate Limit)을 준수하며, 일시적 오류에 대한 재시도 로직을 포함합니다.
    """

    def _call_api(self, prompt: str, timeout: int = 60) -> Optional[str]:
        """Vertex AI Gemini API에 텍스트 생성을 요청합니다.

        Args:
            prompt (str): 모델에 전달할 프롬프트 문자열.
            timeout (int, optional): API 응답 대기 시간(초). 기본값 60.

        Returns:
            Optional[str]: 생성된 응답 텍스트. 실패 시 None 반환.
        """
        if not init_vertex_ai():
            log_error("Vertex AI is not initialized. Please configure VERTEX_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS.")
            return None
            
        project_id = os.getenv("VERTEX_PROJECT_ID")
        
        # Rate Limit 대기 (BaseLLMAdvisor에서 상속받은 CPS 제어 로직 - project_id를 키로 사용)
        self._wait_for_rate_limit(project_id)
            
        # 모델명 변환 및 정리 (Vertex AI 용 형식)
        model_name = self.model_id
        if model_name.startswith("models/"):
            model_name = model_name.replace("models/", "")
            
        # AI Studio 전용 모델명이 설정되어 있을 경우 적절한 Vertex AI 모델명으로 매핑
        if "flash-lite" in model_name:
            model_name = "gemini-2.5-flash"
        elif "pro-preview" in model_name or "gemini-3" in model_name:
            model_name = "gemini-2.5-flash" if "flash" in model_name else "gemini-2.5-pro"
        
        for attempt in range(2):
            try:
                from vertexai.generative_models import GenerativeModel
                model = GenerativeModel(model_name)
                
                # API 호출 수행 (timeout 설정 포함)
                response = model.generate_content(
                    prompt,
                    request_options={"timeout": float(timeout)}
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
                        log_error(f"Vertex AI Gemini Response parse error (blocked by safety?): {ve}")
                        
                log_error(f"Vertex AI Gemini API returned empty or blocked response for {model_name}")
                if attempt < 1:
                    time.sleep(2 ** attempt)
                    continue
            except Exception as e:
                log_error(f"Vertex AI Gemini API Exception ({model_name}) on attempt {attempt + 1}: {e}")
                if attempt < 1:
                    time.sleep(2 ** attempt)
                    continue
        return None

