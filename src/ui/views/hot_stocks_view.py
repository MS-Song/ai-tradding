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
from src.ui.views.stock_table_renderer import (
    render_core_header, render_core_row, CORE_SEPARATOR
)

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
    _investor_cache = {}
    _investor_loaded = False
    
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

    def load_investor_data(hot_items):
        """인기 종목들의 기관/외국인 수급 데이터를 백그라운드로 수집합니다."""
        nonlocal _investor_loaded
        for item in hot_items[:10]:
            code = item.get('code', '')
            if not code:
                continue
            try:
                inv = strategy.api.get_investor_trading_trend(code)
                if inv:
                    _investor_cache[code] = inv
            except:
                pass
        _investor_loaded = True

    # 최초 진입 시 수급 데이터 백그라운드 로드
    hot_initial = dm.cached_hot_raw[:10]
    if hot_initial:
        threading.Thread(target=load_investor_data, args=(hot_initial,), daemon=True).start()

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
            # 인기 리포트 전용 컬럼: NO, 업종PER
            extra_h = [('업종PER', 8, 'right')]
            # NO 컬럼은 Core 앞에 수동 추가
            no_header = align_kr('NO', 4)
            header_str = no_header + CORE_SEPARATOR + render_core_header(extra_headers=extra_h)
            buf.write("\033[1m" + header_str + "\033[0m\n")
            buf.write("-" * tw + "\n")
            
            for idx, item in enumerate(hot, 1):
                code = item.get('code', '')
                # [개선] UI에서 별도 API 호출 대신 sync_worker가 1초마다 갱신하는 공통 캐시 활용
                info = dm.cached_stock_info.get(code, {})
                price = info.get('price', float(item.get('price', 0)))
                rate = info.get('day_rate', float(item.get('rate', 0)))
                
                detail = strategy.api.get_naver_stock_detail(code)
                name = info.get('name') or item.get('name', '')
                inv = _investor_cache.get(code, {})
                
                # 전용 컬럼: 업종PER
                sector_per_str = detail.get('sector_per', 'N/A')
                extra_cols = [(sector_per_str, 8, 'right')]
                
                no_col = align_kr(str(idx), 4)
                core_row = render_core_row(
                    code=code,
                    name=name,
                    price=price,
                    rate=rate,
                    per=detail.get('per', 'N/A'),
                    pbr=detail.get('pbr', 'N/A'),
                    mktcap=detail.get('market_cap', 'N/A'),
                    vol=detail.get('vol', 0),
                    amt=detail.get('amt', 0),
                    frgn=inv.get('frgn_net_buy', 0),
                    inst=inv.get('inst_net_buy', 0),
                    extra_columns=extra_cols
                )
                buf.write(no_col + CORE_SEPARATOR + core_row + "\n")
        
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
