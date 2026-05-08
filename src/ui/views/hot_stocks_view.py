import os
import sys
import time
import threading
import io
import re
from datetime import datetime
from src.utils import *
from src.theme_engine import get_cached_themes, get_theme_for_stock
from src.strategy import PRESET_STRATEGIES
from src.logger import trading_log

def draw_hot_stocks_detail(strategy, dm, tw, th):
    """실시간 인기 테마와 종목 트렌드를 분석하여 AI 리포트 화면을 렌더링합니다.

    이 뷰는 현재 시장에서 가장 뜨거운 관심을 받는 테마와 종목들의 정량적 데이터(PER, 업종PER) 및 
    AI 트렌드 분석가의 정성적 평가를 제공하여 시장의 주도주를 파악하도록 돕습니다.

    Args:
        strategy: 트레이딩 전략 객체 (AI 트렌드 분석 기능 포함).
        dm: 데이터 매니저 객체 (실시간 인기 종목 데이터 참조용).
        tw (int): 터미널 너비.
        th (int): 터미널 높이.

    Logic:
        - `run_bg_analysis`: UI 프리징 없이 인기 테마 및 종목에 대한 AI 진단을 수행합니다.
        - `데이터 캐싱`: AI 리포트는 5분간 캐싱되며, 실패 시 30초의 재시도 유예 기간을 둡니다.
        - `입체 분석`: 종목의 개별 PER과 업종 평균 PER을 비교하여 고평가/저평가 여부를 직관적으로 보여줍니다.

    Controls:
        - [R]: 인기 테마 AI 분석 강제 갱신.
        - [Q, ESC, SPACE]: 화면을 닫고 메인 대시보드로 복귀.
    """
    import io
    import threading
    
    _is_running = False
    
    def run_bg_analysis(hot, themes):
        nonlocal _is_running
        _is_running = True
        dm.set_busy("인기 테마 분석 중", "UI")
        report = None
        try:
            report = strategy.ai_advisor.get_hot_stocks_report_advice(hot, themes, strategy.current_market_vibe)
            strategy.hot_report_cache = report
            strategy.hot_report_time = time.time()
        finally:
            _is_running = False
            if not report:
                strategy.hot_report_err_time = time.time()
            dm.clear_busy("UI")

    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except: tw, th = 80, 24

        buf = io.StringIO()
        buf.write("\033[45;37m" + align_kr(" [AI HOT THEME TREND REPORT] ", tw, 'center') + "\033[0m\n\n")
        
        themes = get_cached_themes()
        if themes:
            theme_line = " [오늘의 인기 테마] "
            for t in themes[:8]: theme_line += f"{t['name']}({t['count']}) | "
            buf.write("\033[1;93m" + theme_line.rstrip(" | ") + "\033[0m\n")
        buf.write("-" * tw + "\n\n")
        
        hot = dm.cached_hot_raw[:10]
        if not hot:
            buf.write(align_kr("인기 검색 데이터가 없습니다.", tw, 'center') + "\n")
        else:
            buf.write("\033[1m" + f"{align_kr('NO', 4)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('현재가', 10)} | {align_kr('등락률', 8)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('업종PER', 7)}" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            
            codes = [item.get('code', '') for item in hot if item.get('code')]
            realtime_data = strategy.api.get_naver_stocks_realtime(codes)
            
            for idx, item in enumerate(hot, 1):
                code = item.get('code', '')
                r_item = realtime_data.get(code, {})
                price = r_item.get('price', float(item.get('price', 0)))
                rate = r_item.get('rate', float(item.get('rate', 0)))
                color = "\033[91m" if rate >= 0 else "\033[94m"
                detail = strategy.api.get_naver_stock_detail(code)
                name = r_item.get('name') or item.get('name', '')
                buf.write(f"{align_kr(str(idx), 4)} | {align_kr(code, 8)} | {align_kr(name[:10], 14)} | {align_kr(f'{int(float(price)):,}', 10, 'right')} | {color}{align_kr(f'{rate:+.2f}%', 8, 'right')}\033[0m | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(detail.get('sector_per','N/A'), 7, 'right')}\n")
        
        curr_t = time.time()
        has_cache = strategy.hot_report_cache and (curr_t - strategy.hot_report_time < 300)
        
        if not has_cache and not _is_running and hot:
            # 실패 시에도 최소 30초는 대기하도록 보호 (API 과부하 방지)
            last_err_t = getattr(strategy, 'hot_report_err_time', 0)
            if curr_t - last_err_t > 30:
                threading.Thread(target=run_bg_analysis, args=(hot, themes), daemon=True).start()

        buf.write("\n\033[1;95m" + " [AI 트렌드 분석가의 인기 테마 진단 (초압축)]" + "\033[0m\n")
        if _is_running:
            buf.write("\033[93m  🧠 인기 테마 및 종목 트렌드를 분석 중입니다... 잠시만 기다려주세요.\033[0m\n")
        elif strategy.hot_report_cache:
            cleaned_hot = clean_ai_text(strategy.hot_report_cache)
            for line in cleaned_hot.split('\n'):
                if line.strip(): buf.write(f"  {line.strip()}\n")
        else:
            buf.write("  ⚠️ 리포트를 생성할 수 없습니다. 잠시 후 'R' 키를 눌러 재시도하세요.\n")
            
        buf.write("\n" + "-" * tw + "\n" + align_kr(" Q, ESC, SPACE: 종료 | R: AI 분석 갱신 ", tw, 'center') + "\n")
        
        sys.stdout.write("\033[H")
        content_lines = buf.getvalue().split('\n')
        for i in range(min(th, len(content_lines))):
            sys.stdout.write(content_lines[i] + "\033[K" + ("\n" if i < th-1 else ""))
        sys.stdout.write("\033[J")
        sys.stdout.flush()
        buf.close()

        inner_cycle = 0
        while inner_cycle < 10:
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == 'r':
                    strategy.hot_report_cache = None
                    strategy.hot_report_err_time = 0
                    break
                elif kl in ['q', 'esc', ' ', '\x1b']:
                    return
            time.sleep(0.1)
            inner_cycle += 1

