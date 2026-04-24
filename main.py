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
            
            # [수정] 주기적 시황 분석 스케줄러 (실전 20분 / 모의 60분 정책 준수)
            is_v = getattr(strategy.api.auth, 'is_virtual', True)
            interval = 20 if not is_v else 60
            if not strategy.is_analyzing and (time.time() - strategy.last_market_analysis_time) > (interval * 60):
                threading.Thread(target=strategy.run_scheduled_analysis, daemon=True).start()
            
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
                # [수정] q / Q / ㅂ / ㅃ 모든 종료 키 즉시 반응
                if k and k.lower() in ['q', 'ㅂ', 'ㅃ']:
                    dm.shutdown("사용자 종료") # [추가] 텔레그램 종료 알림 발송
                    try: tw = os.get_terminal_size().columns
                    except: tw = 110
                    # TUI 정지 및 화면 청소 후 종료 알림
                    restore_terminal_settings(); exit_alt_screen()
                    sys.stdout.write("\033[H\033[2J" + align_kr(" 시스템을 안전하게 종료합니다. 잠시만 기다려주세요... ", tw, 'center') + "\n")
                    sys.stdout.flush()
                    time.sleep(1)
                    os._exit(0)
                elif k and not dm.is_input_active:
                    # [수정] 유효한 명령어 키인지 확인 (p:성과 추가)
                    valid_cmds = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'd', 'h', 'l', 'm', 's', 'p', 'k', 'ㅔ', 'ㅖ', 'ㅏ']
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
        restore_terminal_settings(); exit_alt_screen()

if __name__ == "__main__":
    main()
