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
from src.config_init import ensure_env, get_config

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

_cached_themes = []

# --- 테마 분석 엔진 ---
THEME_KEYWORDS = {
    "반도체": ["반도체", "HBM", "DDR5", "하이닉스", "삼성전자", "한미반도체", "리노공업", "가온칩스", "CXL", "온디바이스"],
    "AI/로봇": ["AI", "인공지능", "로봇", "챗봇", "LLM", "엔비디아", "마음AI", "코난테크", "솔트룩스", "레인보우"],
    "이차전지": ["이차전지", "2차전지", "에코프로", "포스코", "리튬", "배터리", "전고체", "양극재", "음극재", "금양"],
    "바이오": ["바이오", "제약", "셀트리온", "HLB", "헬스케어", "알테오젠", "임상", "유한양행", "한미약품"],
    "엔터/게임": ["엔터", "엔터테인먼트", "하이브", "JYP", "게임", "크래프톤", "넷마블", "네오위즈", "SM"],
    "금융/PBR": ["은행", "금융", "지주", "보험", "증권", "PBR", "밸류업", "KB금융", "하나금융"],
    "에너지/방산": ["에너지", "태양광", "풍력", "수소", "원자력", "원전", "방산", "한화에어로", "현대로템", "넥스원"],
    "가상화폐": ["비트코인", "가상화폐", "우리기술투자", "한화투자증권", "위메이드", "블록체인"],
    "초전도체": ["초전도체", "신성델타테크", "서남", "모비스", "덕성"]
}

def analyze_popular_themes(hot_list, vol_list):
    global _cached_themes
    counts = {k: 0 for k in THEME_KEYWORDS.keys()}
    seen_codes = set()
    
    # 인기/거래량 통합 리스트 조사
    for item in hot_list + vol_list:
        code = item.get('code')
        if code in seen_codes: continue
        seen_codes.add(code)
        
        name = item.get('name', '')
        for theme, keywords in THEME_KEYWORDS.items():
            if any(kw.lower() in name.lower() for kw in keywords):
                counts[theme] += 1
                break # 한 종목당 하나의 테마만 매핑 (우선순위)
                
    # 카운트가 있는 테마만 내림차순 정렬
    sorted_themes = sorted([{"name": k, "count": v} for k, v in counts.items() if v > 0], 
                           key=lambda x: x['count'], reverse=True)
    _cached_themes = sorted_themes

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

import concurrent.futures

# --- 데이터 업데이트 함수 (강제 갱신용) ---
def update_all_data(api, strategy, is_virtual, force=False):
    global _cached_holdings, _cached_asset, _cached_hot_raw, _cached_vol_raw, _cached_recommendations
    global _cached_market_data, _cached_vibe, _cached_panic, _last_update_time, _is_kr_market_active, _last_times, _cached_stock_info, _cached_themes
    
    try:
        curr_t = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_trend = executor.submit(strategy.determine_market_trend)
            future_hot = executor.submit(api.get_naver_hot_stocks)
            future_vol = executor.submit(api.get_naver_volume_stocks)
            future_balance = executor.submit(api.get_full_balance, force=True)
            
            future_trend.result()
            _cached_market_data = strategy.current_market_data
            _cached_vibe = strategy.current_market_vibe
            _cached_panic = strategy.global_panic
            _last_times["index"] = curr_t
            
            h_raw = future_hot.result(); v_raw = future_vol.result()
            _cached_hot_raw = h_raw; _cached_vol_raw = v_raw
            analyze_popular_themes(h_raw, v_raw)
            _last_times["ranking"] = curr_t
            
            h, a = future_balance.result()
            _cached_holdings = h; _cached_asset = a
            _last_times["asset"] = curr_t

        for stock in h:
            code = stock.get('pdno')
            price_data = api.get_inquire_price(code)
            tp, sl, spike = strategy.get_dynamic_thresholds(code, _cached_vibe.lower(), price_data)
            _cached_stock_info[code] = {"tp": tp, "sl": sl, "spike": spike}
        
        _last_update_time = datetime.now().strftime('%H:%M:%S')
        add_log("데이터 동기화 완료")
        return True
    except Exception as e:
        from src.logger import log_error
        log_error(f"Update Error: {e}")
        return False

# --- 데이터 업데이트 스레드 (지수 및 네이버 랭킹 전담: Naver/Yahoo) ---
def index_update_worker(api, strategy):
    global _cached_market_data, _cached_vibe, _cached_panic, _last_times, _is_kr_market_active
    global _cached_hot_raw, _cached_vol_raw, _cached_themes
    while True:
        try:
            curr_t = time.time()
            strategy.determine_market_trend()
            h_raw = api.get_naver_hot_stocks(); v_raw = api.get_naver_volume_stocks()
            analyze_popular_themes(h_raw, v_raw)
            strategy.update_ai_recommendations(_cached_themes, h_raw, v_raw, progress_cb=None)
            with _data_lock:
                _cached_market_data = strategy.current_market_data
                _cached_vibe = strategy.current_market_vibe
                _cached_panic = strategy.global_panic
                _cached_hot_raw = h_raw; _cached_vol_raw = v_raw
            _last_times["index"] = curr_t; _last_times["ranking"] = curr_t
            kospi_info = _cached_market_data.get("KOSPI")
            _is_kr_market_active = kospi_info.get("status") == "02" if (kospi_info and "status" in kospi_info) else is_market_open()
        except Exception as e:
            from src.logger import log_error
            log_error(f"Index/Ranking Update Error: {e}")
        time.sleep(5)

# --- 데이터 업데이트 스레드 (KIS API: 잔고/주문) ---
def data_update_worker(api, strategy, is_virtual):
    global _cached_holdings, _cached_asset, _cached_recommendations, _cached_stock_info
    global _last_update_time, _last_times
    
    update_all_data(api, strategy, is_virtual, force=True)
    
    while True:
        try:
            curr_t = time.time()
            h, a = api.get_full_balance(force=True)
            if h or a.get('total_asset', 0) > 0:
                with _data_lock:
                    _cached_holdings = h; _cached_asset = a
                    for stock in h:
                        code = stock.get('pdno')
                        p_data = api.get_inquire_price(code)
                        tp, sl, spike = strategy.get_dynamic_thresholds(code, _cached_vibe.lower(), p_data)
                        _cached_stock_info[code] = {"tp": tp, "sl": sl, "spike": spike}
                _last_times["asset"] = curr_t
                add_log(f"잔고 업데이트 완료 (Cash: {a['cash']:,}원)")

            vibe = _cached_vibe
            _cached_recommendations = strategy.get_buy_recommendations(market_trend=vibe.lower())
            
            if _is_kr_market_active and not _cached_panic:
                auto_res = strategy.run_cycle(market_trend=vibe.lower(), skip_trade=False)
                if auto_res:
                    for r in auto_res: add_trading_log(f"🤖 자동: {r}")
                
                if strategy.bear_config.get("auto_mode", False) and _cached_recommendations:
                    r = _cached_recommendations[0]
                    p = api.get_inquire_price(r['code'])
                    if p:
                        qty = math.floor(r['suggested_amt'] / p['price'])
                        if qty > 0:
                            success, msg = api.order_market(r['code'], qty, True)
                            if success:
                                msg_txt = f"자동{r['type']}: {r['name']} {qty}주"
                                strategy.last_avg_down_msg = f"[{datetime.now().strftime('%H:%M')}] {msg_txt}"
                                strategy.record_buy(r['code'], p['price'])
                                add_trading_log(f"🤖 {msg_txt}")
                                update_all_data(api, strategy, is_virtual, force=True)

                if strategy.auto_ai_trade and strategy.ai_recommendations:
                    top_ai = strategy.ai_recommendations[0]
                    is_held = any(h['pdno'] == top_ai['code'] for h in _cached_holdings)
                    if not is_held:
                        p = api.get_inquire_price(top_ai['code'])
                        if p:
                            a_cfg = strategy.ai_config
                            amt = a_cfg.get("amount_per_trade", 500000)
                            qty = math.floor(amt / p['price'])
                            if qty > 0:
                                success, msg = api.order_market(top_ai['code'], qty, True)
                                if success:
                                    add_trading_log(f"✨ AI자율매수: {top_ai['name']} {qty}주 선점")
                                    update_all_data(api, strategy, is_virtual, force=True)
                                else:
                                    if "잔고가 부족" in msg: strategy.auto_ai_trade = False
                                    add_log(f"AI매수 실패: {msg}")

            _last_update_time = datetime.now().strftime('%H:%M:%S')
        except Exception as e:
            from src.logger import log_error
            log_error(f"Data Update Error: {e}")
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
        
        buf.write("\033[93m" + align_kr(" [COMMANDS] 1:매도 | 2:매수 | 3:자동매매 | 4:추천매매 | 물타기(5:설정 6:실행) | 9:필터 | A:AI도움 | D:리포트 | S:셋업 | Q:종료", tw) + "\033[0m\n")
        
        # 커맨드 하단 브리핑/가이드 영역 (4줄 확장)
        if prompt_mode: 
            buf.write("\033[1;33m" + align_kr(f" >>> [{prompt_mode} MODE] 입력 대기 중... (ESC 취소)", tw) + "\033[0m\n")
            buf.write("\n" * 3)
        elif strategy.ai_briefing:
            # AI 브리핑 출력 (시장, 전략, 액션, 추천 4개 라인 활용)
            brief_lines = [line.strip() for line in strategy.ai_briefing.split('\n') if line.strip()][:4]
            for line in brief_lines:
                buf.write("\033[1;95m" + align_kr(f" {line}", tw) + "\033[0m\n")
            for _ in range(4 - len(brief_lines)): buf.write("\n")
        else:
            buf.write("\n" * 4) 
        
        buf.write("=" * tw + "\n")

        asset = _cached_asset; p_c = "\033[91m" if asset['pnl'] >= 0 else "\033[94m"
        p_rt = (asset['pnl'] / (asset['total_asset'] - asset['pnl']) * 100) if (asset['total_asset'] - asset['pnl']) > 0 else 0
        asset_line = f" ASSETS | Total: {asset['total_asset']:,.0f} | Stock: {asset['stock_eval']:,.0f} | Profit: {p_c}{asset['pnl']:+,} ({abs(p_rt):.2f}%)\033[0m | Cash: {asset['cash']:,.0f}"
        buf.write(align_kr(asset_line, tw) + "\n")
        
        # 전략 라인 추가 (BASE 전략 표시용은 주입 없이 호출 가능)
        tp_cur, sl_cur, _ = strategy.get_dynamic_thresholds("BASE", _cached_vibe.lower())
        strat_title = "* STRAT" if strategy.is_modified("STRAT") else " STRAT "
        strat_line = f"{strat_title} | 매입/수: 익절 {strategy.base_tp:+.1f}% (현재 {tp_cur:+.1f}%) | 손절 {strategy.base_sl:+.1f}% (현재 {sl_cur:+.1f}%)"
        buf.write(align_kr(strat_line, tw) + "\n")

        bear_title = "* BEAR " if strategy.is_modified("BEAR") else " BEAR  "
        bear_line = f"{bear_title} | 물타기: 트리거 {b_cfg.get('min_loss_to_buy'):+.1f}% | 회당 {b_cfg.get('average_down_amount'):,}원 | 종목한도 {b_cfg.get('max_investment_per_stock'):,}원 | 자동: {auto_st} | 로직: PnL기준 & 현재가<평단"
        buf.write(align_kr(bear_line, tw) + "\n")

        a_cfg = strategy.ai_config
        ai_st = "ON" if a_cfg.get("auto_mode") else "OFF"
        algo_title = "* ALGO " if strategy.is_modified("ALGO") else " ALGO  "
        algo_line = f"{algo_title} | 추천매매: 회당 {a_cfg.get('amount_per_trade'):,}원 | 종목한도 {a_cfg.get('max_investment_per_stock'):,}원 | 자동: {ai_st} | 로직: 테마뉴스모멘텀 & 보합선취매"
        buf.write(align_kr(algo_line, tw) + "\n")
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
        
        # --- 레이아웃 동적 계산 (자산 리스트 우선) ---
        # 상단(10)+브리핑(4)+자산/전략(5)+테마/추천(9)+하단(5) = 약 33줄
        # 30줄 터미널에서도 작동할 수 있도록 유연하게 조정
        fixed_h = 26 if th < 35 else 33
        available_h = max(3, th - fixed_h)
        
        asset_count = len(f_h)
        if asset_count == 0:
            max_h_display = 1
            ranking_items_count = max(5, min(10, available_h))
        else:
            # 1. 자산 리스트에 우선 배분
            max_h_display = min(asset_count, available_h)
            if th < 35: # 작은 화면에서는 자산 리스트를 더 축약
                max_h_display = min(max_h_display, 5)
            
            # 2. 남은 공간을 랭킹에 배분
            ranking_items_count = max(0, th - (fixed_h + max_h_display))
            if th < 35: # 작은 화면에서도 최소 3개는 보이도록 강제
                ranking_items_count = max(3, min(8, ranking_items_count))
            else:
                ranking_items_count = max(3, min(10, ranking_items_count))
                # 랭킹을 위해 자산 리스트를 더 축소 (필요시)
                if fixed_h + max_h_display + ranking_items_count > th:
                    max_h_display = max(1, th - fixed_h - ranking_items_count)

        if not f_h: 
            buf.write(align_kr(f"No active {_ranking_filter} holdings found.", tw, 'center') + "\n")
        else:
            display_h = f_h[:max_h_display]
            
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
        
        # --- 인기 테마 섹션 (자산 아래, HOT SEARCH 위) ---
        buf.write("-" * tw + "\n")
        if _cached_themes:
            theme_str = " 🔥 인기테마: "
            for theme in _cached_themes[:8]: # 상위 8개만 표시
                theme_str += f"{theme['name']}({theme['count']}) | "
            buf.write("\033[93m" + align_kr(theme_str.rstrip(" | "), tw) + "\033[0m\n")
        else:
            buf.write("\n")
        buf.write("-" * tw + "\n")
        
        # --- AI 추천 섹션 (개별 종목 6개 + ETF 3개 분리) ---
        ai_mode = "[\033[91mAUTO\033[0m]" if strategy.auto_ai_trade else "[\033[93mMANUAL\033[0m]"
        buf.write("\033[1;92m" + align_kr(f" ✨ AI 추천 {ai_mode} (보합/저평가 선점)", tw) + "\033[0m\n")
        
        recs = strategy.ai_recommendations
        if not recs:
            buf.write(align_kr(" ... 유망 종목 및 ETF 분석 중 ...", tw) + "\n")
            buf.write("\n" * 2)
        else:
            stocks = [r for r in recs if not r.get('is_etf')]
            etfs = [r for r in recs if r.get('is_etf')]
            
            # 1. 개별 종목 출력 (최대 6개, 2줄)
            col_w = (tw - 4) // 3
            for i in range(2):
                row_str = " "
                for j in range(3):
                    idx = i * 3 + j
                    if idx < len(stocks):
                        r = stocks[idx]
                        rate = float(r['rate'])
                        color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
                        # 형식: (테마) [코드] 이름 (등락률)
                        item_txt = f"({r['theme'][:3]}) [{r['code']}] {r['name'][:8]} ({color}{rate:+.1f}%\033[0m)"
                        row_str += align_kr(item_txt, col_w) + " "
                    else:
                        row_str += " " * (col_w + 1)
                buf.write(row_str.rstrip() + "\n")
            
            # 2. ETF 섹션 (최대 3개, 1줄)
            row_str = " "
            for j in range(3):
                if j < len(etfs):
                    r = etfs[j]
                    rate = float(r['rate'])
                    color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
                    item_txt = f"(ETF) [{r['code']}] {r['name'][:12]} ({color}{rate:+.1f}%\033[0m)"
                    row_str += align_kr(item_txt, col_w) + " "
            buf.write(row_str.rstrip() + "\n")
            
        buf.write("-" * tw + "\n")

        left_w, right_w = (tw - 3) // 2, tw - 3 - (tw - 3) // 2
        
        # 네이버 랭킹 필터링 및 슬라이싱
        if _ranking_filter == "ALL":
            hot_list = _cached_hot_raw[:ranking_items_count]
            vol_list = _cached_vol_raw[:ranking_items_count]
        else:
            hot_list = [g for g in _cached_hot_raw if str(g.get('mkt','')).strip().upper() == _ranking_filter.strip().upper() or _ranking_filter == "ALL"][:ranking_items_count]
            vol_list = [l for l in _cached_vol_raw if str(l.get('mkt','')).strip().upper() == _ranking_filter.strip().upper() or _ranking_filter == "ALL"][:ranking_items_count]

        # Fallback: 인기검색어가 비어있을 경우 거래량 상위 종목 중 등락률 높은 순으로 대체
        if not hot_list and _cached_vol_raw:
            fallback_hot = sorted(_cached_vol_raw, key=lambda x: abs(x.get('rate', 0)), reverse=True)
            hot_list = fallback_hot[:ranking_items_count]

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
            if ranking_items_count > 1:
                buf.write("\n" * (ranking_items_count - 1))
        else:
            for i in range(ranking_items_count): 
                buf.write(f"{format_rank(hot_list[i] if i < len(hot_list) else None, True, left_w)} │ {format_rank(vol_list[i] if i < len(vol_list) else None, False, right_w)}\n")
    
    # --- 하단 로그 및 상태창 배분 (로그 축약 로직 강화) ---
    sys.stdout.write(buf.getvalue())
    remaining = th - len(buf.getvalue().split('\n')) + 1
    
    if remaining > 0:
        if _status_msg and (time.time() - _status_time < 60): sys.stdout.write(f"\033[K {_status_msg}\n")
        else: sys.stdout.write("\033[K \n")
        remaining -= 1
    if remaining > 0:
        if _last_log_msg and (time.time() - _last_log_time < 60): sys.stdout.write(f"\033[K {_last_log_msg}\n")
        else: sys.stdout.write("\033[K \n")
        remaining -= 1

    # 트레이딩 로그 출력 (공간 부족 시 축약)
    if remaining > 0:
        if len(_trading_logs) > remaining:
            # 공간이 부족하면 상단을 생략하고 "외 X건" 표시
            skip_count = len(_trading_logs) - (remaining - 1)
            sys.stdout.write(f"\033[K \033[90m... 외 {skip_count}건의 로그 생략됨\033[0m\n")
            display_logs = _trading_logs[-(remaining - 1):]
            remaining -= 1
        else:
            display_logs = _trading_logs
            
        for i, tl in enumerate(display_logs):
            if remaining <= 0: break
            if i == len(display_logs) - 1 and remaining == 1: sys.stdout.write(f"\033[K {tl}")
            else: sys.stdout.write(f"\033[K {tl}\n")
            remaining -= 1

    while remaining > 0:
        if remaining == 1: sys.stdout.write("\033[K")
        else: sys.stdout.write("\033[K\n")
        remaining -= 1
    sys.stdout.flush(); buf.close()
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
            c = sys.stdin.read(1)
            if c == '\x1b':
                # 다른 키(화살표 등)의 시작일 수 있으므로 짧게 대기하여 확인
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    sys.stdin.read(1) # [ 등을 소비
                    return None
                return 'esc'
            return c.lower()
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

def draw_ai_detail(strategy, tw, th):
    """AI 추천 종목의 상세 분석 정보를 전체 화면으로 출력"""
    buf = io.StringIO()
    buf.write("\033[H\033[2J") # 화면 전체 삭제
    header = " [AI DETAILED STRATEGY REPORT] "
    buf.write("\033[42;30m" + align_kr(header, tw, 'center') + "\033[0m\n\n")
    
    # --- AI 시장 전망 섹션 (시장 브리핑 전체 출력) ---
    buf.write("\033[1;93m" + " [AI 시장 전망 및 종합 의견]" + "\033[0m\n")
    if strategy.ai_briefing:
        for line in strategy.ai_briefing.split('\n'):
            if line.strip():
                buf.write(f"  {line.strip()}\n")
    else:
        buf.write("  분석된 시장 브리핑이 없습니다.\n")
    
    buf.write("\n" + "=" * tw + "\n\n")
    
    recs = strategy.ai_recommendations
    if not recs:
        buf.write(align_kr("현재 분석된 상세 추천 종목이 없습니다. 'A'를 눌러 분석을 먼저 수행하세요.", tw, 'center') + "\n")
    else:
        # 표 헤더 (지표 통합)
        h = f"{align_kr('테마', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('현재가', 9)} | {align_kr('등락', 7)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('배당', 6)} | {align_kr('업종PER', 7)} | {align_kr('AI점수', 6)} | 발굴 근거"
        buf.write("\033[1m" + h + "\033[0m\n")
        buf.write("-" * tw + "\n")
        
        for r in recs:
            code = r['code']
            rate = float(r['rate'])
            color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
            rate_txt = f"{color}{rate:+.1f}%\033[0m"
            gem_mark = "💎" if r.get('is_gem') else "  "
            
            # 지표 데이터 실시간 수집 (캐시 활용)
            detail = strategy.api.get_naver_stock_detail(code)
            
            row = f"{align_kr(r['theme'], 8)} | {align_kr(code, 8)} | {align_kr(gem_mark + r['name'], 14)} | {align_kr(f'{int(float(r.get('price',0))):,}', 9, 'right')} | {align_kr(rate_txt, 7, 'right')} | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(detail.get('yield','N/A'), 6, 'right')} | {align_kr(detail.get('sector_per','N/A'), 7, 'right')} | {align_kr(f'{r['score']:.1f}', 6, 'right')} | {r['reason']}"
            buf.write(row + "\n")
            
    # --- AI 심층 투자 의견 (공간 최적화 출력) ---
    buf.write("\n" + "-" * tw + "\n")
    buf.write("\033[1;92m" + " [AI 수석 전략가 입체 분석 및 대응 전략]" + "\033[0m\n")
    
    if strategy.ai_detailed_opinion:
        opinion_lines = [l.strip() for l in strategy.ai_detailed_opinion.split('\n') if l.strip()]
        # 터미널 높이에 따라 유동적으로 조절 (최대 15줄까지 허용)
        max_opinion_h = max(5, th - 25) # 대략적인 나머지 공간 계산
        for line in opinion_lines[:max_opinion_h]:
            buf.write(f" > {line}\n")
    else:
        buf.write(" ⚠️ 아직 생성된 분석 의견이 없습니다. 'A'를 눌러 분석을 먼저 수행하세요.\n")
            
    buf.write("-" * tw + "\n")
    buf.write(align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue())
    sys.stdout.flush()
    # 키 대기
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()

def perform_interaction(key, api, strategy, cycle):
    global _ranking_filter, _status_msg, _last_log_msg, _cached_recommendations
    flush_input()
    # 키 입력을 소문자로 통일하여 처리
    mode = (key[-1] if 'alt+' in key else key).lower()
    
    # 유효한 키 리스트에 'a', 'd' 확실히 포함
    if mode not in ['1', '2', '3', '4', '5', '6', '9', 'a', 'd', 'q', 's']: return
    
    if mode == 'q':
        show_status("🛑 프로그램을 종료합니다. 잠시만 기다려주세요...")
        draw_tui(strategy, cycle)
        time.sleep(1)
        restore_terminal_settings()
        exit_alt_screen()
        print("\n[AI TRADING SYSTEM] 사용자에 의해 안전하게 종료되었습니다.")
        os._exit(0)

    if mode == 'd':
        restore_terminal_settings()
        draw_ai_detail(strategy, os.get_terminal_size().columns, os.get_terminal_size().lines)
        enter_alt_screen()
        set_terminal_raw()
        flush_input()
        time.sleep(0.2)
        return

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
        config = get_config()
        new_auth = KISAuth()
        api.auth = new_auth
        api.domain = new_auth.domain
        strategy.api = api
        enter_alt_screen()
        set_terminal_raw()
        show_status("✅ 환경 설정이 성공적으로 갱신되었습니다.")
        update_all_data(api, strategy, new_auth.is_virtual, force=True)
        return

    try:
        tw = os.get_terminal_size().columns
    except: tw = 110

    set_terminal_raw()
    try:
        m_label = '매도' if mode=='1' else '매수' if mode=='2' else '자동매매' if mode=='3' else '추천매매' if mode=='4' else '물타기설정' if mode=='5' else '물타기실행' if mode=='6' else '필터' if mode=='9' else 'AI도움' if mode=='a' else '리포트' if mode=='d' else '셋업'
        
        # AI도움(A)이나 리포트(D)는 즉시 실행형이므로 프롬프트 모드 표시 최소화
        if mode not in ['a', 'd']:
            draw_tui(strategy, cycle, prompt_mode=m_label)
        
        # 커서 위치 제어 (COMMAND 가이드 라인 직후)
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
        elif mode == '4':
            res = input_with_esc("> 추천매매설정 [금액 한도 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 3:
                    try:
                        amt, lim = int(inp[0]), int(inp[1])
                        auto = inp[2].lower() == 'y'
                        strategy.ai_config.update({"amount_per_trade": amt, "max_investment_per_stock": lim, "auto_mode": auto})
                        strategy._save_all_states(); show_status(f"✨ AI 추천매매 설정 완료 (자동:{'ON' if auto else 'OFF'})")
                    except Exception as e: show_status(f"❌ 입력 오류: {e}", True)
                else: show_status("⚠️ 입력값이 부족합니다. [금액 한도 y/n] 순으로 입력하세요.", True)
        elif mode == 'a':
            if not os.getenv("GOOGLE_API_KEY"):
                show_status("⚠️ Gemini API Key가 없습니다. [S:셋업]에서 입력하세요.", True)
            else:
                def progress_callback(curr, total, phase="분석"):
                    show_status(f"[AI {phase} 중... {curr}/{total}]")
                    draw_tui(strategy, cycle)

                show_status("🧠 Gemini AI가 시장 상황을 분석 중입니다. 잠시만 기다려주세요...")
                draw_tui(strategy, cycle)
                
                # Update recommendations first with progress
                strategy.update_ai_recommendations(_cached_themes, _cached_hot_raw, _cached_vol_raw, progress_cb=lambda c, t: progress_callback(c, t, "종목발굴"))
                
                advice = strategy.get_ai_advice(progress_cb=lambda c, t: progress_callback(c, t, "심층분석"))
                if advice and "⚠️" not in advice:
                    show_status("✅ AI 분석 완료. 하단 브리핑을 확인하세요.")
                    draw_tui(strategy, cycle) # 브리핑 출력
                    
                    # 수치 파싱 시도 및 반영 여부 확인
                    if strategy.parse_and_apply_ai_strategy():
                        # 파싱 성공 시 확인 절차 (수동 확인용 메시지)
                        show_status("💡 AI가 새로운 전략 수치를 도출했습니다. 반영할까요?")
                        res_a = input_with_esc("> AI 제안 수치를 시스템에 즉시 반영할까요? (y/n): ", tw)
                        if res_a and res_a.strip().lower() == 'y':
                            show_status("🚀 AI 전략이 시스템에 완벽히 반영되었습니다.")
                            update_all_data(api, strategy, True, force=True)
                        else:
                            show_status("⚠️ AI 전략 반영이 취소되었습니다. (기존 설정 유지)")
                    else:
                        show_status("❌ AI 전략 파싱 실패 (수치 형식이 올바르지 않음)", True)
                else:
                    show_status(f"❌ AI 분석 실패: {advice if advice else '알 수 없는 오류'}", True)
                flush_input(); time.sleep(0.2)
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
                                strategy.record_buy(r['code'], p['price'])
                                show_status(f"✅ {r['name']} 매수 완료")
                                update_all_data(api, strategy, True, force=True)
                            else: show_status(f"❌ {msg}", True)
            else:
                show_status("⚠️ 현재 물타기 추천 종목이 없습니다.")
        elif mode == '9':
            res = input_with_esc("> 필터 [1:ALL, 2:KSP, 3:KDQ]: ", tw)
            if res:
                sel = res.strip()
                if sel == '1': _ranking_filter = "ALL"
                elif sel == '2': _ranking_filter = "KSP"
                elif sel == '3': _ranking_filter = "KDQ"
    except Exception as e:
        from src.logger import log_error
        log_error(f"Interaction Error: {e}"); show_status(f"오류: {e}", True)
    finally:
        # 종료/취소 시 입력하던 2줄만 정밀하게 지우기 (화면 전체 삭제 \033[2J 제거)
        sys.stdout.write("\033[5;1H\033[K\033[6;1H\033[K")
        sys.stdout.flush()
        set_terminal_raw(); flush_input()

def main():
    ensure_env(); load_dotenv(); config = get_config(); init_terminal()
    auth = KISAuth(); api = KISAPI(auth); strategy = VibeStrategy(api, config)
    enter_alt_screen()
    threading.Thread(target=index_update_worker, args=(api, strategy), daemon=True).start()
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
