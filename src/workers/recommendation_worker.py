import time
from src.workers.base import BaseWorker
from src.utils import is_market_open
from src.logger import logger

class RecommendationRecoveryWorker(BaseWorker):
    """추세 데이터 누락으로 인해 수동 전용으로 전환된 추천 종목들을 주기적으로 재검토하여 
    자동 매수 모드로 복구하는 워커. (1분 주기)
    """
    def __init__(self, state, api, strategy, dm=None):
        super().__init__("REC_RECOVERY", state, interval=60.0) # 1분 주기
        self.api = api
        self.strategy = strategy
        self.dm = dm

    def run(self):
        """1분마다 수동 추천 종목들의 추세를 재분석합니다."""
        # 시장이 열려있거나 디버그 모드일 때만 작동
        if not self.state.is_kr_market_active and not getattr(self.strategy, "debug_mode", False):
            return

        # 자동 매수 모드가 켜져 있을 때만 의미가 있음
        if not self.strategy.auto_ai_trade:
            return

        try:
            self.set_busy("추세 재검토")
            # AnalysisMixin에 구현된 재검토 로직 호출
            self.strategy.reevaluate_manual_recommendations(dm=self.dm)
            self.set_result("성공", last_task="추천 종목 추세 재검토 완료")
        except Exception as e:
            logger.error(f"RecommendationRecoveryWorker Error: {e}")
            self.set_result("실패", last_task=f"재검토 오류: {e}")
