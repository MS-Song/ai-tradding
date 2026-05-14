import time
from src.workers.base import BaseWorker
from src.utils import is_market_open
from src.logger import logger

class TradeWorker(BaseWorker):
    """매매 전략을 실행하고 실제 주문을 처리하는 실행 워커.
    
    시장이 활성화된 상태에서 주기적으로 `VibeStrategy.run_cycle`을 호출하여 
    보유 종목 관리(익절/손절), 물타기/불타기, AI 자율 매수 등의 매매 로직을 실행합니다.

    [v2.1 자동매매 실행 전제조건]
        1. 자동매매(auto_mode)가 ON일 것
        2. 프로그램 시작 후 시장 분석이 최소 1회 완료되었을 것
        2-1. AI 분석 불가 시(셋업 미완료, 오류 등) 타임아웃 후 표준 알고리즘 모드로 전환
        3. 극단 상황(글로벌 패닉, -10% 급락)은 전략 강제 설정 후 실행 (execution.py에서 처리)

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
        self._warmup_start_time = time.time()  # 워밍업 타이머 시작점
        self._warmup_logged = False  # 워밍업 대기 로그 중복 방지
        self._auto_off_logged = False  # 자동매매 OFF 로그 중복 방지
        self.WARMUP_TIMEOUT_SEC = 300  # 최대 워밍업 대기 시간 (5분)

    def run(self):
        """매매 사이클을 주기적으로 실행합니다.
        
        전제조건 체크 순서:
            1. 한국 시장 개장 여부 및 디버그 모드 확인
            2. 자동매매(auto_mode) ON 확인 → OFF면 매매 전면 대기
            3. 시장 분석 1회 이상 완료 확인 → 미완료면 워밍업 대기
            3-1. 타임아웃(5분) 시 표준 알고리즘 모드로 자동 전환
            4. 모든 조건 충족 시 run_cycle 실행
        """
        # 시장이 열려있거나 디버그 모드일 때만 작동
        if not self.state.is_kr_market_active and not getattr(self.strategy, "debug_mode", False):
            # 현재 시간이 장중인데도 active가 False라면 '확인 중'으로 표시
            msg = "장 종료 (매매 대기)" if not is_market_open() else "시장 상태 확인 중..."
            self.set_result("대기", last_task=msg)
            return

        # ──────────────────────────────────────────────────────────
        # [조건 1] 자동매매(auto_mode) ON 확인
        # 자동매매가 꺼져 있으면 손절/익절 포함 모든 자동 매매를 실행하지 않음
        # ──────────────────────────────────────────────────────────
        if not self.strategy.auto_ai_trade:
            if not self._auto_off_logged:
                logger.info("🔒 [자동매매 OFF] 자동 매매 비활성 상태 - 수동 모드로 대기 중")
                self._auto_off_logged = True
            self.set_result("대기", last_task="🔒 자동매매 OFF (수동 모드)", friendly_name="TRADE_EXECUTION")
            return
        
        # 자동매매가 ON으로 전환되면 로그 플래그 리셋
        if self._auto_off_logged:
            self._auto_off_logged = False
            logger.info("✅ [자동매매 ON] 자동 매매 활성화됨")

        # ──────────────────────────────────────────────────────────
        # [조건 2] 시장 분석 1회 이상 완료 대기 (워밍업 가드)
        # AI 분석(VIBE 판정, 전략 수립)이 완료되기 전에
        # 기본 TP/SL 값으로 손절이 실행되는 것을 방지
        # ──────────────────────────────────────────────────────────
        warmup_elapsed = time.time() - self._warmup_start_time
        is_warmup_timeout = warmup_elapsed >= self.WARMUP_TIMEOUT_SEC
        is_analysis_done = self.strategy.first_analysis_attempted
        
        if not is_analysis_done and not is_warmup_timeout:
            if not self._warmup_logged:
                logger.info("⏳ [워밍업] 최초 시황 분석 완료 대기 중... (매매 보류)")
                self._warmup_logged = True
            remaining = int(self.WARMUP_TIMEOUT_SEC - warmup_elapsed)
            self.set_result("대기", last_task=f"⏳ 워밍업 대기 중 (시장 분석 미완료, 잔여 {remaining}초)", friendly_name="TRADE_EXECUTION")
            return
        
        # ──────────────────────────────────────────────────────────
        # [조건 2-1] 타임아웃 시 표준 알고리즘 모드로 자동 전환
        # AI 분석이 불가능한 환경(셋업 미완료, API 오류 등)에서도
        # 저장된 설정값(trading_state.json) 기반으로 안전하게 매매 실행
        # ──────────────────────────────────────────────────────────
        if is_warmup_timeout and not is_analysis_done:
            if not getattr(self, '_standard_mode_logged', False):
                logger.warning(f"⚠️ [표준 모드] AI 분석 타임아웃 ({self.WARMUP_TIMEOUT_SEC}초) → 표준 알고리즘 모드로 전환 (저장된 설정값 사용)")
                self._standard_mode_logged = True

        # ──────────────────────────────────────────────────────────
        # 모든 전제조건 충족 → 매매 사이클 실행
        # ──────────────────────────────────────────────────────────
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
