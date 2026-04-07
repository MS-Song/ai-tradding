import os
import sys
import unicodedata
import signal
import re
import atexit
from datetime import datetime, time as dtime

# OS별 터미널 제어
IS_WINDOWS = os.name == 'nt'
if not IS_WINDOWS:
    import termios
    import tty

_original_termios = None

def init_terminal():
    global _original_termios
    if IS_WINDOWS:
        os.system('')
    else:
        try:
            _original_termios = termios.tcgetattr(sys.stdin.fileno())
            atexit.register(exit_alt_screen)
            signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
            signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        except: pass

def restore_terminal_settings():
    if not IS_WINDOWS and _original_termios:
        try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, _original_termios)
        except: pass

def set_terminal_raw():
    if IS_WINDOWS: return
    try:
        fd = sys.stdin.fileno()
        new = termios.tcgetattr(fd)
        new[3] = new[3] & ~termios.ECHO & ~termios.ICANON
        termios.tcsetattr(fd, termios.TCSANOW, new)
    except: pass

def enter_alt_screen():
    sys.stdout.write("\033[?1049h\033[H")
    sys.stdout.flush()

def exit_alt_screen():
    restore_terminal_settings()
    sys.stdout.write("\033[?1049l\033[m")
    sys.stdout.flush()

def flush_input():
    if not IS_WINDOWS:
        try: termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except: pass

def get_key_immediate():
    if IS_WINDOWS:
        import msvcrt
        if msvcrt.kbhit():
            try:
                ch = msvcrt.getch()
                if ch in [b'\xe0', b'\x00']:
                    if msvcrt.kbhit(): msvcrt.getch() 
                    return None
                if ch == b'\x1b': return 'esc'
                return ch.decode('utf-8', errors='ignore').lower()
            except: return None
        return None
    else:
        import select
        if select.select([sys.stdin], [], [], 0)[0]:
            c = sys.stdin.read(1)
            if c == '\x1b':
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    sys.stdin.read(1)
                    return None
                return 'esc'
            return c.lower()
    return None

def input_with_esc(prompt, tw):
    sys.stdout.write(f"\033[33m {prompt}\033[0m")
    sys.stdout.flush()
    input_str = ""
    while True:
        k = get_key_immediate()
        if k == 'esc': return None
        elif k == '\r' or k == '\n':
            sys.stdout.write("\n")
            return input_str
        elif k == '\b' or k == 'backspace' or k == '\x7f':
            if len(input_str) > 0:
                input_str = input_str[:-1]
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif k and len(k) == 1:
            input_str += k
            sys.stdout.write(k)
            sys.stdout.flush()
        time.sleep(0.01)

# --- 유틸리티 함수 ---
def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)

def is_us_market_open():
    now = datetime.now()
    if now.weekday() >= 5: return False
    t = now.time()
    return t >= dtime(22, 30) or t <= dtime(5, 0)

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def get_visual_width(text):
    plain_text = ANSI_ESCAPE.sub('', str(text))
    w = 0
    for c in plain_text:
        if ord(c) < 128: w += 1
        elif unicodedata.east_asian_width(c) in ['W', 'F', 'A']: w += 2
        else: w += 1
    return w

def align_kr(text, width, align='left'):
    text = str(text)
    while get_visual_width(text) > width: text = text[:-1]
    cur_w = get_visual_width(text)
    pad = max(0, width - cur_w)
    if align == 'right': return ' ' * pad + text
    if align == 'center':
        l_p = pad // 2
        return ' ' * l_p + text + ' ' * (pad - l_p)
    return text + ' ' * pad

def get_market_name(stock_code):
    proxies = {"069500": "KSP", "150460": "KDQ", "133690": "NAS", "360750": "SPX"}
    m = proxies.get(stock_code)
    if m: return m
    if len(stock_code) == 6 and stock_code.isdigit():
        return "KSP" if stock_code[:2] in ['00', '01', '02', '03', '05', '06', '07'] else "KDQ"
    if len(stock_code) >= 1 and any(c.isalpha() for c in stock_code):
        return "USA"
    return "STK"
