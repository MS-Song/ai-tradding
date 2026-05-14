import os
import sys
import io
import time
import threading
import re
from src.utils import is_market_open, is_us_market_open, get_visual_width, align_kr, ANSI_ESCAPE, get_market_name, get_key_immediate, truncate_log_line
from src.theme_engine import get_cached_themes, get_theme_for_stock

VERSION_CACHE = "Unknown"
try:
    with open("VERSION", "r") as f:
        VERSION_CACHE = f.read().strip()
except: pass

from src.ui.views.dashboard_view import draw_tui
from src.ui.views.manual_view import draw_manual_page
from src.ui.views.trading_logs_view import draw_trading_logs
