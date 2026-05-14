import os
import sys
import time
import threading
import queue
import re
from typing import Optional, Any
from src.utils import *
from src.theme_engine import get_cached_themes
from src.strategy import PRESET_STRATEGIES
from src.logger import trading_log

# [Task 4] 비동기 커맨드 실행을 위한 작업 큐 및 워커 스레드 도입
command_queue = queue.Queue()

def command_worker():
    """비동기 작업 큐에서 명령을 꺼내 순차적으로 실행하는 전전용 워커 스레드입니다.
    
    TUI 렌더링 스레드가 무거운 작업(AI 분석, 주문 대기 등)에 의해 블로킹되는 것을 
    방지하기 위해 사용됩니다.
    """
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

from src.ui.views.recommendation_view import draw_recommendation_report
from src.ui.views.holdings_view import draw_holdings_detail
from src.ui.views.hot_stocks_view import draw_hot_stocks_detail
from src.ui.views.stock_analysis_view import draw_stock_analysis
from src.ui.views.ai_logs_view import draw_ai_logs_report
from src.ui.views.performance_view import draw_performance_report

def get_input(dm, prompt: str, tw: int, prompt_mode: Optional[str] = None) -> str:
    """사용자로부터 터미널 입력을 받으며, 입력 도중에도 TUI 렌더링이 유지되도록 콜백을 연동합니다.

    Args:
        dm (DataManager): 시스템 상태 관리자.
        prompt (str): 입력창에 표시할 메시지.
        tw (int): 터미널 가로 너비.
        prompt_mode (str, optional): 입력 모드 식별자.

    Returns:
        str: 사용자가 입력한 문자열. ESC 입력 시 빈 문자열 반환.
    """
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

def perform_interaction(key: str, api, strategy, dm, cycle: int):
    """사용자의 키 입력을 해석하여 대응하는 액션(매매, 조회, 설정 등)을 실행합니다.

    Args:
        key (str): 눌린 키 값.
        api (TradingAPI): API 클라이언트.
        strategy (VibeStrategy): 전략 엔진.
        dm (DataManager): 상태 관리자.
        cycle (int): 현재 시스템 사이클 번호.
    """
    try:
        import os
        import sys
        import time
        import threading
        from src.ui.renderer import draw_tui, draw_manual_page
        from src.utils import get_key_immediate, restore_terminal_settings, exit_alt_screen, enter_alt_screen, set_terminal_raw, flush_input, get_market_name
        from src.config_init import ensure_env, get_config
        from src.auth import get_auth
        from src.theme_engine import get_cached_themes
        from src.strategy import PRESET_STRATEGIES
        from dotenv import load_dotenv
        
        flush_input()
        key_map = {'ㅂ': 'q', 'ㅃ': 'q', 'ㅅ': 's', 'ㄴ': 's', 'ㅈ': 's', 'ㅁ': 'a', 'ㅣ': 'l', 'ㅠ': 'b', 'ㅇ': 'd', 'ㅎ': 'h', 'ㅔ': 'p', 'ㅖ': 'p'}
        mode = (key[-1] if 'alt+' in key else key).lower()
        if mode in key_map: mode = key_map[mode]
        
        if mode not in ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'd', 'h', 'l', 'm', 'q', 's', 'p', 'u', 'k']: return
        
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24

        f_h = dm.cached_holdings if dm.ranking_filter == "ALL" else [h for h in dm.cached_holdings if get_market_name(h.get('pdno','')) == dm.ranking_filter]
        
        if mode == 'q':
            restore_terminal_settings(); exit_alt_screen()
            print("\n[AI TRADING SYSTEM] 사용자에 의해 안전하게 종료되었습니다."); os._exit(0)
        
        if mode in ['m', 'l', 'b', 'd', 'h', 'a', 'p', 'k']:
            def run_display_task():
                status_map = {
                    'm': "사용자 매뉴얼 조회 중", 'l': "시스템 로그 조회 중", 'b': "보유 종목 진단 중", 'd': "추천 종목 상세 조회 중",
                    'h': "인기 테마 리포트 조회 중", 'a': "AI 결정 로그 조회 중", 'p': "성과 대시보드 조회 중", 'k': "모의거래 자가 진단 중"
                }
                dm.is_full_screen_active = True
                dm.set_busy(status_map.get(mode, f"{mode} 처리"), "UI")
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
                    elif mode == 'k':
                        if strategy.mock_tester.is_active:
                            draw_mock_tester_menu(strategy, dm)
                        else:
                            print("\n" + align_kr(" ❌ 자가 진단 메뉴는 모의투자 환경에서만 사용 가능합니다. ", tw_r, 'center'))
                            time.sleep(1.5)
                    # 복귀 시 화면 깨짐 방지: alt screen을 새로 여는 대신 현재 화면을 확실히 청소
                    sys.stdout.write("\033[H\033[2J"); sys.stdout.flush()
                    set_terminal_raw(); flush_input(); dm.last_size = (0, 0)
                except Exception as display_e:
                    from src.logger import log_error
                    log_error(f"Display Task Error ({mode}): {display_e}")
                finally: 
                    dm.clear_busy("UI")
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
                        dm.set_busy("종목 분석 중", "UI")
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
                            dm.clear_busy("UI")
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
                print("\n" + "="*60 + "\n ⚙️  AI-Vibe-Trader 환경 설정 모드\n" + "="*60); flush_input()
                ensure_env(force=True); load_dotenv(override=True); config = get_config()
                new_auth = get_auth()
                
                # 증권사가 변경되었을 경우 클래스 상속 구조가 바뀌어야 하므로 시스템 전체 재시작
                if new_auth.__class__.__name__ != api.auth.__class__.__name__:
                    print("\n" + align_kr(" ⚠️ 증권사 설정이 변경되어 시스템을 재시작합니다... ", tw, 'center'))
                    time.sleep(2)
                    restore_terminal_settings()
                    exit_alt_screen()
                    os.execl(sys.executable, sys.executable, *sys.argv)
                
                api.auth = new_auth; api.domain = new_auth.domain; api.clear_cache(); strategy.api = api
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
                    max_qty = int(float(h['hldg_qty']))
                    user_qty = int(float(inp[1])) if len(inp) > 1 and inp[1].replace('.','',1).isdigit() else max_qty
                    
                    qty = min(user_qty, max_qty)
                    price = int(float(inp[2])) if len(inp) > 2 and inp[2].replace('.','',1).isdigit() else 0
                    
                    qty_adjusted = user_qty > max_qty

                    def task_sell():
                        dm.set_busy("매도 처리", "MANUAL_TRADE")
                        try:
                            p_disp = f"{price:,}원" if price > 0 else "시장가"
                            if qty_adjusted:
                                dm.add_trading_log(f"⚠️ {name} 보유수량({max_qty}) 초과 -> {qty}주로 조정")
                            
                            dm.add_trading_log(f"[{code}] {name} {p_disp} {qty}주 매도시도")
                            success, msg = api.order_market(code, qty, False, price)
                            if success:
                                curr_p = float(api.get_naver_stock_detail(code).get('price', price)) if price == 0 else float(price)
                                profit = (curr_p - float(h.get('pchs_avg_pric', 0))) * qty
                                trading_log.log_trade("수동매도", code, name, curr_p, qty, f"수동 매도 ({p_disp})", profit=profit, model_id="수동", ma_20=dm.ma_20_cache.get(code, 0.0))
                                strategy.record_sell(code, is_full_exit=(qty >= max_qty))
                                dm.show_status(f"✅ 매도 성공: {name}"); dm.update_all_data(dm.api.auth.is_virtual, force=True)
                            else:
                                from src.logger import log_error
                                log_error(f"수동 매도 실패 ({h['prdt_name']}): {msg}")
                                dm.add_trading_log(f"❌ 수동 매도 실패 ({name}): {msg}")
                                dm.show_status(f"❌ 매도 실패: {msg}", True)
                        finally: dm.clear_busy("MANUAL_TRADE")
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
                        new_bin = "AI-Vibe-Trader_new.exe" if is_windows else "AI-Vibe-Trader-Linux_new"
                        
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
                        dm.set_busy("매수 처리", "MANUAL_TRADE")
                        try:
                            detail = api.get_naver_stock_detail(code); buy_name = detail.get('name', code)
                            p_disp = f"{price:,}원" if price > 0 else "시장가"
                            dm.add_trading_log(f"[{code}] {buy_name} {p_disp} {qty}주 매입시도")
                            is_new = not any(h['pdno'] == code for h in dm.cached_holdings)
                            success, msg = api.order_market(code, qty, True, price)
                            if success:
                                curr_p = float(api.get_naver_stock_detail(code).get('price', price)) if price == 0 else float(price)
                                strategy.record_buy(code, curr_p, "수동")
                                trading_log.log_trade("수동매수", code, buy_name, curr_p, qty, f"수동 매수 ({p_disp})", model_id="수동", ma_20=dm.ma_20_cache.get(code, 0.0))
                                dm.show_status(f"✅ 매수 성공: {buy_name}")
                                if is_new:
                                    try:
                                        strategy.auto_assign_preset(code, buy_name)
                                    except Exception as ai_e:
                                        from src.logger import log_error
                                        log_error(f"AI 전략 할당 실패: {ai_e}")
                                dm.update_all_data(dm.api.auth.is_virtual, force=True)
                            else:
                                from src.logger import log_error
                                log_error(f"수동 매수 실패 ({buy_name}): {msg}")
                                dm.show_status(f"❌ 매수 실패: {msg}", True)
                        finally: dm.clear_busy("MANUAL_TRADE")
                    threading.Thread(target=task_buy, name=f"[{code}_매수]", daemon=True).start()

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
            if strategy.is_analyzing:
                dm.show_status("⚠️ 이미 분석이 진행 중입니다.", True)
                return
                
            def task_ai():
                dm.set_busy("AI분석", "AI_ENGINE")
                try:
                    def prog_cb(c, t, m="AI분석"): 
                        if "분석 중:" in m: m = "AI추천"
                        dm.set_busy(f"{m}({c}/{t})", "AI_ENGINE")
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
                    dm.clear_busy("AI_ENGINE")
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
                        dm.set_busy("AI 통합 전략 진단", "AI_ENGINE")
                        try:
                            batch_results = strategy.perform_portfolio_batch_review(skip_trade=True, include_manual=True)
                            
                            dm.show_status("✅ 일괄 전략 진단 완료")
                        finally: dm.clear_busy("AI_ENGINE")
                    command_queue.put((task_bulk, (), {}))
            elif res_code.strip().isdigit():
                idx = int(res_code.strip())
                if 0 < idx <= len(f_h):
                    h = f_h[idx - 1]; code, name = h['pdno'], h['prdt_name']
                    res_strat = get_input(dm, f"> [{name}] 전략 번호 (엔터=AI): ", tw, prompt_mode='STRATEGY')
                    if res_strat is not None:
                        def task_single(sid_raw):
                            dm.set_busy("AI 전략 분석", "AI_ENGINE")
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
                            finally: dm.clear_busy("AI_ENGINE")
                        command_queue.put((task_single, (res_strat,), {}))

    except Exception as e:
        import traceback
        from src.logger import log_error
        log_error(f"Interaction Error: {e}\n{traceback.format_exc()}")
        dm.show_status(f"오류: {e}", True)
    finally:
        sys.stdout.write("\033[7;1H\033[K\033[8;1H\033[K"); sys.stdout.flush(); set_terminal_raw(); flush_input()

def draw_mock_tester_menu(strategy, dm):
    """모의거래 전용 자가 진단 및 테스트 제어 메뉴를 화면에 그립니다.

    가상 시간 워프, 드라이런 토글, 데이터 무결성 검증 등 개발 및 테스트용 
    특수 기능을 제공합니다.

    Args:
        strategy (VibeStrategy): 전략 엔진.
        dm (DataManager): 상태 관리자.
    """
    while True:
        try:
            size = os.get_terminal_size(); tw, th = size.columns, size.lines
        except: tw, th = 80, 24
        
        sys.stdout.write("\033[H\033[2J")
        print("="*tw)
        print(align_kr("🧪 모의거래 자가 진단 및 테스트 메뉴 (MOCK TESTER)", tw, 'center'))
        print("="*tw)
        print(f"\n   현재 환경: {'모의투자(Paper)' if strategy.mock_tester.is_active else '실전(Real)'}")
        print(f"   현재 시간: {strategy.mock_tester.get_now().strftime('%Y-%m-%d %H:%M:%S')} (Offset: {strategy.mock_tester.virtual_time_offset:+.0f}s)")
        print(f"   드라이런 : {'✅ ENABLED (주문 차단)' if strategy.mock_tester.dry_run_enabled else '❌ DISABLED (실제 주문)'}")
        print("\n   [제어 명령]")
        print("   1. 드라이런(Dry-run) 모드 토글")
        print("   2. 시간 워프 (P3: Conclusion 14:35 시점으로)")
        print("   3. 시간 워프 (P4: Preparation 15:15 시점으로)")
        print("   4. 시간 오프셋 리셋 (현재 시간으로)")
        print("   5. 데이터 무결성 즉시 검증")
        print("\n   Q. 메인 화면으로 돌아가기")
        print("\n" + "="*tw)
        sys.stdout.write(f"\n {B_YELLOW}명령을 선택하세요: {RESET}")
        sys.stdout.flush()
        
        set_terminal_raw()
        k = get_key_immediate()
        if k:
            k = k.lower()
            if k == 'q' or k == 'ㅂ': break
            elif k == '1':
                strategy.mock_tester.dry_run_enabled = not strategy.mock_tester.dry_run_enabled
                dm.show_status(f"드라이런 모드 {'활성화' if strategy.mock_tester.dry_run_enabled else '비활성화'}됨")
            elif k == '2':
                strategy.mock_tester.warp_to_phase("P3")
            elif k == '3':
                strategy.mock_tester.warp_to_phase("P4")
            elif k == '4':
                strategy.mock_tester.virtual_time_offset = 0
                dm.show_status("가상 시간 오프셋이 초기화되었습니다.")
            elif k == '5':
                tui_data = {"vibe": dm.vibe, "holdings": dm.cached_holdings, "asset": dm.cached_asset}
                if strategy.mock_tester.validate_tui_data(tui_data):
                    print(f"\n   {G_GREEN}✅ 데이터 무결성 검증 통과!{RESET}")
                else:
                    print(f"\n   {B_RED}❌ 데이터 결함 감지됨 (로그 확인 필요){RESET}")
                time.sleep(1.5)
        time.sleep(0.1)
