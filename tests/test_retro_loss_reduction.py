import pytest
import time
from datetime import datetime, time as dtime
from unittest.mock import MagicMock, patch
from src.strategy.risk_manager import RiskManager
from src.strategy.exit_manager import ExitManager
from src.utils import get_now
from tests.test_advanced_integration import MockStrategy

class TestRetroLossReduction:
    """[복기반영 #6] 손해 축소 5대 핵심 전략 단위 테스트"""

    def test_hard_cap_calculation_in_risk_manager(self):
        """[솔루션 2] RiskManager 단일 종목 투자금 하드캡 (10% / 800만원) 검증"""
        api = MagicMock()
        rm = RiskManager(api, config={"max_stock_inv_rate": 0.10, "max_stock_inv_cap": 8000000.0})
        
        # 1. 총자산 1.2억원일 때: 10%는 1200만원이지만 800만원 상한선 적용
        cap_1 = rm.get_max_investment_per_stock(120000000.0)
        assert cap_1 == 8000000.0

        # 2. 총자산 5000만원일 때: 10%인 500만원 적용 (800만원 미만이므로 10% 적용)
        cap_2 = rm.get_max_investment_per_stock(50000000.0)
        assert cap_2 == 5000000.0

        # 3. 총자산 300만원일 때: 최소 50만원 보장
        cap_3 = rm.get_max_investment_per_stock(3000000.0)
        assert cap_3 == 500000.0

    def test_opening_gap_guard_sl_buffer_in_exit_manager(self):
        """[솔루션 1] 09:00~09:15 오프닝 갭 가드 시초가 노이즈 SL 1.0% 완화 버퍼 검증"""
        em = ExitManager(base_tp=5.0, base_sl=-5.0)
        
        # P1 일반 상황 (09:15 이후)
        p1_normal = {"id": "P1", "tp_delta": 2.0, "sl_delta": -1.0, "is_opening_gap_guard": False}
        tp1, sl1, _ = em.get_thresholds("005930", "BULL", phase_cfg=p1_normal)
        
        # P1 시초가 노이즈 구간 (09:00~09:15)
        p1_gap_guard = {"id": "P1", "tp_delta": 2.0, "sl_delta": -1.0, "is_opening_gap_guard": True}
        tp2, sl2, _ = em.get_thresholds("005930", "BULL", phase_cfg=p1_gap_guard)
        
        # 손절선이 1.0% 추가 완화되어 시초 노이즈 털림을 방어해야 함
        assert sl2 == sl1 - 1.0

    def test_opening_gap_guard_freezes_autonomous_buys(self):
        """[솔루션 1] 09:00~09:20 오프닝 갭 가드 동안 신규 자율 매수 동결 검증"""
        strategy = MockStrategy()
        strategy.ai_recommendations = [{"code": "005930", "name": "삼성전자", "score": 90.0, "price": 70000}]
        strategy.get_market_phase = MagicMock(return_value={"id": "P1", "is_stabilizing": True})
        
        strategy.api.order_market.reset_mock()
        results = strategy.run_cycle(holdings=[], asset_info={"total_asset": 10000000, "cash": 5000000})
        
        # 신규 매수 주문이 전혀 나가지 않고 보류 메시지가 기록되어야 함
        strategy.api.order_market.assert_not_called()
        assert any("오프닝 갭 가드" in r for r in results)

    def test_daily_ticker_sl_lock(self):
        """[솔루션 3] 당일 동일 종목 2회 손절 시 당일 매수 차단 검증"""
        strategy = MockStrategy()
        today = get_now().strftime('%Y-%m-%d')
        strategy.last_sl_date = today
        strategy.daily_ticker_sl_count = {"005930": 2} # 당일 2회 손절 발생
        strategy.ai_recommendations = [{"code": "005930", "name": "삼성전자", "score": 95.0, "price": 70000, "rate": 1.0}]
        strategy.get_market_phase = MagicMock(return_value={"id": "P2", "is_stabilizing": False})
        
        strategy.api.order_market.reset_mock()
        results = strategy.run_cycle(holdings=[], asset_info={"total_asset": 10000000, "cash": 5000000})
        
        # 2회 손절된 종목은 매수가 차단되어야 함
        strategy.api.order_market.assert_not_called()

    def test_trailing_stop_trigger(self):
        """[솔루션 4] +3.0% 돌파 후 고점 대비 1.0%p 밀릴 때 트레일링 스탑 매도 검증"""
        strategy = MockStrategy()
        today = get_now().strftime('%Y-%m-%d')
        strategy.last_sl_date = today
        strategy.boot_time = time.time() - 3600 # 부트 초기 보호 해제
        strategy.get_market_phase = MagicMock(return_value={"id": "P2", "is_stabilizing": False})
        strategy.exit_mgr.base_tp = 10.0 # 기본 익절 10%
        strategy.exit_mgr.base_sl = -5.0
        
        # 1. +4.5% 최고점 기록
        strategy.max_profit_rates = {"005930": 4.5}
        
        # 2. 현재 수익률이 3.2%로 고점(4.5%) 대비 1.3%p 밀린 상황
        holdings = [{"pdno": "005930", "prdt_name": "삼성전자", "evlu_pfls_rt": 3.2, "hldg_qty": 10, "prpr": 70000, "pchs_avg_pric": 67800}]
        
        strategy.api.order_market.reset_mock()
        results = strategy.run_cycle(holdings=holdings, asset_info={"total_asset": 10000000, "cash": 5000000})
        
        # 트레일링스탑 전량 매도가 호출되어야 함
        strategy.api.order_market.assert_called_with("005930", 10, False)
        assert any("트레일링스탑" in r for r in results)

    def test_bear_negative_rate_filter_in_alpha_engine(self):
        """[솔루션 5] Bear 장세에서 음봉 낙주 종목 auto_eligible=False 필터링 검증"""
        from src.strategy.alpha_engine import VibeAlphaEngine
        api = MagicMock()
        alpha = VibeAlphaEngine(api)
        
        # 음봉 종목 (등락률 -3.5%)
        neg_item = {"code": "005930", "name": "삼성전자", "rate": -3.5, "price": 70000}
        themes = [{"name": "반도체", "count": 5}]
        
        api.get_naver_stocks_realtime.return_value = {}
        api.get_naver_stock_detail.return_value = {"market_cap": 3000000, "pbr": 1.0, "per": 10.0}
        api.get_investor_trading_trend.return_value = {"frgn_net_buy": 0, "inst_net_buy": 0, "pnsn_net_buy": 0, "thst_net_buy": 0}
        
        res = alpha.analyze(themes, [neg_item], [], kr_vibe="BEAR")
        for item in res:
            if item['code'] == "005930":
                # 하락장에서 음봉 낙주 종목은 자동 매수가 비활성화되어야 함
                assert item.get('auto_eligible') is False

    def test_sl_guard_minimum_margin_floor(self):
        """[하위종목 방어 1] SL Guard 상한선 -2.5% 안전마진 강제 확보 검증"""
        em = ExitManager(base_tp=5.0, base_sl=-5.0)
        # 방어모드(sl_mod=3.0) + P2(sl_delta=1.0) -> 원래대로면 -5.0 + 3.0 + 1.0 = -1.0%로 극단 타이트해짐
        p2 = {"id": "P2", "tp_delta": -1.0, "sl_delta": 1.0}
        _, sl, _ = em.get_thresholds("005930", "DEFENSIVE", phase_cfg=p2)
        # SL Guard에 의해 -1.0%가 아닌 최소 -2.5%의 안전마진이 확보되어야 함
        assert sl == -2.5

    def test_new_buy_noise_grace_period(self):
        """[하위종목 방어 2] 신규 매수 후 10분(600초) 이내 호가 노이즈 손절 유예 검증"""
        strategy = MockStrategy()
        cur_t = strategy.mock_tester.get_now().timestamp()
        # 3분(180초) 전에 매수한 종목
        strategy.last_buy_times["005930"] = cur_t - 180
        strategy.last_sell_times["005930"] = cur_t - 7200
        # 현재 수익률 -3.0% (SL -2.5% 터치)
        holdings = [{"pdno": "005930", "prdt_name": "삼성전자", "evlu_pfls_rt": -3.0, "hldg_qty": 10, "prpr": 67900, "pchs_avg_pric": 70000}]
        strategy.exit_mgr.base_sl = -2.5
        strategy.api.order_market.reset_mock()

        results = strategy.run_cycle(holdings=holdings, asset_info={"total_asset": 10000000, "cash": 5000000})

        # 10분 이내이므로 기계적 손절이 나가지 않고 초단기 보호가 발동해야 함
        strategy.api.order_market.assert_not_called()
        assert any("초단기 보호" in r for r in results)

    def test_dust_trading_prevention(self):
        """[하위종목 방어 3] 자투리 1주 매매(Dust Trading) 전면 차단 검증"""
        strategy = MockStrategy()
        # 총자산 1,000만원, 가용 현금 3만원 (최소 주문 Floor 30만원에 미달)
        asset_info = {"total_asset": 10000000, "cash": 30000}
        # 주가 25,000원 종목 (과거엔 현금 3만원으로 1주를 억지 매수했었음)
        strategy.ai_recommendations = [{"code": "005930", "name": "삼성전자", "score": 90.0, "price": 25000, "rate": 1.0}]
        strategy.get_market_phase = MagicMock(return_value={"id": "P2", "is_stabilizing": False})
        strategy.api.order_market.reset_mock()

        results = strategy.run_cycle(holdings=[], asset_info=asset_info)

        # 억지 1주 매수가 차단되어 주문이 실행되지 않아야 함
        strategy.api.order_market.assert_not_called()

    def test_low_liquidity_trading_value_filter(self):
        """[하위종목 방어 4] 거래대금 30억 미만 소외주 자동 매수 배제 검증"""
        from src.strategy.alpha_engine import VibeAlphaEngine
        api = MagicMock()
        alpha = VibeAlphaEngine(api)

        # 거래대금 15억원(1,500백만)인 소외주
        low_liq_item = {"code": "005930", "name": "소외주", "rate": 2.0, "price": 10000, "amt": 1500}
        themes = [{"name": "테마", "count": 3}]

        api.get_naver_stocks_realtime.return_value = {}
        api.get_naver_stock_detail.return_value = {"market_cap": 2000000, "pbr": 1.0, "per": 10.0, "amt": 1500}
        api.get_investor_trading_trend.return_value = {"frgn_net_buy": 0, "inst_net_buy": 0, "pnsn_net_buy": 0, "thst_net_buy": 0}

        res = alpha.analyze(themes, [low_liq_item], [], kr_vibe="NEUTRAL")
        for item in res:
            if item['code'] == "005930":
                # 거래대금 30억 미만 소외주는 슬리피지 방어를 위해 auto_eligible이 False여야 함
                assert item.get('auto_eligible') is False

    def test_retrospective_overall_summary_collection(self):
        """[하위종목 방어 5] RetrospectiveEngine 전체 매매 수수료 및 종합 통계 집계 검증"""
        from src.strategy.retrospective_engine import RetrospectiveEngine
        from src.logger import trading_log

        today = get_now().strftime('%Y-%m-%d')
        # 임의 거래 데이터 주입
        with trading_log.lock:
            trading_log.data["trades"] = [
                {"time": f"{today} 09:30:00", "code": "A", "name": "A사", "type": "익절", "profit": 50000, "price": 10000, "qty": 10},
                {"time": f"{today} 10:00:00", "code": "B", "name": "B사", "type": "손절", "profit": -30000, "price": 20000, "qty": 5},
                {"time": f"{today} 11:00:00", "code": "C", "name": "하위종목", "type": "손절", "profit": -15000, "price": 5000, "qty": 10},
            ]

        retro = RetrospectiveEngine(api=MagicMock())
        top_p, top_l, summary = retro.get_daily_top_trades(today, return_summary=True)

        assert summary["total_trades"] == 3
        assert summary["total_realized_profit"] == 5000.0  # 50000 - 30000 - 15000
        assert summary["est_fees_and_taxes"] > 0
        assert summary["dust_trade_count"] == 3  # 모두 30만원 미만 거래

