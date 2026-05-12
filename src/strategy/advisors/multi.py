from typing import List, Tuple, Optional, Callable
from src.strategy.advisors.base import BaseAdvisor
from src.strategy.advisors.gemini import GeminiAdvisor
from src.strategy.advisors.groq import GroqAdvisor

class MultiLLMAdvisor(BaseAdvisor):
    """여러 LLM 공급자를 순차적으로 호출하여 무중단 서비스를 제공하는 멀티 LLM 어드바이저.
    
    메인 모델(예: Gemini) 장애 시 백업 모델(예: Groq)로 자동 전환(Fail-over)되는 
    복원력 있는 구조를 가집니다. 각 공급자별로 독립적인 호출 제한(CPS)이 적용됩니다.
    """
    def __init__(self, api, llm_sequence: List[Tuple[str, str]]):
        """MultiLLMAdvisor를 초기화합니다.

        Args:
            api: KIS API 클라이언트.
            llm_sequence (List[Tuple[str, str]]): (공급자, 모델ID) 쌍의 우선순위 리스트.
        """
        self.api = api
        self.advisors: List[BaseAdvisor] = []
        self.last_used_advisor: Optional[BaseAdvisor] = None
        
        for provider, model_id in llm_sequence:
            import os
            if provider.upper() == "GEMINI":
                cps = float(os.getenv("GEMINI_MAX_CPS", "1.0"))
                self.advisors.append(GeminiAdvisor(api, model_id, max_cps=cps))
            elif provider.upper() == "GROQ":
                cps = float(os.getenv("GROQ_MAX_CPS", "0.5"))
                self.advisors.append(GroqAdvisor(api, model_id, max_cps=cps))

    def _get_model_tag(self) -> str:
        """가장 최근에 성공적으로 호출된 모델의 식별 태그(예: [G3.1P])를 반환합니다."""
        if self.last_used_advisor and hasattr(self.last_used_advisor, 'short_id'):
            return f"[{self.last_used_advisor.short_id}]"
        return "[AI]"

    def _try_all(self, method_name: str, *args, **kwargs):
        """등록된 어드바이저들을 순서대로 호출하며 성공할 때까지 시도합니다."""
        errors = []
        for advisor in self.advisors:
            try:
                method = getattr(advisor, method_name)
                res = method(*args, **kwargs)
                if res is not None:
                    self.last_used_advisor = advisor
                    return res
            except Exception as e:
                m_tag = getattr(advisor, "short_id", advisor.model_id)
                errors.append(f"{m_tag}: {str(e)}")
                continue
        
        if errors:
            from src.logger import log_error
            log_error(f"MultiLLM Error (All Failed): {', '.join(errors)}")
        return None

    def get_advice(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 투자 전략 제언을 시도합니다."""
        return self._try_all("get_advice", *args, **kwargs)

    def get_detailed_report_advice(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 종목 리포트 생성을 시도합니다."""
        return self._try_all("get_detailed_report_advice", *args, **kwargs)

    def get_stock_report_advice(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 개별 종목 분석을 시도합니다."""
        return self._try_all("get_stock_report_advice", *args, **kwargs)

    def get_holdings_report_advice(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 보유 종목 진단을 시도합니다."""
        return self._try_all("get_holdings_report_advice", *args, **kwargs)

    def get_hot_stocks_report_advice(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 인기 종목 분석을 시도합니다."""
        return self._try_all("get_hot_stocks_report_advice", *args, **kwargs)

    def get_rebalance_advice(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 리밸런싱 조언을 시도합니다."""
        return self._try_all("get_rebalance_advice", *args, **kwargs)

    def verify_market_vibe(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 시장 장세 재검증을 시도합니다."""
        return self._try_all("verify_market_vibe", *args, **kwargs)

    def simulate_preset_strategy(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 프리셋 전략 선정을 시도합니다."""
        return self._try_all("simulate_preset_strategy", *args, **kwargs)

    def final_buy_confirm(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 매수 최종 승인을 시도하고 모델 태그를 사유에 추가합니다."""
        res = self._try_all("final_buy_confirm", *args, **kwargs)
        if res:
            decision, reason, wait_mins = res
            tag = self._get_model_tag()
            return decision, f"{tag} {reason}", wait_mins
        return False, "All LLM services failed", 60

    def closing_sell_confirm(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 장 마감 청산 결정을 시도하고 모델 태그를 추가합니다."""
        res = self._try_all("closing_sell_confirm", *args, **kwargs)
        if res:
            decision, reason = res
            tag = self._get_model_tag()
            return decision, f"{tag} {reason}"
        return True, "All LLM services failed"

    def compare_stock_superiority(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 종목 교체 여부 판단을 시도하고 모델 태그를 추가합니다."""
        res = self._try_all("compare_stock_superiority", *args, **kwargs)
        if res:
            superior, sell_code, reason, wait_mins = res
            tag = self._get_model_tag()
            return superior, sell_code, f"{tag} {reason}", wait_mins
        return False, None, "All LLM services failed", 60

    def get_portfolio_strategic_review(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 포트폴리오 일괄 리뷰를 시도합니다."""
        return self._try_all("get_portfolio_strategic_review", *args, **kwargs)

    def analyze_trade_retrospective(self, *args, **kwargs):
        """모든 어드바이저를 순회하며 매매 복기 분석을 시도합니다."""
        return self._try_all("analyze_trade_retrospective", *args, **kwargs)
