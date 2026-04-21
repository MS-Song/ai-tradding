from typing import List, Tuple, Optional, Callable
from src.strategy.advisors.base import BaseAdvisor
from src.strategy.advisors.gemini import GeminiAdvisor
from src.strategy.advisors.groq import GroqAdvisor

class MultiLLMAdvisor(BaseAdvisor):
    def __init__(self, api, llm_sequence: List[Tuple[str, str]]):
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
        if self.last_used_advisor and hasattr(self.last_used_advisor, 'short_id'):
            return f"[{self.last_used_advisor.short_id}]"
        return "[AI]"

    def _try_all(self, method_name: str, *args, **kwargs):
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

    def get_advice(self, *args, **kwargs): return self._try_all("get_advice", *args, **kwargs)
    def get_detailed_report_advice(self, *args, **kwargs): return self._try_all("get_detailed_report_advice", *args, **kwargs)
    def get_stock_report_advice(self, *args, **kwargs): return self._try_all("get_stock_report_advice", *args, **kwargs)
    def get_holdings_report_advice(self, *args, **kwargs): return self._try_all("get_holdings_report_advice", *args, **kwargs)
    def get_hot_stocks_report_advice(self, *args, **kwargs): return self._try_all("get_hot_stocks_report_advice", *args, **kwargs)
    def get_rebalance_advice(self, *args, **kwargs): return self._try_all("get_rebalance_advice", *args, **kwargs)
    def verify_market_vibe(self, *args, **kwargs): return self._try_all("verify_market_vibe", *args, **kwargs)

    def simulate_preset_strategy(self, *args, **kwargs):
        return self._try_all("simulate_preset_strategy", *args, **kwargs)

    def final_buy_confirm(self, *args, **kwargs):
        res = self._try_all("final_buy_confirm", *args, **kwargs)
        if res:
            decision, reason = res
            tag = self._get_model_tag()
            return decision, f"{tag} {reason}"
        return False, "All LLM services failed"

    def closing_sell_confirm(self, *args, **kwargs):
        res = self._try_all("closing_sell_confirm", *args, **kwargs)
        if res:
            decision, reason = res
            tag = self._get_model_tag()
            return decision, f"{tag} {reason}"
        return True, "All LLM services failed"

    def compare_stock_superiority(self, *args, **kwargs):
        res = self._try_all("compare_stock_superiority", *args, **kwargs)
        if res:
            superior, sell_code, reason = res
            tag = self._get_model_tag()
            return superior, sell_code, f"{tag} {reason}"
        return False, None, "All LLM services failed"
