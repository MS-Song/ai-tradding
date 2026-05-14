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

def draw_holdings_detail(strategy, dm):
    """현재 보유 포트폴리오의 상세 현황과 AI 진단 의견을 보여주는 TUI 리포트 화면을 렌더링합니다.

    이 뷰는 보유 종목의 정량적 지표(수익률, PER, PBR)뿐만 아니라, AI가 포트폴리오 전체를 
    입체적으로 분석한 정성적 조언을 함께 제공합니다.

    Args:
        strategy: 트레이딩 전략 객체 (AI 진단 로직 포함).
        dm: 데이터 매니저 객체 (계좌 및 보유 종목 데이터 참조용).

    Logic:
        - `run_bg_analysis`: UI 프리징을 방지하기 위해 별도 스레드에서 AI 진단을 수행합니다.
        - `자산 요약`: 총자산 대비 현재 평가 손익과 현금 비중을 한눈에 파악합니다.
        - `AI 진단 의견`: 개별 종목의 수익성과 시황을 고려한 매니저의 대응 전략(Hold/Sell 등)을 출력합니다.

    Controls:
        - [R]: AI 포트폴리오 진단 즉시 시작/갱신.
        - [Q, ESC, SPACE]: 화면을 닫고 메인 대시보드로 복귀.
    """
    import io
    import os
    import threading
    from datetime import datetime
    
    _is_running_analysis = False
    _investor_cache = {}  # 종목별 기관/외국인 수급 캐시
    _investor_loaded = False
    
    def run_bg_analysis():
        nonlocal _is_running_analysis
        _is_running_analysis = True
        dm.set_busy("AI 포트폴리오 진단 중", "UI")
        try:
            strategy.refresh_holdings_opinion(progress_cb=lambda c, t: dm.set_busy(f"진단({c}/{t})", "UI"))
        finally:
            _is_running_analysis = False
            with dm.data_lock:
                dm.worker_results["GLOBAL"] = "성공"
            dm.clear_busy("UI")
            time.sleep(0.2)
            flush_input()

    def load_investor_data():
        """보유 종목들의 기관/외국인 수급 데이터를 백그라운드로 수집합니다."""
        nonlocal _investor_loaded
        if not dm.cached_holdings:
            _investor_loaded = True
            return
        for h in dm.cached_holdings:
            code = h['pdno']
            try:
                inv = strategy.api.get_investor_trading_trend(code)
                if inv:
                    _investor_cache[code] = inv
            except:
                pass
        _investor_loaded = True

    # 최초 진입 시 수급 데이터 백그라운드 로드
    threading.Thread(target=load_investor_data, daemon=True).start()

    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO()

        is_v = getattr(strategy.api.auth, 'is_virtual', True)
        header_bg = "45" if is_v else "44"
        buf.write(f"\033[{header_bg};37m" + align_kr(" [AI HOLDINGS PORTFOLIO REPORT] ", tw, 'center') + "\033[0m\n")
        buf.write("=" * tw + "\n")

        # 자산 요약
        asset = dm.cached_asset; p_c = "\033[91m" if asset['pnl'] > 0 else "\033[94m" if asset['pnl'] < 0 else "\033[0m"
        p_rt = (asset['pnl'] / (asset['total_asset'] - asset['pnl']) * 100) if (asset['total_asset'] - asset['pnl']) > 0 else 0
        buf.write(align_kr(f" [자산 요약] 총자산: {asset['total_asset']:,.0f} | 평가손익: {p_c}{int(asset['pnl']):+,} ({p_rt:+.2f}%)\033[0m | 현금: {asset['cash']:,.0f}", tw) + "\n")
        buf.write("-" * tw + "\n")
        
        if not dm.cached_holdings:
            buf.write(align_kr("현재 보유 중인 종목이 없습니다.", tw, 'center') + "\n")
        else:
            # 보유 리포트 전용 컬럼: 수익률, 평가손액
            extra_h = [('수익률', 10, 'right'), ('평가손액', 12, 'right')]
            header_str = render_core_header(extra_headers=extra_h)
            buf.write("\033[1m" + header_str + "\033[0m\n")
            buf.write("-" * tw + "\n")
            max_h = max(3, th - 15)
            for h in dm.cached_holdings[:max_h]:
                code = h['pdno']
                pnl_rt = float(h.get('evlu_pfls_rt', 0))
                pnl_amt = int(float(h.get('evlu_pfls_amt', 0)))
                pnl_color = "\033[91m" if pnl_amt > 0 else "\033[94m" if pnl_amt < 0 else "\033[0m"
                
                detail = strategy.api.get_naver_stock_detail(code, force=False)
                inv = _investor_cache.get(code, {})
                
                # 전용 컬럼 값
                rt_str = f"{pnl_color}{pnl_rt:+.2f}%\033[0m"
                amt_str = f"{pnl_color}{pnl_amt:+,}\033[0m"
                extra_cols = [(rt_str, 10, 'right'), (amt_str, 12, 'right')]
                
                row = render_core_row(
                    code=code,
                    name=h['prdt_name'],
                    price=detail.get('price', 0),
                    rate=detail.get('rate', 0.0),
                    per=detail.get('per', 'N/A'),
                    pbr=detail.get('pbr', 'N/A'),
                    mktcap=detail.get('market_cap', 'N/A'),
                    vol=detail.get('vol', 0),
                    amt=detail.get('amt', 0),
                    frgn=inv.get('frgn_net_buy', 0),
                    inst=inv.get('inst_net_buy', 0),
                    extra_columns=extra_cols
                )
                buf.write(row + "\n")

        buf.write("\n\033[1;96m" + " [AI 포트폴리오 매니저의 실시간 진단 의견]" + "\033[0m")
        if hasattr(strategy, 'ai_holdings_update_time') and strategy.ai_holdings_update_time > 0:
            t_str = datetime.fromtimestamp(strategy.ai_holdings_update_time).strftime('%H:%M:%S')
            buf.write(f" (분석완료: {t_str})\n")
        else: buf.write("\n")
        
        if _is_running_analysis:
            buf.write(f"\n  \033[93m🔄 포트폴리오를 입체 분석 중입니다... ({dm.global_busy_msg or '대기중'})\033[0m\n")
        elif strategy.ai_holdings_opinion:
            max_lines = max(3, th - buf.getvalue().count('\n') - 5)
            cleaned_opinion = clean_ai_text(strategy.ai_holdings_opinion)
            lines = [l.strip() for l in cleaned_opinion.split('\n') if l.strip()]
            for line in lines[:max_lines]: buf.write(f"  {line}\n")
        else:
            buf.write("\n  ⚠️ 아직 진단 데이터가 없습니다. 'R' 키를 눌러 AI 분석을 시작하세요.\n")

        # 하단 상태 바 및 키 안내
        buf.write("\n" + "-" * tw + "\n")
        if _is_running_analysis:
            status_line = f" \033[93m[작업중]\033[0m {dm.global_busy_msg}"
        elif hasattr(strategy, 'ai_holdings_update_time') and strategy.ai_holdings_update_time > 0:
            elapsed = time.time() - strategy.ai_holdings_update_time
            t_str = datetime.fromtimestamp(strategy.ai_holdings_update_time).strftime('%H:%M:%S')
            status_line = f" \033[92m[분석완료]\033[0m {t_str} ({int(elapsed//60)}분 전)"
        else:
            status_line = " \033[90m[미분석]\033[0m AI 진단 데이터 없음"
        buf.write(status_line + "\n")
        
        # R키 안내: 10분 이상 경과 또는 미분석 시에만 표시
        has_recent = hasattr(strategy, 'ai_holdings_update_time') and strategy.ai_holdings_update_time > 0 and (time.time() - strategy.ai_holdings_update_time < 600)
        if has_recent:
            buf.write(align_kr(" Q, ESC, SPACE: 종료 | R: AI 재진단 ", tw, 'center') + "\n")
        else:
            buf.write(align_kr(" Q, ESC, SPACE: 종료 | \033[93mR: AI 진단 시작\033[0m ", tw, 'center') + "\n")

        
        # [수정] 부드러운 화면 갱신
        sys.stdout.write("\033[H")
        content_lines = buf.getvalue().split('\n')
        for i in range(min(th, len(content_lines))):
            sys.stdout.write(content_lines[i] + "\033[K" + ("\n" if i < th-1 else ""))
        sys.stdout.write("\033[J")
        sys.stdout.flush()

        
        # 키 입력 루프 (비차단 렌더링을 위해 짧은 대기 후 재진입)
        inner_cycle = 0
        while inner_cycle < 10: 
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == 'r':
                    if not _is_running_analysis:
                        threading.Thread(target=run_bg_analysis, daemon=True).start()
                    break
                elif kl in ['q', 'esc', ' ']:
                    buf.close()
                    return
            time.sleep(0.01)
            inner_cycle += 1
