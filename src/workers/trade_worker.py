import time
from src.workers.base import BaseWorker
from src.utils import is_market_open

class TradeWorker(BaseWorker):
    def __init__(self, state, api, strategy):
        super().__init__("TRADE", state, interval=1.0)
        self.api = api
        self.strategy = strategy

    def run(self):
        # 시장이 열려있거나 디버그 모드일 때만 작동
        if not self.state.is_kr_market_active and not getattr(self.strategy, "debug_mode", False):
            self.set_result("대기", last_task="장 종료 (매매 대기)")
            return

        # 1. 매매 루프 실행 (VibeStrategy.run_cycle)
        try:
            self.set_busy("매매 검토", friendly_name="TRADE_EXECUTION")
            
            # strategy.run_cycle은 내부적으로 API를 호출하고 로깅함
            # DataManager의 인스턴스를 전달하여 필요한 정보를 참조하게 함
            self.strategy.run_cycle(self.state)
            
            self.set_result("성공", last_task="전략 매매 사이클 수행 완료")
        except Exception as e:
            self.set_result("실패", last_task=f"매매 엔진 오류: {e}")

        # 2. 거래량 폭발/스파이크 감지 (추가 로직)
        # ...
