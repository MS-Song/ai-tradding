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
    ensure_env(); load_dotenv(); config = get_config(); init_terminal()
    auth = KISAuth(); api = KISAPI(auth); strategy = VibeStrategy(api, config)
    
    dm = DataManager(api, strategy)
    auth.on_error_message = lambda msg: dm.show_status(msg, is_error=True)
    
    # [수정] 프로그램 시작 시 시황 분석을 백그라운드 스레드로 실행
    def background_analysis():
        strategy.is_analyzing = True
        strategy.analysis_status_msg = "시장 분석 중..."
        strategy.perform_full_market_analysis()
        strategy.is_analyzing = False
        strategy.analysis_status_msg = "분석 완료"
        perform_interaction('8', api, strategy, dm, 0)
    threading.Thread(target=background_analysis, daemon=True).start()
    
    enter_alt_screen()
    dm.start_workers(auth.is_virtual)
    set_terminal_raw()
    try:
        cycle = 0
        _command_busy = False  # 키 중복 처리 방지 플래그
        _tui_tick = 0          # TUI 렌더링 주기 제어 카운터
        while True:
            cycle += 1
            if not auth.is_token_valid(): auth.generate_token()
            
            # [수정] 주기적 시황 분석 스케줄러 (백그라운드 실행)
            interval = 20 if not auth.is_virtual else 60
            if not strategy.is_analyzing and (time.time() - strategy.last_market_analysis_time) > (interval * 60):
                threading.Thread(target=strategy.perform_full_market_analysis, daemon=True).start()
            
            # 5초 = 100 tick × 0.05s / TUI는 10tick(0.5s)마다 1번 렌더링
            for i in range(100):
                # [수정] 전체 화면 모드일 때는 메인 TUI 렌더링 및 키 입력 건너뜀
                if dm.is_full_screen_active:
                    time.sleep(0.05)
                    continue

                # TUI 렌더링: 0.5초 주기 유지 (10 tick 마다)
                _tui_tick += 1
                if _tui_tick % 10 == 0:
                    draw_tui(strategy, dm, cycle)
                
                # 키 입력 감지 (0.05s 주기로 즉시 반응)
                k = get_key_immediate()
                if k == 'q':
                    dm.is_running = False
                    try: tw = os.get_terminal_size().columns
                    except: tw = 110
                    sys.stdout.write("\033[H\033[2J" + align_kr(" 시스템을 종료합니다. 잠시만 기다려주세요... ", tw, 'center') + "\n")
                    sys.stdout.flush()
                    time.sleep(1)
                    return
                elif k and not dm.is_input_active:
                    # 커맨드 처리 중 중복 키 차단
                    if _command_busy:
                        pass  # 처리 중 추가 입력 무시
                    else:
                        _command_busy = True
                        dm.show_status(f"⏳ [{k.upper()}] 동작 준비 중...")
                        draw_tui(strategy, dm, cycle)  # 즉시 상태 표시 반영
                        def _run_cmd(key=k):
                            nonlocal _command_busy
                            try:
                                perform_interaction(key, api, strategy, dm, cycle)
                            finally:
                                _command_busy = False
                        threading.Thread(target=_run_cmd, daemon=True).start()
                
                time.sleep(0.05)
    except KeyboardInterrupt: 
        dm.is_running = False
    finally: 
        dm.is_running = False
        restore_terminal_settings(); exit_alt_screen()

if __name__ == "__main__":
    main()
