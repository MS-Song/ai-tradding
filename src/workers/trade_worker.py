import time
from src.workers.base import BaseWorker
from src.utils import is_market_open

class TradeWorker(BaseWorker):
    """매매 전략을 실행하고 실제 주문을 처리하는 실행 워커.
    
    시장이 활성화된 상태에서 주기적으로 `VibeStrategy.run_cycle`을 호출하여 
    보유 종목 관리(익절/손절), 물타기/불타기, AI 자율 매수 등의 매매 로직을 실행합니다.

    Attributes:
        api: 매매 주문 집행을 위한 API 클라이언트.
        strategy: 매매 로직을 포함하는 VibeStrategy(ExecutionMixin) 인스턴스.
    """
    def __init__(self, state, api, strategy):
        """TradeWorker를 초기화합니다.

        Args:
            state (DataManager): 시스템 전역 상태 인스턴스.
            api: 매매 주문 집행을 위한 API 클라이언트.
            strategy (VibeStrategy): 매매 사이클 로직을 포함하는 전략 엔진.
        """
        super().__init__("TRADE", state, interval=1.0)
        self.api = api
        self.strategy = strategy

    def run(self):
        """매매 사이클을 주기적으로 실행합니다.
        
        1. 한국 시장 개장 여부 및 디버그 모드 상태를 확인합니다.
        2. `strategy.run_cycle`을 호출하여 7단계 매매 흐름을 수행합니다.
        3. 수행 결과를 상태 관리자에 보고하여 UI에 표시합니다.
        """
        # 시장이 열려있거나 디버그 모드일 때만 작동
        if not self.state.is_kr_market_active and not getattr(self.strategy, "debug_mode", False):
            # 현재 시간이 장중인데도 active가 False라면 '확인 중'으로 표시
            msg = "장 종료 (매매 대기)" if not is_market_open() else "시장 상태 확인 중..."
            self.set_result("대기", last_task=msg)
            return

        # 1. 매매 루프 실행 (VibeStrategy.run_cycle)
        try:
            self.set_busy("매매 검토", friendly_name="TRADE_EXECUTION")
            
            # strategy.run_cycle은 내부적으로 log_trade()를 호출하여 TUI에 실시간 반영함
            self.strategy.run_cycle(
                market_trend=self.state.vibe.lower(),
                holdings=self.state.holdings,
                asset_info=self.state.asset
            )
            
            self.set_result("성공", last_task="전략 매매 사이클 수행 완료", friendly_name="TRADE_EXECUTION")
        except Exception as e:
            self.set_result("실패", last_task=f"매매 엔진 오류: {e}", friendly_name="TRADE_EXECUTION")

        # 2. 거래량 폭발/스파이크 감지 (추가 로직)
        # ...
