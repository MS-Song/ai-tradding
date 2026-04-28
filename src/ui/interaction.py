import os
import sys
import time
import threading
import queue
from datetime import datetime
from src.utils import *
from src.theme_engine import get_cached_themes
from src.strategy import PRESET_STRATEGIES
from src.logger import trading_log

# [Task 4] 비동기 커맨드 실행을 위한 작업 큐 및 워커 스레드 도입
command_queue = queue.Queue()

def command_worker():
    """작업 큐에서 명령을 꺼내 순차적으로 실행하는 워커 스레드"""
    while True:
        try:
            item = command_queue.get()
            if item is None: break
            task, args, kwargs = item
            task(*args, **kwargs)
        except Exception as e:
            from src.logger import log_error
            log_error(f"Command Execution Error: {e}")
        finally:
            command_queue.task_done()
            if 'dm' in locals() or 'dm' in globals():
                try:
                    # dm이 전역에 있거나 전달된 경우 결과 기록
                    import __main__
                    if hasattr(__main__, 'dm'):
                        __main__.dm.worker_results["GLOBAL"] = "성공"
                except: pass

# 워커 스레드 시작
threading.Thread(target=command_worker, daemon=True).start()

def draw_recommendation_report(strategy, dm, tw, th):
    import io
    buf = io.StringIO(); buf.write("\033[H\033[2J")
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
        for r in recs:
            code = r['code']; rate = float(r['rate']); color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
            gem_mark = "💎" if r.get('is_gem') else ("📊" if r.get('is_etf') else "  ")
            detail = strategy.api.get_naver_stock_detail(code)
            buf.write(f"{align_kr(r['theme'], 8)} | {align_kr(code, 8)} | {align_kr(gem_mark + r['name'], 14)} | {align_kr(f'{int(float(r.get('price',0))):,}', 9, 'right')} | {align_kr(f'{color}{rate:+.1f}%\033[0m', 7, 'right')} | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(f'{r['score']:.1f}', 6, 'right')} | {r['reason']}\n")
    buf.write("\n" + "-" * tw + "\n\033[1;92m" + " [AI 수석 전략가 입체 분석 및 대응 전략 (초압축)]" + "\033[0m\n")
    
    # [Task 10] 리포트 캐싱 및 1회 분석 로직
    curr_t = time.time()
    if not strategy.rec_report_cache or (curr_t - strategy.rec_report_time > 600): # 10분 캐시
        if recs:
            buf.write("\033[93m  🧠 추천 종목들을 입체 분석 중입니다... 잠시만 기다려주세요.\033[0m\n")
            sys.stdout.write(buf.getvalue()); sys.stdout.flush()
            report = strategy.ai_advisor.get_detailed_report_advice(recs, strategy.current_market_vibe)
            strategy.rec_report_cache = report
            strategy.rec_report_time = curr_t
            # 분석 후 버퍼 갱신을 위해 리턴 후 재호출하거나, 그냥 여기서 다시 그림 (여기서는 간단히 덮어쓰기)
            buf.seek(0); buf.truncate()
            return draw_recommendation_report(strategy, dm, tw, th) # 재귀 호출로 캐시된 데이터 표시
    
    if strategy.rec_report_cache:
        cleaned_report = clean_ai_text(strategy.rec_report_cache)
        for line in cleaned_report.split('\n'):
            if line.strip(): buf.write(f"  > {line.strip()}\n")
    else: buf.write("  ⚠️ 분석된 데이터가 없습니다. 먼저 '8:시황' 분석을 수행하세요.\n")
    
    buf.write("-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue()); sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()

def draw_holdings_detail(strategy, dm):
    import io
    import os
    import threading
    from datetime import datetime
    
    _is_running_analysis = False
    
    def run_bg_analysis():
        nonlocal _is_running_analysis
        _is_running_analysis = True
        dm.set_busy("AI 포트폴리오 진단 중")
        try:
            strategy.refresh_holdings_opinion(progress_cb=lambda c, t: dm.set_busy(f"진단({c}/{t})"))
        finally:
            _is_running_analysis = False
            with dm.data_lock:
                dm.worker_results["GLOBAL"] = "성공"
            dm.clear_busy()
            time.sleep(0.2)
            flush_input()

    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO(); buf.write("\033[H\033[2J")
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
            buf.write("\033[1m" + f"{align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('수익률', 10)} | {align_kr('평가손액', 12)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)}" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            max_h = max(3, th - 15)
            for h in dm.cached_holdings[:max_h]:
                code = h['pdno']; pnl_rt = float(h.get('evlu_pfls_rt', 0)); pnl_amt = int(float(h.get('evlu_pfls_amt', 0)))
                color = "\033[91m" if pnl_amt > 0 else "\033[94m" if pnl_amt < 0 else "\033[0m"
                detail = strategy.api.get_naver_stock_detail(code, force=False)
                buf.write(f"{align_kr(code, 8)} | {align_kr(h['prdt_name'], 14)} | {color}{align_kr(f'{pnl_rt:+.2f}%', 10, 'right')}\033[0m | {color}{align_kr(f'{pnl_amt:+,}', 12, 'right')}\033[0m | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')}\n")

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
        sys.stdout.write(buf.getvalue()); sys.stdout.flush()
        
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

def draw_hot_stocks_detail(strategy, dm, tw, th):
    import io
    buf = io.StringIO()
    buf.write("\033[H\033[2J")
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
        
        # [Architect 개선] 종목 상세 정보를 벌크로 미리 가져와 루프 내 지연 최소화
        codes = [item.get('code', '') for item in hot if item.get('code')]
        realtime_data = strategy.api.get_naver_stocks_realtime(codes)
        
        for idx, item in enumerate(hot, 1):
            code = item.get('code', '')
            r_item = realtime_data.get(code, {})
            price = r_item.get('price', float(item.get('price', 0)))
            rate = r_item.get('rate', float(item.get('rate', 0)))
            color = "\033[91m" if rate >= 0 else "\033[94m"
            
            # 펀더멘털 데이터는 캐시된 정보를 우선 활용 (HTML 크롤링 방지)
            detail = strategy.api.get_naver_stock_detail(code)
            name = r_item.get('name') or item.get('name', '')
            
            buf.write(f"{align_kr(str(idx), 4)} | {align_kr(code, 8)} | {align_kr(name[:10], 14)} | {align_kr(f'{int(float(price)):,}', 10, 'right')} | {color}{align_kr(f'{rate:+.2f}%', 8, 'right')}\033[0m | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(detail.get('sector_per','N/A'), 7, 'right')}\n")
    
    # [Task 10] 인기 테마 리포트 캐싱 (5분/300초 기준)
    curr_t = time.time()
    if not strategy.hot_report_cache or (curr_t - strategy.hot_report_time > 300):
        # 분석 중임을 알리기 위해 현재까지의 내용을 먼저 출력
        buf.write("\n" + "-" * tw + "\n\033[1;95m" + " [트렌드 분석 중... 잠시 기다려주세요]" + "\033[0m\n")
        sys.stdout.write(buf.getvalue()); sys.stdout.flush()
        
        # 실제 AI 분석 수행 (지연 발생)
        report = strategy.ai_advisor.get_hot_stocks_report_advice(hot, themes, strategy.current_market_vibe)
        strategy.hot_report_cache = report
        strategy.hot_report_time = curr_t
        
        # 분석 완료 후 캐시된 데이터를 포함하여 처음부터 다시 그리기 (재귀 호출로 깔끔하게 처리)
        buf.close()
        return draw_hot_stocks_detail(strategy, dm, tw, th)
    
    buf.write("\n\033[1;95m" + " [AI 트렌드 분석가의 인기 테마 진단 (초압축)]" + "\033[0m\n")
    if strategy.hot_report_cache:
        cleaned_hot = clean_ai_text(strategy.hot_report_cache)
        for line in cleaned_hot.split('\n'):
            if line.strip(): buf.write(f"  {line.strip()}\n")
    else:
        buf.write("  ⚠️ 리포트를 생성할 수 없습니다.\n")
        
    buf.write("\n" + "-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue()); sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()


def draw_stock_analysis(strategy, dm, code, tw, th):
    sys.stdout.write("\033[H\033[2J")
    sys.stdout.write("\033[42;30m" + align_kr(f" [AI STOCK ANALYSIS REPORT: {code}] ", tw, 'center') + "\033[0m\n\n")
    sys.stdout.write(f"\033[93m 🚀 {code} 종목 분석을 시작합니다. 잠시만 기다려주세요...\033[0m\n"); sys.stdout.flush()
    dm.show_status(f"🔍 {code} 종목 상세 데이터를 수집 중입니다...")
    detail = strategy.api.get_naver_stock_detail(code); news = strategy.api.get_naver_stock_news(code); name = detail.get('name', '알 수 없는 종목')
    color = "\033[91m" if detail.get('rate', 0) >= 0 else "\033[94m"
    sys.stdout.write(f"\n\033[1;93m [종목 정보] {name} ({code})\033[0m\n")
    sys.stdout.write(f"  * 실시간시세: {int(float(detail.get('price',0))):,}원 ({color}{detail.get('rate',0):+.2f}%\033[0m)\n")
    sys.stdout.write(f"  * 시가총액  : {detail.get('market_cap')}\n")
    sys.stdout.write(f"  * 펀더멘털  : PER {detail.get('per')} | PBR {detail.get('pbr')} | 배당 {detail.get('yield')} | 업종PER {detail.get('sector_per')}\n")
    sys.stdout.write("\n\033[1;96m [최신 소식 및 공시]\033[0m\n")
    if news:
        for n in news[:3]: sys.stdout.write(f"  - {n}\n")
    else: sys.stdout.write("  - 최근 소식 없음\n")
    
    # [Phase 3] 기술적 차트 시각화 추가
    dm.show_status(f"📊 {code} 차트 데이터를 렌더링 중입니다...")
    candles = strategy.api.get_minute_chart_price(code)
    if candles:
        from src.strategy.chart_renderer import ChartRenderer
        chart_txt = ChartRenderer.render_candle_chart(candles, width=tw-15, height=12, title=f"[{name}] 기술적 흐름 (분봉)")
        sys.stdout.write("\n" + chart_txt + "\n\n")
    
    sys.stdout.write("-" * tw + "\n\n"); sys.stdout.flush()
    dm.show_status("🧠 AI가 분석을 위해 데이터를 확인 중입니다...")
    sys.stdout.write("\033[1;95m 🤖 AI가 확인 중입니다... (리포트 생성)\033[0m\n"); sys.stdout.flush()
    report = strategy.ai_advisor.get_stock_report_advice(code, name, detail, news)
    if report:
        sys.stdout.write("\033[1;92m [Gemini AI 심층 분석 의견]\033[0m\n")
        cleaned_report = clean_ai_text(report)
        for line in cleaned_report.split('\n'):
            if line.strip(): sys.stdout.write(f"  {line.strip()}\n")
    else: sys.stdout.write("  ⚠️ 리포트를 생성할 수 없습니다. API 키 또는 네트워크 상태를 확인하세요.\n")
    sys.stdout.write("\n" + "-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n"); sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    dm.show_status("✅ 분석 완료")

def draw_ai_logs_report(strategy, dm):
    import io
    import os
    import copy
    from src.logger import trading_log
    
    current_tab = 1
    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO(); buf.write("\033[H\033[2J")
        is_v = getattr(strategy.api.auth, 'is_virtual', True)
        header_bg = "45" if is_v else "44"
        buf.write(f"\033[{header_bg};37m" + align_kr(" [AI DECISION & LOG REPORT] ", tw, 'center') + "\033[0m\n")
        
        # 탭 메뉴 바
        tab1_s = "\033[7m" if current_tab == 1 else ""
        tab2_s = "\033[7m" if current_tab == 2 else ""
        tab3_s = "\033[7m" if current_tab == 3 else ""
        tab4_s = "\033[7m" if current_tab == 4 else ""
        
        menu_bar = f" {tab1_s} 1.매수거절 \033[0m | {tab2_s} 2.종목교체 \033[0m | {tab3_s} 3.매수사유 \033[0m | {tab4_s} 4.전략수립근거(보유) \033[0m "
        buf.write(align_kr(menu_bar, tw, 'center') + "\n")
        buf.write("=" * tw + "\n\n")

        if current_tab == 1:
            buf.write("\033[1;91m" + " [AI 매수 거절 히스토리 (오늘)]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            rejections = trading_log.data.get("rejections", [])
            today = datetime.now().strftime('%Y-%m-%d')
            today_rejections = [r for r in rejections if r.get('time', '').startswith(today)]
            
            if not today_rejections:
                buf.write("  오늘 기록된 매수 거절 내역이 없습니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('시간', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('모델', 8)} | 거절 사유" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 13)
                for item in today_rejections[:max_items]:
                    t_str = item['time'].split(' ')[-1]
                    m_id = item.get('model_id', '')
                    m_name = trading_log._normalize_model_name(m_id)
                    reason = item['reason'].replace('\n', ' ')
                    # 가용 너비 계산 (시간 10 + 코드 8 + 종목명 14 + 모델 8 + 구분자 12 = 52)
                    avail_w = max(20, tw - 55)
                    if get_visual_width(reason) > avail_w:
                        while get_visual_width(reason) > avail_w - 2: reason = reason[:-1]
                        reason += ".."
                    buf.write(f" {align_kr(t_str, 10)} | {align_kr(item['code'], 8)} | {align_kr(item['name'], 14)} | {align_kr(m_name, 8)} | {reason}\n")

        elif current_tab == 2:
            buf.write("\033[1;92m" + " [종목 한도(8개) 초과에 따른 당일 교체 히스토리]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            today = datetime.now().strftime('%Y-%m-%d')
            today_replacements = [r for r in strategy.replacement_logs if r.get('time', '').startswith(today)]
            
            if not today_replacements:
                buf.write("  오늘 기록된 종목 교체 내역이 없습니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('시간', 10)} | {align_kr('OUT(매도)', 22)} | {align_kr('IN(매수)', 22)} | 교체 사유" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 13)
                for item in today_replacements[:max_items]:
                    t_str = item['time'].split(' ')[-1]
                    out_info = f"[{item.get('out_code','?')}] {item.get('out_name','?')[:12]}"
                    in_info = f"[{item.get('in_code','?')}] {item.get('in_name','?')[:12]}"
                    reason = item['reason'].replace('\n', ' ')
                    # 가용 너비 계산 (10 + 22 + 22 + 9 = 63)
                    avail_w = max(20, tw - 66)
                    if get_visual_width(reason) > avail_w:
                        while get_visual_width(reason) > avail_w - 2: reason = reason[:-1]
                        reason += ".."
                    buf.write(f" {align_kr(t_str, 10)} | {align_kr(out_info, 22)} | {align_kr(in_info, 22)} | {reason}\n")

        elif current_tab == 3:
            buf.write("\033[1;93m" + " [AI 당일 매수 승인 및 진입 근거]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            reasons = trading_log.data.get("buy_reasons", [])
            today = datetime.now().strftime('%Y-%m-%d')
            today_reasons = [r for r in reasons if r.get('time', '').startswith(today)]
            
            if not today_reasons:
                buf.write("  오늘 기록된 매수 승인 사유가 없습니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('시간', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('모델', 8)} | 매수 승인 사유" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 13)
                for item in today_reasons[:max_items]:
                    t_str = item['time'].split(' ')[-1]
                    m_id = item.get('model_id', '')
                    m_name = trading_log._normalize_model_name(m_id)
                    reason = item['reason'].replace('\n', ' ')
                    avail_w = max(20, tw - 55)
                    if get_visual_width(reason) > avail_w:
                        while get_visual_width(reason) > avail_w - 2: reason = reason[:-1]
                        reason += ".."
                    buf.write(f" {align_kr(t_str, 10)} | {align_kr(item['code'], 8)} | {align_kr(item['name'], 14)} | {align_kr(m_name, 8)} | {reason}\n")

        elif current_tab == 4:
            buf.write("\033[1;96m" + " [현재 보유 종목별 AI 전략 수립 근거]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            presets = strategy.preset_eng.preset_strategies
            active_presets = {k: v for k, v in presets.items() if v.get('preset_id') != '00'}
            
            if not active_presets:
                buf.write("  현재 AI 프리셋 전략이 할당된 종목이 없습니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('시간', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('전략명', 12)} | 분석 근거" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                with dm.data_lock:
                    p_items = copy.deepcopy(active_presets)
                
                p_list = []
                for code, p in p_items.items():
                    # 실제로 현재 잔고에 있는 종목만 보여줌
                    if any(h['pdno'] == code for h in dm.cached_holdings):
                        buy_time = p.get('buy_time', '1970-01-01 00:00:00')
                        p_list.append({"code": code, "p": p, "buy_time": buy_time})
                
                p_list.sort(key=lambda x: x['buy_time'] if x['buy_time'] else '0000', reverse=True)
                
                max_items = max(3, th - 13)
                for item in p_list[:max_items]:
                    code = item["code"]
                    p = item["p"]
                    b_time_str = p.get('buy_time', '??').split(' ')[-1] if p.get('buy_time') else '??'
                    detail = strategy.api.get_naver_stock_detail(code)
                    name = detail.get('name', code)
                    reason = p.get('reason', '').replace('\n', ' ')
                    # 가용 너비 계산 (10 + 8 + 14 + 12 + 15 = 59)
                    avail_w = max(20, tw - 62)
                    if get_visual_width(reason) > avail_w:
                        while get_visual_width(reason) > avail_w - 2: reason = reason[:-1]
                        reason += ".."
                    buf.write(f" {align_kr(b_time_str, 10)} | {align_kr(code, 8)} | {align_kr(name, 14)} | {align_kr(p['name'], 12)} | {reason}\n")

        buf.write("\n" + "-" * tw + "\n")
        buf.write(align_kr(" [1, 2, 3, 4]: 탭 전환 | Q, ESC, SPACE: 종료 ", tw, 'center') + "\n")
        sys.stdout.write(buf.getvalue()); sys.stdout.flush()
        
        while True:
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == '1': current_tab = 1; break
                elif kl == '2': current_tab = 2; break
                elif kl == '3': current_tab = 3; break
                elif kl == '4': current_tab = 4; break
                elif kl in ['q', 'esc', ' ']:
                    buf.close()
                    return
            time.sleep(0.01)

def draw_performance_report(strategy, dm):
    import io
    import os
    from src.logger import trading_log
    
    current_tab = 1
    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO(); buf.write("\033[H\033[2J")
        is_v = getattr(strategy.api.auth, 'is_virtual', True)
        header_bg = "45" if is_v else "44"
        buf.write(f"\033[{header_bg};37m" + align_kr(" [AI TRADING PERFORMANCE DASHBOARD] ", tw, 'center') + "\033[0m\n")
        
        # 탭 메뉴 바
        t1 = "\033[7m" if current_tab == 1 else ""
        t2 = "\033[7m" if current_tab == 2 else ""
        t3 = "\033[7m" if current_tab == 3 else ""
        t4 = "\033[7m" if current_tab == 4 else ""
        
        menu = f" {t1} 1.수익 상위(Top 10) \033[0m | {t2} 2.손실 상위(Shame 10) \033[0m | {t3} 3.금일 투자 성과 \033[0m | {t4} 4.투자 적중 \033[0m "
        buf.write(align_kr(menu, tw, 'center') + "\n")
        buf.write("=" * tw + "\n\n")

        if current_tab == 1:
            # 1. 수익금 TOP 10
            top_stocks = trading_log.get_top_profitable_stocks(10)
            buf.write("\033[1;93m" + " [종목별 누적 수익금 TOP 10 (Hall of Fame)]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            if not top_stocks:
                buf.write("  누적 수익 데이터를 수집 중입니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('순위', 4)} | {align_kr('코드', 8)} | {align_kr('종목명', 12)} | {align_kr('TOTAL (회수)', 18)} | {align_kr('모델별 (회수)', 25)}" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 14)
                item_count = 0
                for i, (code, s) in enumerate(top_stocks, 1):
                    if item_count >= max_items: break
                    color = "\033[91m"
                    total_val = f"{int(s['total_profit']):+,} ({s['count']}회)"
                    buf.write(f" {align_kr(str(i), 4)} | {align_kr(code, 8)} | {align_kr(s['name'][:12], 12)} | {color}{align_kr(total_val, 18, 'right')}\033[0m | ")
                    m_items = list(s['models'].items())
                    if m_items:
                        first_m, first_s = m_items[0]
                        m_val = f"{first_m} {int(first_s['profit']):+,} ({first_s['count']}회)"
                        m_color = "\033[91m" if first_s['profit'] > 0 else "\033[94m" if first_s['profit'] < 0 else "\033[90m"
                        buf.write(f"{m_color}{align_kr(m_val, 25, 'left')}\033[0m\n")
                        item_count += 1
                        for m_name, m_stat in m_items[1:]:
                            if item_count >= max_items: break
                            m_val = f"{m_name} {int(m_stat['profit']):+,} ({m_stat['count']}회)"
                            m_color = "\033[91m" if m_stat['profit'] > 0 else "\033[94m" if m_stat['profit'] < 0 else "\033[90m"
                            buf.write(f" {' '*4} | {' '*8} | {' '*12} | {' '*18} | {m_color}{align_kr(m_val, 25, 'left')}\033[0m\n")
                            item_count += 1
                    else: buf.write("\n")
                    buf.write("-" * tw + "\n"); item_count += 1

        elif current_tab == 2:
            # 2. 손실금 TOP 10
            loss_stocks = trading_log.get_top_loss_stocks(10)
            buf.write("\033[1;91m" + " [종목별 누적 손실금 TOP 10 (Hall of Shame)]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            if not loss_stocks:
                buf.write("  누적 손실 데이터가 없습니다 (클린 포트폴리오!).\n")
            else:
                buf.write("\033[1m" + f" {align_kr('순위', 4)} | {align_kr('코드', 8)} | {align_kr('종목명', 12)} | {align_kr('TOTAL (회수)', 18)} | {align_kr('모델별 (회수)', 25)}" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 14)
                item_count = 0
                for i, (code, s) in enumerate(loss_stocks, 1):
                    if item_count >= max_items: break
                    color = "\033[94m"
                    total_val = f"{int(s['total_profit']):+,} ({s['count']}회)"
                    buf.write(f" {align_kr(str(i), 4)} | {align_kr(code, 8)} | {align_kr(s['name'][:12], 12)} | {color}{align_kr(total_val, 18, 'right')}\033[0m | ")
                    m_items = list(s['models'].items())
                    if m_items:
                        first_m, first_s = m_items[0]
                        m_val = f"{first_m} {int(first_s['profit']):+,} ({first_s['count']}회)"
                        m_color = "\033[91m" if first_s['profit'] > 0 else "\033[94m" if first_s['profit'] < 0 else "\033[90m"
                        buf.write(f"{m_color}{align_kr(m_val, 25, 'left')}\033[0m\n")
                        item_count += 1
                        for m_name, m_stat in m_items[1:]:
                            if item_count >= max_items: break
                            m_val = f"{m_name} {int(m_stat['profit']):+,} ({m_stat['count']}회)"
                            m_color = "\033[91m" if m_stat['profit'] > 0 else "\033[94m" if m_stat['profit'] < 0 else "\033[90m"
                            buf.write(f" {' '*4} | {' '*8} | {' '*12} | {' '*18} | {m_color}{align_kr(m_val, 25, 'left')}\033[0m\n")
                            item_count += 1
                    else: buf.write("\n")
                    buf.write("-" * tw + "\n"); item_count += 1

        elif current_tab == 3:
            # 3. 금일 투자 성과 (개편된 좌우 테이블 레이아웃)
            from datetime import datetime as dt_cls
            today = dt_cls.now().strftime('%Y-%m-%d')
            
            # --- 데이터 수집 ---
            buy_trades = []; sell_trades = []; sell_types = ["익절", "손절", "청산", "확정", "매도", "종료"]
            with trading_log.lock:
                for t in trading_log.data.get("trades", []):
                    if not t["time"].startswith(today): continue
                    t_type = t.get("type", "")
                    if "매수" in t_type: buy_trades.append(t)
                    elif any(x in t_type for x in sell_types): sell_trades.append(t)
            
            def get_current_price(code):
                for h in dm.cached_holdings:
                    if h.get("pdno") == code: return int(float(h.get("prpr", 0)))
                try:
                    detail = strategy.api.get_naver_stock_detail(code)
                    return int(float(detail.get("price", 0)))
                except: return 0

            kospi_rate = dm.cached_market_data.get("KOSPI", {}).get("rate", 0)
            kosdaq_rate = dm.cached_market_data.get("KOSDAQ", {}).get("rate", 0)
            realized_profit = trading_log.get_daily_profit()
            asset = dm.cached_asset
            daily_pnl_rate = asset.get('daily_pnl_rate', 0.0); daily_pnl_amt = asset.get('daily_pnl_amt', 0.0)

            # ① 브리핑 헤더
            r_color = "\033[91m" if realized_profit > 0 else "\033[94m" if realized_profit < 0 else "\033[93m"
            d_color = "\033[91m" if daily_pnl_rate > 0 else "\033[94m" if daily_pnl_rate < 0 else "\033[93m"
            k_color = "\033[91m" if kospi_rate >= 0 else "\033[94m"
            kd_color = "\033[91m" if kosdaq_rate >= 0 else "\033[94m"
            buf.write("\033[1;96m" + " [금일 투자 성과 브리핑]" + "\033[0m\n")
            buf.write(f" 📋 {today} | 실현: {r_color}{realized_profit:+,}원\033[0m | 평가: {d_color}{int(daily_pnl_amt):+,}원 ({abs(daily_pnl_rate):.2f}%)\033[0m | KOSPI: {k_color}{kospi_rate:+.2f}%\033[0m | KOSDAQ: {kd_color}{kosdaq_rate:+.2f}%\033[0m\n")
            buf.write("-" * tw + "\n")

            # ② [순서 변경] 투자 성과 진단 (2번째 배치)
            my_rate = daily_pnl_rate; market_rate = kospi_rate; alpha = my_rate - market_rate
            if my_rate > 0 and market_rate > 0:
                verdict_msg = f"\033[91m✅ 상승장 초과 수익! Alpha: +{alpha:.2f}%p\033[0m" if alpha >= 0 else f"\033[93m⚠️ 시장 대비 소폭 지체. Alpha: {alpha:.2f}%p\033[0m"
            elif my_rate > 0 and market_rate <= 0:
                verdict_msg = f"\033[91m🏆 하락장 수익! 탁월한 선정. Alpha: {alpha:+.2f}%p\033[0m"
            elif my_rate <= 0 and market_rate > 0:
                verdict_msg = f"\033[94m🚨 시장 소외! 전략 재점검 필요. Alpha: {alpha:+.2f}%p\033[0m"
            else:
                verdict_msg = f"\033[93m🛡️ 하락장 방어 성공. Alpha: {alpha:+.2f}%p\033[0m" if alpha >= 0 else f"\033[94m❌ 리스크 관리 강화 필요. Alpha: {alpha:+.2f}%p\033[0m"
            buf.write(f" \033[1;93m[📊 투자 성과 진단]\033[0m 내 수익률({d_color}{my_rate:+.2f}%\033[0m) vs KOSPI({k_color}{market_rate:+.2f}%\033[0m) → {verdict_msg}\n")
            buf.write("-" * tw + "\n")

            # ③ [좌우 배치] 매수/매도 테이블
            other_w = 53 # 가격(8)|현재(8)|평균(8)|손익(10)|방법(8)|평가(6) = 48 + 5 separators
            half_w = tw // 2
            name_w = max(12, half_w - other_w - 2)
            
            def smart_align(text, width):
                if get_visual_width(text) <= width:
                    return align_kr(text, width)
                t = str(text)
                while get_visual_width(t + "..") > width and len(t) > 0:
                    t = t[:-1]
                return align_kr(t + "..", width)

            def format_trade_row(info, is_buy):
                code = info['code']; name = info['name']
                # [개선] 오늘 매수평단가가 아닌, 계좌 실제 평단가(Cost Basis)를 우선 표시하여 사용자 혼선 방지
                price = info['avg_price'] 
                cur = get_current_price(code)
                ma_20 = dm.ma_20_cache.get(code, 0)
                
                # 손익 계산
                if is_buy:
                    # 매수 쪽은 현재 들고 있는 비중의 평가손익 (계좌 평단 기준)
                    pnl = (cur - price) * info['total_qty']
                else:
                    # 매도 쪽은 오늘 확정된 실현손익
                    pnl = info['total_pnl']
                
                p_color = "\033[91m" if pnl > 0 else "\033[94m" if pnl < 0 else ""
                
                # [개선] Verdict(평가) 로직 고도화: 단순 가격 비교가 아닌 손익과 시황을 결합하여 입체적 진단
                if is_buy:
                    # 매수(Entry) 평가: 현재 수익권인가?
                    if pnl > 0: verdict = "✅성공"
                    elif pnl < 0: verdict = "❌실패"
                    else: verdict = "➖보합"
                    v_color = "\033[91m" if pnl > 0 else ("\033[94m" if pnl < 0 else "")
                else:
                    # 매도(Exit) 평가: 타이밍이 적절했는가?
                    if pnl > 0:
                        if cur <= price: verdict = "✅완벽" # 최고가 매도 또는 매도 후 하락 (익절 성공)
                        else: verdict = "❌일찍" # 매도 후 더 오름 (수익 극대화 실패)
                    else:
                        if cur <= price: verdict = "🛡️방어" # 손절 후 더 하락 (추가 손실 방어 성공)
                        else: verdict = "❌손절" # 손절 후 반등 (최악의 타이밍 손절)
                    v_color = "\033[91m" if verdict in ["✅완벽", "🛡️방어"] else "\033[94m"
                
                ma_str = f"{int(ma_20):,}" if ma_20 > 0 else "-"
                
                row = (f"{smart_align(f'[{code}]{name}', name_w)}|"
                       f"{align_kr(f'{int(price):,}', 8, 'right')}|"
                       f"{align_kr(f'{int(cur):,}', 8, 'right')}|"
                       f"{align_kr(ma_str, 8, 'right')}|"
                       f"{p_color}{align_kr(f'{int(pnl):,}', 10, 'right')}\033[0m|"
                       f"{align_kr(info['type'][:4], 8)}|"
                       f"{v_color}{align_kr(verdict, 6)}\033[0m")
                return row

            # 데이터 요약 (계좌 평단가 및 실현 손익 기반 역추산 평단가 적용)
            buy_summary = {}
            for t in buy_trades:
                c = t['code']; q = int(t['qty']); p = float(t['price'])
                if c not in buy_summary:
                    # 계좌에서 실제 보유 중인 종목이라면 평단가(Cost Basis)를 가져옴
                    acc_avg = 0.0
                    for h in dm.cached_holdings:
                        if h.get('pdno') == c:
                            acc_avg = float(h.get('pchs_avg_pric', 0))
                            break
                    buy_summary[c] = {"name": t['name'], "code": c, "total_amt": 0, "total_qty": 0, "type": t['type'], "acc_avg": acc_avg}
                
                buy_summary[c]["total_amt"] += p * q; buy_summary[c]["total_qty"] += q
                # 계좌 정보가 있으면 계좌 평단 사용, 없으면 오늘 매수 평균 사용
                if buy_summary[c]["acc_avg"] > 0:
                    buy_summary[c]["avg_price"] = buy_summary[c]["acc_avg"]
                else:
                    buy_summary[c]["avg_price"] = buy_summary[c]["total_amt"] / buy_summary[c]["total_qty"]

            sell_summary = {}
            for t in sell_trades:
                c = t['code']; q = int(t['qty']); p = float(t['price']); pr = float(t.get('profit', 0))
                if c not in sell_summary: 
                    sell_summary[c] = {"name": t['name'], "code": c, "total_amt": 0, "total_qty": 0, "total_pnl": 0, "type": t['type']}
                sell_summary[c]["total_amt"] += p * q; sell_summary[c]["total_qty"] += q; sell_summary[c]["total_pnl"] += pr; sell_summary[c]["avg_price"] = sell_summary[c]["total_amt"] / sell_summary[c]["total_qty"]

            # [추가] 매도된 종목 중 오늘 매수 이력이 있는 경우, 매수 섹션의 평단가도 실현 손익 기준으로 보정 (이미 잔고에 없을 때)
            for c, b_info in buy_summary.items():
                if b_info["acc_avg"] == 0 and c in sell_summary:
                    # 실현 손익 기반으로 원래의 평단가 역추산: (매도가 - (수익금 / 수량))
                    s_info = sell_summary[c]
                    if s_info["total_qty"] > 0:
                        derived_buy_p = s_info["avg_price"] - (s_info["total_pnl"] / s_info["total_qty"])
                        b_info["avg_price"] = derived_buy_p
            
            buy_list = list(buy_summary.values()); sell_list = list(sell_summary.values()); max_rows = max(len(buy_list), len(sell_list))
            
            # 성과 계산
            buy_wins = 0
            for b in buy_list:
                cur = get_current_price(b['code'])
                if cur >= b['avg_price']: buy_wins += 1
            buy_rate = (buy_wins / len(buy_list) * 100) if buy_list else 0
            
            sell_wins = 0
            for s in sell_list:
                cur = get_current_price(s['code'])
                if cur <= s['avg_price']: sell_wins += 1
            sell_rate = (sell_wins / len(sell_list) * 100) if sell_list else 0

            h_buy = f"\033[1;42;1;37m{align_kr(f' [📈 매수 성과: {buy_wins}/{len(buy_list)} ({buy_rate:.0f}%)] ', half_w-1, 'center')}\033[0m"
            h_sell = f"\033[1;41;1;37m{align_kr(f' [📉 매도 성과: {sell_wins}/{len(sell_list)} ({sell_rate:.0f}%)] ', tw-half_w-1, 'center')}\033[0m"
            buf.write(f"{h_buy} {h_sell}\n")
            t_head = f"{smart_align('종목(코드)명', name_w)}|{align_kr('매수가', 8)}|{align_kr('현재가', 8)}|{align_kr('평균선', 8)}|{align_kr('평가손익', 10)}|{align_kr('방법', 8)}|{align_kr('평가', 6)}"
            t_head_s = f"{smart_align('종목(코드)명', name_w)}|{align_kr('매도가', 8)}|{align_kr('현재가', 8)}|{align_kr('평균선', 8)}|{align_kr('실현손익', 10)}|{align_kr('방법', 8)}|{align_kr('평가', 6)}"
            buf.write(f"\033[1m{align_kr(t_head, half_w-1)} \033[1m{align_kr(t_head_s, tw-half_w-1)}\033[0m\n")
            buf.write("-" * (half_w-1) + " " + "-" * (tw-half_w-1) + "\n")
            for i in range(max(1, max_rows)):
                b_row = format_trade_row(buy_list[i], True) if i < len(buy_list) else " " * (half_w - 1)
                s_row = format_trade_row(sell_list[i], False) if i < len(sell_list) else ""
                buf.write(f"{align_kr(b_row, half_w-1)} {s_row}\n")
            buf.write("-" * tw + "\n")
            
            # ④ 모델별 누적 성과 (축약)
            model_stats = trading_log.get_model_performance()
            if model_stats:
                buf.write("\033[1;95m [🤖 모델별 누적 성과]\033[0m ")
                m_line = ""
                for m, s in model_stats.items():
                    p_color = "\033[91m" if s['total_profit'] > 0 else "\033[94m"
                    m_line += f"{m}: {p_color}{int(s['total_profit']):+,}원\033[0m | "
                buf.write(m_line.rstrip(" | ") + "\n")

        elif current_tab == 4:
            # 4. 투자 적중 (매매 복기 누적 분석)
            retro = getattr(strategy, 'retrospective', None)
            buf.write("\033[1;95m" + " [투자 적중 분석 (매매 복기 누적 리포트)]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            if not retro: buf.write("  ⚠️ 투자 적중 엔진이 초기화되지 않았습니다.\n")
            else:
                stats = retro.get_cumulative_stats()
                if stats["total_days"] > 0:
                    net_color = "\033[91m" if stats["net_profit"] > 0 else "\033[94m"; wr_color = "\033[91m" if stats["win_rate"] >= 50 else "\033[94m"
                    buf.write(f" \033[1m[누적 {stats['total_days']}일]\033[0m 승률: {wr_color}{stats['win_rate']:.1f}%\033[0m | 수익종목: \033[91m{int(stats['total_profit']):+,}\033[0m | 손실종목: \033[94m{int(stats['total_loss']):+,}\033[0m | 순이익: {net_color}{int(stats['net_profit']):+,}\033[0m\n")
                    buf.write("-" * tw + "\n")
                reports = retro.get_reports(limit=3)
                if not reports:
                    buf.write("\n  📭 아직 생성된 복기 리포트가 없습니다.\n  ℹ️ 매일 오후 4시(16:00)에 자동 생성되며, 장 마감 후 30분마다 업데이트됩니다.\n")
                else:
                    max_l = max(5, th - 16); l_cnt = 0
                    for date_str, report in reports:
                        if l_cnt >= max_l: break
                        gen_t = report.get("generated_at", "?").split(' ')[-1]; vibe = report.get("market_vibe", "N/A")
                        buf.write(f"\n \033[1;93m📊 [{date_str}]\033[0m 생성: {gen_t} | 갱신: {report.get('update_count', 1)}회 | 장세: {vibe}\n"); l_cnt += 1
                        for s in report.get("top_profits", []):
                            if l_cnt >= max_l: break
                            buf.write(f"  \033[92m🟢 {s.get('name', '?')}\033[0m \033[91m{int(s.get('total_profit', 0)):+,}\033[0m원" + (f" (종가:{int(s['closing_price']):,}원)" if s.get("closing_price") else "") + "\n"); l_cnt += 1
                        for s in report.get("top_losses", []):
                            if l_cnt >= max_l: break
                            buf.write(f"  \033[91m🔴 {s.get('name', '?')}\033[0m \033[94m{int(s.get('total_profit', 0)):+,}\033[0m원" + (f" (종가:{int(s['closing_price']):,}원)" if s.get("closing_price") else "") + "\n"); l_cnt += 1
                        ai_text = report.get("ai_analysis", "")
                        if ai_text:
                            cleaned_ai = clean_ai_text(ai_text)
                            for line in cleaned_ai.split('\n'):
                                if l_cnt >= max_l: break
                                s_line = line.strip()
                                if s_line:
                                    if get_visual_width(s_line) > tw - 4:
                                        while get_visual_width(s_line) > tw - 6: s_line = s_line[:-1]
                                        s_line += ".."
                                    buf.write(f"  {s_line}\n"); l_cnt += 1
                        buf.write("-" * tw + "\n"); l_cnt += 1

        buf.write("\n" + "-" * tw + "\n")
        buf.write(align_kr(" [1, 2, 3, 4]: 탭 전환 | Q, ESC, SPACE: 종료 ", tw, 'center') + "\n")
        sys.stdout.write(buf.getvalue()); sys.stdout.flush()
        
        while True:
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == '1': current_tab = 1; break
                elif kl == '2': current_tab = 2; break
                elif kl == '3': current_tab = 3; break
                elif kl == '4': current_tab = 4; break
                elif kl in ['q', 'esc', ' ']:
                    buf.close()
                    return
            time.sleep(0.01)

def get_input(dm, prompt, tw, prompt_mode=None):
    """[Task 4] 입력 중에도 렌더링이 멈추지 않도록 콜백 연동"""
    dm.current_prompt_mode = prompt_mode
    def cb(p, b):
        dm.input_prompt = p
        dm.input_buffer = b
        dm.is_input_active = bool(p)
        from src.ui.renderer import draw_tui
        draw_tui(dm.strategy, dm, 0) # DataManager의 상태를 사용하므로 인자 제거
    res = input_with_esc(prompt, tw, callback=cb)
    dm.is_input_active = False
    dm.current_prompt_mode = None
    return res

def perform_interaction(key, api, strategy, dm, cycle):
    try:
        import os
        import sys
        import time
        import threading
        from src.ui.renderer import draw_tui, draw_manual_page
        from src.utils import get_key_immediate, restore_terminal_settings, exit_alt_screen, enter_alt_screen, set_terminal_raw, flush_input, get_market_name
        from src.config_init import ensure_env, get_config
        from src.auth import KISAuth
        from src.theme_engine import get_cached_themes
        from src.strategy import PRESET_STRATEGIES
        from dotenv import load_dotenv
        
        flush_input()
        key_map = {'ㅂ': 'q', 'ㅃ': 'q', 'ㅅ': 's', 'ㄴ': 's', 'ㅈ': 's', 'ㅁ': 'a', 'ㅣ': 'l', 'ㅠ': 'b', 'ㅇ': 'd', 'ㅎ': 'h', 'ㅔ': 'p', 'ㅖ': 'p'}
        mode = (key[-1] if 'alt+' in key else key).lower()
        if mode in key_map: mode = key_map[mode]
        
        if mode not in ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'd', 'h', 'l', 'm', 'q', 's', 'p', 'u']: return
        
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24

        f_h = dm.cached_holdings if dm.ranking_filter == "ALL" else [h for h in dm.cached_holdings if get_market_name(h.get('pdno','')) == dm.ranking_filter]
        
        if mode == 'q':
            restore_terminal_settings(); exit_alt_screen()
            print("\n[AI TRADING SYSTEM] 사용자에 의해 안전하게 종료되었습니다."); os._exit(0)
        
        if mode in ['m', 'l', 'b', 'd', 'h', 'a', 'p']:
            def run_display_task():
                status_map = {
                    'm': "사용자 매뉴얼 조회 중", 'l': "시스템 로그 조회 중", 'b': "보유 종목 진단 중", 'd': "추천 종목 상세 조회 중",
                    'h': "인기 테마 리포트 조회 중", 'a': "AI 결정 로그 조회 중", 'p': "성과 대시보드 조회 중"
                }
                dm.is_full_screen_active = True
                dm.set_busy(status_map.get(mode, f"{mode} 처리"))
                try:
                    restore_terminal_settings()
                    size = os.get_terminal_size(); tw_r, th_r = size.columns, size.lines
                    if mode == 'm': draw_manual_page()
                    elif mode == 'l':
                        from src.ui.renderer import draw_trading_logs
                        draw_trading_logs(strategy, dm)
                    elif mode == 'b': draw_holdings_detail(strategy, dm)
                    elif mode == 'd': draw_recommendation_report(strategy, dm, tw_r, th_r)
                    elif mode == 'h': draw_hot_stocks_detail(strategy, dm, tw_r, th_r)
                    elif mode == 'a': draw_ai_logs_report(strategy, dm)
                    elif mode == 'p': draw_performance_report(strategy, dm)
                    # 복귀 시 화면 깨짐 방지: alt screen을 새로 여는 대신 현재 화면을 확실히 청소
                    sys.stdout.write("\033[H\033[2J"); sys.stdout.flush()
                    set_terminal_raw(); flush_input(); dm.last_size = (0, 0)
                except Exception as display_e:
                    from src.logger import log_error
                    log_error(f"Display Task Error ({mode}): {display_e}")
                finally: 
                    dm.clear_busy()
                    dm.is_full_screen_active = False
            threading.Thread(target=run_display_task, daemon=True).start()
            return
    
        if mode == '7':
            res = get_input(dm, "> 분석할 종목 번호 또는 코드(6자리) 입력: ", tw)
            if res:
                res = res.strip()
                target_code = ""
                if res.isdigit() and len(res) <= 3:
                    idx = int(res)
                    if 0 < idx <= len(f_h): target_code = f_h[idx-1]['pdno']
                elif len(res) == 6: target_code = res
                if target_code:
                    def run_analysis_task(t_code):
                        dm.is_full_screen_active = True
                        dm.set_busy("종목 분석 중")
                        try:
                            restore_terminal_settings()
                            size = os.get_terminal_size(); tw_a, th_a = size.columns, size.lines
                            draw_stock_analysis(strategy, dm, t_code, tw_a, th_a)
                            sys.stdout.write("\033[H\033[2J"); sys.stdout.flush()
                            set_terminal_raw(); flush_input(); dm.last_size = (0, 0)
                        except Exception as analysis_e:
                            from src.logger import log_error
                            log_error(f"Analysis Task Error ({t_code}): {analysis_e}")
                        finally:
                            dm.clear_busy()
                            dm.is_full_screen_active = False
                    threading.Thread(target=run_analysis_task, args=(target_code,), name=f"[{target_code}_분석]", daemon=True).start()
            return
    
        if mode == 's':
            dm.show_status("⚙️ 환경 설정 모드로 전환합니다...")
            draw_tui(strategy, dm, cycle)
            dm.is_full_screen_active = True
            try:
                time.sleep(0.5)
                restore_terminal_settings(); exit_alt_screen()
                os.system('cls' if os.name == 'nt' else 'clear')
                print("\n" + "="*60 + "\n ⚙️  KIS-Vibe-Trader 환경 설정 모드\n" + "="*60); flush_input()
                ensure_env(force=True); load_dotenv(override=True); config = get_config()
                new_auth = KISAuth(); api.auth = new_auth; api.domain = new_auth.domain; api.clear_cache(); strategy.api = api
                strategy.reload_config(config)
                enter_alt_screen(); set_terminal_raw(); dm.last_size = (0, 0)
                dm.set_busy("데이터 동기화 중...")
                is_v = getattr(api.auth, 'is_virtual', True)
                dm.update_all_data(is_v, force=True)
                dm.show_status("✅ 모든 데이터 동기화 완료")
                dm.clear_busy()
                dm.is_full_screen_active = False
                strategy.is_ready = True
                dm.add_log("🔄 시스템 설정 반영 및 데이터 동기화가 완료되었습니다.")
                draw_tui(strategy, dm, cycle)
            finally:
                dm.is_full_screen_active = False
            return
    
        if mode == '1':
            res = get_input(dm, "> 매도 [번호 수량 가격] 입력: ", tw)
            if res:
                inp = res.strip().split()
                if inp and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                    h = f_h[int(inp[0])-1]; code, name = h['pdno'], h['prdt_name']
                    qty = int(float(inp[1])) if len(inp) > 1 and inp[1].replace('.','',1).isdigit() else int(float(h['hldg_qty']))
                    price = int(float(inp[2])) if len(inp) > 2 and inp[2].replace('.','',1).isdigit() else 0
                    def task_sell():
                        dm.set_busy("매도 처리")
                        try:
                            p_disp = f"{price:,}원" if price > 0 else "시장가"
                            dm.add_trading_log(f"[{code}] {name} {p_disp} {qty}주 매도시도")
                            success, msg = api.order_market(code, qty, False, price)
                            if success:
                                curr_p = float(api.get_naver_stock_detail(code).get('price', price)) if price == 0 else float(price)
                                profit = (curr_p - float(h.get('pchs_avg_pric', 0))) * qty
                                trading_log.log_trade("수동매도", code, name, curr_p, qty, f"수동 매도 ({p_disp})", profit=profit, model_id="수동")
                                dm.add_trading_log(f"✅ [{name}] {qty}주 매도 완료 ({p_disp})")
                                dm.show_status(f"✅ 매도 성공: {name}"); dm.update_all_data(dm.api.auth.is_virtual, force=True)
                            else:
                                from src.logger import log_error
                                log_error(f"수동 매도 실패 ({h['prdt_name']}): {msg}")
                                dm.show_status(f"❌ 매도 실패: {msg}", True)
                        finally: dm.clear_busy()
                    threading.Thread(target=task_sell, name=f"[{code}_{name}_매도]", daemon=True).start()

        elif mode == 'u':
            if not dm.update_info.get("has_update"):
                dm.show_status("✨ 현재 최신 버전을 사용 중입니다.")
                return
            
            res = get_input(dm, f"> v{dm.update_info['latest_version']} 업데이트를 진행할까요? (y/n): ", tw)
            if res and res.lower() == 'y':
                def task_update():
                    dm.set_busy("업데이트 다운로드 중", "GLOBAL")
                    try:
                        from src.updater import download_update, apply_update_and_restart
                        import platform
                        
                        is_windows = platform.system() == "Windows"
                        new_bin = "KIS-Vibe-Trader_new.exe" if is_windows else "KIS-Vibe-Trader-Linux_new"
                        
                        def prog_cb(d, t):
                            dm.set_busy(f"다운로드 중 ({d/t*100:.1f}%)", "GLOBAL")
                        
                        url = dm.update_info["download_url"]
                        if not url:
                            dm.show_status("❌ 다운로드 URL을 찾을 수 없습니다.", True)
                            return

                        success = download_update(url, new_bin, progress_cb=prog_cb)
                        if success:
                            dm.show_status("✅ 다운로드 완료! 2초 후 재기동합니다...")
                            dm.notifier.notify_alert("업데이트 적용", f"🛠️ v{dm.update_info['latest_version']} 업데이트를 적용하고 재기동합니다.")
                            time.sleep(2)
                            apply_update_and_restart(new_bin)
                        else:
                            dm.show_status("❌ 업데이트 다운로드 실패", True)
                    except Exception as e:
                        from src.logger import log_error
                        log_error(f"Update Process Error: {e}")
                        dm.show_status(f"❌ 업데이트 오류: {e}", True)
                    finally:
                        dm.clear_busy("GLOBAL")
                
                threading.Thread(target=task_update, daemon=True).start()

        elif mode == '2':
            res = get_input(dm, "> 매수 [코드 수량 가격] 입력: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 2:
                    code, qty = inp[0], int(inp[1]); price = int(inp[2]) if len(inp) > 2 and inp[2].isdigit() else 0
                    def task_buy():
                        dm.set_busy("매수 처리")
                        try:
                            detail = api.get_naver_stock_detail(code); name = detail.get('name', code)
                            p_disp = f"{price:,}원" if price > 0 else "시장가"
                            dm.add_trading_log(f"[{code}] {name} {p_disp} {qty}주 매입시도")
                            is_new = not any(h['pdno'] == code for h in dm.cached_holdings)
                            success, msg = api.order_market(code, qty, True, price)
                            if success:
                                curr_p = float(api.get_naver_stock_detail(code).get('price', price)) if price == 0 else float(price)
                                trading_log.log_trade("수동매수", code, name, curr_p, qty, f"수동 매수 ({p_disp})", model_id="수동")
                                dm.add_trading_log(f"✅ [{name}] {qty}주 매수 완료 ({p_disp})")
                                dm.show_status(f"✅ 매수 성공: {name}")
                                if is_new:
                                    try:
                                        strategy.auto_assign_preset(code, name)
                                    except Exception as ai_e:
                                        from src.logger import log_error
                                        log_error(f"AI 전략 할당 실패: {ai_e}")
                                dm.update_all_data(dm.api.auth.is_virtual, force=True)
                            else:
                                from src.logger import log_error
                                log_error(f"수동 매수 실패 ({top_ai['name']}): {msg}")
                                dm.show_status(f"❌ 매수 실패: {msg}", True)
                        finally: dm.clear_busy()
                    threading.Thread(target=task_buy, name=f"[{code}_{name}_매수]", daemon=True).start()

        elif mode == '3':
            res = get_input(dm, "> 수정 [번호 TP SL] 또는 [TP SL]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 2 and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                    h = f_h[int(inp[0])-1]
                    if inp[1].lower() == 'r': strategy.reset_manual_threshold(h['pdno']); dm.show_status(f"🔄 초기화: {h['prdt_name']}")
                    elif len(inp) >= 3:
                        try: strategy.set_manual_threshold(h['pdno'], float(inp[1]), float(inp[2])); dm.show_status(f"✅ 설정: {h['prdt_name']}")
                        except: dm.show_status("❌ 입력 오류", True)
                elif len(inp) == 2:
                    try: strategy.base_tp, strategy.base_sl = float(inp[0]), float(inp[1]); strategy._save_all_states(); dm.show_status(f"✅ 기본 전략 변경")
                    except: dm.show_status("❌ 입력 오류", True)

        elif mode == '4':
            res = get_input(dm, "> AI추천설정 [금액 한도 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 3:
                    try: strategy.ai_config.update({"amount_per_trade": int(inp[0]), "max_investment_per_stock": int(inp[1]), "auto_mode": inp[2].lower() == 'y'}); strategy._save_all_states(); dm.show_status(f"✨ 설정 완료")
                    except: dm.show_status("❌ 입력 오류", True)

        elif mode == '8':
            def task_ai():
                dm.set_busy("AI분석")
                try:
                    def prog_cb(c, t, m="AI분석"): 
                        if "분석 중:" in m: m = "AI추천"
                        dm.set_busy(f"{m}({c}/{t})")
                    def item_cb(i): 
                        with dm.data_lock: 
                            if not any(r['code'] == i['code'] for r in strategy.ai_recommendations):
                                strategy.ai_recommendations.append(i)
                                strategy.ai_recommendations.sort(key=lambda x: x['score'], reverse=True)
                    with dm.data_lock: strategy.ai_recommendations = []
                    strategy.determine_market_trend(force_ai=True)
                    strategy.update_ai_recommendations(get_cached_themes(), dm.cached_hot_raw, dm.cached_vol_raw, progress_cb=prog_cb, on_item_found=item_cb)
                    advice = strategy.get_ai_advice(progress_cb=lambda c, t: prog_cb(c, t, "심층분석"))
                    if advice and "⚠️" not in advice:
                        dm.show_status("✅ AI 분석 완료")
                        if strategy.parse_and_apply_ai_strategy():
                            if strategy.ai_config.get("auto_apply"): dm.show_status("🚀 전략 자동 반영됨")
                    else:
                        from src.logger import log_error
                        log_error(f"AI 시황 분석 실패 (결과 없음 또는 ⚠️ 포함) | Vibe: {strategy.current_market_vibe}")
                        dm.show_status(f"❌ AI 분석 실패", True)
                finally:
                    strategy.is_ready = True
                    dm.clear_busy()
            command_queue.put((task_ai, (), {}))

        elif mode == '5':
            res = get_input(dm, "> 물타기설정 [트리거% 금액 한도 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 4:
                    try:
                        trig, amt, lim = float(inp[0]), int(inp[1]), int(inp[2])
                        if amt < 1000: amt *= 10000
                        if lim < 1000: lim *= 10000
                        strategy.bear_config.update({"min_loss_to_buy": trig, "average_down_amount": amt, "max_investment_per_stock": lim, "auto_mode": inp[3].lower() == 'y'}); strategy._save_all_states(); dm.show_status(f"✅ 물타기 설정 완료")
                    except: dm.show_status("❌ 입력 오류", True)

        elif mode == '6':
            res = get_input(dm, "> 불타기설정 [트리거% 금액 한도 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 4:
                    try:
                        trig, amt, lim = float(inp[0]), int(inp[1]), int(inp[2])
                        if amt < 1000: amt *= 10000
                        if lim < 1000: lim *= 10000
                        strategy.bull_config.update({"min_profit_to_pyramid": trig, "average_down_amount": amt, "max_investment_per_stock": lim, "auto_mode": inp[3].lower() == 'y'}); strategy._save_all_states(); dm.show_status(f"✅ 불타기 설정 완료")
                    except: dm.show_status("❌ 입력 오류", True)

        elif mode == '9':
            res_code = get_input(dm, "> 전략 적용 종목 번호 (엔터=전체): ", tw)
            if res_code is None: pass
            elif res_code.strip() == '':
                if not f_h: dm.show_status("⚠️ 보유 종목 없음", True)
                else:
                    def task_bulk():
                        dm.set_busy("AI 통합 전략 진단")
                        try:
                            batch_results = strategy.perform_portfolio_batch_review(skip_trade=True, include_manual=True)
                            
                            dm.show_status("✅ 일괄 전략 진단 완료")
                        finally: dm.clear_busy()
                    command_queue.put((task_bulk, (), {}))
            elif res_code.strip().isdigit():
                idx = int(res_code.strip())
                if 0 < idx <= len(f_h):
                    h = f_h[idx - 1]; code, name = h['pdno'], h['prdt_name']
                    res_strat = get_input(dm, f"> [{name}] 전략 번호 (엔터=AI): ", tw, prompt_mode='STRATEGY')
                    if res_strat is not None:
                        def task_single(sid_raw):
                            dm.set_busy("AI 전략 분석")
                            try:
                                if sid_raw.strip() == '':
                                    result = strategy.auto_assign_preset(code, name)
                                    if result:
                                        dm.add_trading_log(f"✅ [{name}] {result['preset_name']} TP:{result['tp']:+.1f}% SL:{result['sl']:.1f}%")
                                        dm.show_status(f"✅ AI 추천 전략 적용")
                                    else:
                                        from src.logger import log_error
                                        log_error(f"AI 전략 추천 실패: {name}({code})")
                                        dm.add_trading_log(f"⚠️ [{name}] AI 전략 추천 실패")
                                        dm.show_status(f"❌ AI 전략 추천 실패", True)
                                else:
                                    antis_id = sid_raw.strip().zfill(2)
                                    if antis_id in PRESET_STRATEGIES:
                                        if antis_id == '00':
                                            strategy.assign_preset(code, '00', name=name)
                                            dm.add_trading_log(f"🔄 [{name}] 표준 전략 복귀")
                                            dm.show_status(f"🔄 표준 복귀")
                                        else:
                                            detail = api.get_naver_stock_detail(code); news = api.get_naver_stock_news(code)
                                            try:
                                                res = strategy.ai_advisor.simulate_preset_strategy(code, name, strategy.current_market_vibe, detail, news)
                                            except Exception as ai_e:
                                                from src.logger import log_error
                                                log_error(f"AI 전략 시뮬레이션 실패: {ai_e}")
                                                res = None
                                            
                                            tp = res['tp'] if res else PRESET_STRATEGIES[antis_id]['default_tp']
                                            sl = res['sl'] if res else PRESET_STRATEGIES[antis_id]['default_sl']
                                            strategy.assign_preset(code, antis_id, tp, sl, res['reason'] if res else '', name=name, is_manual=True)
                                            dm.add_trading_log(f"✅ [{name}] {PRESET_STRATEGIES[antis_id]['name']} TP:{tp:+.1f}% SL:{sl:.1f}%")
                                            dm.show_status(f"✅ {PRESET_STRATEGIES[antis_id]['name']} 적용")
                                    else:
                                        from src.logger import log_error
                                        log_error(f"무효한 프리셋 번호 입력: {antis_id}")
                                        dm.show_status("⚠️ 무효한 번호", True)
                            finally: dm.clear_busy()
                        command_queue.put((task_single, (res_strat,), {}))



    except Exception as e:
        from src.logger import log_error
        log_error(f"Interaction Error: {e}"); dm.show_status(f"오류: {e}", True)
    finally:
        sys.stdout.write("\033[7;1H\033[K\033[8;1H\033[K"); sys.stdout.flush(); set_terminal_raw(); flush_input()
