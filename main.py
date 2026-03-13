import os
import time
import yaml
import sys
import unicodedata
import io
import signal
import re
import select
import atexit
import threading
import math
from datetime import datetime, time as dtime
from dotenv import load_dotenv

# OS별 터미널 제어
if os.name != 'nt':
    import termios
    import tty

from src.logger import logger
from src.auth import KISAuth
from src.api import KISAPI
from src.strategy import VibeStrategy

# --- OS/Terminal 설정 ---
IS_WINDOWS = os.name == 'nt'
_original_termios = None

def init_terminal():
    global _original_termios
    if IS_WINDOWS:
        os.system('')
    else:
        try:
            _original_termios = termios.tcgetattr(sys.stdin.fileno())
            atexit.register(exit_alt_screen)
            signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
            signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        except: pass

def restore_terminal_settings():
    if not IS_WINDOWS and _original_termios:
        try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, _original_termios)
        except: pass

def set_terminal_raw():
    if IS_WINDOWS: return
    try:
        fd = sys.stdin.fileno()
        new = termios.tcgetattr(fd)
        new[3] = new[3] & ~termios.ECHO & ~termios.ICANON
        termios.tcsetattr(fd, termios.TCSANOW, new)
    except: pass

def enter_alt_screen():
    sys.stdout.write("\033[?1049h\033[H")
    sys.stdout.flush()

def exit_alt_screen():
    restore_terminal_settings()
    sys.stdout.write("\033[?1049l\033[m")
    sys.stdout.flush()

def flush_input():
    if not IS_WINDOWS:
        try: termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except: pass

# --- 유틸리티 함수 ---
def load_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as f: return yaml.safe_load(f)
    except: return {}

def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)

def is_us_market_open():
    now = datetime.now()
    if now.weekday() >= 5: return False
    t = now.time()
    return t >= dtime(22, 30) or t <= dtime(5, 0)

def get_visual_width(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    plain_text = ansi_escape.sub('', str(text))
    w = 0
    for c in plain_text:
        if unicodedata.east_asian_width(c) in ['W', 'F', 'A']: w += 2
        else: w += 1
    return w

def align_kr(text, width, align='left'):
    text = str(text)
    while get_visual_width(text) > width: text = text[:-1]
    cur_w = get_visual_width(text)
    pad = max(0, width - cur_w)
    if align == 'right': return ' ' * pad + text
    if align == 'center':
        l_p = pad // 2
        return ' ' * l_p + text + ' ' * (pad - l_p)
    return text + ' ' * pad

def get_market_name(stock_code):
    proxies = {"069500": "KSP", "150460": "KDQ", "133690": "NAS", "360750": "SPX"}
    m = proxies.get(stock_code)
    if m: return m
    if len(stock_code) == 6 and stock_code.isdigit():
        return "KSP" if stock_code[:2] in ['00', '01', '02', '03', '05', '06', '07'] else "KDQ"
    # 해외 주식 (티커 3자 이상 영문/숫자 혼합 또는 영문)
    if len(stock_code) >= 1 and any(c.isalpha() for c in stock_code):
        return "USA"
    return "STK"

# --- 전역 상태 및 데이터 캐시 ---
_status_msg = ""
_status_time = 0
_last_log_msg = ""
_last_log_time = 0
_last_size = (0, 0)
_cached_holdings = []
_cached_asset = {"total_asset":0, "stock_eval":0, "cash":0, "pnl":0, "deposit":0}
_cached_gains_raw = []
_cached_loses_raw = []
_cached_recommendations = [] # 물타기 추천 리스트
_cached_market_data = {}
_cached_vibe = "Neutral"
_cached_panic = False
_last_update_time = ""
_ranking_filter = "ALL"
_is_kr_market_active = False
_data_lock = threading.Lock()

def show_status(msg, is_error=False):
    global _status_msg, _status_time
    color = "\033[91m" if is_error else "\033[92m"
    _status_msg = f"{color}[STATUS] {msg}\033[0m"
    _status_time = time.time()

def add_log(msg):
    global _last_log_msg, _last_log_time
    _last_log_msg = f"\033[96m[LOG] {msg}\033[0m"
    _last_log_time = time.time()

# --- 데이터 업데이트 스레드 ---
def data_update_worker(api, strategy, interval, is_virtual):
    global _cached_holdings, _cached_asset, _cached_gains_raw, _cached_loses_raw, _cached_recommendations
    global _cached_market_data, _cached_vibe, _cached_panic, _last_update_time, _is_kr_market_active
    api_delay = 1.0 if is_virtual else 0.1
    internal_cycle = 0
    while True:
        try:
            internal_cycle += 1
            strategy.determine_market_trend()
            kospi_info = strategy.current_market_data.get("KOSPI")
            with _data_lock:
                _is_kr_market_active = kospi_info.get("status") == "02" if (kospi_info and "status" in kospi_info) else False
            
            time.sleep(api_delay)
            # 1. 자동 매매 분석
            skip_r = "첫 사이클" if internal_cycle == 1 else "장 종료" if not _is_kr_market_active else ""
            auto_res = strategy.run_cycle(market_trend=strategy.current_market_vibe.lower(), skip_trade=(skip_r != ""))
            
            # 2. 물타기 추천 탐색
            recoms = strategy.get_buy_recommendations(market_trend=strategy.current_market_vibe.lower())
            
            time.sleep(api_delay)
            h, a = api.get_full_balance()
            g_raw, l_raw = api.get_top_gainers(), api.get_top_losers()
            
            with _data_lock:
                _cached_holdings = h; _cached_asset = a
                _cached_gains_raw = g_raw; _cached_loses_raw = l_raw
                _cached_recommendations = recoms # 추천 캐시
                _cached_market_data = strategy.current_market_data
                _cached_vibe = strategy.current_market_vibe
                _cached_panic = strategy.global_panic
                _last_update_time = datetime.now().strftime('%H:%M:%S')
                if auto_res and not skip_r:
                    for r in auto_res: add_log(f"🤖 {r}")
        except Exception as e:
            logger.error(f"Data Update Error: {e}")
        time.sleep(max(1, interval - 5))

# --- TUI 렌더러 ---
def draw_tui(strategy, remaining_sec, cycle_info, prompt_mode=None):
    global _last_size, _status_msg, _status_time, _last_log_msg, _last_log_time
    global _cached_holdings, _cached_asset, _cached_gains_raw, _cached_loses_raw
    global _cached_market_data, _cached_vibe, _cached_panic, _last_update_time, _ranking_filter, _cached_recommendations
    
    try:
        size = os.get_terminal_size()
        tw, th = size.columns, size.lines
    except: tw, th = 110, 30

    buf = io.StringIO()
    if (tw, th) != _last_size: buf.write("\033[2J"); _last_size = (tw, th)
    buf.write("\033[H")
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    k_st, u_st = ("OPEN" if is_market_open() else "CLOSED"), ("OPEN" if is_us_market_open() else "CLOSED")
    
    h_l = f" [AI TRADING SYSTEM] | {now} | KR:{k_st} | US:{u_st} | Cycle:{cycle_info}"
    h_r = f"REFRESH IN: {remaining_sec:2d}s "
    gap = max(0, tw - get_visual_width(h_l) - get_visual_width(h_r))
    buf.write("\033[44m" + h_l + " " * gap + h_r + "\033[0m\n")
    
    with _data_lock:
        # [2] Market Info (명칭 및 환율 키 수정)
        idx_l = " MARKET: "
        for k in ["KOSPI", "KOSDAQ", "NASDAQ", "NAS_FUT", "S&P500"]:
            # KIS 내부 키와 외부 캐시 키 호환성 체크
            d = _cached_market_data.get(k)
            if d:
                color = "\033[91m" if d['rate'] >= 0 else "\033[94m"
                # 화면 표시용 약어 매핑
                disp_map = {"KOSPI": "KSP", "KOSDAQ": "KDQ", "NASDAQ": "NAS", "NAS_FUT": "NAS.F", "S&P500": "SPX"}
                name = disp_map.get(k, k[:3])
                idx_l += f"{name} {d['price']:,.1f}({color}{d['rate']:+0.2f}%\033[0m)  "
        buf.write(align_kr(idx_l, tw) + "\n")

        # [3] Vibe & FX (환율 키 USD로 수정)
        v_c = "\033[91m" if "Bull" in _cached_vibe else ("\033[94m" if "Bear" in _cached_vibe else "\033[93m")
        panic_txt = " !!! PANIC !!!" if _cached_panic else ""
        vibe_line = f" VIBE: {v_c}{_cached_vibe.upper()}\033[0m {panic_txt}"

        fx = _cached_market_data.get("USD_KRW") or _cached_market_data.get("USD")
        if fx:
            fx_color = "\033[91m" if fx['rate'] >= 0 else "\033[94m"
            vibe_line += f" | 💵 USD/KRW: {fx_color}{fx['price']:,.2f}\033[0m ({fx['rate']:+0.2f}%)"

        buf.write(align_kr(vibe_line, tw) + "\n")
        
        # [3] Commands & Recommendations
        buf.write("\033[93m" + align_kr(" [COMMANDS] 1:매도 | 2:매수 | 3:전략수정 | 4:필터 | 5:물타기 | c:삭제", tw) + "\033[0m\n")
        
        # 물타기 추천 알림 바
        if _cached_recommendations:
            r = _cached_recommendations[0]
            recom_txt = f" 🔔 [추천] {r['name']} ({r['rt']:.2f}%) -> {r['suggested_amt']:,}원 추가매수 권장 (5번 실행)"
            buf.write("\033[1;30;43m" + align_kr(recom_txt, tw) + "\033[0m\n")
        elif prompt_mode:
            buf.write("\033[1;33m" + align_kr(f" >>> [{prompt_mode} MODE] 입력 대기 중... (ESC 취소)", tw) + "\033[0m\n")
        else: buf.write(" " * tw + "\n")
        
        buf.write("\n" * 1 + "=" * tw + "\n")

        # [4] Account
        asset = _cached_asset
        p_c = "\033[91m" if asset['pnl'] >= 0 else "\033[94m"
        p_rt = (asset['pnl'] / (asset['total_asset'] - asset['pnl']) * 100) if (asset['total_asset'] - asset['pnl']) > 0 else 0
        buf.write(align_kr(f" ASSETS | Total: {asset['total_asset']:,.0f} | Stock: {asset['stock_eval']:,.0f} | Cash: {asset['cash']:,.0f}", tw) + "\n")
        buf.write(align_kr(f" PnL    | Profit: {p_c}{asset['pnl']:+,} ({p_rt:+.2f}%)\033[0m | Deposit: {asset['deposit']:,.0f}", tw) + "\n")
        buf.write("-" * tw + "\n")

        # [5] Portfolio
        w = [4, 5, 25, 11, 11, 8, 13, 12, 9, 12]
        header = align_kr("NO",w[0])+align_kr("MKT",w[1])+align_kr("SYMBOL",w[2])+align_kr("AVG",w[3],'right')+align_kr("CURR",w[4],'right')+align_kr("QTY",w[5],'right')+align_kr("EVAL",w[6],'right')+align_kr("PnL",w[7],'right')+align_kr("RT",w[8],'right')+"   "+align_kr("TP/SL",w[9],'right')
        buf.write("\033[1m" + align_kr(header, tw) + "\033[0m\n")
        f_h = _cached_holdings if _ranking_filter == "ALL" else [h for h in _cached_holdings if get_market_name(h.get('pdno','')) == _ranking_filter]
        if not f_h: buf.write(align_kr(f"No active {_ranking_filter} holdings.", tw, 'center') + "\n")
        else:
            for idx, h in enumerate(f_h, 1):
                code, name = h.get("pdno", ""), h.get("prdt_name", "Unknown")[:12]
                tp, sl, spike = strategy.get_dynamic_thresholds(code, _cached_vibe.lower())
                p_a, p_cu = float(h.get('pchs_avg_pric', 0)), float(h.get('prpr', 0))
                pnl = (p_cu - p_a) * float(h.get('hldg_qty', 0))
                color = "\033[91m" if pnl >= 0 else "\033[94m"
                row = align_kr(str(idx), w[0]) + align_kr(get_market_name(code), w[1]) + align_kr(f"[{code}] {name}" + (" *" if spike else ""), w[2]) + \
                      align_kr(f"{int(p_a):,}", w[3], 'right') + align_kr(f"{int(p_cu):,}", w[4], 'right') + \
                      align_kr(f"{int(float(h.get('hldg_qty', 0))):,}", w[5], 'right') + align_kr(f"{int(float(h.get('evlu_amt', 0))):,}", w[6], 'right') + \
                      color + align_kr(f"{int(pnl):+,}", w[7], 'right') + "\033[0m" + color + align_kr(f"{float(h.get('evlu_pfls_rt', 0)):+.2f}%", w[8], 'right') + "\033[0m" + \
                      "   " + align_kr(f"{tp:+1.1f}/{sl:+1.1f}%", w[9], 'right')
                buf.write(align_kr(row, tw) + "\n")
        buf.write("=" * tw + "\n")

        # [6] Ranking
        half_w = (tw - 3) // 2
        m_label = "ALL" if _ranking_filter == "ALL" else "KOSPI" if _ranking_filter == "KSP" else "KOSDAQ" if _ranking_filter == "KDQ" else "USA"
        gains = _cached_gains_raw[:5] if _ranking_filter == "ALL" else [g for g in _cached_gains_raw if g.get('mkt') == _ranking_filter][:5]
        loses = _cached_loses_raw[:5] if _ranking_filter == "ALL" else [l for l in _cached_loses_raw if l.get('mkt') == _ranking_filter][:5]
        def format_rank(item, is_hot=True):
            if not item: return " " * half_w
            rw = [4, 9, 14, 10, 8]
            rt_v = f"{float(item['rate']):>6.2f}%"
            row = f"{align_kr(item.get('mkt','KSP')[:3],rw[0])} {align_kr(f'[{item['code']}]',rw[1])} {align_kr(item['name'],rw[2])} {align_kr(f'{int(item['price']):,}',rw[3],'right')} {align_kr(rt_v,rw[4],'right')}"
            color = "\033[91m" if is_hot else "\033[94m"
            return align_kr(row.replace(rt_v, f"{color}{rt_v}\033[0m"), half_w)
        buf.write(f" \033[1;91m{align_kr('✨ TOP GAINERS ('+m_label+')', half_w)}\033[0m │ \033[1;94m{align_kr('❄️ TOP LOSERS ('+m_label+')', half_w)}\033[0m\n")
        buf.write("─" * half_w + "─┼─" + "─" * half_w + "\n")
        for i in range(5):
            buf.write(f"{format_rank(gains[i] if i < len(gains) else None, True)} │ {format_rank(loses[i] if i < len(loses) else None, False)}\n")
    
    buf.write("=" * tw + "\n")
    if _status_msg and (time.time() - _status_time < 60): buf.write(f" {_status_msg}\n")
    else: buf.write(" " * tw + "\n")
    if _last_log_msg and (time.time() - _last_log_time < 60): buf.write(f" {_last_log_msg}\n")
    else: buf.write(" " * tw + "\n")
    if _last_update_time:
        update_info = f" ✅ LAST UPDATE: {_last_update_time} | FILTER: {m_label} "
        buf.write("\033[90m" + align_kr(update_info, tw, 'right') + "\033[0m")

    buf.write("\033[J")
    sys.stdout.write(buf.getvalue())
    sys.stdout.flush()
    buf.close()

# --- 입력 처리 ---
def get_key_immediate():
    if IS_WINDOWS:
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch == b'\x1b': return 'esc'
            return ch.decode('utf-8').lower()
        return None
    else:
        if select.select([sys.stdin], [], [], 0)[0]:
            c = sys.stdin.read(1)
            if c == '\x1b':
                if select.select([sys.stdin], [], [], 0.05)[0]: return 'alt+' + sys.stdin.read(1)
                return 'esc'
            return c.lower()
    return None

def perform_interaction(key, api, strategy, cycle, remaining):
    global _ranking_filter, _status_msg, _last_log_msg, _cached_recommendations
    mode = key[-1] if 'alt+' in key else key
    if mode not in ['1', '2', '3', '4', '5', 'c']: return
    if mode == 'c': _status_msg = ""; _last_log_msg = ""; draw_tui(strategy, remaining, cycle); return
    
    restore_terminal_settings()
    if not IS_WINDOWS: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _original_termios)
    flush_input()
    
    try:
        m_label = '매도' if mode=='1' else '매수' if mode=='2' else '수정' if mode=='3' else '필터' if mode=='4' else '물타기'
        draw_tui(strategy, 0, cycle, prompt_mode=m_label)
        sys.stdout.write("\033[5;1H\033[K")
        sys.stdout.flush()
        
        f_h = _cached_holdings if _ranking_filter == "ALL" else [h for h in _cached_holdings if get_market_name(h.get('pdno','')) == _ranking_filter]
        
        if mode == '1': # 매도
            print("\033[1;33m > 매도 [번호 수량] 입력 (예: 1 10): \033[0m", end="", flush=True)
            inp = sys.stdin.readline().strip().split()
            if inp and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                h = f_h[int(inp[0])-1]
                qty = int(inp[1]) if len(inp) > 1 and inp[1].isdigit() else int(float(h['hldg_qty']))
                success, msg = api.order_market(h['pdno'], qty, False)
                if success: show_status(f"✅ 매도 성공: {h['prdt_name']}"); add_log(f"매도 완료: {h['prdt_name']} {qty}주")
                else: show_status(f"❌ 매도 실패: {msg}", True)
            else: show_status("❌ 오류: 잘못된 번호", True)
            
        elif mode == '2': # 매수
            print("\033[1;33m > 매수 [코드 수량] 입력 (예: 005930 5): \033[0m", end="", flush=True)
            inp = sys.stdin.readline().strip().split()
            if len(inp) >= 2:
                success, msg = api.order_market(inp[0], int(inp[1]), True)
                if success: show_status(f"✅ 매수 성공: {inp[0]}"); add_log(f"매수 완료: {inp[0]} {inp[1]}주")
                else: show_status(f"❌ 매수 실패: {msg}", True)
            else: show_status("❌ 오류: 입력 형식 불량", True)
            
        elif mode == '3': # 수정
            print("\033[1;33m > 수정 [번호 TP SL] 입력 (예: 1 5.0 -2.0): \033[0m", end="", flush=True)
            inp = sys.stdin.readline().strip().split()
            if len(inp) >= 3 and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                h = f_h[int(inp[0])-1]
                try:
                    tp, sl = float(inp[1]), float(inp[2])
                    curr_rt = float(h.get('evlu_pfls_rt', 0))
                    if sl > 0 or tp <= curr_rt:
                        print(f"\n\033[1;31m [⚠️ 주의] 즉시 매도 가능 조건입니다. 계속?(y/n): \033[0m", end="", flush=True)
                        if sys.stdin.readline().strip().lower() != 'y':
                            show_status("⚠️ 전략 수정 취소"); return
                    strategy.manual_thresholds[h['pdno']] = [tp, sl]
                    strategy.save_manual_thresholds()
                    show_status(f"✅ 설정 완료: {h['prdt_name']}"); add_log(f"전략 변경: {h['prdt_name']} ({tp}/{sl}%)")
                except: show_status("❌ 오류: 숫자만 입력", True)
            else: show_status("❌ 오류: 입력 형식 불량", True)
            
        elif mode == '4': # 필터
            sys.stdout.write("\033[1;33m > 필터 [1:ALL, 2:KSP, 3:KDQ, 4:USA]: \033[0m")
            sys.stdout.flush(); sel = sys.stdin.readline().strip()
            if sel == '1': _ranking_filter = "ALL"
            elif sel == '2': _ranking_filter = "KSP"
            elif sel == '3': _ranking_filter = "KDQ"
            elif sel == '4': _ranking_filter = "USA"
            show_status(f"✅ 필터 변경 완료: {_ranking_filter}")
            
        elif mode == '5': # 물타기 추천 실행
            if _cached_recommendations:
                r = _cached_recommendations[0]
                print(f"\033[1;33m > [물타기] {r['name']} {r['suggested_amt']:,}원 매수할까요? (y/n): \033[0m", end="", flush=True)
                if sys.stdin.readline().strip().lower() == 'y':
                    price_info = api.get_inquire_price(r['code'])
                    if price_info:
                        qty = math.floor(r['suggested_amt'] / price_info['price'])
                        if qty > 0:
                            success, msg = api.order_market(r['code'], qty, True)
                            if success: 
                                show_status(f"✅ 물타기 성공: {r['name']}")
                                add_log(f"물타기 완료: {r['name']} {qty}주")
                                _cached_recommendations.pop(0) # 실행 후 제거
                            else: show_status(f"❌ 실패: {msg}", True)
                    else: show_status("❌ 가격 조회 실패", True)
            else: show_status("⚠️ 현재 추천 종목이 없습니다.")
            
    except Exception as e: show_status(f"시스템 오류: {e}", True)
    finally:
        sys.stdout.write("\033[2J"); sys.stdout.flush()
        set_terminal_raw(); flush_input(); draw_tui(strategy, 0, cycle)

def main():
    global _cached_holdings, _cached_asset, _cached_gains_raw, _cached_loses_raw
    load_dotenv(); config = load_config(); init_terminal()
    auth = KISAuth(is_virtual=True); interval = 60 if auth.is_virtual else 10
    api = KISAPI(auth); strategy = VibeStrategy(api, config)
    enter_alt_screen()
    try: tw = os.get_terminal_size().columns
    except: tw = 110
    sys.stdout.write("\033[H\033[44m" + align_kr(" [AI TRADING SYSTEM] INITIALIZING... ", tw) + "\033[0m\n")
    sys.stdout.write("\n" * 3 + align_kr("🚀 Connecting to KIS API & Analyzing Markets...", tw, 'center') + "\n")
    sys.stdout.write(align_kr("Dashboard is loading. Please wait 3-5 seconds.", tw, 'center') + "\n" * 3)
    sys.stdout.write("=" * tw + "\n"); sys.stdout.flush()
    threading.Thread(target=data_update_worker, args=(api, strategy, interval, auth.is_virtual), daemon=True).start()
    set_terminal_raw()
    try:
        cycle = 0
        while True:
            cycle += 1
            if not auth.is_token_valid(): auth.generate_token()
            for i in range(interval, 0, -1):
                draw_tui(strategy, i, cycle)
                start_t = time.time()
                while time.time() - start_t < 1.0:
                    k = get_key_immediate()
                    if k in ['alt+1', 'alt+2', 'alt+3', 'alt+4', 'alt+5', '1', '2', '3', '4', '5', 'c']:
                        perform_interaction(k, api, strategy, cycle, i)
                        break
                    time.sleep(0.05)
    except KeyboardInterrupt: pass
    finally:
        restore_terminal_settings(); exit_alt_screen()
        print("\n[AI Trading] System terminated.")

if __name__ == "__main__":
    main()
