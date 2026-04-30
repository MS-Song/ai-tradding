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

def draw_recommendation_report(strategy, dm, tw, th):
    import io
    import threading
    
    _is_running = False
    
    def run_bg_analysis(recs):
        nonlocal _is_running
        _is_running = True
        dm.set_busy("추천 종목 상세 분석 중", "UI")
        try:
            report = strategy.ai_advisor.get_detailed_report_advice(recs, strategy.current_market_vibe)
            strategy.rec_report_cache = report
            strategy.rec_report_time = time.time()
        finally:
            _is_running = False
            dm.clear_busy("UI")

    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except: tw, th = 80, 24
        
        buf = io.StringIO()
        buf.write("\033[42;30m" + align_kr(" [AI DETAILED STRATEGY REPORT: TOP 10 RECOMMENDATIONS] ", tw, 'center') + "\033[0m\n\n")

        buf.write("\033[1;93m" + " [AI 시장 전망 및 종합 의견]" + "\033[0m\n")
        if strategy.ai_briefing:
            for line in strategy.ai_briefing.split('\n'):
                if line.strip(): buf.write(f"  {line.strip()}\n")
        else: buf.write("  분석된 시장 브리핑이 없습니다.\n")
        buf.write("\n" + "=" * tw + "\n\n")
        recs = strategy.ai_recommendations
        if not recs: buf.write(align_kr("현재 분석된 상세 추천 종목이 없습니다. '8'을 눌러 분석을 먼저 수행하세요.", tw, 'center') + "\n")
        else:
            buf.write("\033[1m" + f"{align_kr('테마', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('현재가', 9)} | {align_kr('등락', 7)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('AI점수', 6)} | 발굴 근거" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            for r in recs[:max(1, th-15)]:
                code = r['code']; rate = float(r['rate']); color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
                gem_mark = "💎" if r.get('is_gem') else ("📊" if r.get('is_etf') else "  ")
                detail = strategy.api.get_naver_stock_detail(code, force=False)
                theme_raw = r.get('theme', '?')
                theme_clean = re.sub(r'\(.*?\)', '', theme_raw).strip()
                theme_fmt = align_kr(theme_clean, 8)
                buf.write(f"[{theme_fmt}] | {align_kr(code, 8)} | {align_kr(gem_mark + r['name'], 14)} | {align_kr(f'{int(float(r.get('price',0))):,}', 9, 'right')} | {align_kr(f'{color}{rate:+.1f}%\033[0m', 7, 'right')} | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(f'{r['score']:.1f}', 6, 'right')} | {r['reason']}\n")
        
        buf.write("\n" + "-" * tw + "\n\033[1;92m" + " [AI 수석 전략가 입체 분석 및 대응 전략 (초압축)]" + "\033[0m\n")
        
        curr_t = time.time()
        has_cache = strategy.rec_report_cache and (curr_t - strategy.rec_report_time < 600)
        
        if not has_cache and not _is_running and recs:
            threading.Thread(target=run_bg_analysis, args=(recs,), daemon=True).start()
            
        if _is_running:
            buf.write("\033[93m  🧠 추천 종목들을 입체 분석 중입니다... 잠시만 기다려주세요.\033[0m\n")
        elif strategy.rec_report_cache:
            cleaned_report = clean_ai_text(strategy.rec_report_cache)
            for line in cleaned_report.split('\n'):
                if line.strip(): buf.write(f"  > {line.strip()}\n")
        else:
            buf.write("  ⚠️ 분석된 데이터가 없습니다. 먼저 '8:시황' 분석을 수행하세요.\n")
        
        buf.write("-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
        
        # 화면 출력
        sys.stdout.write("\033[H")
        content_lines = buf.getvalue().split('\n')
        for i in range(min(th, len(content_lines))):
            sys.stdout.write(content_lines[i] + "\033[K" + ("\n" if i < th-1 else ""))
        sys.stdout.write("\033[J")
        sys.stdout.flush()
        buf.close()

        # 입력 감지 (비차단)
        inner_cycle = 0
        while inner_cycle < 10:
            k = get_key_immediate()
            if k: return
            time.sleep(0.1)
            inner_cycle += 1

