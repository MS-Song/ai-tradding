import os
import sys
import time
import threading
from datetime import datetime
from src.utils import *
from src.theme_engine import get_cached_themes
from src.strategy import PRESET_STRATEGIES
from src.logger import trading_log

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
    else: buf.write(" ⚠️ 아직 생성된 보유 종목 분석 의견이 없습니다. '7:분석'을 실행하세요.\n")
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

def perform_interaction(key, api, strategy, dm, cycle):
    import os
    import time
    from src.ui.renderer import draw_tui, draw_manual_page
    from src.utils import get_key_immediate, input_with_esc
    from src.config_init import ensure_env, get_config
    from src.auth import KISAuth
    from dotenv import load_dotenv
    
    flush_input(); mode = (key[-1] if 'alt+' in key else key).lower()
    if mode not in ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'd', 'h', 'l', 'm', 'q', 's']: return
    if mode == 'q':
        restore_terminal_settings(); exit_alt_screen()
        print("\n[AI TRADING SYSTEM] 사용자에 의해 안전하게 종료되었습니다."); os._exit(0)
    if mode == 'm':
        restore_terminal_settings(); draw_manual_page(os.get_terminal_size().columns, os.get_terminal_size().lines)
        enter_alt_screen(); set_terminal_raw(); flush_input(); dm.strategy.last_size = (0, 0); return
    if mode == 'l':
        dm.set_busy("로그 조회")
        try:
            from src.ui.renderer import draw_trading_logs
            restore_terminal_settings(); draw_trading_logs(strategy, dm, os.get_terminal_size().columns, os.get_terminal_size().lines)
            enter_alt_screen(); set_terminal_raw(); flush_input(); dm.strategy.last_size = (0, 0); time.sleep(0.2)
        finally: dm.clear_busy()
        return
    if mode == 'b':
        dm.set_busy("보유 리포트 생성")
        try:
            restore_terminal_settings(); draw_holdings_detail(strategy, dm, os.get_terminal_size().columns, os.get_terminal_size().lines)
            enter_alt_screen(); set_terminal_raw(); flush_input(); dm.strategy.last_size = (0, 0); time.sleep(0.2)
        finally: dm.clear_busy()
        return
    if mode == 'd':
        dm.set_busy("추천 리포트 생성")
        try:
            restore_terminal_settings(); draw_recommendation_report(strategy, dm, os.get_terminal_size().columns, os.get_terminal_size().lines)
            enter_alt_screen(); set_terminal_raw(); flush_input(); dm.strategy.last_size = (0, 0); time.sleep(0.2)
        finally: dm.clear_busy()
        return
    if mode == 'h':
        dm.set_busy("인기 테마 분석")
        try:
            restore_terminal_settings(); draw_hot_stocks_detail(strategy, dm, os.get_terminal_size().columns, os.get_terminal_size().lines)
            enter_alt_screen(); set_terminal_raw(); flush_input(); dm.strategy.last_size = (0, 0); time.sleep(0.2)
        finally: dm.clear_busy()
        return
    if mode == 's':
        dm.show_status("⚙️ 환경 설정 모드로 전환합니다. 잠시만 기다려주세요...")
        draw_tui(strategy, dm, cycle); time.sleep(0.5); exit_alt_screen()
        print("\n" + "="*60 + "\n ⚙️  KIS-Vibe-Trader 환경 설정 모드\n" + "="*60); flush_input()
        ensure_env(force=True); load_dotenv(override=True); config = get_config()
        new_auth = KISAuth(); api.auth = new_auth; api.domain = new_auth.domain; strategy.api = api
        enter_alt_screen(); set_terminal_raw(); dm.strategy.last_size = (0, 0)
        dm.show_status("✅ 환경 설정이 성공적으로 갱신되었습니다.")
        dm.update_all_data(new_auth.is_virtual, force=True); return

    try: tw = os.get_terminal_size().columns
    except: tw = 110
    set_terminal_raw()
    try:
        m_label = '매도' if mode=='1' else '매수' if mode=='2' else '자동' if mode=='3' else '추천' if mode=='4' else '물타기' if mode=='5' else '불타기' if mode=='6' else 'AI분석' if mode=='7' else 'AI시황' if mode=='8' else '전략' if mode=='9' else '보유리포트' if mode=='b' else '추천리포트' if mode=='d' else '인기리포트' if mode=='h' else '메뉴얼' if mode=='m' else '셋업'
        if mode not in ['a', 'd', '8']: draw_tui(strategy, dm, cycle, prompt_mode=m_label)
        try: th = os.get_terminal_size().lines
        except: th = 30
        if mode in ['a', '8']: prompt_row = max(8, th - 5); sys.stdout.write(f"\033[{prompt_row};1H\033[K")
        else: sys.stdout.write("\033[8;1H\033[K")
        sys.stdout.flush()
        f_h = dm.cached_holdings if dm.ranking_filter == "ALL" else [h for h in dm.cached_holdings if get_market_name(h.get('pdno','')) == dm.ranking_filter]
        
        if mode == '1':
            res = input_with_esc("> 매도 [번호 수량 가격] 입력 (공백 구분, 가격 미입력시 시장가): ", tw)
            if res:
                inp = res.strip().split()
                if inp and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                    h = f_h[int(inp[0])-1]; code, name = h['pdno'], h['prdt_name']
                    qty = int(float(inp[1])) if len(inp) > 1 and inp[1].replace('.','',1).isdigit() else int(float(h['hldg_qty']))
                    price = int(float(inp[2])) if len(inp) > 2 and inp[2].replace('.','',1).isdigit() else 0
                    price_display = f"{price:,}원" if price > 0 else "시장가"
                    dm.add_trading_log(f"[{code}] {name} {price_display} {qty}주 매도시도")
                    def run_sell():
                        dm.set_busy("매도 처리")
                        try:
                            success, msg = api.order_market(code, qty, False, price)
                            if success: 
                                # 수익금 계산 (Group 2 반영)
                                pchs_avg = float(h.get('pchs_avg_pric', 0))
                                curr_p = float(api.get_naver_stock_detail(code).get('price', price)) if price == 0 else float(price)
                                trade_profit = (curr_p - pchs_avg) * qty
                                
                                trading_log.log_trade("수동매도", code, name, curr_p, qty, f"수동 매도 ({price_display})", profit=trade_profit)
                                
                                dm.show_status(f"✅ 매도 성공: {name}"); dm.add_trading_log(f"수동매도완료: {name} {qty}주 @ {price_display}")
                                draw_tui(strategy, dm, cycle); dm.update_all_data(True, force=True); draw_tui(strategy, dm, cycle)
                            else: dm.show_status(f"❌ 매도 실패: {msg}", True); draw_tui(strategy, dm, cycle)
                        finally: dm.clear_busy()
                    threading.Thread(target=run_sell, daemon=True).start()
        elif mode == '2':
            res = input_with_esc("> 매수 [코드 수량 가격] 입력 (공백 구분, 가격 미입력시 시장가): ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 2:
                    code, qty = inp[0], int(inp[1]); price = int(inp[2]) if len(inp) > 2 and inp[2].isdigit() else 0
                    name = "알수없음"
                    for h in dm.cached_holdings:
                        if h['pdno'] == code: name = h['prdt_name']; break
                    if name == "알수없음":
                        detail = api.get_naver_stock_detail(code)
                        if detail: name = detail.get('name', code)
                    price_display = f"{price:,}원" if price > 0 else "시장가"
                    dm.add_trading_log(f"[{code}] {name} {price_display} {qty}주 매입시도")
                    is_new_stock = not any(h['pdno'] == code for h in dm.cached_holdings)
                    dm.set_busy("매수 처리")
                    try:
                        success, msg = api.order_market(code, qty, True, price)
                        if success:
                            # 체결가 가져오기 (Group 2 반영)
                            curr_p = float(api.get_naver_stock_detail(code).get('price', price)) if price == 0 else float(price)
                            trading_log.log_trade("수동매수", code, name, curr_p, qty, f"수동 매수 ({price_display})")
                            
                            dm.show_status(f"✅ 매수 성공: {code}"); dm.add_trading_log(f"수동매수완료: {name} {qty}주 @ {price_display}")
                            draw_tui(strategy, dm, cycle)
                            if is_new_stock:
                                sys.stdout.write("\033[9;1H")
                                sys.stdout.write(f"\033[K  \033[96m[{code}] {name}\033[0m  00:표준 | 01:골든크로스 | 02:모멘텀 | 03:52주신고가 | 04:연속상승 | 05:이격도 | 06:돌파실패 | 07:강한종가 | 08:변동성확장 | 09:평균회귀 | 10:추세필터 | 엔터:AI\n")
                                sys.stdout.flush()
                                res_strat = input_with_esc("> 전략 번호 선택 (엔터=AI 자동추천, ESC=표준): ", tw)
                                if res_strat is not None:
                                    if res_strat.strip() == '': dm.set_busy("AI 전략 분석"); strategy.auto_assign_preset(code, name)
                                    else:
                                        sel_id = res_strat.strip().zfill(2)
                                        if sel_id in PRESET_STRATEGIES and sel_id != '00':
                                            dm.set_busy("AI 수치 계산"); detail_s = strategy.api.get_naver_stock_detail(code); news_s = strategy.api.get_naver_stock_news(code)
                                            result = strategy.ai_advisor.simulate_preset_strategy(code, name, strategy.current_market_vibe, detail_s, news_s)
                                            tp_use = result['tp'] if result else PRESET_STRATEGIES[sel_id]['default_tp']; sl_use = result['sl'] if result else PRESET_STRATEGIES[sel_id]['default_sl']
                                            strategy.assign_preset(code, sel_id, tp_use, sl_use, result['reason'] if result else '')
                            dm.update_all_data(True, force=True)
                        else: dm.show_status(f"❌ 매수 실패: {msg}", True)
                    finally: dm.clear_busy()
        elif mode == '4':
            res = input_with_esc("> 추천매매설정 [금액 한도 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 3:
                    try:
                        amt, lim = int(inp[0]), int(inp[1]); auto = inp[2].lower() == 'y'
                        strategy.ai_config.update({"amount_per_trade": amt, "max_investment_per_stock": lim, "auto_mode": auto}); strategy._save_all_states(); dm.show_status(f"✨ AI 추천매매 설정 완료 (자동:{'ON' if auto else 'OFF'})")
                    except Exception as e: dm.show_status(f"❌ 입력 오류: {e}", True)
                else: dm.show_status("⚠️ 입력값이 부족합니다. [금액 한도 y/n] 순으로 입력하세요.", True)
        elif mode == '7':
            res = input_with_esc("> 분석할 종목 코드(6자리) 입력: ", tw)
            if res and len(res.strip()) == 6:
                restore_terminal_settings(); draw_stock_analysis(strategy, dm, res.strip(), os.get_terminal_size().columns, os.get_terminal_size().lines)
                enter_alt_screen(); set_terminal_raw(); flush_input(); dm.strategy.last_size = (0, 0)
        elif mode in ['a', '8']:
            if not os.getenv("GOOGLE_API_KEY"): dm.show_status("⚠️ Gemini API Key가 없습니다. [S:셋업]에서 입력하세요.", True)
            else:
                last_draw_t = [0.0]
                def progress_callback(curr, total, phase_msg="분석"):
                    dm.show_status(f"[AI {phase_msg} 중... {curr}/{total}]")
                    if time.time() - last_draw_t[0] > 0.2: draw_tui(strategy, dm, cycle); last_draw_t[0] = time.time()
                def item_found_cb(item):
                    with dm.data_lock:
                        if not any(r['code'] == item['code'] for r in strategy.ai_recommendations): strategy.ai_recommendations.append(item.copy()); strategy.ai_recommendations.sort(key=lambda x: x['score'], reverse=True)
                    if time.time() - last_draw_t[0] > 0.3: draw_tui(strategy, dm, cycle); last_draw_t[0] = time.time()
                dm.show_status("🧠 Gemini AI가 시장 상황을 분석 중입니다. 잠시만 기다려주세요...")
                with dm.data_lock: strategy.ai_recommendations = []
                draw_tui(strategy, dm, cycle); dm.set_busy("AI 시장 분석")
                try:
                    strategy.update_ai_recommendations(get_cached_themes(), dm.cached_hot_raw, dm.cached_vol_raw, progress_cb=progress_callback, on_item_found=item_found_cb)
                    advice = strategy.get_ai_advice(progress_cb=lambda c, t, p="심층분석": progress_callback(c, t, "종목 심층분석"))
                finally: dm.clear_busy()
                
                if advice and "⚠️" not in advice:
                    dm.show_status("✅ AI 분석 완료. 상단 브리핑을 확인하세요."); draw_tui(strategy, dm, cycle)
                    
                    # AI 전략 파싱 시도
                    if strategy.parse_and_apply_ai_strategy():
                        # 자동 반영 여부 체크
                        if strategy.ai_config.get("auto_apply"):
                            dm.show_status("🚀 AI 전략이 시스템에 자동 반영되었습니다.")
                            # 구분선을 === 로 변경하여 시각적 피드백 제공 (11행 타겟)
                            sys.stdout.write(f"\033[11;1H\033[K\033[1;92m{'=' * tw}\033[0m\n"); sys.stdout.flush()
                            dm.update_all_data(True, force=True); time.sleep(1.0)
                        else:
                            # 11행의 ==== 구분선을 일시적으로 지우고 프롬프트 표시
                            sys.stdout.write("\033[11;1H\033[K"); sys.stdout.flush()
                            dm.show_status("💡 AI가 새로운 전략 수치를 도출했습니다. 반영할까요?")
                            res_a = input_with_esc("> AI 제안 수치를 시스템에 즉시 반영할까요? (y/n): ", tw)
                            
                            # 입력 후 원래의 구분선으로 복구
                            sys.stdout.write(f"\033[11;1H\033[K{'=' * tw}\n"); sys.stdout.flush()
                            
                            if res_a and res_a.strip().lower() == 'y':
                                dm.show_status("🚀 AI 전략이 시스템에 완벽히 반영되었습니다."); dm.update_all_data(True, force=True)
                            else:
                                dm.show_status("⚠️ AI 전략 반영이 취소되었습니다. (기존 설정 유지)")
                    else:
                        dm.show_status("❌ AI 전략 파싱 실패 (수치 형식이 올바르지 않음)", True)
                else:
                    dm.show_status(f"❌ AI 분석 실패: {advice if advice else '알 수 없는 오류'}", True)
                flush_input(); time.sleep(0.2)
        elif mode == '3':
            res = input_with_esc("> 수정 [번호 TP SL] 또는 [TP SL] 입력 (초기화는 '번호 r'): ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 2 and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                    h = f_h[int(inp[0])-1]
                    if inp[1].lower() == 'r':
                        strategy.reset_manual_threshold(h['pdno'])
                        dm.show_status(f"🔄 전략 초기화 완료: {h['prdt_name']}")
                    elif len(inp) >= 3:
                        try:
                            tp, sl = float(inp[1]), float(inp[2])
                            strategy.set_manual_threshold(h['pdno'], tp, sl)
                            dm.show_status(f"✅ 설정 완료: {h['prdt_name']}")
                        except: dm.show_status("❌ 수치 입력 오류", True)
                elif len(inp) == 2:
                    try:
                        tp, sl = float(inp[0]), float(inp[1])
                        strategy.base_tp = tp
                        strategy.base_sl = sl
                        strategy._save_all_states()
                        dm.show_status(f"✅ 기본 전략 변경 완료: 익절 {tp}% / 손절 {sl}%")
                    except: dm.show_status("❌ 기본 전략 입력 오류", True)
                elif len(inp) == 1 and inp[0].lower() == 'r':
                    strategy.reset_all_manual_thresholds()
                    dm.show_status(f"🔄 모든 종목 수동 전략 초기화 완료")
        elif mode == '5':
            res = input_with_esc("> 물타기설정 [트리거% 금액(원) 한도(원) 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 4:
                    try:
                        trig, amt, lim = float(inp[0]), int(inp[1]), int(inp[2])
                        if amt < 1000: amt *= 10000
                        if lim < 1000: lim *= 10000
                        auto = inp[3].lower() == 'y'; strategy.bear_config.update({"min_loss_to_buy": trig, "average_down_amount": amt, "max_investment_per_stock": lim, "auto_mode": auto}); strategy._save_all_states(); dm.show_status(f"✅ 물타기 설정 저장 완료 (자동:{'ON' if auto else 'OFF'})")
                    except: dm.show_status("❌ 입력 형식 오류", True)
        elif mode == '6':
            res = input_with_esc("> 불타기설정 [트리거% 금액(원) 한도(원) 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 4:
                    try:
                        trig, amt, lim = float(inp[0]), int(inp[1]), int(inp[2])
                        if amt < 1000: amt *= 10000
                        if lim < 1000: lim *= 10000
                        auto = inp[3].lower() == 'y'; strategy.bull_config.update({"min_profit_to_pyramid": trig, "average_down_amount": amt, "max_investment_per_stock": lim, "auto_mode": auto}); strategy._save_all_states(); dm.show_status(f"✅ 불타기 설정 저장 완료 (자동:{'ON' if auto else 'OFF'})")
                    except: dm.show_status("❌ 입력 형식 오류", True)
        elif mode == '9':
            res_code = input_with_esc("> 전략 적용할 종목 번호 입력 (엔터=전체 AI 일괄 할당): ", tw)
            if res_code is None:
                pass  # ESC: 취소
            elif res_code.strip() == '':
                # ── 빈 입력: 보유 전 종목 AI 일괄 전략 할당 ──────────────────
                if not f_h:
                    dm.show_status("⚠️ 보유 종목이 없습니다.", True)
                else:
                    total = len(f_h)
                    dm.show_status(f"🧠 AI가 보유 {total}종목에 최적 전략을 일괄 할당합니다...")
                    draw_tui(strategy, dm, cycle)
                    success_cnt, fail_cnt = 0, 0
                    def run_bulk_assign():
                        nonlocal success_cnt, fail_cnt
                        dm.set_busy("AI 일괄 전략 할당")
                        try:
                            for i, h in enumerate(f_h, 1):
                                code, name = h['pdno'], h['prdt_name']
                                dm.show_status(f"🧠 [{i}/{total}] {name} 전략 분석 중...")
                                result = strategy.auto_assign_preset(code, name)
                                if result:
                                    success_cnt += 1
                                    dm.add_trading_log(f"✅ [{name}] {result['preset_name']} TP:{result['tp']:+.1f}% SL:{result['sl']:.1f}%")
                                else:
                                    fail_cnt += 1
                                    dm.add_trading_log(f"⚠️ [{name}] AI 전략 추천 실패 (표준 유지)")
                                draw_tui(strategy, dm, cycle)
                            dm.show_status(f"✅ AI 일괄 전략 할당 완료: {success_cnt}성공 / {fail_cnt}실패")
                        finally:
                            dm.clear_busy()
                        draw_tui(strategy, dm, cycle)
                    threading.Thread(target=run_bulk_assign, daemon=True).start()
            elif res_code.strip().isdigit():
                idx_num = int(res_code.strip())
                if 0 < idx_num <= len(f_h):
                    h = f_h[idx_num - 1]; code, name = h['pdno'], h['prdt_name']; current_preset = strategy.get_preset_label(code)
                    sys.stdout.write("\033[9;1H"); sys.stdout.write(f"\033[K  \033[96m[{code}] {name}\033[0m (현재: {current_preset if current_preset else '표준'})  00:표준 | 01:골든크로스 | 02:모멘텀 | 03:52주신고가 | 04:연속상승 | 05:이격도 | 06:돌파실패 | 07:강한종가 | 08:변동성확장 | 09:평균회귀 | 10:추세필터 | 엔터:AI\n"); sys.stdout.flush()
                    res_strat = input_with_esc("> 전략 번호 선택 (엔터=AI 자동추천): ", tw)
                    if res_strat is None: pass
                    elif res_strat.strip() == '':
                        dm.show_status("🧠 AI가 최적 전략을 시뮬레이션 중입니다..."); draw_tui(strategy, dm, cycle); result = strategy.auto_assign_preset(code, name)
                        if result: dm.show_status(f"✅ [{name}] AI 추천 전략: [{result['preset_name']}] TP:{result['tp']:+.1f}% SL:{result['sl']:.1f}% ({result['reason']})")
                        else: dm.show_status(f"❌ AI 전략 추천 실패. 수동으로 선택해주세요.", True)
                    else:
                        sel_id = res_strat.strip().zfill(2)
                        if sel_id in PRESET_STRATEGIES:
                            if sel_id == '00': strategy.assign_preset(code, '00'); dm.show_status(f"🔄 [{name}] 표준 전략으로 복귀 (기본 TP/SL 적용)")
                            else:
                                dm.show_status(f"🧠 [{PRESET_STRATEGIES[sel_id]['name']}] 전략 기반 동적 TP/SL 계산 중..."); draw_tui(strategy, dm, cycle)
                                detail = strategy.api.get_naver_stock_detail(code); news = strategy.api.get_naver_stock_news(code); vibe = strategy.current_market_vibe; result = strategy.ai_advisor.simulate_preset_strategy(code, name, vibe, detail, news)
                                if result and result['preset_id'] != sel_id: tp_use, sl_use = result['tp'], result['sl']
                                else: tp_use = result['tp'] if result else PRESET_STRATEGIES[sel_id]['default_tp']; sl_use = result['sl'] if result else PRESET_STRATEGIES[sel_id]['default_sl']
                                strategy.assign_preset(code, sel_id, tp_use, sl_use, result['reason'] if result else PRESET_STRATEGIES[sel_id]['desc'])
                                dm.show_status(f"✅ [{name}] [{PRESET_STRATEGIES[sel_id]['name']}] 전략 적용 (TP:{tp_use:+.1f}% SL:{sl_use:.1f}%)")
                        else: dm.show_status("⚠️ 유효하지 않은 전략 번호입니다.", True)
                else: dm.show_status("⚠️ 유효하지 않은 종목 번호입니다.", True)
    except Exception as e:
        from src.logger import log_error
        log_error(f"Interaction Error: {e}"); dm.show_status(f"오류: {e}", True)
    finally: sys.stdout.write("\033[7;1H\033[K\033[8;1H\033[K"); sys.stdout.flush(); set_terminal_raw(); flush_input()
