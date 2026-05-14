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
    render_core_header, render_core_row, CORE_SEPARATOR, get_core_width
)

def draw_recommendation_report(strategy, dm, tw, th):
    """AI가 엄선한 TOP 10 추천 종목의 상세 분석 리포트 화면을 렌더링합니다.

    이 뷰는 종목별 정량적 데이터(등락률, PER, PBR, AI 스코어)와 함께, AI 수석 전략가가 
    도출한 해당 종목들의 입체적 대응 전략을 상세히 제공합니다.

    Args:
        strategy: 트레이딩 전략 객체 (AI 추천 엔진 및 리포트 캐시 포함).
        dm: 데이터 매니저 객체 (실시간 지표 참조용).
        tw (int): 터미널 너비.
        th (int): 터미널 높이.

    Logic:
        - `run_bg_analysis`: UI 프리징 없이 추천 종목들에 대한 상세 분석 리포트를 생성합니다.
        - `특수 마커`: 유망 종목(💎)과 ETF(📊)를 시각적으로 구분하여 표시합니다.
        - `데이터 캐싱`: 추천 리포트는 10분간 캐싱되어 불필요한 AI 호출을 방지합니다.

    Controls:
        - [아무 키]: 리포트 화면을 닫고 메인 대시보드로 복귀.
    """
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
            # AI추천 전용 컬럼: 테마, AI점수, 발굴근거
            w_theme, w_score = 12, 8
            extra_h = [('테마', w_theme, 'left'), ('AI점수', w_score, 'right'), ('발굴 근거', 0, 'left')]
            header_str = render_core_header(extra_headers=[('테마', w_theme, 'left'), ('AI점수', w_score, 'right')]) + CORE_SEPARATOR + "발굴 근거"
            buf.write("\033[1;97m" + header_str + "\033[0m\n")
            buf.write("\033[90m" + "═" * tw + "\033[0m\n")
            
            for r in recs[:max(1, th-15)]:
                code = r['code']
                rate = float(r['rate'])
                gem_mark = "💎" if r.get('is_gem') else ("📊" if r.get('is_etf') else "  ")
                
                theme_raw = r.get('theme', '?')
                theme_clean = re.sub(r'\(.*?\)', '', theme_raw).strip()
                theme_fmt = f"[{theme_clean}]"
                
                # 수급 데이터 (이미 추천 데이터에 포함)
                inv = r.get('investor', {})
                frgn = inv.get('frgn_net_buy', 0)
                inst = inv.get('inst_net_buy', 0)
                
                # PER/PBR 가져오기 (detail 캐시 활용)
                detail = strategy.api.get_naver_stock_detail(code, force=False)

                reason = r.get('reason', '').replace('\n', ' ')
                
                # 가용 너비 계산하여 발굴근거 자르기
                core_w = get_core_width()
                extra_fixed_w = w_theme + w_score + len(CORE_SEPARATOR) * 3
                avail_w = tw - core_w - extra_fixed_w - 2
                if get_visual_width(reason) > avail_w:
                    while get_visual_width(reason) > max(5, avail_w - 3): reason = reason[:-1]
                    reason += "..."
                
                # 전용 컬럼
                extra_cols = [
                    (theme_fmt, w_theme, 'left'),
                    (f'{r["score"]:.1f}', w_score, 'right'),
                ]
                
                core_row = render_core_row(
                    code=code,
                    name=gem_mark + r['name'],
                    price=r.get('price', 0),
                    rate=rate,
                    per=detail.get('per', 'N/A'),
                    pbr=detail.get('pbr', 'N/A'),
                    mktcap=r.get('market_cap', 'N/A'),
                    vol=r.get('vol', 0),
                    amt=r.get('amt', 0),
                    frgn=frgn,
                    inst=inst,
                    extra_columns=extra_cols
                )
                buf.write(core_row + CORE_SEPARATOR + reason + "\n")
        
        buf.write("\n" + "\033[90m" + "─" * tw + "\033[0m\n\033[1;96m" + " [AI 수급 사이클 심층 진단 (최근 10일 흐름)]" + "\033[0m\n")
        if recs:
            for r in recs[:5]: # 상위 5개 종목 집중 진단
                inv = r.get('investor', {})
                history = inv.get('history', [])
                if not history: continue
                
                # 사이클 사유 추출
                cycle = inv.get('cycle', '')
                if cycle == "매집":
                    diag = "5일 중 4일 이상 매수 확인 (Accumulation Level: High)"
                elif cycle == "가속":
                    diag = "최근 2일 매입 강도가 이전 3일 대비 강화됨 (Acceleration)"
                elif cycle == "전환":
                    diag = "매도 우위에서 오늘 '쌍끌이 전환' 초입 진입 (Turnaround)"
                else:
                    diag = "안정적인 수급 흐름 유지 중"
                
                buf.write(f"  🔹 \033[1m{r['name']}\033[0m: {diag}\n")
        else:
            buf.write("  진단할 데이터가 없습니다.\n")

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
