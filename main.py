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
_trading_logs = [] # 최근 10개 거래 로그
_last_size = (0, 0)
_cached_holdings = []
_cached_asset = {"total_asset":0, "stock_eval":0, "cash":0, "pnl":0, "deposit":0}
_cached_stock_info = {} # 종목별 추가 정보 캐시 (TP/SL, 볼륨 스파이크 등)
_cached_hot_raw = []
_cached_vol_raw = []
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

def add_trading_log(msg):
    global _trading_logs
    t_str = datetime.now().strftime('%H:%M:%S')
    _trading_logs.append(f"\033[95m[TRADING] [{t_str}] {msg}\033[0m")
    if len(_trading_logs) > 10:
        _trading_logs.pop(0)
    from src.logger import log_trade
    log_trade(msg)

# --- 데이터 업데이트 함수 (강제 갱신용) ---
def update_all_data(api, strategy, is_virtual, force=False):
    global _cached_holdings, _cached_asset, _cached_hot_raw, _cached_vol_raw, _cached_recommendations
    global _cached_market_data, _cached_vibe, _cached_panic, _last_update_time, _is_kr_market_active, _last_times, _cached_stock_info
    
    try:
        curr_t = time.time()
        # 1. 지수
        strategy.determine_market_trend()
        _cached_market_data = strategy.current_market_data
        _cached_vibe = strategy.current_market_vibe
        _cached_panic = strategy.global_panic
        _last_times["index"] = curr_t
        
        # 2. 잔고 및 총자산
        h, a = api.get_full_balance(force=True)
        _cached_holdings = h; _cached_asset = a
        _last_times["asset"] = curr_t
        
        # 3. 종목별 상세 정보 캐싱 (볼륨 스파이크 체크 포함)
        for stock in h:
            code = stock.get('pdno')
            price_data = api.get_inquire_price(code)
            tp, sl, spike = strategy.get_dynamic_thresholds(code, _cached_vibe.lower(), price_data)
            _cached_stock_info[code] = {"tp": tp, "sl": sl, "spike": spike}
        
        # 4. 랭킹 (네이버 기반)
        _cached_hot_raw = api.get_naver_hot_stocks()
        _cached_vol_raw = api.get_naver_volume_stocks()
        _last_times["ranking"] = curr_t
        
        add_log("데이터 전체 업데이트 완료")
        return True
    except Exception as e:
        from src.logger import log_error
        log_error(f"Update Error: {e}")
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
            from src.logger import log_error
            log_error(f"Index Update Error: {e}")
        time.sleep(5)

# --- 데이터 업데이트 스레드 (KIS API: 잔고/랭킹/주문) ---
def data_update_worker(api, strategy, is_virtual):
    global _cached_holdings, _cached_asset, _cached_hot_raw, _cached_vol_raw, _cached_recommendations, _cached_stock_info
    global _last_update_time, _last_times
    
    update_all_data(api, strategy, is_virtual, force=True)
    
    step = 1 # 1:잔고/총자산(현금포함), 2:랭킹 정보
    while True:
        try:
            curr_t = time.time()
            if step == 1: # 1단계: 주식 잔고 및 총자산 조회 (현금 포함)
                h, a = api.get_full_balance(force=True)
                if h or a.get('total_asset', 0) > 0:
                    with _data_lock:
                        _cached_holdings = h; _cached_asset = a
                        # 종목 상세 정보 순차 캐싱
                        for stock in h:
                            code = stock.get('pdno')
                            p_data = api.get_inquire_price(code)
                            tp, sl, spike = strategy.get_dynamic_thresholds(code, _cached_vibe.lower(), p_data)
                            _cached_stock_info[code] = {"tp": tp, "sl": sl, "spike": spike}
                            
                    _last_times["asset"] = curr_t
                    add_log(f"잔고 및 상세정보 업데이트 성공 (Cash: {a['cash']:,}원)")
                
            elif step == 2: # 2단계: 랭킹 정보 (네이버 기반)
                h_raw = api.get_naver_hot_stocks(); v_raw = api.get_naver_volume_stocks()
                with _data_lock:
                    _cached_hot_raw = h_raw; _cached_vol_raw = v_raw
                _last_times["ranking"] = curr_t
                add_log(f"네이버 랭킹 업데이트 완료")

            vibe = _cached_vibe
            _cached_recommendations = strategy.get_buy_recommendations(market_trend=vibe.lower())
            
            # [자동화 로직] 장중 자동 매매 실행
            if _is_kr_market_active:
                # 1. TP/SL 자동 매매
                auto_res = strategy.run_cycle(market_trend=vibe.lower(), skip_trade=False)
                if auto_res:
                    for r in auto_res: add_trading_log(f"🤖 자동: {r}")
                
                # 2. 물타기 자동 실행
                if strategy.bear_config.get("auto_mode", False) and _cached_recommendations:
                    r = _cached_recommendations[0]
                    p = api.get_inquire_price(r['code'])
                    if p:
                        qty = math.floor(r['suggested_amt'] / p['price'])
                        if qty > 0:
                            success, msg = api.order_market(r['code'], qty, True)
                            if success:
                                msg_txt = f"자동물타기: {r['name']} {qty}주"
                                strategy.last_avg_down_msg = f"[{datetime.now().strftime('%H:%M')}] {msg_txt}"
                                strategy.record_buy(r['code'], p['price']) # 가격 기록 추가
                                add_trading_log(f"🤖 {msg_txt}")
                                update_all_data(api, strategy, is_virtual, force=True)

            _last_update_time = datetime.now().strftime('%H:%M:%S')
            
            # 다음 단계 (1, 2 로테이션)
            step = 1 if step == 2 else step + 1
            
        except Exception as e:
            err_msg = str(e)
            if "초당 거래건수를 초과" in err_msg:
                show_status("⚠️ API 부하 조절 중...", True); time.sleep(10)
            else:
                from src.logger import log_error
                log_error(f"Data Update Error: {err_msg}"); show_status("⚠️ 데이터 동기화 일시 오류", True)
        time.sleep(5)

# --- TUI 렌더러 ---
def draw_tui(strategy, cycle_info, prompt_mode=None):
    global _last_size, _status_msg, _status_time, _last_log_msg, _last_log_time, _trading_logs
    global _cached_holdings, _cached_asset, _cached_hot_raw, _cached_vol_raw, _cached_stock_info
    global _cached_market_data, _cached_vibe, _cached_panic, _last_update_time, _ranking_filter, _cached_recommendations, _last_times
    
    try:
        size = os.get_terminal_size(); tw, th = size.columns, size.lines
    except: tw, th = 110, 30

    buf = io.StringIO()
    if (tw, th) != _last_size: buf.write("\033[2J"); _last_size = (tw, th)
    buf.write("\033[H")
    
    now_dt = datetime.now()
    k_st, u_st = ("OPEN" if is_market_open() else "CLOSED"), ("OPEN" if is_us_market_open() else "CLOSED")
    
    m_label = "ALL" if _ranking_filter == "ALL" else "KOSPI" if _ranking_filter == "KSP" else "KOSDAQ" if _ranking_filter == "KDQ" else "USA"
    h_l = f" [AI TRADING SYSTEM] | {now_dt.strftime('%Y-%m-%d %H:%M:%S')} | KR:{k_st} | US:{u_st}"
    h_r = f" ✅ LAST UPDATE: {_last_update_time} | FILTER: {m_label} "
    buf.write("\033[44m" + h_l + " " * max(0, tw - get_visual_width(h_l) - get_visual_width(h_r)) + h_r + "\033[0m\n")
    
    with _data_lock:
        # K Market Line (KSP -> K200F -> KDQ -> VIX -> USDKRW 순서)
        k_mkt_l = " K Market: "
        # 1. KSP, K200F, KDQ, VIX 순차 처리 (VIX는 내부적으로 VOSPI 키 사용)
        for k in ["KOSPI", "KPI200", "KOSDAQ", "VOSPI"]:
            d = _cached_market_data.get(k)
            if d:
                color = "\033[91m" if d['rate'] >= 0 else "\033[94m"
                disp_map = {"KOSPI": "KSP", "KPI200": "K200F", "KOSDAQ": "KDQ", "VOSPI": "VIX"}
                k_mkt_l += f"{disp_map.get(k, k[:3])} {d['price']:,.2f}({color}{d['rate']:+0.2f}%\033[0m)  "
        
        # 2. 환율 (맨 뒤)
        usd_krw = _cached_market_data.get("FX_USDKRW")
        if usd_krw:
            color = "\033[91m" if usd_krw['rate'] >= 0 else "\033[94m"
            k_mkt_l += f"USDKRW {usd_krw['price']:,.1f}({color}{usd_krw['rate']:+0.2f}%\033[0m)"
            
        buf.write(align_kr(k_mkt_l, tw) + "\n")

        # US Market Line
        u_mkt_l = " US Market: "
        for k in ["DOW", "NASDAQ", "NAS_FUT", "S&P500", "SPX_FUT"]:
            d = _cached_market_data.get(k)
            if d:
                color = "\033[91m" if d['rate'] >= 0 else "\033[94m"
                disp_map = {"DOW": "DOW", "NASDAQ": "NAS", "NAS_FUT": "NAS.F", "S&P500": "SPX", "SPX_FUT": "SPX.F"}
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
        
        buf.write("\033[93m" + align_kr(" [COMMANDS] 1:매도 | 2:매수 | 3:매입/수 전략수정 | 4:AI전략 | 5:물타기설정 | 6:물타기실행 | 9:필터 | S:셋업 | Q:종료", tw) + "\033[0m\n")
        if _cached_recommendations:
            r = _cached_recommendations[0]
            avg_chg = r.get('expected_avg_change', '계산불가')
            buf.write("\033[1;30;43m" + align_kr(f" 🔔 [추천] {r['name']} ({r['rt']:.2f}%) -> {r['suggested_amt']:,}원 추가매수 (평단 {avg_chg}) (6번 실행)", tw) + "\033[0m\n")
        elif prompt_mode: buf.write("\033[1;33m" + align_kr(f" >>> [{prompt_mode} MODE] 입력 대기 중... (ESC 취소)", tw) + "\033[0m\n")
        else:
            trig = b_cfg.get("min_loss_to_buy"); lim = b_cfg.get("max_investment_per_stock")/10000
            buf.write("\033[90m" + align_kr(f" 🔔 [물타기] 추천 없음 (조건: {trig}% 이하, 한도 {lim:,.0f}만, 자동:{auto_st} 탐색 중...)", tw) + "\033[0m\n")
        
        # 최근 물타기 내역 추가
        buf.write("\033[90m" + align_kr(f" └─ 최근 물타기: {strategy.last_avg_down_msg}", tw) + "\033[0m\n")
        buf.write("=" * tw + "\n")

        asset = _cached_asset; p_c = "\033[91m" if asset['pnl'] >= 0 else "\033[94m"
        p_rt = (asset['pnl'] / (asset['total_asset'] - asset['pnl']) * 100) if (asset['total_asset'] - asset['pnl']) > 0 else 0
        asset_line = f" ASSETS | Total: {asset['total_asset']:,.0f} | Stock: {asset['stock_eval']:,.0f} | Profit: {p_c}{asset['pnl']:+,} ({abs(p_rt):.2f}%)\033[0m | Cash: {asset['cash']:,.0f}"
        buf.write(align_kr(asset_line, tw) + "\n")
        
        # 전략 라인 추가 (BASE 전략 표시용은 주입 없이 호출 가능)
        tp_cur, sl_cur, _ = strategy.get_dynamic_thresholds("BASE", _cached_vibe.lower())
        strat_line = f" STRAT  | 매입/수: 익절 {strategy.base_tp:+.1f}% (현재 {tp_cur:+.1f}%) | 손절 {strategy.base_sl:+.1f}% (현재 {sl_cur:+.1f}%)"
        buf.write(align_kr(strat_line, tw) + "\n")
        
        bear_line = f" BEAR   | 물타기: 트리거 {b_cfg.get('min_loss_to_buy'):+.1f}% | 회당 {b_cfg.get('average_down_amount'):,}원 | 종목한도 {b_cfg.get('max_investment_per_stock'):,}원 | 자동: {auto_st} | 로직: PnL기준 & 현재가<평단"
        buf.write(align_kr(bear_line, tw) + "\n")
        buf.write("-" * tw + "\n")

        # 컬럼 정의 (터미널 너비 tw에 맞춰 유연하게 배분)
        eff_w = tw - 4
        w = [
            max(4, int(eff_w * 0.04)),  # NO
            max(5, int(eff_w * 0.05)),  # MKT
            max(15, int(eff_w * 0.18)), # SYMBOL
            max(10, int(eff_w * 0.10)), # CURR
            max(14, int(eff_w * 0.14)), # DAY
            max(10, int(eff_w * 0.10)), # AVG
            max(8, int(eff_w * 0.08)),  # QTY
            max(10, int(eff_w * 0.10)), # EVAL
            max(18, int(eff_w * 0.14)), # PnL
            max(12, int(eff_w * 0.07))  # TP/SL
        ]
        header = align_kr("NO",w[0])+align_kr("MKT",w[1])+align_kr("SYMBOL",w[2])+align_kr("CURR",w[3],'right')+align_kr("DAY",w[4],'right')+align_kr("AVG",w[5],'right')+align_kr("QTY",w[6],'right')+align_kr("EVAL",w[7],'right')+align_kr("PnL",w[8],'right')+"  "+align_kr("TP/SL",w[9],'right')
        buf.write("\033[1m" + align_kr(header, tw) + "\033[0m\n")
        f_h = _cached_holdings if _ranking_filter == "ALL" else [h for h in _cached_holdings if get_market_name(h.get('pdno','')) == _ranking_filter]
        if not f_h: buf.write(align_kr(f"No active {_ranking_filter} holdings.", tw, 'center') + "\n")
        else:
            # 하단 로그 공간 확보를 위해 리스트 제한
            max_h_display = th - 30 # 네이버 랭킹 10줄 추가로 인해 더 많은 공간 필요
            display_h = f_h[:max_h_display] if len(f_h) > max_h_display else f_h
            
            for idx, h in enumerate(display_h, 1):
                code, name = h.get("pdno", ""), h.get("prdt_name", "Unknown")
                name_max = (w[2] - 10) // 2 * 2
                name_disp = name[:name_max] if name_max > 4 else name[:4]
                
                info = _cached_stock_info.get(code, {"tp": 0, "sl": 0, "spike": False})
                tp, sl, spike = info["tp"], info["sl"], info["spike"]
                
                p_a, p_cu = float(h.get('pchs_avg_pric', 0)), float(h.get('prpr', 0))
                d_v, d_r = float(h.get('prdy_vrss', 0)), float(h.get('prdy_ctrt', 0))
                d_c = "\033[91m" if d_v > 0 else "\033[94m" if d_v < 0 else ""
                d_txt = f"{d_v:+,g}({abs(d_r):.2f}%)"
                
                pnl_amt = (p_cu - p_a) * float(h.get('hldg_qty', 0))
                pnl_rt = float(h.get('evlu_pfls_rt', 0))
                color = "\033[91m" if pnl_amt >= 0 else "\033[94m"
                pnl_txt = f"{int(pnl_amt):+,}({abs(pnl_rt):.2f}%)"
                
                row = align_kr(str(idx), w[0]) + align_kr(get_market_name(code), w[1]) + align_kr(f"[{code}] {name_disp}" + (" *" if spike else ""), w[2]) + \
                      align_kr(f"{int(p_cu):,}", w[3], 'right') + \
                      d_c + align_kr(d_txt, w[4], 'right') + "\033[0m" + \
                      align_kr(f"{int(p_a):,}", w[5], 'right') + \
                      align_kr(f"{int(float(h.get('hldg_qty', 0))):,}", w[6], 'right') + \
                      align_kr(f"{int(float(h.get('evlu_amt', 0))):,}", w[7], 'right') + \
                      color + align_kr(pnl_txt, w[8], 'right') + "\033[0m" + \
                      "  " + align_kr(f"{tp:+.1f}/{sl:+.1f}%", w[9], 'right')
                buf.write(align_kr(row, tw) + "\n")
            
            if len(f_h) > max_h_display:
                buf.write(align_kr(f"... 외 {len(f_h) - max_h_display}종목 생략됨", tw, 'center') + "\n")
        buf.write("=" * tw + "\n")

        left_w, right_w = (tw - 3) // 2, tw - 3 - (tw - 3) // 2
        
        # 네이버 랭킹 필터링 및 슬라이싱 (10개)
        if _ranking_filter == "ALL":
            hot_list = _cached_hot_raw[:10]
            vol_list = _cached_vol_raw[:10]
        else:
            hot_list = [g for g in _cached_hot_raw if str(g.get('mkt','')).strip().upper() == _ranking_filter.strip().upper() or _ranking_filter == "ALL"][:10]
            vol_list = [l for l in _cached_vol_raw if str(l.get('mkt','')).strip().upper() == _ranking_filter.strip().upper() or _ranking_filter == "ALL"][:10]

        # Fallback: 인기검색어가 비어있을 경우 거래량 상위 종목 중 등락률 높은 순으로 대체
        if not hot_list and _cached_vol_raw:
            fallback_hot = sorted(_cached_vol_raw, key=lambda x: abs(x.get('rate', 0)), reverse=True)
            hot_list = fallback_hot[:10]

        def format_rank(item, is_hot=True, width=left_w):
            if not item: return " " * width
            rw = [4, 9, 14, 10, 8]
            rt_v = f"{float(item['rate']):>6.2f}%"
            row = f"{align_kr(item.get('mkt','KSP')[:3],rw[0])} {align_kr(f'[{item['code']}]',rw[1])} {align_kr(item['name'],rw[2])} {align_kr(f'{int(float(item['price'])):,}',rw[3],'right')} {align_kr(rt_v,rw[4],'right')}"
            return align_kr(row.replace(rt_v, f"{('\033[91m' if float(item['rate']) >= 0 else '\033[94m')}{rt_v}\033[0m"), width)
            
        buf.write(f"\033[1;93m{align_kr('🔥 HOT SEARCH (Naver)', left_w)}\033[0m │ \033[1;96m{align_kr('📊 VOLUME TOP (Naver)', right_w)}\033[0m\n")
        buf.write("─" * left_w + "─┼─" + "─" * right_w + "\n")
        
        if not hot_list and not vol_list:
            buf.write(align_kr("네이버 랭킹 데이터 수집 중...", tw, 'center') + "\n")
            buf.write("\n" * 9)
        else:
            for i in range(10): 
                buf.write(f"{format_rank(hot_list[i] if i < len(hot_list) else None, True, left_w)} │ {format_rank(vol_list[i] if i < len(vol_list) else None, False, right_w)}\n")
    
    # --- 하단 로그 및 상태창 배분 ---
    output_lines = buf.getvalue().split('\n')
    current_count = len(output_lines)
    sys.stdout.write(buf.getvalue())
    remaining = th - current_count
    
    if remaining > 0:
        if _status_msg and (time.time() - _status_time < 60): sys.stdout.write(f"\033[K {_status_msg}\n")
        else: sys.stdout.write("\033[K \n")
        remaining -= 1
    if remaining > 0:
        if _last_log_msg and (time.time() - _last_log_time < 60): sys.stdout.write(f"\033[K {_last_log_msg}\n")
        else: sys.stdout.write("\033[K \n")
        remaining -= 1
    if remaining > 0:
        display_logs = _trading_logs[-remaining:] if len(_trading_logs) > remaining else _trading_logs
        for i, tl in enumerate(display_logs):
            if i == len(display_logs) - 1 and remaining == 1: sys.stdout.write(f"\033[K {tl}")
            else: sys.stdout.write(f"\033[K {tl}\n")
            remaining -= 1
    while remaining > 0:
        if remaining == 1: sys.stdout.write("\033[K")
        else: sys.stdout.write("\033[K\n")
        remaining -= 1
    sys.stdout.flush(); buf.close()

# --- 입력 처리 (생략 없이 유지) ---
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
    sys.stdout.write(f"\033[33m {prompt}\033[0m")
    sys.stdout.flush()
    input_str = ""
    while True:
        k = get_key_immediate()
        if k == 'esc': return None
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
    if mode not in ['1', '2', '3', '4', '5', '6', '9', 'q', 's']: return
    
    if mode == 'q':
        show_status("🛑 프로그램을 종료합니다. 잠시만 기다려주세요...")
        draw_tui(strategy, cycle)
        time.sleep(1)
        restore_terminal_settings()
        exit_alt_screen()
        print("\n[AI TRADING SYSTEM] 사용자에 의해 안전하게 종료되었습니다.")
        os._exit(0)

    if mode == 's':
        show_status("⚙️ 환경 설정 모드로 전환합니다. 잠시만 기다려주세요...")
        draw_tui(strategy, cycle)
        time.sleep(0.5)
        exit_alt_screen()
        print("\n" + "="*60)
        print(" ⚙️  KIS-Vibe-Trader 환경 설정 모드")
        print("="*60)
        flush_input()
        ensure_env(force=True)
        load_dotenv(override=True)
        config = load_config()
        new_auth = KISAuth()
        api.auth = new_auth
        api.domain = new_auth.domain
        strategy.api = api
        enter_alt_screen()
        set_terminal_raw()
        show_status("✅ 환경 설정이 성공적으로 갱신되었습니다.")
        update_all_data(api, strategy, new_auth.is_virtual, force=True)
        return

    restore_terminal_settings()
    try:
        tw = os.get_terminal_size().columns
    except: tw = 110

    try:
        m_label = '매도' if mode=='1' else '매수' if mode=='2' else '전략수정' if mode=='3' else 'AI전략' if mode=='4' else '물타기설정' if mode=='5' else '물타기실행' if mode=='6' else '필터' if mode=='9' else '셋업'
        draw_tui(strategy, cycle, prompt_mode=m_label)
        sys.stdout.write("\033[5;1H\033[K")
        sys.stdout.flush()
        f_h = _cached_holdings if _ranking_filter == "ALL" else [h for h in _cached_holdings if get_market_name(h.get('pdno','')) == _ranking_filter]
        
        if mode == '1':
            res = input_with_esc("> 매도 [번호 수량 가격] 입력 (공백 구분, 가격 미입력시 시장가): ", tw)
            if res:
                inp = res.strip().split()
                if inp and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                    h = f_h[int(inp[0])-1]
                    qty = int(inp[1]) if len(inp) > 1 and inp[1].isdigit() else int(float(h['hldg_qty']))
                    price = int(inp[2]) if len(inp) > 2 and inp[2].isdigit() else 0
                    success, msg = api.order_market(h['pdno'], qty, False, price)
                    if success: 
                        show_status(f"✅ 매도 성공: {h['prdt_name']}")
                        add_trading_log(f"수동매도: {h['prdt_name']} {qty}주 @ {price if price else '시장가'}")
                        update_all_data(api, strategy, True, force=True)
                    else: show_status(f"❌ 매도 실패: {msg}", True)
        elif mode == '2':
            res = input_with_esc("> 매수 [코드 수량 가격] 입력 (공백 구분, 가격 미입력시 시장가): ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 2:
                    code, qty = inp[0], int(inp[1])
                    price = int(inp[2]) if len(inp) > 2 and inp[2].isdigit() else 0
                    success, msg = api.order_market(code, qty, True, price)
                    if success: 
                        show_status(f"✅ 매수 성공: {code}")
                        add_trading_log(f"수동매수: {code} {qty}주 @ {price if price else '시장가'}")
                        update_all_data(api, strategy, True, force=True)
                    else: show_status(f"❌ 매수 실패: {msg}", True)
        elif mode == '3':
            res = input_with_esc("> 수정 [번호 TP SL] 입력 (초기화는 '번호 r'): ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 2 and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                    h = f_h[int(inp[0])-1]
                    if inp[1].lower() == 'r':
                        if h['pdno'] in strategy.manual_thresholds:
                            del strategy.manual_thresholds[h['pdno']]; strategy.save_manual_thresholds()
                            show_status(f"🔄 전략 초기화 완료: {h['prdt_name']}")
                        else: show_status("⚠️ 수동 설정된 전략이 없습니다.")
                    elif len(inp) >= 3:
                        try:
                            tp, sl = float(inp[1]), float(inp[2])
                            strategy.manual_thresholds[h['pdno']] = [tp, sl]; strategy.save_manual_thresholds()
                            show_status(f"✅ 설정 완료: {h['prdt_name']}")
                        except: show_status("❌ 수치 입력 오류", True)
        elif mode == '5':
            res = input_with_esc("> 물타기설정 [트리거% 금액 한도 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 4:
                    try:
                        trig, amt, lim = float(inp[0]), int(inp[1]), int(inp[2])
                        auto = inp[3].lower() == 'y'
                        strategy.bear_config.update({"min_loss_to_buy": trig, "average_down_amount": amt, "max_investment_per_stock": lim, "auto_mode": auto})
                        strategy._save_all_states(); show_status(f"✅ 물타기 설정 저장 완료 (자동:{'ON' if auto else 'OFF'})")
                    except: show_status("❌ 입력 형식 오류", True)
        elif mode == '6':
            if _cached_recommendations:
                r = _cached_recommendations[0]
                res_c = input_with_esc(f"> {r['name']} {r['suggested_amt']:,}원 물타기할까요? (y/n): ", tw)
                if res_c and res_c.strip().lower() == 'y':
                    p = api.get_inquire_price(r['code'])
                    if p:
                        qty = math.floor(r['suggested_amt'] / p['price'])
                        if qty > 0:
                            success, msg = api.order_market(r['code'], qty, True)
                            if success:
                                strategy.last_avg_down_msg = f"[{datetime.now().strftime('%H:%M')}] 수동물타기: {r['name']} {qty}주"
                                strategy._save_state(r['code']); show_status(f"✅ {r['name']} 매수 완료")
                                update_all_data(api, strategy, True, force=True)
                            else: show_status(f"❌ {msg}", True)
        elif mode == '9':
            res = input_with_esc("> 필터 [1:ALL, 2:KSP, 3:KDQ]: ", tw)
            if res:
                sel = res.strip()
                if sel == '1': _ranking_filter = "ALL"
                elif sel == '2': _ranking_filter = "KSP"
                elif sel == '3': _ranking_filter = "KDQ"
    except Exception as e:
        log_error(f"Interaction Error: {e}"); show_status(f"오류: {e}", True)
    finally:
        sys.stdout.write("\033[2J"); sys.stdout.flush()
        set_terminal_raw(); flush_input()

def main():
    ensure_env(); load_dotenv(); config = load_config(); init_terminal()
    auth = KISAuth(); api = KISAPI(auth); strategy = VibeStrategy(api, config)
    enter_alt_screen()
    threading.Thread(target=index_update_worker, args=(strategy,), daemon=True).start()
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
