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
            # 헤더와 데이터 컬럼 너비 정의
            w_theme, w_code, w_name, w_price, w_rate, w_supply, w_cycle, w_score = 12, 8, 16, 10, 8, 10, 8, 8
            
            header = (
                f"{align_kr('테마', w_theme)} | "
                f"{align_kr('코드', w_code)} | "
                f"{align_kr('종목명', w_name)} | "
                f"{align_kr('현재가', w_price, 'right')} | "
                f"{align_kr('등락', w_rate, 'right')} | "
                f"{align_kr('수급상태', w_supply, 'center')} | "
                f"{align_kr('사이클', w_cycle, 'center')} | "
                f"{align_kr('AI점수', w_score, 'right')} | "
                "발굴 근거"
            )
            buf.write("\033[1;97m" + header + "\033[0m\n")
            buf.write("\033[90m" + "═" * tw + "\033[0m\n")
            
            for r in recs[:max(1, th-15)]:
                code = r['code']
                rate = float(r['rate'])
                color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
                gem_mark = "💎" if r.get('is_gem') else ("📊" if r.get('is_etf') else "  ")
                
                theme_raw = r.get('theme', '?')
                theme_clean = re.sub(r'\(.*?\)', '', theme_raw).strip()
                theme_fmt = f"[{theme_clean}]"
                
                # 수급 데이터 및 사이클 추출
                inv = r.get('investor', {})
                f_net, i_net, p_net = inv.get('frgn_net_buy', 0), inv.get('inst_net_buy', 0), inv.get('pnsn_net_buy', 0)
                
                signals = []
                if f_net > 0: signals.append("\033[91mF↑\033[0m")
                if i_net > 0: signals.append("\033[91mI↑\033[0m")
                if p_net > 0: signals.append("\033[91mP↑\033[0m")
                supply_str = " ".join(signals) if signals else "-"
                
                cycle_tag = inv.get('cycle', '-')
                cycle_fmt = f"[{cycle_tag}]" if cycle_tag != "-" else "-"

                reason = r.get('reason', '').replace('\n', ' ')
                
                # 가용 너비 계산 (기존 컬럼 너비 + 구분자들 너비 합산)
                # ANSI 코드가 들어간 경우 get_visual_width로 실제 폭 계산 필요
                fixed_w = w_theme + w_code + w_name + w_price + w_rate + w_supply + w_cycle + w_score + (8 * 3)
                avail_w = tw - fixed_w - 2
                
                if get_visual_width(reason) > avail_w:
                    while get_visual_width(reason) > max(5, avail_w - 3): reason = reason[:-1]
                    reason += "..."
                
                row = (
                    f"{align_kr(theme_fmt, w_theme)} | "
                    f"{align_kr(code, w_code)} | "
                    f"{align_kr(gem_mark + r['name'], w_name)} | "
                    f"{align_kr(f'{int(float(r.get('price',0))):,}', w_price, 'right')} | "
                    f"{align_kr(f'{color}{rate:+.1f}%\033[0m', w_rate, 'right')} | "
                    f"{align_kr(supply_str, w_supply, 'center')} | "
                    f"{align_kr(cycle_fmt, w_cycle, 'center')} | "
                    f"{align_kr(f'{r['score']:.1f}', w_score, 'right')} | "
                    f"{reason}"
                )
                buf.write(row + "\n")
        
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

