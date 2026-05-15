import os
import sys
import time
import unicodedata
import signal
import re
import atexit
import functools
from datetime import datetime, time as dtime, timezone, timedelta

KST = timezone(timedelta(hours=9))

def get_now():
    """현재 시간을 KST(GMT+9) 기준으로 반환합니다. 
    서버의 로컬 시간 설정과 무관하게 항상 한국 시간을 보장합니다."""
    return datetime.now(KST).replace(tzinfo=None)


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
        # ECHO: 입력 문자 화면 출력 끔, ICANON: 엔터 대기(Line Buffering) 끔
        new[3] = new[3] & ~termios.ECHO & ~termios.ICANON
        # VMIN=1: 최소 1바이트 읽을 때까지 대기, VTIME=0: 타임아웃 없음
        new[6][termios.VMIN] = 1
        new[6][termios.VTIME] = 0
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
        try: 
            termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
            # Python 내부 버퍼에 남은 데이터도 소진 시도
            import select
            while select.select([sys.stdin.fileno()], [], [], 0)[0]:
                os.read(sys.stdin.fileno(), 1024)
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
        import os
        fd = sys.stdin.fileno()
        if select.select([fd], [], [], 0)[0]:
            try:
                # [중요] sys.stdin.read(1)은 Python의 TextIOWrapper에 의해 버퍼링(Line Buffering)될 수 있음.
                # 리눅스에서 엔터를 쳐야만 입력이 전달되는 문제를 해결하기 위해 os.read로 직접 읽음.
                b = os.read(fd, 1)
                if not b: return None
                
                # ESC 및 시퀀스 처리
                if b == b'\x1b':
                    # 추가 데이터가 있는지 아주 짧게 확인하여 시퀀스(방향키 등)면 버림
                    if select.select([fd], [], [], 0.01)[0]:
                        os.read(fd, 8) 
                        return None
                    return 'esc'
                
                # UTF-8 멀티바이트 조립 (한글 자모 등 대응)
                if b[0] & 0x80:
                    if (b[0] & 0xE0) == 0xC0: # 2 bytes
                        b += os.read(fd, 1)
                    elif (b[0] & 0xE0) == 0xE0: # 3 bytes (한글 등)
                        b += os.read(fd, 2)
                    elif (b[0] & 0xF0) == 0xF0: # 4 bytes
                        b += os.read(fd, 3)
                
                decoded = b.decode('utf-8', errors='ignore')
                result = normalize_key(decoded)
                return result.lower() if result else None
            except:
                return None
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
    d = get_now()
    count = 0
    while count < n:
        if d.weekday() < 5: # 월-금
            count += 1
        if count < n:
            d -= timedelta(days=1)
    return d.date()

def is_market_open():
    now = get_now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)

def is_ai_enabled_time():
    """AI 자동 기능 실행 가능 시간 체크 (장 시작 20분 전 ~ 장 마감 20분 후)"""
    now = get_now()
    if now.weekday() >= 5: return False
    return dtime(8, 40) <= now.time() <= dtime(15, 50)

def is_us_market_open():
    now = get_now()
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
    """한글 및 ANSI 색상 코드가 포함된 문자열을 시각적 너비에 맞춰 정렬합니다."""
    text = str(text)
    
    # 1. 시각적 너비가 초과할 경우 안전하게 자르기 (ANSI 코드 파손 방지)
    if get_visual_width(text) > width:
        # ANSI 코드를 제외한 순수 텍스트만 추출하여 자름 (가장 안전한 방법)
        plain = ANSI_ESCAPE.sub('', text)
        while get_visual_width(plain) > max(0, width - 2):
            plain = plain[:-1]
        text = plain + ".."
        
    cur_w = get_visual_width(text)
    pad = max(0, width - cur_w)
    
    if align == 'right': 
        return ' ' * pad + text
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

def clean_ai_text(text: str) -> str:
    """TUI 가독성을 위해 AI 응답에서 마크다운 요소(볼드체 등)를 제거합니다."""
    if not text:
        return ""
    # 마크다운 볼드체 (**, __) 제거
    text = text.replace("**", "").replace("__", "")
    # 불필요한 마크다운 코드 블록 제거 (혹시나 포함된 경우)
    text = re.sub(r'```[a-zA-Z]*\n?', '', text)
    text = text.replace('```', '')
    return text.strip()

def safe_cast_float(val: any, default: float = 0.0) -> float:
    """한글 단위(조, 억, 원) 및 특수문자(%, ,)가 포함된 문자열을 안전하게 float으로 변환합니다.
    시가총액의 경우 '억' 단위로 통일하여 반환합니다.
    """
    if val is None: return default
    s = str(val).strip()
    if not s or s.upper() in ['N/A', 'NAN']: return default
    
    try:
        # 모든 공백(\n, \t, space 등) 제거 및 콤마 제거
        s = re.sub(r'\s+', '', s).replace(',', '')
        
        # '원' 기호 제거
        s = s.replace('원', '').replace('%', '')
        
        # 조/억 단위가 포함된 경우 처리
        if '조' in s or '억' in s:
            total = 0.0
            
            # '조' 처리
            if '조' in s:
                parts = s.split('조')
                if parts[0]:
                    total += float(parts[0]) * 10000
                s = parts[1] if len(parts) > 1 else ""
            
            # '억' 처리
            if '억' in s:
                parts = s.split('억')
                if parts[0]:
                    total += float(parts[0])
                # '억' 뒤에 남은 숫자가 있을 수 있으나 보통 시총에선 없음. 있으면 무시하거나 추가 처리
            elif s: 
                # '조' 뒤에 단위 없이 숫자만 있는 경우 (예: '7조 8983')
                # 숫자가 아닌 문자(괄호 등)가 섞여있을 수 있으므로 정제
                s_clean = re.sub(r'[^0-9.-]', '', s)
                if s_clean:
                    total += float(s_clean)
            
            return total
            
        # 단위가 없는 일반 숫자인 경우 (RSI, PBR 등)
        # 숫자와 부호, 소수점만 남기고 제거 (예: "1.23배" -> "1.23")
        s_clean = re.sub(r'[^0-9.-]', '', s)
        if not s_clean: return default
        return float(s_clean)
    except:
        return default
# --- ANSI 컬러 상수 ---
RESET = "\033[0m"
B_RED = "\033[1;31m"
G_GREEN = "\033[1;32m"
B_YELLOW = "\033[1;33m"
B_BLUE = "\033[1;34m"
B_MAGENTA = "\033[1;35m"
B_CYAN = "\033[1;36m"
B_WHITE = "\033[1;37m"

def truncate_log_line(text: str, max_width: int, suffix: str = '…') -> str:
    """ANSI 이스케이프 코드를 보존하면서 시각 너비(한글 2칸) 기준으로 텍스트를 잘라냅니다.

    Args:
        text (str): 자를 원본 텍스트 (ANSI 색상 코드 포함 가능).
        max_width (int): 제한할 최대 시각 너비.
        suffix (str, optional): 잘린 위치에 붙일 접미사. 기본값 '…'.

    Returns:
        str: 잘린 텍스트와 ANSI 색상 초기화 코드가 포함된 문자열.
    """
    if not text: return ""
    text = str(text)
    plain = ANSI_ESCAPE.sub('', text)
    if get_visual_width(plain) <= max_width:
        return text  # 잘라낼 필요 없음

    suffix_w = get_visual_width(suffix)
    target_w = max_width - suffix_w

    # ANSI 토큰 단위로 순회하며 시각 너비를 누적
    result = []
    cur_w = 0
    i = 0
    while i < len(text):
        m = ANSI_ESCAPE.match(text, i)
        if m:
            # ANSI 시퀀스는 너비 0 — 그대로 보존
            result.append(m.group())
            i = m.end()
        else:
            ch = text[i]
            # unicodedata는 상단에 이미 임포트됨
            if ord(ch) < 128:
                cw = 1
            elif unicodedata.east_asian_width(ch) in ['W', 'F', 'A']:
                cw = 2
            else:
                cw = 1
            if cur_w + cw > target_w:
                break
            result.append(ch)
            cur_w += cw
            i += 1

    return ''.join(result) + '\033[0m' + suffix
