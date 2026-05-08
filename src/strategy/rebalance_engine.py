import json
import time
from datetime import datetime
from typing import List, Dict, Optional

class RebalanceEngine:
    """포트폴리오 비중 분석 및 리밸런싱 전략 엔진.

    보유 종목의 비중(Weight)과 수익률을 분석하여 AI 어드바이저로부터 
    포트폴리오 최적화(매도/매수/유지) 조언을 수집합니다. 주로 Phase 4(장 마감 전)
    또는 사용자 요청 시 작동합니다.

    Attributes:
        api: 시세 및 잔고 정보 조회를 위한 API 클라이언트.
        ai_advisor: 리밸런싱 전략 수립을 위한 AI 분석 엔진.
        rebalance_advice (str): 마지막으로 수립된 리밸런싱 조언 내용.
        last_check_time (float): 마지막 분석 수행 시각 (timestamp).
        check_interval (int): 자동 분석 주기 (초 단위).
    """
    
    def __init__(self, api, ai_advisor):
        """RebalanceEngine을 초기화합니다.

        Args:
            api: 시세 및 잔고 정보 조회를 위한 API 클라이언트 인스턴스.
            ai_advisor: 포트폴리오 분석 및 리밸런싱 조언을 담당하는 AI 어드바이저.
        """
        self.api = api
        self.ai_advisor = ai_advisor
        self.rebalance_advice = ""
        self.last_check_time = 0
        self.check_interval = 3600 * 24 # 기본 1일 1회 (유저 요청에 따라 유동적)

    def analyze_and_suggest(self, holdings: List[dict], total_asset: float, force=False) -> Optional[str]:
        """현재 포트폴리오를 분석하여 AI 리밸런싱 제안을 생성합니다.

        보유 종목의 평가 금액을 기준으로 자산 내 비중을 계산하고,
        수익률 데이터를 포함하여 AI에게 전달함으로써 종목 교체나 비중 조절 의견을 구합니다.

        Args:
            holdings (List[dict]): 현재 보유 종목 리스트.
            total_asset (float): 총 자산 가치.
            force (bool): 분석 주기와 무관하게 즉시 분석을 수행할지 여부.

        Returns:
            Optional[str]: 생성된 AI 리밸런싱 제안 텍스트.
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

        # 2. AI 리밸런싱 조언 요청 (Advisor 인터페이스 사용)
        advice = self.ai_advisor.get_rebalance_advice(portfolio_summary)
        
        if advice:
            self.rebalance_advice = advice.strip()
            self.last_check_time = now
            return self.rebalance_advice
        
        return "AI 분석 실패로 리밸런싱 제안을 생성할 수 없습니다."

    def get_advice(self):
        """마지막으로 생성된 리밸런싱 조언을 반환합니다.

        Returns:
            str: 리밸런싱 조언 텍스트.
        """
        return self.rebalance_advice if self.rebalance_advice else "아직 리밸런싱 분석이 수행되지 않았습니다."
