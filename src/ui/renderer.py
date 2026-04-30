import os
import sys
import io
import time
import threading
import re
from datetime import datetime
from src.utils import is_market_open, is_us_market_open, get_visual_width, align_kr, ANSI_ESCAPE, get_market_name, get_key_immediate
from src.theme_engine import get_cached_themes, get_theme_for_stock

VERSION_CACHE = "Unknown"
try:
    with open("VERSION", "r") as f:
        VERSION_CACHE = f.read().strip()
except: pass

def truncate_log_line(text: str, max_width: int, suffix: str = '…') -> str:
    """ANSI 이스케이프 코드를 보존하면서 시각 너비(한글 2칸) 기준으로 텍스트를 잘라냅니다.
    max_width를 초과하는 경우 suffix(기본 '…')를 붙입니다."""
    import unicodedata
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

from src.ui.views.dashboard_view import draw_tui
from src.ui.views.manual_view import draw_manual_page
from src.ui.views.trading_logs_view import draw_trading_logs
