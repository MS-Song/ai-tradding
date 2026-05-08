import os
import time
import sys
import io
import select
import atexit
import threading
from datetime import datetime
from dotenv import load_dotenv

from src.config_init import ensure_env, get_config
from src.auth import KISAuth
from src.api import KISAPI
from src.strategy import VibeStrategy
from src.utils import *
from src.data_manager import DataManager
from src.ui.renderer import draw_tui
from src.ui.interaction import perform_interaction

def main():
    """KIS-Vibe-Trader의 메인 엔트리 포인트입니다.

    시스템 초기화(설정, 인증, API, 전략), 데이터 매니저를 통한 백그라운드 워커 구동, 
    TUI(터미널 UI) 렌더링 루프 및 사용자 키 입력 처리를 통합적으로 제어합니다.
    """
    ensure_env(); load_dotenv(); config = get_config(); init_terminal()
    auth = KISAuth(); api = KISAPI(auth); strategy = VibeStrategy(api, config)
    
    dm = DataManager(api, strategy)
    auth.on_error_message = lambda msg: dm.show_status(msg, is_error=True)
    
    enter_alt_screen()
    
    # [안전장치] TUI 실행 중 백그라운드 스레드의 의도치 않은 print()가 화면을 깨뜨리지 않도록
    # sys.stdout을 안전 래퍼로 교체: ESC 시퀀스(\033[H 등)를 포함한 TUI 전용 출력만 허용하고
    # 그 외의 텍스트 출력(print 등)은 error.log로 우회합니다.
    import logging as _logging
    _safe_real_stdout = sys.stdout
    class _SafeStdout:
        """TUI 실행 중 ANSI 제어 코드 없는 일반 print() 출력을 가로채서 로그로 리디렉션하여 화면을 보호합니다."""
        def write(self, text):
            """텍스트 출력을 가로채서 필터링합니다. 
            
            ANSI 이스케이프 코드가 포함된 TUI 전용 출력은 허용하고, 
            그 외의 일반 텍스트(print 등)는 로거로 리디렉션합니다.
            """
            # ANSI 이스케이프 코드 포함 또는 빈 문자열이면 실제 출력 (TUI 렌더러 정상 동작 허용)
            # dm.is_full_screen_active(셋업 모드 등)인 경우에도 실제 출력 허용
            if not text or '\033[' in text or text in ('\n', '\r', '\r\n') or dm.is_full_screen_active:
                _safe_real_stdout.write(text)
            else:
                # 일반 print() 출력 → error.log로 리디렉션 (TUI 화면 보호)
                stripped = text.strip()
                if stripped:
                    _logging.getLogger("VibeTrader").error(f"[STDOUT 캡처] {stripped}")
        def flush(self):
            """버퍼를 비웁니다."""
            _safe_real_stdout.flush()
        def fileno(self):
            """파일 디스크립터 번호를 반환합니다."""
            return _safe_real_stdout.fileno()
        # TextIOWrapper 호환용 속성
        @property
        def encoding(self):
            """인코딩 정보를 반환합니다."""
            return getattr(_safe_real_stdout, 'encoding', 'utf-8')
        @property
        def errors(self):
            """에러 핸들링 방식을 반환합니다."""
            return getattr(_safe_real_stdout, 'errors', 'replace')
    sys.stdout = _SafeStdout()
    
    dm.start_workers(auth.is_virtual)
    set_terminal_raw()
    try:
        cycle = 0
        _command_busy = False  # 키 중복 처리 방지 플래그
        _tui_tick = 0          # TUI 렌더링 주기 제어 카운터
        while True:
            cycle += 1
            if not auth.is_token_valid(): auth.generate_token()
            
            # 주기적 시황 분석 스케줄러 (실전 20분 / 모의 60분 정책 준수)
            is_v = getattr(strategy.api.auth, 'is_virtual', True)
            interval = 20 if not is_v else 60
            if not strategy.is_analyzing and (time.time() - strategy.last_market_analysis_time) > (interval * 60):
                threading.Thread(target=strategy.run_scheduled_analysis, args=(dm,), daemon=True).start()
            
            # 5초 = 100 tick × 0.05s / TUI는 10tick(0.5s)마다 1번 렌더링
            for i in range(100):
                # 전체 화면 모드일 때는 메인 TUI 렌더링 및 키 입력 건너뜀
                if dm.is_full_screen_active:
                    time.sleep(0.05)
                    continue

                # TUI 렌더링: 0.5초 주기 유지 (10 tick 마다)
                _tui_tick += 1
                if _tui_tick % 10 == 0:
                    # 모의거래 환경용 데이터 무결성 검증
                    is_valid = True
                    if strategy.mock_tester.is_active:
                        tui_data = {
                            "vibe": dm.vibe,
                            "holdings": dm.cached_holdings,
                            "asset": dm.cached_asset
                        }
                        is_valid = strategy.mock_tester.validate_tui_data(tui_data)
                    
                    if is_valid:
                        draw_tui(strategy, dm, cycle)
                
                # 키 입력 감지 (0.05s 주기로 즉시 반응)
                k = get_key_immediate()
                # q / Q / ㅂ / ㅃ 모든 종료 키 즉시 반응
                if k and k.lower() in ['q', 'ㅂ', 'ㅃ']:
                    dm.shutdown("사용자 종료") # 텔레그램 종료 알림 발송
                    try: tw = os.get_terminal_size().columns
                    except: tw = 110
                    # TUI 정지 및 화면 청소 후 종료 알림
                    sys.stdout = _safe_real_stdout
                    restore_terminal_settings(); exit_alt_screen()
                    sys.stdout.write("\033[H\033[2J" + align_kr(" 시스템을 안전하게 종료합니다. 잠시만 기다려주세요... ", tw, 'center') + "\n")
                    sys.stdout.flush()
                    time.sleep(1)
                    os._exit(0)
                elif k and not dm.is_input_active:
                    # 유효한 명령어 키인지 확인
                    valid_cmds = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'd', 'h', 'l', 'm', 's', 'p', 'u', 'k', 'ㅔ', 'ㅖ', 'ㅏ']
                    if k.lower() not in valid_cmds:
                        continue

                    # 커맨드 처리 중 중복 키 차단
                    if _command_busy:
                        pass
                    else:
                        _command_busy = True
                        dm.show_status(f"⏳ [{k.upper()}] 동작 준비 중...")
                        draw_tui(strategy, dm, cycle)
                        def _run_cmd(key=k):
                            nonlocal _command_busy
                            try:
                                # 매매 로직 실행 전 busy 체크 (GLOBAL 작업 중이 아닌 경우에만 실행)
                                if not dm.is_blocking_busy():
                                    perform_interaction(key, api, strategy, dm, cycle)
                            finally:
                                _command_busy = False
                                # 동작이 끝났을 때 '준비 중' 메시지가 남아있으면 제거 (다른 상태 메시지가 없는 경우만)
                                if "준비 중" in dm.status_msg:
                                    dm.show_status("")
                        threading.Thread(target=_run_cmd, daemon=True).start()
                
                time.sleep(0.05)
    except KeyboardInterrupt: 
        dm.is_running = False
    finally: 
        dm.is_running = False
        sys.stdout = _safe_real_stdout
        restore_terminal_settings(); exit_alt_screen()

if __name__ == "__main__":
    main()
