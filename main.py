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
from src.config_init import ensure_env

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
_cached_recommendations = [] 
_cached_market_data = {}
_cached_vibe = "Neutral"
_cached_panic = False
_last_update_time = ""
_ranking_filter = "ALL"
_is_kr_market_active = False
_data_lock = threading.Lock()

# 개별 갱신 시각 관리
_last_times = {"index": 0, "asset": 0, "ranking": 0}

def show_status(msg, is_error=False):
    global _status_msg, _status_time
    color = "\033[91m" if is_error else "\033[92m"
    _status_msg = f"{color}[STATUS] {msg}\033[0m"
    _status_time = time.time()

def add_log(msg):
    global _last_log_msg, _last_log_time
    _last_log_msg = f"\033[96m[LOG] {msg}\033[0m"
    _last_log_time = time.time()

# --- 데이터 업데이트 함수 (강제 갱신용) ---
def update_all_data(api, strategy, is_virtual, force=False):
    global _cached_holdings, _cached_asset, _cached_gains_raw, _cached_loses_raw, _cached_recommendations
    global _cached_market_data, _cached_vibe, _cached_panic, _last_update_time, _is_kr_market_active, _last_times
    
    try:
        curr_t = time.time()
        # 1. 지수
        strategy.determine_market_trend()
        _cached_market_data = strategy.current_market_data
        _cached_vibe = strategy.current_market_vibe
        _cached_panic = strategy.global_panic
        _last_times["index"] = curr_t
        
        # 2. 주문 가능 금액
        cash = api.get_orderable_cash()
        
        # 3. 잔고 및 총자산
        h, a = api.get_full_balance(force=True)
        a["cash"] = cash
        
        _cached_holdings = h; _cached_asset = a
        _last_times["asset"] = curr_t
        
        # 4. 랭킹
        _cached_gains_raw = api.get_top_gainers()
        _cached_loses_raw = api.get_top_losers()
        _last_times["ranking"] = curr_t
        
        add_log("데이터 전체 업데이트 완료")
        return True
    except Exception as e:
        logger.error(f"Update Error: {e}")
        return False

# --- 데이터 업데이트 스레드 (지수 전담: Naver/Yahoo) ---
def index_update_worker(strategy):
    global _cached_market_data, _cached_vibe, _cached_panic, _last_times, _is_kr_market_active
    while True:
        try:
            curr_t = time.time()
            # Naver/Yahoo API는 KIS 제한과 무관하므로 즉시/자주 호출 가능
            strategy.determine_market_trend()
            with _data_lock:
                _cached_market_data = strategy.current_market_data
                _cached_vibe = strategy.current_market_vibe
                _cached_panic = strategy.global_panic
            _last_times["index"] = curr_t
            
            # 장 상태 업데이트 (KOSPI 데이터 기준)
            kospi_info = _cached_market_data.get("KOSPI")
            _is_kr_market_active = kospi_info.get("status") == "02" if (kospi_info and "status" in kospi_info) else is_market_open()
            
        except Exception as e:
            logger.error(f"Index Update Error: {e}")
        time.sleep(5)

# --- 데이터 업데이트 스레드 (KIS API: 잔고/랭킹/주문) ---
def data_update_worker(api, strategy, is_virtual):
    global _cached_holdings, _cached_asset, _cached_gains_raw, _cached_loses_raw, _cached_recommendations
    global _last_update_time, _last_times
    
    update_all_data(api, strategy, is_virtual, force=True)
    
    step = 1 # 1:주문가능금액, 2:잔고/총자산, 3:랭킹 (0번 지수는 전담 스레드로 이동)
    while True:
        try:
            curr_t = time.time()
            if step == 1: # 1단계: 주문 가능 금액만 조회
                cash = api.get_orderable_cash()
                with _data_lock: _cached_asset["cash"] = cash
                _last_times["asset"] = curr_t
                add_log(f"주문 가능 금액 업데이트 완료 ({cash:,}원)")
                
            elif step == 2: # 2단계: 주식 잔고 및 총자산 조회
                h, a = api.get_full_balance(force=True)
                if h or a.get('total_asset', 0) > 0:
                    with _data_lock:
                        _cached_holdings = h; _cached_asset = a
                    _last_times["asset"] = curr_t
                    add_log(f"잔고 및 총자산 업데이트 성공")
                
            elif step == 3: # 3단계: 랭킹 정보
                g_raw = api.get_top_gainers(); l_raw = api.get_top_losers()
                with _data_lock:
                    _cached_gains_raw = g_raw; _cached_loses_raw = l_raw
                _last_times["ranking"] = curr_t
                add_log(f"랭킹 업데이트 완료")

            vibe = _cached_vibe
            _cached_recommendations = strategy.get_buy_recommendations(market_trend=vibe.lower())
            
            # [자동화 로직] 장중 자동 매매 실행
            if _is_kr_market_active:
                # 1. TP/SL 자동 매매
                auto_res = strategy.run_cycle(market_trend=vibe.lower(), skip_trade=False)
                if auto_res:
                    for r in auto_res: add_log(f"🤖 {r}")
                
                # 2. 물타기 자동 실행
                if strategy.bear_config.get("auto_mode", False) and _cached_recommendations:
                    r = _cached_recommendations[0]
                    p = api.get_inquire_price(r['code'])
                    if p:
                        qty = math.floor(r['suggested_amt'] / p['price'])
                        if qty > 0:
                            success, msg = api.order_market(r['code'], qty, True)
                            if success:
                                msg_txt = f"[{datetime.now().strftime('%H:%M')}] 자동물타기: {r['name']} {qty}주"
                                strategy.last_avg_down_msg = msg_txt
                                strategy._save_state(r['code'])
                                add_log(f"🤖 {msg_txt}")
                                update_all_data(api, strategy, is_virtual, force=True)

            _last_update_time = datetime.now().strftime('%H:%M:%S')
            
            # 다음 단계 (1, 2, 3 로테이션)
            step = 1 if step == 3 else step + 1
            
        except Exception as e:
            err_msg = str(e)
            if "초당 거래건수를 초과" in err_msg:
                show_status("⚠️ API 부하 조절 중...", True); time.sleep(10)
            else:
                logger.error(f"Data Update Error: {err_msg}"); show_status("⚠️ 데이터 동기화 일시 오류", True)
        time.sleep(5)

# --- TUI 렌더러 ---
def draw_tui(strategy, cycle_info, prompt_mode=None):
    global _last_size, _status_msg, _status_time, _last_log_msg, _last_log_time
    global _cached_holdings, _cached_asset, _cached_gains_raw, _cached_loses_raw
    global _cached_market_data, _cached_vibe, _cached_panic, _last_update_time, _ranking_filter, _cached_recommendations, _last_times
    
    try:
        size = os.get_terminal_size(); tw, th = size.columns, size.lines
    except: tw, th = 110, 30

    buf = io.StringIO()
    if (tw, th) != _last_size: buf.write("\033[2J"); _last_size = (tw, th)
    buf.write("\033[H")
    
    now_dt = datetime.now()
    k_st, u_st = ("OPEN" if is_market_open() else "CLOSED"), ("OPEN" if is_us_market_open() else "CLOSED")
    
    curr_t = time.time()
    t_idx = int(curr_t - _last_times["index"]) if _last_times["index"] > 0 else 0
    t_ast = int(curr_t - _last_times["asset"]) if _last_times["asset"] > 0 else 0
    t_rnk = int(curr_t - _last_times["ranking"]) if _last_times["ranking"] > 0 else 0

    h_l = f" [AI TRADING SYSTEM] | {now_dt.strftime('%Y-%m-%d %H:%M:%S')} | KR:{k_st} | US:{u_st}"
    h_r = f" 지수:{t_idx:02d}s | 자산:{t_ast:02d}s | 랭킹:{t_rnk:02d}s "
    buf.write("\033[44m" + h_l + " " * max(0, tw - get_visual_width(h_l) - get_visual_width(h_r)) + h_r + "\033[0m\n")
    
    with _data_lock:
        # K Market Line
        k_mkt_l = " K Market: "
        for k in ["KOSPI", "KOSDAQ"]:
            d = _cached_market_data.get(k)
            if d:
                color = "\033[91m" if d['rate'] >= 0 else "\033[94m"
                disp_map = {"KOSPI": "KSP", "KOSDAQ": "KDQ"}
                k_mkt_l += f"{disp_map.get(k, k[:3])} {d['price']:,.2f}({color}{d['rate']:+0.2f}%\033[0m)  "
        buf.write(align_kr(k_mkt_l, tw) + "\n")

        # US Market Line
        u_mkt_l = " US Market: "
        for k in ["NASDAQ", "NAS_FUT", "S&P500", "SPX_FUT"]:
            d = _cached_market_data.get(k)
            if d:
                color = "\033[91m" if d['rate'] >= 0 else "\033[94m"
                disp_map = {"NASDAQ": "NAS", "NAS_FUT": "NAS.F", "S&P500": "SPX", "SPX_FUT": "SPX.F"}
                u_mkt_l += f"{disp_map.get(k, k[:3])} {d['price']:,.1f}({color}{d['rate']:+0.2f}%\033[0m)  "
        buf.write(align_kr(u_mkt_l, tw) + "\n")

        v_c = "\033[91m" if "Bull" in _cached_vibe else ("\033[94m" if "Bear" in _cached_vibe else "\033[93m")
        panic_txt = " !!! PANIC !!!" if _cached_panic else ""
        b_cfg = strategy.bear_config
        auto_st = "ON" if b_cfg.get("auto_mode") else "OFF"
        
        if "Bear" in _cached_vibe:
            vibe_desc = f"(하락장: 물타기 [\033[94m{b_cfg.get('min_loss_to_buy')}% / {b_cfg.get('average_down_amount')/10000:,.0f}만 / 자동:{auto_st}\033[0m])"
        elif "Bull" in _cached_vibe:
            vibe_desc = "(\033[91m상승장: 익절 기준 상향 보정 [+3.0%]\033[0m)"
        else:
            vibe_desc = "(보합장: 기본 전략 유지)"
            
        buf.write(align_kr(f" VIBE: {v_c}{_cached_vibe.upper()}\033[0m {panic_txt} {vibe_desc}", tw) + "\n")
        
        buf.write("\033[93m" + align_kr(" [COMMANDS] 1:매도 | 2:매수 | 3:전략수정 | 4:필터 | 5:물타기설정 | 6:물타기실행 | c:로그삭제", tw) + "\033[0m\n")
        if _cached_recommendations:
            r = _cached_recommendations[0]
            buf.write("\033[1;30;43m" + align_kr(f" 🔔 [추천] {r['name']} ({r['rt']:.2f}%) -> {r['suggested_amt']:,}원 추가매수 (5번 실행)", tw) + "\033[0m\n")
        elif prompt_mode: buf.write("\033[1;33m" + align_kr(f" >>> [{prompt_mode} MODE] 입력 대기 중... (ESC 취소)", tw) + "\033[0m\n")
        else:
            trig = b_cfg.get("min_loss_to_buy"); lim = b_cfg.get("max_investment_per_stock")/10000
            buf.write("\033[90m" + align_kr(f" 🔔 [물타기] 추천 없음 (조건: {trig}% 이하, 한도 {lim:,.0f}만, 자동:{auto_st} 탐색 중...)", tw) + "\033[0m\n")
        
        # 최근 물타기 내역 추가
        buf.write("\033[90m" + align_kr(f" └─ 최근 물타기: {strategy.last_avg_down_msg}", tw) + "\033[0m\n")
        buf.write("=" * tw + "\n")

        asset = _cached_asset; p_c = "\033[91m" if asset['pnl'] >= 0 else "\033[94m"
        p_rt = (asset['pnl'] / (asset['total_asset'] - asset['pnl']) * 100) if (asset['total_asset'] - asset['pnl']) > 0 else 0
        buf.write(align_kr(f" ASSETS | Total: {asset['total_asset']:,.0f} | Stock: {asset['stock_eval']:,.0f} | Cash(주문가능): {asset['cash']:,.0f}", tw) + "\n")
        buf.write(align_kr(f" PnL    | Profit: {p_c}{asset['pnl']:+,} ({p_rt:+.2f}%)\033[0m | Deposit(현금잔액): {asset['deposit']:,.0f}", tw) + "\n")
        buf.write("-" * tw + "\n")

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
                pnl = (p_cu - p_a) * float(h.get('hldg_qty', 0)); color = "\033[91m" if pnl >= 0 else "\033[94m"
                row = align_kr(str(idx), w[0]) + align_kr(get_market_name(code), w[1]) + align_kr(f"[{code}] {name}" + (" *" if spike else ""), w[2]) + \
                      align_kr(f"{int(p_a):,}", w[3], 'right') + align_kr(f"{int(p_cu):,}", w[4], 'right') + \
                      align_kr(f"{int(float(h.get('hldg_qty', 0))):,}", w[5], 'right') + align_kr(f"{int(float(h.get('evlu_amt', 0))):,}", w[6], 'right') + \
                      color + align_kr(f"{int(pnl):+,}", w[7], 'right') + "\033[0m" + color + align_kr(f"{float(h.get('evlu_pfls_rt', 0)):+.2f}%", w[8], 'right') + "\033[0m" + \
                      "   " + align_kr(f"{tp:+1.1f}/{sl:+1.1f}%", w[9], 'right')
                buf.write(align_kr(row, tw) + "\n")
        buf.write("=" * tw + "\n")

        left_w, right_w = (tw - 3) // 2, tw - 3 - (tw - 3) // 2
        m_label = "ALL" if _ranking_filter == "ALL" else "KOSPI" if _ranking_filter == "KSP" else "KOSDAQ" if _ranking_filter == "KDQ" else "USA"
        gains = _cached_gains_raw[:5]; loses = _cached_loses_raw[:5]
        def format_rank(item, is_hot=True, width=left_w):
            if not item: return " " * width
            rw = [4, 9, 14, 10, 8]
            rt_v = f"{float(item['rate']):>6.2f}%"
            row = f"{align_kr(item.get('mkt','KSP')[:3],rw[0])} {align_kr(f'[{item['code']}]',rw[1])} {align_kr(item['name'],rw[2])} {align_kr(f'{int(item['price']):,}',rw[3],'right')} {align_kr(rt_v,rw[4],'right')}"
            return align_kr(row.replace(rt_v, f"{('\033[91m' if is_hot else '\033[94m')}{rt_v}\033[0m"), width)
        buf.write(f"\033[1;91m{align_kr('✨ TOP GAINERS ('+m_label+')', left_w)}\033[0m │ \033[1;94m{align_kr('❄️ TOP LOSERS ('+m_label+')', right_w)}\033[0m\n")
        buf.write("─" * left_w + "─┼─" + "─" * right_w + "\n")
        for i in range(5): buf.write(f"{format_rank(gains[i] if i < len(gains) else None, True, left_w)} │ {format_rank(loses[i] if i < len(loses) else None, False, right_w)}\n")
    
    buf.write("=" * tw + "\n")
    if _status_msg and (time.time() - _status_time < 60): buf.write(f"\033[K {_status_msg}\n")
    else: buf.write("\033[K \n")
    if _last_log_msg and (time.time() - _last_log_time < 60): buf.write(f"\033[K {_last_log_msg}\n")
    else: buf.write("\033[K \n")
    if _last_update_time: buf.write("\033[90m\033[K" + align_kr(f" ✅ LAST UPDATE: {_last_update_time} | FILTER: {m_label} ", tw, 'right') + "\033[0m")
    sys.stdout.write(buf.getvalue()); sys.stdout.flush(); buf.close()

# --- 입력 처리 ---
def get_key_immediate():
    if IS_WINDOWS:
        import msvcrt
        if msvcrt.kbhit():
            try:
                ch = msvcrt.getch()
                if ch in [b'\xe0', b'\x00']:
                    if msvcrt.kbhit(): msvcrt.getch() 
                    return None
                if ch == b'\x1b': return 'esc'
                return ch.decode('utf-8', errors='ignore').lower()
            except: return None
        return None
    else:
        if select.select([sys.stdin], [], [], 0)[0]:
            c = sys.stdin.read(1); return 'esc' if c == '\x1b' else c.lower()
    return None

def input_with_esc(prompt, tw):
    """ESC 취소가 가능한 커스텀 입력 함수"""
    sys.stdout.write(f"\033[33m {prompt}\033[0m")
    sys.stdout.flush()
    
    input_str = ""
    while True:
        k = get_key_immediate()
        if k == 'esc':
            return None
        elif k == '\r' or k == '\n':
            sys.stdout.write("\n")
            return input_str
        elif k == '\b' or k == 'backspace' or k == '\x7f':
            if len(input_str) > 0:
                input_str = input_str[:-1]
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif k and len(k) == 1:
            input_str += k
            sys.stdout.write(k)
            sys.stdout.flush()
        time.sleep(0.01)

def perform_interaction(key, api, strategy, cycle):
    global _ranking_filter, _status_msg, _last_log_msg, _cached_recommendations
    mode = key[-1] if 'alt+' in key else key
    if mode not in ['1', '2', '3', '4', '5', '6', 'c']: return
    if mode == 'c': _status_msg = ""; _last_log_msg = ""; return
    
    # 터미널 설정 일시 해제하여 입력을 원활하게 함 (Windows 대응)
    restore_terminal_settings()
    try:
        size = os.get_terminal_size()
        tw = size.columns
    except: tw = 110

    try:
        m_label = '매도' if mode=='1' else '매수' if mode=='2' else '수정' if mode=='3' else '필터' if mode=='4' else '물타기'
        draw_tui(strategy, cycle, prompt_mode=m_label)
        
        # 입력 위치 확보 (하단 Status 영역 근처)
        sys.stdout.write("\033[5;1H\033[K")
        sys.stdout.flush()
        
        f_h = _cached_holdings if _ranking_filter == "ALL" else [h for h in _cached_holdings if get_market_name(h.get('pdno','')) == _ranking_filter]
        
        if mode == '1': # 매도
            res = input_with_esc("> 매도 [번호 수량 가격] 입력 (공백 구분, 가격 미입력시 시장가): ", tw)
            if res is None: return # ESC 취소
            inp = res.strip().split()
            if inp and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                h = f_h[int(inp[0])-1]
                qty = int(inp[1]) if len(inp) > 1 and inp[1].isdigit() else int(float(h['hldg_qty']))
                price = int(inp[2]) if len(inp) > 2 and inp[2].isdigit() else 0
                
                success, msg = api.order_market(h['pdno'], qty, False, price)
                if success: 
                    show_status(f"✅ 매도 성공: {h['prdt_name']}")
                    add_log(msg)
                    update_all_data(api, strategy, True, force=True)
                else: show_status(f"❌ 매도 실패: {msg}", True)

        elif mode == '2': # 매수
            res = input_with_esc("> 매수 [코드 수량 가격] 입력 (공백 구분, 가격 미입력시 시장가): ", tw)
            if res is None: return # ESC 취소
            inp = res.strip().split()
            if len(inp) >= 2:
                code = inp[0]
                qty = int(inp[1])
                price = int(inp[2]) if len(inp) > 2 and inp[2].isdigit() else 0
                
                success, msg = api.order_market(code, qty, True, price)
                if success: 
                    show_status(f"✅ 매수 성공: {code}")
                    add_log(msg)
                    update_all_data(api, strategy, True, force=True)
                else: show_status(f"❌ 매수 실패: {msg}", True)

        elif mode == '3': # 전략수정
            res = input_with_esc("> 수정 [번호 TP SL] 입력 (초기화는 '번호 r'): ", tw)
            if res is None: return # ESC 취소
            inp = res.strip().split()
            if len(inp) >= 2 and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                h = f_h[int(inp[0])-1]
                # 초기화 로직 추가
                if inp[1].lower() == 'r':
                    if h['pdno'] in strategy.manual_thresholds:
                        del strategy.manual_thresholds[h['pdno']]
                        strategy.save_manual_thresholds()
                        show_status(f"🔄 전략 초기화 완료: {h['prdt_name']}")
                        # update_all_data 제거: 로컬 설정 변경이므로 즉시 반영됨
                    else:
                        show_status("⚠️ 수동 설정된 전략이 없습니다.")
                elif len(inp) >= 3:
                    try:
                        tp, sl = float(inp[1]), float(inp[2])
                        strategy.manual_thresholds[h['pdno']] = [tp, sl]; strategy.save_manual_thresholds()
                        show_status(f"✅ 설정 완료: {h['prdt_name']}")
                        # update_all_data 제거
                    except: show_status("❌ 수치 입력 오류", True)

        elif mode == '4': # 필터
            res = input_with_esc("> 필터 [1:ALL, 2:KSP, 3:KDQ]: ", tw)
            if res is None: return # ESC 취소
            sel = res.strip()
            if sel == '1': _ranking_filter = "ALL"
            elif sel == '2': _ranking_filter = "KSP"
            elif sel == '3': _ranking_filter = "KDQ"

        elif mode == '5': # 물타기 설정
            res = input_with_esc("> 물타기설정 [트리거% 금액 한도 자동(y/n)]: ", tw)
            if res is None: return
            inp = res.strip().split()
            if len(inp) >= 4:
                try:
                    trig = float(inp[0])
                    amt = int(inp[1])
                    lim = int(inp[2])
                    auto = inp[3].lower() == 'y'
                    
                    strategy.bear_config.update({
                        "min_loss_to_buy": trig, 
                        "average_down_amount": amt, 
                        "max_investment_per_stock": lim, 
                        "auto_mode": auto
                    })
                    strategy._save_all_states()
                    show_status(f"✅ 물타기 설정 저장 완료 (자동:{'ON' if auto else 'OFF'})")
                except: show_status("❌ 입력 형식 오류 (예: -3.0 500000 3000000 n)", True)

        elif mode == '6': # 물타기 실행
            if not _cached_recommendations:
                show_status("⚠️ 현재 추천된 물타기 종목이 없습니다.")
            else:
                r = _cached_recommendations[0]
                res_c = input_with_esc(f"> {r['name']} {r['suggested_amt']:,}원 물타기할까요? (y/n): ", tw)
                if res_c and res_c.strip().lower() == 'y':
                    p = api.get_inquire_price(r['code'])
                    if p:
                        qty = math.floor(r['suggested_amt'] / p['price'])
                        if qty > 0:
                            success, msg = api.order_market(r['code'], qty, True)
                            if success:
                                msg_txt = f"[{datetime.now().strftime('%H:%M')}] 수동물타기: {r['name']} {qty}주"
                                strategy.last_avg_down_msg = msg_txt
                                strategy._save_state(r['code'])
                                show_status(f"✅ {r['name']} 매수 완료")
                                add_log(msg)
                                update_all_data(api, strategy, True, force=True)
                            else: show_status(f"❌ {msg}", True)
    except Exception as e: show_status(f"오류: {e}", True)
    finally: 
        sys.stdout.write("\033[2J"); sys.stdout.flush()
        set_terminal_raw()
        flush_input()

def main():
    ensure_env(); load_dotenv(); config = load_config(); init_terminal()
    auth = KISAuth(); api = KISAPI(auth); strategy = VibeStrategy(api, config)
    enter_alt_screen()
    
    # 1. 지수 전담 스레드 (Naver/Yahoo)
    threading.Thread(target=index_update_worker, args=(strategy,), daemon=True).start()
    # 2. KIS 데이터 스레드 (잔고/랭킹/주문)
    threading.Thread(target=data_update_worker, args=(api, strategy, auth.is_virtual), daemon=True).start()
    
    set_terminal_raw()
    try:
        cycle = 0
        while True:
            cycle += 1
            if not auth.is_token_valid(): auth.generate_token()
            for i in range(50):
                draw_tui(strategy, cycle)
                start_t = time.time()
                while time.time() - start_t < 0.5:
                    k = get_key_immediate()
                    if k: perform_interaction(k, api, strategy, cycle)
                    time.sleep(0.05)
    except KeyboardInterrupt: pass
    finally: restore_terminal_settings(); exit_alt_screen()

if __name__ == "__main__": main()
