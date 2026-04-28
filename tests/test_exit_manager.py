import pytest
from src.strategy.exit_manager import ExitManager

def test_exit_manager_base_thresholds():
    """기본 TP/SL 값이 정상적으로 반환되는지 확인"""
    em = ExitManager(base_tp=5.0, base_sl=-5.0)
    # Neutral 상태에서는 보정 없이 5.0, -5.0 (Fee Guard에 의해 TP 1.0 보장되지만 기본이 5.0이므로 유지)
    tp, sl, spike = em.get_thresholds("005930", "NEUTRAL")
    assert tp == 5.0
    assert sl == -5.0
    assert spike is False

def test_exit_manager_vibe_modifiers():
    """시장 분위기(Vibe)에 따른 보정 로직 검증"""
    em = ExitManager(base_tp=5.0, base_sl=-5.0)
    
    # BULL: TP +3.0, SL +1.0 -> 8.0, -4.0
    tp, sl, _ = em.get_thresholds("005930", "BULL")
    assert tp == 8.0
    assert sl == -4.0
    
    # BEAR: TP -2.0, SL -2.0 -> 3.0, -7.0
    tp, sl, _ = em.get_thresholds("005930", "BEAR")
    assert tp == 3.0
    assert sl == -7.0
    
    # DEFENSIVE: TP -3.0, SL -3.0 -> 2.0, -8.0
    tp, sl, _ = em.get_thresholds("005930", "DEFENSIVE")
    assert tp == 2.0
    assert sl == -8.0

def test_exit_manager_vol_spike():
    """거래량 폭발(Vol Spike) 시 TP 상향 검증"""
    em = ExitManager(base_tp=5.0, base_sl=-5.0)
    price_data = {"vol": 1500, "prev_vol": 1000} # 1.5배
    
    tp, sl, spike = em.get_thresholds("005930", "NEUTRAL", price_data=price_data)
    assert tp == 7.0 # 5.0 + 2.0
    assert spike is True

def test_exit_manager_fee_guard():
    """익절가가 수수료 방어선(1.0%) 이하로 내려가지 않는지 확인"""
    em = ExitManager(base_tp=2.0, base_sl=-5.0)
    
    # DEFENSIVE(-3.0) 적용 시 2.0 - 3.0 = -1.0 이 되지만, Fee Guard에 의해 1.0으로 고정되어야 함
    tp, sl, _ = em.get_thresholds("005930", "DEFENSIVE")
    assert tp == 1.0
    assert sl == -8.0

def test_exit_manager_phase_adjustment():
    """시간 페이즈별 보정 로직 검증"""
    em = ExitManager(base_tp=5.0, base_sl=-5.0)
    
    # Phase 1: TP +2.0, SL -1.0 (완화)
    p1_cfg = {"id": "P1", "tp_delta": 2.0, "sl_delta": 1.0}
    tp, sl, _ = em.get_thresholds("005930", "NEUTRAL", phase_cfg=p1_cfg)
    assert tp == 7.0
    assert sl == -4.0 # -5.0 + 1.0

    # 하락장(BEAR)에서는 Phase 1의 SL 완화가 적용되지 않아야 함 (규정상)
    tp, sl, _ = em.get_thresholds("005930", "BEAR", phase_cfg=p1_cfg)
    # BEAR 기본 보정: TP -2.0, SL -2.0 -> 3.0, -7.0
    # P1 TP 보정(+2.0)은 적용되지만 SL 보정(+1.0)은 skip됨
    assert tp == 5.0 # (5-2)+2
    assert sl == -7.0 # ( -5-2 )
