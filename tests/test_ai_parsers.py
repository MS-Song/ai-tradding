import pytest
from unittest.mock import MagicMock
from src.strategy.advisors.base import BaseLLMAdvisor

class DummyAdvisor(BaseLLMAdvisor):
    """테스트를 위한 최소 구현체"""
    def _call_api(self, prompt: str, timeout: int = 60):
        return self.mock_response

    def get_advice(self, *args, **kwargs): pass
    def get_detailed_report_advice(self, *args, **kwargs): pass
    def get_stock_report_advice(self, *args, **kwargs): pass
    def get_holdings_report_advice(self, *args, **kwargs): pass
    def get_hot_stocks_report_advice(self, *args, **kwargs): pass

    def verify_market_vibe(self, *args, **kwargs): pass
    def closing_sell_confirm(self, *args, **kwargs): pass
    def get_rebalance_advice(self, *args, **kwargs): pass
    def compare_stock_superiority(self, *args, **kwargs): pass
    def analyze_trade_retrospective(self, *args, **kwargs): pass

@pytest.fixture
def advisor():
    api = MagicMock()
    return DummyAdvisor(api, "test-model")

def test_parse_simulate_preset_strategy(advisor):
    """AI 프리셋 전략 응답 파싱 검증"""
    # 표준 형식
    advisor.mock_response = "전략번호:03, 익절:+5.5%, 손절:-3.2%, 유효시간:120분, 근거:추세 지지 확인"
    res = advisor.simulate_preset_strategy("005930", "삼성전자", "Bull")
    assert res["preset_id"] == "03"
    assert res["tp"] == 5.5
    assert res["sl"] == -3.2
    assert res["lifetime_mins"] == 120

    # 비표준 형식 (볼드체, 띄어쓰기 등)
    advisor.mock_response = "**전략번호**: 07\n**익절**: +8.0%\n**손절**: -4.0%\n**유효시간**: 60분\n**근거**: 급등주 포착"
    res = advisor.simulate_preset_strategy("005930", "삼성전자", "Bull")
    assert res["preset_id"] == "07"
    assert res["tp"] == 8.0
    assert res["sl"] == -4.0
    assert res["lifetime_mins"] == 60

def test_parse_final_buy_confirm(advisor):
    """AI 최종 매수 컨펌 응답 파싱 검증"""
    detail = {"price": "70000"}
    
    # 긍정 응답 (Yes)
    advisor.mock_response = "결정: Yes, 사유: 이평선 지지 및 수급 개선 확인"
    decision, reason = advisor.final_buy_confirm("005930", "삼성전자", "Bull", detail, [])
    assert decision is True
    assert "지지" in reason

    # 부정 응답 (No)
    advisor.mock_response = "결정: No, 사유: 과매수 구간 및 거래량 부족"
    decision, reason = advisor.final_buy_confirm("005930", "삼성전자", "Bull", detail, [])
    assert decision is False
    assert "과매수" in reason

    # 한글 응답 (예/아니오)
    advisor.mock_response = "결정: 예, 사유: 강력한 모멘텀"
    decision, _ = advisor.final_buy_confirm("005930", "삼성전자", "Bull", detail, [])
    assert decision is True

def test_parse_portfolio_review_json(advisor):
    """포트폴리오 배치 리뷰 JSON 응답 파싱 검증"""
    # BaseLLMAdvisor의 get_portfolio_strategic_review 로직 테스트
    advisor.mock_response = """
    아래는 분석 결과입니다.
    ```json
    {
      "005930": {
        "action": "HOLD",
        "preset_id": "01",
        "tp": 5.0,
        "sl": -3.0,
        "lifetime": 60,
        "reason": "추세 유지"
      },
      "000660": {
        "action": "SELL",
        "reason": "데드크로스 발생"
      }
    }
    ```
    참고하세요.
    """
    res = advisor.get_portfolio_strategic_review([{"code":"005930", "name":"삼성전자", "rt":1.0}], "Bull", {})
    assert res is not None
    assert res["005930"]["action"] == "HOLD"
    assert res["000660"]["action"] == "SELL"
