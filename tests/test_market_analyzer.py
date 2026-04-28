import pytest
from unittest.mock import MagicMock
from src.strategy.market_analyzer import MarketAnalyzer

@pytest.fixture
def mock_api():
    api = MagicMock()
    # 기본 지수 데이터 설정
    api.get_multiple_index_prices.return_value = {
        "KOSPI": {"name": "KOSPI", "price": 2500.0, "rate": 0.0},
        "KOSDAQ": {"name": "KOSDAQ", "price": 800.0, "rate": 0.0},
        "VOSPI": {"name": "VOSPI", "price": 15.0, "rate": 0.0},
        "BTC_USD": {"name": "BTC_USD", "price": 60000.0, "rate": 0.0}
    }
    return api

@pytest.fixture
def mock_indicator_eng():
    eng = MagicMock()
    return eng

def test_market_analyzer_circuit_breaker_vix(mock_api):
    """VIX(VOSPI) 지수에 따른 DEFENSIVE 전환 확인"""
    analyzer = MarketAnalyzer(mock_api)
    mock_api.get_multiple_index_prices.return_value["VOSPI"] = {"price": 26.0, "rate": 6.0}
    
    vibe, is_panic = analyzer.update()
    assert vibe == "DEFENSIVE"

def test_market_analyzer_circuit_breaker_btc(mock_api):
    """비트코인 폭락 시 DEFENSIVE 전환 확인"""
    analyzer = MarketAnalyzer(mock_api)
    mock_api.get_multiple_index_prices.return_value["BTC_USD"] = {"price": 55000.0, "rate": -5.5}
    
    vibe, is_panic = analyzer.update()
    assert vibe == "DEFENSIVE"

def test_market_analyzer_bull_vibe(mock_api, mock_indicator_eng):
    """상승장(Bull) 판정 로직 검증 (지수 상승 + DEMA 지지)"""
    analyzer = MarketAnalyzer(mock_api, mock_indicator_eng)
    
    # 지수 0.6% 상승
    mock_api.get_multiple_index_prices.return_value["KOSPI"] = {"rate": 0.6}
    mock_api.get_multiple_index_prices.return_value["KOSDAQ"] = {"rate": 0.6}
    
    # DEMA 지지 (현재가 > DEMA)
    mock_api.get_index_chart_price.return_value = [{"stck_clpr": "2500"}] * 40
    mock_indicator_eng.calculate_dema.return_value = 2400.0 # 현재가(2500) > DEMA(2400)
    
    vibe, _ = analyzer.update()
    assert vibe == "Bull"

def test_market_analyzer_bear_vibe(mock_api, mock_indicator_eng):
    """하락장(Bear) 판정 로직 검증 (지수 하락 + DEMA 저항)"""
    analyzer = MarketAnalyzer(mock_api, mock_indicator_eng)
    
    # 지수 0.6% 하락
    mock_api.get_multiple_index_prices.return_value["KOSPI"] = {"rate": -0.6}
    mock_api.get_multiple_index_prices.return_value["KOSDAQ"] = {"rate": -0.6}
    
    # DEMA 저항 (현재가 < DEMA)
    mock_api.get_index_chart_price.return_value = [{"stck_clpr": "2500"}] * 40
    mock_indicator_eng.calculate_dema.return_value = 2600.0 # 현재가(2500) < DEMA(2600)
    
    vibe, _ = analyzer.update()
    assert vibe == "Bear"

def test_market_analyzer_global_panic(mock_api):
    """글로벌 패닉 트리거 검증 (나스닥 -1.5% 이하)"""
    analyzer = MarketAnalyzer(mock_api)
    mock_api.get_multiple_index_prices.return_value["NASDAQ"] = {"rate": -1.6}
    
    # 데이터를 채우기 위해 update() 호출 필요
    analyzer.update()
    
    is_panic = analyzer._check_global_panic()
    assert is_panic is True
