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
    if not recs: buf.write(align_kr("현재 분석된 상세 추천 종목이 없습니다. 'A'를 눌러 분석을 먼저 수행하세요.", tw, 'center') + "\n")
    else:
        buf.write("\033[1m" + f"{align_kr('테마', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('현재가', 9)} | {align_kr('등락', 7)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('AI점수', 6)} | 발굴 근거" + "\033[0m\n")
        buf.write("-" * tw + "\n")
        for r in recs:
            code = r['code']; rate = float(r['rate']); color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
            gem_mark = "💎" if r.get('is_gem') else ("📊" if r.get('is_etf') else "  ")
            detail = strategy.api.get_naver_stock_detail(code)
            buf.write(f"{align_kr(r['theme'], 8)} | {align_kr(code, 8)} | {align_kr(gem_mark + r['name'], 14)} | {align_kr(f'{int(float(r.get('price',0))):,}', 9, 'right')} | {align_kr(f'{color}{rate:+.1f}%\033[0m', 7, 'right')} | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(f'{r['score']:.1f}', 6, 'right')} | {r['reason']}\n")
    buf.write("\n" + "-" * tw + "\n\033[1;92m" + " [AI 수석 전략가 입체 분석 및 대응 전략]" + "\033[0m\n")
    if strategy.ai_detailed_opinion:
        for line in strategy.ai_detailed_opinion.split('\n'):
            if line.strip(): buf.write(f" > {line.strip()}\n")
    else: buf.write(" ⚠️ 아직 생성된 상세 분석 의견이 없습니다. '8:시황'을 실행하세요.\n")
    buf.write("-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue()); sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()

def draw_holdings_detail(strategy, dm, tw, th):
    import io
    buf = io.StringIO(); buf.write("\033[H\033[2J")
    buf.write("\033[44;37m" + align_kr(" [AI HOLDINGS PORTFOLIO REPORT] ", tw, 'center') + "\033[0m\n\n")
    asset = dm.cached_asset; p_c = "\033[91m" if asset['pnl'] > 0 else "\033[94m" if asset['pnl'] < 0 else "\033[0m"
    p_rt = (asset['pnl'] / (asset['total_asset'] - asset['pnl']) * 100) if (asset['total_asset'] - asset['pnl']) > 0 else 0
    buf.write(align_kr(f" [자산 요약] 총자산: {asset['total_asset']:,.0f} | 평가손익: {p_c}{int(asset['pnl']):+,} ({p_rt:+.2f}%)\033[0m | 현금: {asset['cash']:,.0f}", tw) + "\n")
    buf.write("-" * tw + "\n\n")
    if not dm.cached_holdings: buf.write(align_kr("현재 보유 중인 종목이 없습니다.", tw, 'center') + "\n")
    else:
        buf.write("\033[1m" + f"{align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('수익률', 10)} | {align_kr('평가손액', 12)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('업종PER', 7)}" + "\033[0m\n")
        buf.write("-" * tw + "\n")
        for h in dm.cached_holdings:
            code = h['pdno']; pnl_rt = float(h.get('evlu_pfls_rt', 0)); pnl_amt = int(float(h.get('evlu_pfls_amt', 0)))
            color = "\033[91m" if pnl_amt > 0 else "\033[94m" if pnl_amt < 0 else "\033[0m"
            detail = strategy.api.get_naver_stock_detail(code)
            buf.write(f"{align_kr(code, 8)} | {align_kr(h['prdt_name'], 14)} | {color}{align_kr(f'{pnl_rt:+.2f}%', 10, 'right')}\033[0m | {color}{align_kr(f'{pnl_amt:+,}', 12, 'right')}\033[0m | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(detail.get('sector_per','N/A'), 7, 'right')}\n")
    buf.write("\n" + "-" * tw + "\n\033[1;96m" + " [AI 포트폴리오 매니저의 실시간 진단 의견]" + "\033[0m\n")
    if strategy.ai_holdings_opinion:
        for line in strategy.ai_holdings_opinion.split('\n'):
            if line.strip(): buf.write(f"  {line.strip()}\n")
    else: buf.write(" ⚠️ 아직 생성된 보유 종목 분석 의견이 없습니다. '8:시황'을 실행하세요.\n")
    buf.write("\n" + "-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue()); sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()

def draw_hot_stocks_detail(strategy, dm, tw, th):
    sys.stdout.write("\033[H\033[2J")
    sys.stdout.write("\033[45;37m" + align_kr(" [AI HOT THEME TREND REPORT] ", tw, 'center') + "\033[0m\n\n")
    themes = get_cached_themes()
    if themes:
        theme_line = " [오늘의 인기 테마] "
        for t in themes[:8]: theme_line += f"{t['name']}({t['count']}) | "
        sys.stdout.write("\033[1;93m" + theme_line.rstrip(" | ") + "\033[0m\n")
    sys.stdout.write("-" * tw + "\n\n")
    hot = dm.cached_hot_raw[:10]
    if not hot: sys.stdout.write(align_kr("인기 검색 데이터가 없습니다.", tw, 'center') + "\n")
    else:
        sys.stdout.write("\033[1m" + f"{align_kr('NO', 4)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('현재가', 10)} | {align_kr('등락률', 8)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('업종PER', 7)}" + "\033[0m\n")
        sys.stdout.write("-" * tw + "\n")
        for idx, item in enumerate(hot, 1):
            code = item.get('code', ''); rate = float(item.get('rate', 0)); color = "\033[91m" if rate >= 0 else "\033[94m"
            detail = strategy.api.get_naver_stock_detail(code)
            sys.stdout.write(f"{align_kr(str(idx), 4)} | {align_kr(code, 8)} | {align_kr(item.get('name','')[:10], 14)} | {align_kr(f'{int(float(item.get("price",0))):,}', 10, 'right')} | {color}{align_kr(f'{rate:+.2f}%', 8, 'right')}\033[0m | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(detail.get('sector_per','N/A'), 7, 'right')}\n")
    sys.stdout.flush()
    sys.stdout.write("\n" + "-" * tw + "\n\033[1;95m" + " [트렌드 분석 중... 잠시 기다려주세요]" + "\033[0m\n"); sys.stdout.flush()
    report = strategy.ai_advisor.get_hot_stocks_report_advice(hot, themes, strategy.current_market_vibe)
    sys.stdout.write("\033[1;95m" + " [AI 트렌드 분석가의 인기 테마 진단]" + "\033[0m\n")
    if report:
        for line in report.split('\n'):
            if line.strip(): sys.stdout.write(f"  {line.strip()}\n")
    else: sys.stdout.write("  ⚠️ 리포트를 생성할 수 없습니다.\n")
    sys.stdout.write("\n" + "-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n"); sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)

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
    sys.stdout.write("-" * tw + "\n\n"); sys.stdout.flush()
    dm.show_status("🧠 AI가 분석을 위해 데이터를 확인 중입니다...")
    sys.stdout.write("\033[1;95m 🤖 AI가 확인 중입니다... (데이터 분석)\033[0m\n"); sys.stdout.flush(); time.sleep(0.5)
    sys.stdout.write("\033[1;95m 🤖 AI가 확인 중입니다... (리포트 생성)\033[0m\n"); sys.stdout.flush()
    report = strategy.ai_advisor.get_stock_report_advice(code, name, detail, news)
    if report:
        sys.stdout.write("\033[1;92m [Gemini AI 심층 분석 의견]\033[0m\n")
        for line in report.split('\n'):
            if line.strip(): sys.stdout.write(f"  {line.strip()}\n")
    else: sys.stdout.write("  ⚠️ 리포트를 생성할 수 없습니다. API 키 또는 네트워크 상태를 확인하세요.\n")
    sys.stdout.write("\n" + "-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n"); sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    dm.show_status("✅ 분석 완료")

def get_input(dm, prompt, tw):
    """[Task 4] 입력 중에도 렌더링이 멈추지 않도록 콜백 연동"""
    def cb(p, b):
        dm.input_prompt = p
        dm.input_buffer = b
        dm.is_input_active = bool(p)
    res = input_with_esc(prompt, tw, callback=cb)
    dm.is_input_active = False
    return res

def perform_interaction(key, api, strategy, dm, cycle):
    import os
    import time
    from src.ui.renderer import draw_tui, draw_manual_page
    from src.utils import get_key_immediate
    from src.config_init import ensure_env, get_config
    from src.auth import KISAuth
    from dotenv import load_dotenv
    
    flush_input(); mode = (key[-1] if 'alt+' in key else key).lower()
    if mode not in ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'd', 'h', 'l', 'm', 'q', 's']: return
    
    # 즉시 종료
    if mode == 'q':
        restore_terminal_settings(); exit_alt_screen()
        print("\n[AI TRADING SYSTEM] 사용자에 의해 안전하게 종료되었습니다."); os._exit(0)
    
    # 화면 전환 커맨드
    if mode in ['m', 'l', 'b', 'd', 'h', '7']:
        def run_display_task():
            dm.is_full_screen_active = True
            dm.set_busy(f"{mode} 처리")
            try:
                restore_terminal_settings()
                size = os.get_terminal_size(); tw, th = size.columns, size.lines
                if mode == 'm': draw_manual_page(tw, th)
                elif mode == 'l':
                    from src.ui.renderer import draw_trading_logs
                    draw_trading_logs(strategy, dm, tw, th)
                elif mode == 'b': draw_holdings_detail(strategy, dm, tw, th)
                elif mode == 'd': draw_recommendation_report(strategy, dm, tw, th)
                elif mode == 'h': draw_hot_stocks_detail(strategy, dm, tw, th)
                elif mode == '7':
                    res = get_input(dm, "> 분석할 종목 번호 또는 코드(6자리) 입력: ", tw)
                    target_code = ""
                    if res:
                        res = res.strip()
                        if res.isdigit() and len(res) <= 3: # 번호(인덱스)
                            idx = int(res)
                            if 0 < idx <= len(f_h): target_code = f_h[idx-1]['pdno']
                        elif len(res) == 6: # 종목코드
                            target_code = res
                    if target_code: draw_stock_analysis(strategy, dm, target_code, tw, th)
                enter_alt_screen(); set_terminal_raw(); flush_input(); dm.strategy.last_size = (0, 0)
            finally: 
                dm.clear_busy()
                dm.is_full_screen_active = False
        threading.Thread(target=run_display_task, daemon=True).start()
        return

    # 환경 설정
    if mode == 's':
        dm.show_status("⚙️ 환경 설정 모드로 전환합니다...")
        draw_tui(strategy, dm, cycle); time.sleep(0.5); exit_alt_screen()
        print("\n" + "="*60 + "\n ⚙️  KIS-Vibe-Trader 환경 설정 모드\n" + "="*60); flush_input()
        ensure_env(force=True); load_dotenv(override=True); config = get_config()
        new_auth = KISAuth(); api.auth = new_auth; api.domain = new_auth.domain; strategy.api = api
        enter_alt_screen(); set_terminal_raw(); dm.strategy.last_size = (0, 0)
        dm.show_status("✅ 환경 설정 완료")
        dm.update_all_data(new_auth.is_virtual, force=True); return

    # 나머지 커맨드 처리 (입력 수집 -> 큐에 작업 삽입)
    try:
        tw = os.get_terminal_size().columns
    except:
        tw = 110

    f_h = dm.cached_holdings if dm.ranking_filter == "ALL" else [h for h in dm.cached_holdings if get_market_name(h.get('pdno','')) == dm.ranking_filter]
    
    try:
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
                                trading_log.log_trade("수동매도", code, name, curr_p, qty, f"수동 매도 ({p_disp})", profit=profit)
                                dm.show_status(f"✅ 매도 성공: {name}"); dm.update_all_data(True, force=True)
                            else: dm.show_status(f"❌ 매도 실패: {msg}", True)
                        finally: dm.clear_busy()
                    command_queue.put((task_sell, (), {}))

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
                                trading_log.log_trade("수동매수", code, name, curr_p, qty, f"수동 매수 ({p_disp})")
                                dm.show_status(f"✅ 매수 성공: {name}")
                                if is_new: strategy.auto_assign_preset(code, name)
                                dm.update_all_data(True, force=True)
                            else: dm.show_status(f"❌ 매수 실패: {msg}", True)
                        finally: dm.clear_busy()
                    command_queue.put((task_buy, (), {}))

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

        elif mode in ['a', '8']:
            if not os.getenv("GOOGLE_API_KEY"): dm.show_status("⚠️ API Key 누락", True)
            else:
                def task_ai():
                    dm.set_busy("AI 시장 분석")
                    try:
                        def prog_cb(c, t, m="분석"): dm.show_status(f"[AI {m} 중... {c}/{t}]")
                        def item_cb(i): 
                            with dm.data_lock: 
                                if not any(r['code'] == i['code'] for r in strategy.ai_recommendations): strategy.ai_recommendations.append(i); strategy.ai_recommendations.sort(key=lambda x: x['score'], reverse=True)
                        with dm.data_lock: strategy.ai_recommendations = []
                        strategy.update_ai_recommendations(get_cached_themes(), dm.cached_hot_raw, dm.cached_vol_raw, progress_cb=prog_cb, on_item_found=item_cb)
                        advice = strategy.get_ai_advice(progress_cb=lambda c, t: prog_cb(c, t, "심층분석"))
                        if advice and "⚠️" not in advice:
                            dm.show_status("✅ AI 분석 완료")
                            if strategy.parse_and_apply_ai_strategy():
                                if strategy.ai_config.get("auto_apply"): dm.show_status("🚀 전략 자동 반영됨")
                        else: dm.show_status(f"❌ AI 분석 실패", True)
                    finally: dm.clear_busy()
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
                        total = len(f_h); success = 0
                        dm.set_busy("AI 일괄 전략 할당")
                        try:
                            for i, h in enumerate(f_h, 1):
                                code, name = h['pdno'], h['prdt_name']
                                dm.show_status(f"🧠 [{i}/{total}] {name} 분석 중...")
                                result = strategy.auto_assign_preset(code, name)
                                if result:
                                    success += 1
                                    dm.add_trading_log(f"✅ [{name}] {result['preset_name']} TP:{result['tp']:+.1f}% SL:{result['sl']:.1f}%")
                                else:
                                    dm.add_trading_log(f"⚠️ [{name}] AI 전략 추천 실패 (표준 유지)")
                            dm.show_status(f"✅ 일괄 할당 완료: {success}/{total}")
                        finally: dm.clear_busy()
                    command_queue.put((task_bulk, (), {}))
            elif res_code.strip().isdigit():
                idx = int(res_code.strip())
                if 0 < idx <= len(f_h):
                    h = f_h[idx - 1]; code, name = h['pdno'], h['prdt_name']
                    res_strat = get_input(dm, f"> [{name}] 전략 번호 (엔터=AI): ", tw)
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
                                        dm.add_trading_log(f"⚠️ [{name}] AI 전략 추천 실패")
                                        dm.show_status(f"❌ AI 전략 추천 실패", True)
                                else:
                                    sel_id = sid_raw.strip().zfill(2)
                                    if sel_id in PRESET_STRATEGIES:
                                        if sel_id == '00':
                                            strategy.assign_preset(code, '00', name=name)
                                            dm.add_trading_log(f"🔄 [{name}] 표준 전략 복귀")
                                            dm.show_status(f"🔄 표준 복귀")
                                        else:
                                            detail = api.get_naver_stock_detail(code); news = api.get_naver_stock_news(code)
                                            res = strategy.ai_advisor.simulate_preset_strategy(code, name, strategy.current_market_vibe, detail, news)
                                            tp = res['tp'] if res else PRESET_STRATEGIES[sel_id]['default_tp']
                                            sl = res['sl'] if res else PRESET_STRATEGIES[sel_id]['default_sl']
                                            strategy.assign_preset(code, sel_id, tp, sl, res['reason'] if res else '', name=name)
                                            dm.add_trading_log(f"✅ [{name}] {PRESET_STRATEGIES[sel_id]['name']} TP:{tp:+.1f}% SL:{sl:.1f}%")
                                            dm.show_status(f"✅ {PRESET_STRATEGIES[sel_id]['name']} 적용")

                                    else: dm.show_status("⚠️ 무효한 번호", True)
                            finally: dm.clear_busy()

                        command_queue.put((task_single, (res_strat,), {}))
    except Exception as e:
        from src.logger import log_error
        log_error(f"Interaction Error: {e}"); dm.show_status(f"오류: {e}", True)
    finally:
        sys.stdout.write("\033[7;1H\033[K\033[8;1H\033[K"); sys.stdout.flush(); set_terminal_raw(); flush_input()
