import time
import json
from datetime import datetime, timedelta
from src.logger import logger

class MockTradingTester:
    """
    모의거래 환경 전용 자동화 테스트 서포터
    1. TUI 데이터 무결성 체크
    2. 가상 시간 주입 (Time-travel)
    3. 주문 드라이런 (Dry-run)
    """
    def __init__(self, strategy):
        self.strategy = strategy
        self.is_active = self._check_mock_env()
        self.virtual_time_offset = 0  # 초 단위 시간 오프셋
        self.dry_run_enabled = False
        
        if self.is_active:
            logger.info("🧪 [MOCK_TESTER] 모의거래 환경 감지 - 자가 진단 모드 활성화")

    def _check_mock_env(self):
        """API 키 또는 설정을 통해 모의거래 여부 확인"""
        # [수정] KIS API의 auth.is_virtual 속성을 우선 확인
        api = self.strategy.api
        is_mock = False
        
        if hasattr(api, 'auth') and hasattr(api.auth, 'is_virtual'):
            is_mock = api.auth.is_virtual
        
        # 보조 수단: 설정 파일 기반 확인
        if not is_mock:
            is_mock = self.strategy.base_config.get("is_paper_trading", False)
            
        return is_mock

    def get_now(self):
        """가상 시간이 적용된 현재 시간 반환"""
        if not self.is_active or self.virtual_time_offset == 0:
            return datetime.now()
        return datetime.now() + timedelta(seconds=self.virtual_time_offset)

    def warp_to_phase(self, phase_id: str):
        """특정 페이즈 시점(예: P4 장마감)으로 시간을 워프"""
        if not self.is_active: return
        
        now = datetime.now()
        target_time = now
        if phase_id == "P4":
            target_time = now.replace(hour=15, minute=15, second=0)
        elif phase_id == "P3":
            target_time = now.replace(hour=14, minute=35, second=0)
            
        self.virtual_time_offset = (target_time - now).total_seconds()
        logger.info(f"⏰ [TIME_WARP] 시간을 {phase_id} 시점({target_time.strftime('%H:%M')})으로 이동합니다.")

    def validate_tui_data(self, data: dict):
        """TUI에 표시될 데이터의 무결성을 실시간 검증 (가시화 전 단계)"""
        if not self.is_active: return
        
        try:
            # 필수 데이터 누락 체크
            required_keys = ['vibe', 'holdings', 'asset']
            missing = [k for k in required_keys if k not in data]
            if missing:
                logger.error(f"❌ [TUI_VALIDATE] 데이터 누락 감지: {missing}")
                return False
            
            # 비정상 수치 체크 (예: 0원 수익률이 너무 많거나 데이터가 비어있는지)
            if len(data['holdings']) > 0 and all(h.get('prpr') == 0 for h in data['holdings']):
                logger.error("❌ [TUI_VALIDATE] 모든 보유 종목 가격이 0원으로 표시됨 (데이터 무결성 오류)")
                return False
                
            return True
        except Exception as e:
            logger.error(f"❌ [TUI_VALIDATE] 검증 중 오류: {e}")
            return False

    def intercept_order(self, code, qty, is_buy):
        """주문 실행 전 가로채기 (Dry-run)"""
        if self.is_active and self.dry_run_enabled:
            side = "매수" if is_buy else "매도"
            logger.info(f"🛡️ [DRY_RUN] 주문 실행 차단: {code} | {qty}주 | {side} (가상 체결 처리)")
            return True, "DRY_RUN_SUCCESS"
        return None  # None 반환 시 실제 주문 진행
