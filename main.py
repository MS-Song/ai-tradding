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
    
    # [수정] 프로그램 시작 시 시황 분석을 백그라운드 스레드로 실행
    def background_analysis():
        strategy.is_analyzing = True
        strategy.analysis_status_msg = "시장 분석 중..."
        strategy.perform_full_market_analysis()
        strategy.is_analyzing = False
        strategy.analysis_status_msg = "분석 완료"
    threading.Thread(target=background_analysis, daemon=True).start()
    
    dm = DataManager(api, strategy)
    enter_alt_screen()
    dm.start_workers(auth.is_virtual)
    set_terminal_raw()
    try:
        cycle = 0
        while True:
            cycle += 1
            if not auth.is_token_valid(): auth.generate_token()
            
            # [수정] 주기적 시황 분석 스케줄러 (백그라운드 실행)
            interval = 20 if not auth.is_virtual else 60
            if not strategy.is_analyzing and (time.time() - strategy.last_market_analysis_time) > (interval * 60):
                threading.Thread(target=strategy.perform_full_market_analysis, daemon=True).start()
            
            # 종료 로직: 루프 내에서 직접 키 입력 확인
            k = get_key_immediate()
            if k == 'q':
                try: tw = os.get_terminal_size().columns
                except: tw = 110
                sys.stdout.write("\033[H\033[2J" + align_kr(" 시스템을 종료합니다. 잠시만 기다려주세요... ", tw, 'center') + "\n")
                sys.stdout.flush()
                time.sleep(1)
                break
            elif k:
                # 일반 입력 처리
                if not dm.is_input_active:
                    threading.Thread(target=perform_interaction, args=(k, api, strategy, dm, cycle), daemon=True).start()

            for i in range(10): # 약 5초마다 대기 (0.5s * 10)
                draw_tui(strategy, dm, cycle)
                # ... 기존 로직 유지 ...
                time.sleep(0.5)
    except KeyboardInterrupt: pass
    finally: restore_terminal_settings(); exit_alt_screen()

if __name__ == "__main__":
    main()
