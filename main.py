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
    enter_alt_screen()
    dm.start_workers(auth.is_virtual)
    set_terminal_raw()
    try:
        cycle = 0
        while True:
            cycle += 1
            if not auth.is_token_valid(): auth.generate_token()
            for i in range(50):
                draw_tui(strategy, dm, cycle)
                start_t = time.time()
                while time.time() - start_t < 0.5:
                    k = get_key_immediate()
                    if k: perform_interaction(k, api, strategy, dm, cycle)
                    time.sleep(0.05)
    except KeyboardInterrupt: pass
    finally: restore_terminal_settings(); exit_alt_screen()

if __name__ == "__main__":
    main()
