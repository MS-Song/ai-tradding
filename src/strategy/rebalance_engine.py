import json
import time
from datetime import datetime
from typing import List, Dict, Optional

class RebalanceEngine:
    """포트폴리오 비중 분석 및 리밸런싱 전략 엔진 ([Phase 4])"""
    
    def __init__(self, api, ai_advisor):
        self.api = api
        self.ai_advisor = ai_advisor
        self.rebalance_advice = ""
        self.last_check_time = 0
        self.check_interval = 3600 * 24 # 기본 1일 1회 (유저 요청에 따라 유동적)

    def analyze_and_suggest(self, holdings: List[dict], total_asset: float, force=False) -> Optional[str]:
        """
        현재 포트폴리오를 분석하여 AI 리밸런싱 제안을 생성합니다.
        """
        now = time.time()
        if not force and now - self.last_check_time < self.check_interval:
            return self.rebalance_advice

        if not holdings:
            self.rebalance_advice = "보유 종목이 없어 리밸런싱이 필요하지 않습니다."
            self.last_check_time = now
            return self.rebalance_advice

        # 1. 포트폴리오 데이터 요약 (비중 및 수익률)
        portfolio_summary = []
        for h in holdings:
            eval_amt = float(h.get('evlu_amt', 0))
            weight = (eval_amt / total_asset * 100) if total_asset > 0 else 0
            portfolio_summary.append({
                "code": h.get('pdno'),
                "name": h.get('prdt_name'),
                "weight": f"{weight:.1f}%",
                "profit": f"{h.get('evlu_pfls_rt', 0)}%"
            })

        # 2. AI 리밸런싱 프롬프트 구성
        prompt = f"""
        당신은 포트폴리오 전략가입니다. 아래 포트폴리오의 비중과 수익률을 보고 리밸런싱 제안을 하세요.
        [포트폴리오 데이터]
        {json.dumps(portfolio_summary, ensure_ascii=False)}
        
        [가이드라인]
        - 특정 종목 비중이 30% 이상이면 리스크 분산을 위해 비중 축소 제안.
        - 수익률 15% 이상 종목은 부분 익절 후 저평가주 교체 제안.
        - 성과가 저조한 종목 중 비중이 큰 종목은 과감한 리밸런싱 제안.
        
        [답변 형식]
        - 3줄 이내로 간결하게 핵심만 한국어로 기술.
        - '~하는 것을 권장합니다' 체 사용.
        """

        advice = self.ai_advisor._safe_gemini_call(prompt)
        if advice:
            self.rebalance_advice = advice.strip()
            self.last_check_time = now
            return self.rebalance_advice
        
        return "AI 분석 실패로 리밸런싱 제안을 생성할 수 없습니다."

    def get_advice(self):
        return self.rebalance_advice if self.rebalance_advice else "아직 리밸런싱 분석이 수행되지 않았습니다."
