import pytest
from src.strategy.recovery_engine import RecoveryEngine
from src.strategy.pyramiding_engine import PyramidingEngine

@pytest.fixture
def recovery_eng():
    config = {"min_loss_to_buy": -3.0, "average_down_amount": 500000}
    return RecoveryEngine(config)

@pytest.fixture
def pyramiding_eng():
    config = {"min_profit_to_pyramid": 3.0, "average_down_amount": 500000}
    return PyramidingEngine(config)

def test_recovery_engine_trigger(recovery_eng):
    """물타기 트리거 조건 검증"""
    item = {
        "pdno": "005930",
        "prpr": 70000,
        "pchs_avg_pric": 73000,
        "evlu_pfls_rt": -4.1, # 손절선(-5.0)보다 높고 트리거(-3.0)보다 낮음
        "hldg_qty": 10
    }
    # SL이 -5.0일 때, 트리거는 SL + 1.0 = -4.0으로 보정됨.
    # 현재 -4.1이므로 트리거(-4.0) 이하이면서 SL(-5.0) 이상인 구간에 해당하여 발동되어야 함.
    res = recovery_eng.get_recommendation(item, is_panic=False, current_sl=-5.0, vibe="Neutral")
    assert res is not None
    assert res["type"] == "물타기"

def test_recovery_engine_safety_gap(recovery_eng):
    """손절선과 물타기 트리거 사이의 안전 간격(Safety Gap) 검증"""
    item = {
        "pdno": "005930", "prpr": 70000, "pchs_avg_pric": 73000, "evlu_pfls_rt": -4.5
    }
    # 설정이 -3.0이라도 SL이 -5.0이면, 최소 간격 1.0에 의해 -4.0으로 자동 상향 조정됨.
    # 현재 -4.5 < -4.0 이므로 발동되어야 함.
    res = recovery_eng.get_recommendation(item, is_panic=False, current_sl=-5.0)
    assert res is not None

def test_recovery_engine_bear_market(recovery_eng):
    """하락장(BEAR)에서 물타기 간격 확대 검증"""
    item = {
        "pdno": "005930", "prpr": 70000, "pchs_avg_pric": 73000, "evlu_pfls_rt": -4.0
    }
    # BEAR에선 safety_gap이 2.5로 늘어남.
    # SL이 -5.0이면 트리거는 -5.0 + 2.5 = -2.5가 됨.
    # 현재 -4.0 < -2.5 이므로 발동됨.
    res = recovery_eng.get_recommendation(item, is_panic=False, current_sl=-5.0, vibe="Bear")
    assert res is not None

def test_pyramiding_engine_trigger(pyramiding_eng):
    """불타기 트리거 조건 검증 (수익률 + BULL vibe)"""
    item = {
        "pdno": "005930", "prpr": 75000, "pchs_avg_pric": 70000, "evlu_pfls_rt": 7.1
    }
    # BULL 상황에서 수익률 7.1% (트리거 3.0% 이상)
    res = pyramiding_eng.get_recommendation(item, vibe="Bull", is_panic=False, vol_spike=False, tp_threshold=10.0)
    assert res is not None
    assert res["type"] == "불타기"

def test_pyramiding_engine_tp_conflict(pyramiding_eng):
    """익절선(TP)과 불타기 트리거 충돌 방지 검증"""
    item = {
        "pdno": "005930", "prpr": 75000, "pchs_avg_pric": 70000, "evlu_pfls_rt": 4.5
    }
    # 설정은 3.0%이지만, 만약 익절선(TP)이 5.0%라면 불타기 트리거는 TP - 1.0 = 4.0%로 제한됨.
    # 현재 4.5% > 4.0% 이므로 발동되어야 함.
    res = pyramiding_eng.get_recommendation(item, vibe="Bull", is_panic=False, vol_spike=False, tp_threshold=5.0)
    assert res is not None

def test_pyramiding_engine_bear_disable(pyramiding_eng):
    """하락장/방어모드에서 불타기 비활성화 검증"""
    item = {
        "pdno": "005930", "prpr": 75000, "pchs_avg_pric": 70000, "evlu_pfls_rt": 5.0
    }
    # BEAR 모드에선 수익률이 높아도 불타기 안 함
    res = pyramiding_eng.get_recommendation(item, vibe="Bear", is_panic=False, vol_spike=True, tp_threshold=10.0)
    assert res is None
