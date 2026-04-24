import os
import sys
import time
import unicodedata
import signal
import re
import atexit
import functools
from datetime import datetime, time as dtime

# ────────────────────────────────────────────────────────────
# 한글 두벌식 키보드 → 영문 QWERTY 역매핑
# 한글 IME 활성 상태에서 물리 키를 눌렀을 때 터미널로 전달되는
# 한글 자음/모음 유니코드를 원래 알파벳으로 되돌림
# ────────────────────────────────────────────────────────────
KOREAN_KEY_MAP = {
    'ㅂ': 'q', 'ㅈ': 'w', 'ㄷ': 'e', 'ㄱ': 'r', 'ㅅ': 't',
    'ㅛ': 'y', 'ㅕ': 'u', 'ㅑ': 'i', 'ㅐ': 'o', 'ㅔ': 'p',
    'ㅁ': 'a', 'ㄴ': 's', 'ㅇ': 'd', 'ㄹ': 'f', 'ㅎ': 'g',
    'ㅗ': 'h', 'ㅓ': 'j', 'ㅏ': 'k', 'ㅣ': 'l',
    'ㅋ': 'z', 'ㅌ': 'x', 'ㅊ': 'c', 'ㅍ': 'v', 'ㅠ': 'b',
    'ㅜ': 'n', 'ㅡ': 'm',
    # 쌍자음 (Shift+키) → 대응 소문자
    'ㅃ': 'q', 'ㅉ': 'w', 'ㄸ': 'e', 'ㄲ': 'r', 'ㅆ': 't',
    'ㅒ': 'o', 'ㅖ': 'p',
}

def normalize_key(ch: str) -> str:
    """한글 자모 문자를 QWERTY 위치 영문자로 변환. 이미 영문이면 그대로 반환."""
    if not ch:
        return ch
    # 단일 한글 자모 (U+3131~U+3163 호환 자모 블록)
    mapped = KOREAN_KEY_MAP.get(ch)
    if mapped:
        return mapped
    # 완성형 한글 음절(가~힣)은 무시 (IME가 조합 완성 후 전송하는 경우)
    if len(ch) == 1 and '가' <= ch <= '힣':
        return ''
    return ch

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
    if IS_WINDOWS:
        import msvcrt
        # Windows: 키보드 버퍼에 남은 모든 입력 소진
        while msvcrt.kbhit():
            msvcrt.getch()
    else:
        try: termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except: pass

def get_key_immediate():
    if IS_WINDOWS:
        import msvcrt
        if msvcrt.kbhit():
            try:
                ch = msvcrt.getch()
                # 방향키/특수키 시퀀스 건너뜀
                if ch in [b'\xe0', b'\x00']:
                    if msvcrt.kbhit(): msvcrt.getch()
                    return None
                if ch == b'\x1b': return 'esc'
                first = ch[0]
                # 멀티바이트 UTF-8 한글 조립
                # 0xC0~0xDF: 2바이트, 0xE0~0xEF: 3바이트, 0xF0~: 4바이트
                raw = ch
                if first >= 0xE0 and first < 0xF0:
                    for _ in range(2):
                        if msvcrt.kbhit(): raw += msvcrt.getch()
                elif first >= 0xC0:
                    if msvcrt.kbhit(): raw += msvcrt.getch()
                decoded = raw.decode('utf-8', errors='ignore')
                if not decoded:  # UTF-8 실패 시 CP949 시도
                    try: decoded = raw.decode('cp949', errors='ignore')
                    except: decoded = ''
                result = normalize_key(decoded).lower() if decoded else ''
                return result if result else None
            except: return None
        return None
    else:
        import select
        if select.select([sys.stdin], [], [], 0)[0]:
            c = sys.stdin.read(1)  # text-mode: 이미 완성된 유니코드 문자
            if c == '\x1b':
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    sys.stdin.read(1)
                    return None
                return 'esc'
            result = normalize_key(c)
            return result.lower() if result else None
    return None

def input_with_esc(prompt, tw, callback=None):
    if callback: callback(prompt, "")
    input_str = ""
    while True:
        k = get_key_immediate()
        if k:
            if k == 'esc': 
                if callback: callback("", "")
                return None
            elif k == '\r' or k == '\n':
                if callback: callback("", "")
                return input_str
            elif k == '\b' or k == 'backspace' or k == '\x7f':
                if len(input_str) > 0:
                    input_str = input_str[:-1]
            elif len(k) == 1:
                input_str += k
            
            # [수정] 붙여넣기 및 빠른 입력 시 버퍼에 쌓인 문자를 한꺼번에 처리
            # 화면을 매 문자마다 다시 그리는(callback) 비용을 줄여 입력 유실 방지
            while True:
                has_more = False
                if IS_WINDOWS:
                    import msvcrt
                    if msvcrt.kbhit(): has_more = True
                else:
                    import select
                    if select.select([sys.stdin], [], [], 0)[0]: has_more = True
                
                if not has_more: break
                
                kb = get_key_immediate()
                if not kb: break
                if kb == 'esc': 
                    if callback: callback("", "")
                    return None
                if kb == '\r' or kb == '\n':
                    if callback: callback("", "")
                    return input_str
                if kb in ['\b', 'backspace', '\x7f']:
                    if len(input_str) > 0: input_str = input_str[:-1]
                elif len(kb) == 1:
                    input_str += kb

            if callback: callback(prompt, input_str)
            
        time.sleep(0.01)

# --- 신규: API 안정성 장치 ---
def retry_api(max_retries=3, delay=1.2, backoff=2.0, exceptions=(Exception,)):
    """API 호출 재시도를 위한 데코레이터. 지수 백오프 적용.
    KIS API의 Rate Limit(초당 호출 제한) 및 네트워크 불안정 대응 목적."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            curr_delay = delay
            last_exception = None
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    retries += 1
                    last_exception = e
                    # 로깅 시 순환 참조 방지를 위해 지연 임포트
                    from src.logger import log_error
                    log_error(f"⚠️ API 재시도 {retries}/{max_retries} ({func.__name__}): {e}")
                    
                    if retries < max_retries:
                        time.sleep(curr_delay)
                        curr_delay *= backoff
            
            if last_exception:
                raise last_exception
            return None
        return wrapper
    return decorator

# --- 유틸리티 함수 ---
def get_business_days_ago(n):
    """오늘 포함 최근 n개 영업일을 제외한 기준 날짜(date객체)를 반환"""
    from datetime import timedelta
    d = datetime.now()
    count = 0
    while count < n:
        if d.weekday() < 5: # 월-금
            count += 1
        if count < n:
            d -= timedelta(days=1)
    return d.date()

def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)

def is_ai_enabled_time():
    """AI 자동 기능 실행 가능 시간 체크 (장 시작 20분 전 ~ 장 마감 20분 후)"""
    now = datetime.now()
    if now.weekday() >= 5: return False
    return dtime(8, 40) <= now.time() <= dtime(15, 50)

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
