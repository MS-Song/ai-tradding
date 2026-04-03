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
from src.strategy import VibeStrategy, PRESET_STRATEGIES
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

ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def get_visual_width(text):
    plain_text = ANSI_ESCAPE.sub('', str(text))
    w = 0
    for c in plain_text:
        if ord(c) < 128: w += 1
        elif unicodedata.east_asian_width(c) in ['W', 'F', 'A']: w += 2
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
_cached_asset = {"total_asset":0, "total_principal":0, "stock_eval":0, "stock_principal":0, "cash":0, "pnl":0, "deposit":0}
_cached_stock_info = {} # 종목별 추가 정보 캐시 (TP/SL, 볼륨 스파이크 등)
_cached_hot_raw = []
_cached_vol_raw = []
_cached_recommendations = [] 
_cached_market_data = {}
_cached_vibe = "Neutral"
_cached_panic = False
_last_update_time = ""
_ranking_filter = "ALL"

# --- 글로벌 진행 표시기 상태 ---
_global_busy_msg = None
_busy_anim_step = 0

def set_busy(msg):
    global _global_busy_msg
    _global_busy_msg = msg

def clear_busy():
    global _global_busy_msg
    _global_busy_msg = None
_is_kr_market_active = False
_data_lock = threading.Lock()
_ui_lock = threading.Lock()

# 개별 갱신 시각 관리
_last_times = {"index": 0, "asset": 0, "ranking": 0}

def show_status(msg, is_error=False):
    global _status_msg, _status_time
    color = "\033[91m" if is_error else "\033[92m"
    # 터미널 너비 초과 방지 (ANSI 코드 제외 실제 표시 길이 기준 잘라냄)
    try:
        max_len = os.get_terminal_size().columns - 12  # [STATUS] + 여백
    except: max_len = 100
    if len(msg) > max_len:
        msg = msg[:max_len - 2] + ".." 
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
    
    set_busy("데이터 동기화")
    try:
        curr_t = time.time()
        # ... (생략된 기존 로직 수행) ...
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
            p_data = api.get_inquire_price(code)
            tp, sl, spike = strategy.get_dynamic_thresholds(code, _cached_vibe.lower(), p_data)
            
            # 시세 API에서 가져온 전일 대비 데이터를 캐시에 저장
            day_val = p_data.get('vrss', 0) if p_data else 0
            day_rate = p_data.get('ctrt', 0) if p_data else 0
            
            _cached_stock_info[code] = {
                "tp": tp, "sl": sl, "spike": spike,
                "day_val": day_val, "day_rate": day_rate
            }
        
        _last_update_time = datetime.now().strftime('%H:%M:%S')
        add_log("데이터 동기화 완료")
        return True
    except Exception as e:
        from src.logger import log_error
        log_error(f"Update Error: {e}")
        return False
    finally:
        clear_busy()

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
            strategy.refresh_yesterday_recs_performance(h_raw, v_raw)
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
                        
                        # 시세 API에서 가져온 전일 대비 데이터를 캐시에 저장
                        day_val = p_data.get('vrss', 0) if p_data else 0
                        day_rate = p_data.get('ctrt', 0) if p_data else 0
                        
                        _cached_stock_info[code] = {
                            "tp": tp, "sl": sl, "spike": spike,
                            "day_val": day_val, "day_rate": day_rate
                        }
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
                    
                    # [개편] 평시 장세(Bull/Neutral)에서 인버스 상품 추천 시 자동 매수 제외
                    skip_auto_buy = False
                    if top_ai.get('is_inverse', False) and "defensive" not in vibe.lower() and "bear" not in vibe.lower():
                        skip_auto_buy = True
                        add_log(f"보류: {top_ai['name']} (인버스 상품은 하락 방어장에서만 자동 매수)")
                    
                    is_held = any(h['pdno'] == top_ai['code'] for h in _cached_holdings)
                    if not is_held and not skip_auto_buy:
                        p = api.get_inquire_price(top_ai['code'])
                        if p:
                            a_cfg = strategy.ai_config
                            amt = a_cfg.get("amount_per_trade", 500000)
                            qty = math.floor(amt / p['price'])
                            if qty > 0:
                                success, msg = api.order_market(top_ai['code'], qty, True)
                                if success:
                                    add_trading_log(f"✨ AI자율매수: {top_ai['name']} {qty}주 선점")
                                    # 자동 매수 성공 → 프리셋 전략 자동 할당
                                    preset_result = strategy.auto_assign_preset(top_ai['code'], top_ai['name'])
                                    if preset_result:
                                        add_trading_log(f"📋 전략 자동적용: [{preset_result['preset_name']}] TP:{preset_result['tp']:+.1f}% SL:{preset_result['sl']:.1f}%")
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
    
    with _ui_lock:
        try:
            size = os.get_terminal_size(); tw, th = size.columns, size.lines
        except: tw, th = 110, 30

        buf = io.StringIO()
        if (tw, th) != _last_size: buf.write("\033[2J"); _last_size = (tw, th)
        buf.write("\033[H")
    
    now_dt = datetime.now()
    k_st, u_st = ("OPEN" if is_market_open() else "CLOSED"), ("OPEN" if is_us_market_open() else "CLOSED")
    
    # 상단 헤더 구성
    m_label = "ALL" if _ranking_filter == "ALL" else "KOSPI" if _ranking_filter == "KSP" else "KOSDAQ" if _ranking_filter == "KDQ" else "USA"
    h_l = f" [AI TRADING SYSTEM] | {now_dt.strftime('%Y-%m-%d %H:%M:%S')} | KR:{k_st} | US:{u_st}"
    h_r = f" ✅ LAST UPDATE: {_last_update_time} | FILTER: {m_label} "
    
    # --- 글로벌 진행 표시기 (중앙 배치) ---
    busy_txt = ""
    if _global_busy_msg:
        global _busy_anim_step
        _busy_anim_step = (_busy_anim_step + 1) % 4
        dots = "." * (_busy_anim_step + 1)
        # 배경색(44m)을 유지하면서 글자색만 노란색(33m)으로 변경하고, 다시 흰색 글자+파랑배경으로 복구
        busy_txt = f"\033[1;33m{_global_busy_msg}{dots}\033[0;37;44m"
    
    # 가용 공간 계산 및 중앙 정렬
    total_h_w = get_visual_width(h_l) + get_visual_width(h_r)
    space_between = max(0, tw - total_h_w)
    
    if busy_txt:
        # 진행 중 문구가 있을 경우 중앙에 삽입
        busy_plain = ANSI_ESCAPE.sub('', busy_txt)
        busy_w = get_visual_width(busy_plain)
        l_pad = max(0, (space_between - busy_w) // 2)
        r_pad = max(0, space_between - busy_w - l_pad)
        header_line = h_l + " " * l_pad + busy_txt + " " * r_pad + h_r
    else:
        header_line = h_l + " " * space_between + h_r

    # 전체 라인이 tw 너비를 채우도록 추가 패딩 (오차 방지)
    final_w = get_visual_width(header_line)
    if final_w < tw:
        header_line += " " * (tw - final_w)

    buf.write("\033[44m" + header_line + "\033[0m\n")
    
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
        
        # 2. 환율 (KR 라인 끝)
        usd_krw = _cached_market_data.get("FX_USDKRW")
        btc_krw = _cached_market_data.get("BTC_KRW")
        btc_usd = _cached_market_data.get("BTC_USD")
        
        if usd_krw:
            color = "\033[91m" if usd_krw['rate'] >= 0 else "\033[94m"
            k_mkt_l += f"USDKRW {usd_krw['price']:,.1f}({color}{usd_krw['rate']:+0.2f}%\033[0m)  "
            
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

        # C Market Line (Crypto Market 전용 라인: 제목에 색상 없이 초기화 후 시작)
        c_mkt_l = "\033[0m C Market:  "
        if btc_krw and btc_usd and usd_krw:
            # 1. K-BTC (국내 원화 가격)
            k_color = "\033[91m" if btc_krw['rate'] >= 0 else "\033[94m"
            c_mkt_l += f"K-BTC {btc_krw['price']:,.0f}({k_color}{btc_krw['rate']:+0.2f}%\033[0m)   "
            
            # 2. BTC (해외 달러 가격 -> 원화 환산)
            usd_to_krw_price = btc_usd['price'] * usd_krw['price']
            u_color = "\033[91m" if btc_usd['rate'] >= 0 else "\033[94m"
            c_mkt_l += f"BTC {usd_to_krw_price:,.0f}({u_color}{btc_usd['rate']:+0.2f}%\033[0m)   "
            
            # 3. PREM (금액 차이 및 비율)
            diff_amt = btc_krw['price'] - usd_to_krw_price
            k_prem = (diff_amt / usd_to_krw_price) * 100
            p_color = "\033[91m" if k_prem >= 0 else "\033[94m"
            c_mkt_l += f"PREM {int(diff_amt):+,}({p_color}{k_prem:+0.2f}%\033[0m)"
        
        buf.write(align_kr(c_mkt_l, tw) + "\n")

        v_c = "\033[91m" if "Bull" in _cached_vibe else ("\033[94m" if "Bear" in _cached_vibe else "\033[93m")
        panic_txt = " !!! PANIC !!!" if _cached_panic else ""
        b_cfg = strategy.bear_config
        auto_st = "ON" if b_cfg.get("auto_mode") else "OFF"
        
        # [Task 6] Market Phase 정보 및 아이콘 추가
        phase = strategy.get_market_phase()
        phase_icons = {"P1": "🔥", "P2": "🧘", "P3": "💰", "P4": "🛒", "IDLE": "💤"}
        phase_icon = phase_icons.get(phase['id'], "💤")
        phase_txt = f" [PHASE: {phase_icon}{phase['name']}]"

        if "Bear" in _cached_vibe:
            vibe_desc = f"(하락장: 물타기 [\033[94m{b_cfg.get('min_loss_to_buy')}% / {b_cfg.get('average_down_amount')/10000:,.0f}만 / 자동:{auto_st}\033[0m])"
        elif "Bull" in _cached_vibe:
            vibe_desc = "(\033[91m상승장: 익절 기준 상향 보정 [+3.0%]\033[0m)"
        else:
            vibe_desc = "(보합장: 기본 전략 유지)"
            
        # AI 검증 교정 메시지 추가 (있을 경우만)
        ai_msg = strategy.analyzer.ai_override_msg if hasattr(strategy.analyzer, "ai_override_msg") else ""
        if ai_msg:
            if "일치" in ai_msg:
                ai_msg_formatted = f"\033[92m{ai_msg}\033[0m"
            else:
                ai_msg_formatted = f"\033[93m{ai_msg}\033[0m"
        else:
            ai_msg_formatted = ""
            
        buf.write(align_kr(f" VIBE: {v_c}{_cached_vibe.upper()}\033[0m{phase_txt} {panic_txt} {vibe_desc}{ai_msg_formatted}", tw) + "\n")
        
        # 3번 메뉴 명칭 변경: 전략 -> 자동
        buf.write("\033[93m" + align_kr(f" [COMMANDS] 1:매도 | 2:매수 | 3:자동 | 4:추천 | 5:물타기 6:불타기 | 7:분석 8:시황 | 9:전략 | 리포트 B:보유 D:추천 H:인기 | M:메뉴얼 | S:셋업 | Q:종료", tw) + "\033[0m\n")
        
        # --- [이동] AI 브리핑 출력 (커맨드 메뉴 바로 아래) ---
        if strategy.ai_briefing and not prompt_mode:
            # AI 브리핑 출력 (시장, 전략, 액션, 추천 각 1줄씩 총 4개 라인 고정)
            all_lines = [line.strip() for line in strategy.ai_briefing.split('\n') if line.strip()]
            brief_map = {"시장": "", "전략": "", "액션": "", "추천": ""}
            for l in all_lines:
                for k in brief_map.keys():
                    if f"AI[{k}]:" in l: brief_map[k] = l; break
            
            # 순서대로 4줄 출력 (내용이 없어도 라인 확보)
            for k in ["시장", "전략", "액션", "추천"]:
                line_txt = brief_map[k] if brief_map[k] else f"AI[{k}]: 분석 데이터 없음"
                buf.write("\033[1;95m" + align_kr(f" {line_txt}", tw) + "\033[0m\n")
        elif prompt_mode: 
            buf.write("\033[1;33m" + align_kr(f" >>> [{prompt_mode} MODE] 입력 대기 중... (ESC 취소)", tw) + "\033[0m\n")
            buf.write("\n" * 3)
        else:
            buf.write("\n" * 4) 
        
        buf.write("=" * tw + "\n")

        asset = _cached_asset
        
        # Total
        tot_eval = asset.get('total_asset', 0)
        tot_prin = asset.get('total_principal', 0)
        tot_rt = ((tot_eval - tot_prin) / tot_prin * 100) if tot_prin > 0 else 0
        # 컬러 로직: 양수(수익)는 빨강(91), 음수(손실)는 파랑(94)
        tot_color = "\033[91m" if tot_rt > 0 else "\033[94m" if tot_rt < 0 else "\033[0m"
        tot_str = f"평가액: {tot_eval:,.0f} (원금: {tot_prin:,.0f}, {tot_color}{tot_rt:+.2f}%\033[0m)"
        
        # Cash
        cash_val = asset.get('cash', 0)
        cash_str = f"인출가능: {cash_val:,.0f}"
        
        # Stock
        stk_eval = asset.get('stock_eval', 0)
        stk_prin = asset.get('stock_principal', 0)
        stk_rt = ((stk_eval - stk_prin) / stk_prin * 100) if stk_prin > 0 else 0
        stk_color = "\033[91m" if stk_rt > 0 else "\033[94m" if stk_rt < 0 else "\033[0m"
        stk_str = f"주식총액: {stk_eval:,.0f} ({stk_color}{stk_rt:+.2f}%\033[0m)"
        
        asset_line = f" Asset | {tot_str} | {cash_str} | {stk_str}"
        buf.write(align_kr(asset_line, tw) + "\n")
        
        # 전략 라인 추가 (BASE 전략 표시용은 주입 없이 호출 가능)
        tp_cur, sl_cur, _ = strategy.get_dynamic_thresholds("BASE", _cached_vibe.lower())
        strat_title = "* STRAT" if strategy.is_modified("STRAT") else " STRAT "
        strat_line = f"{strat_title} | 매입/수: 익절 {strategy.base_tp:+.1f}% (현재 {tp_cur:+.1f}%) | 손절 {strategy.base_sl:+.1f}% (현재 {sl_cur:+.1f}%)"
        buf.write(align_kr(strat_line, tw) + "\n")

        bear_title = "* BEAR " if strategy.is_modified("BEAR") else " BEAR  "
        bear_line = f"{bear_title} | 물타기: 트리거 \033[94m{b_cfg.get('min_loss_to_buy'):+.1f}%\033[0m | 회당 {b_cfg.get('average_down_amount'):,}원 | 종목한도 {b_cfg.get('max_investment_per_stock'):,}원 | 자동: {auto_st} | PnL 하락 방어"
        buf.write(align_kr(bear_line, tw) + "\n")

        u_cfg = strategy.bull_config
        u_st = "ON" if u_cfg.get("auto_mode") else "OFF"
        bull_title = "* BULL " if strategy.is_modified("BULL") else " BULL  "
        bull_line = f"{bull_title} | 불타기: 트리거 \033[91m+{u_cfg.get('min_profit_to_pyramid'):.1f}%\033[0m | 회당 {u_cfg.get('average_down_amount'):,}원 | 종목한도 {u_cfg.get('max_investment_per_stock'):,}원 | 자동: {u_st} | 수익 비중 확대"
        buf.write(align_kr(bull_line, tw) + "\n")

        a_cfg = strategy.ai_config
        ai_st = "ON" if a_cfg.get("auto_mode") else "OFF"
        algo_title = "* ALGO " if strategy.is_modified("ALGO") else " ALGO  "
        algo_line = f"{algo_title} | 추천매매: 회당 {a_cfg.get('amount_per_trade'):,}원 | 종목한도 {a_cfg.get('max_investment_per_stock'):,}원 | 자동: {ai_st} | 테마 모멘텀"
        buf.write(align_kr(algo_line, tw) + "\n")
        buf.write("-" * tw + "\n")

        # 컬럼 정의 (터미널 너비 tw에 맞춰 유연하게 배분)
        eff_w = tw - 4
        w = [
            max(4, int(eff_w * 0.03)),  # NO
            max(5, int(eff_w * 0.04)),  # MKT
            max(15, int(eff_w * 0.15)), # SYMBOL
            max(10, int(eff_w * 0.09)), # CURR
            max(14, int(eff_w * 0.12)), # DAY
            max(10, int(eff_w * 0.08)), # AVG
            max(8, int(eff_w * 0.07)),  # QTY
            max(10, int(eff_w * 0.08)), # EVAL
            max(18, int(eff_w * 0.12)), # PnL
            max(10, int(eff_w * 0.07)), # TP/SL
            max(10, int(eff_w * 0.10)), # STGY (간격 확보를 위해 비중 상향)
            max(6, int(eff_w * 0.05))   # REM
        ]
        header = align_kr("NO",w[0])+align_kr("MKT",w[1])+align_kr("SYMBOL",w[2])+align_kr("CURR",w[3],'right')+align_kr("DAY",w[4],'right')+align_kr("AVG",w[5],'right')+align_kr("QTY",w[6],'right')+align_kr("EVAL",w[7],'right')+align_kr("PnL",w[8],'right')+"  "+align_kr("TP/SL",w[9],'right')+"  "+align_kr("전략",w[10],'center')+align_kr("남음",w[11],'right')
        buf.write("\033[1m" + align_kr(header, tw) + "\033[0m\n")
        f_h = _cached_holdings if _ranking_filter == "ALL" else [h for h in _cached_holdings if get_market_name(h.get('pdno','')) == _ranking_filter]
        
        # --- 레이아웃 동적 계산 (자산 리스트 우선) ---
        # 상단(6)+브리핑(4)+자산/전략(6)+테마(3)+랭킹헤더(2)+로그(2) = 약 23줄 (고정 영역)
        # 랭킹 10줄을 포함하면 총 33줄이 최소 필요 높이
        base_fixed = 23
        ranking_target = 10
        
        asset_count = len(f_h)
        # 랭킹 10개와 고정 영역을 제외한 나머지 공간을 자산 리스트에 할당
        max_h_display = max(1, th - base_fixed - ranking_target)
        
        # 만약 보유 종목이 적다면 남는 공간을 랭킹에 더 주거나 그냥 둠 (여기서는 자산 리스트 최적화)
        if asset_count < max_h_display:
            max_h_display = asset_count
        
        # 랭킹 아이템 수는 남은 공간 전체 활용 (최대 10개)
        ranking_items_count = min(10, max(3, th - base_fixed - max_h_display))
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
                
                # [개선] 시세 API에서 가져온 정밀 전일 대비 데이터 사용
                d_v = info.get("day_val", float(h.get('prdy_vrss', 0)))
                d_r = info.get("day_rate", float(h.get('prdy_ctrt', 0)))
                
                d_c = "\033[91m" if d_v > 0 else "\033[94m" if d_v < 0 else ""
                d_txt = f"{int(d_v):+,}({abs(d_r):.1f}%)" if d_v != 0 else "-"
                
                pnl_amt = (p_cu - p_a) * float(h.get('hldg_qty', 0))
                pnl_rt = float(h.get('evlu_pfls_rt', 0))
                color = "\033[91m" if pnl_amt >= 0 else "\033[94m"
                pnl_txt = f"{int(pnl_amt):+,}({abs(pnl_rt):.2f}%)"
                
                # 프리셋 전략 컬럼 표시 (미설정 시 '표준')
                preset_label = strategy.get_preset_label(code)
                stgy_txt = preset_label if preset_label else "표준"
                stgy_color = "\033[96m" if preset_label else "\033[90m"  # 시안색/회색

                # [Task 6] 데드라인 남은 시간 계산
                rem_txt = "-"
                p_strat = strategy.preset_strategies.get(code)
                if p_strat and p_strat.get('deadline'):
                    try:
                        deadline_dt = datetime.strptime(p_strat['deadline'], '%Y-%m-%d %H:%M:%S')
                        diff = deadline_dt - datetime.now()
                        rem_mins = int(diff.total_seconds() / 60)
                        rem_txt = f"{rem_mins}M" if rem_mins > 0 else "EXP"
                    except: rem_txt = "ERR"
                
                row = align_kr(str(idx), w[0]) + align_kr(get_market_name(code), w[1]) + align_kr(f"[{code}] {name_disp}" + (" *" if spike else ""), w[2]) + \
                      align_kr(f"{int(p_cu):,}", w[3], 'right') + \
                      d_c + align_kr(d_txt, w[4], 'right') + "\033[0m" + \
                      align_kr(f"{int(p_a):,}", w[5], 'right') + \
                      align_kr(f"{int(float(h.get('hldg_qty', 0))):,}", w[6], 'right') + \
                      align_kr(f"{int(float(h.get('evlu_amt', 0))):,}", w[7], 'right') + \
                      color + align_kr(pnl_txt, w[8], 'right') + "\033[0m" + \
                      "  " + align_kr(f"{tp:+.1f}/{sl:+.1f}%", w[9], 'right') + \
                      "  " + stgy_color + align_kr(stgy_txt, w[10], 'center') + "\033[0m" + \
                      align_kr(rem_txt, w[11], 'right')
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
        
        # --- 어제 추천 종목 성과 (Yesterday's Recs) ---
        y_recs = strategy.yesterday_recs_processed
        if y_recs:
            top_y = y_recs[:3]
            y_content = ""
            for r in top_y:
                color = "\033[91m" if r['change'] >= 0 else "\033[94m"
                y_content += f"\033[0m{r['name']}({color}{r['change']:+0.2f}%\033[0m) | "
            y_line = f"\033[90m 📅 어제 추천 성과: {y_content.rstrip(' | ')}"
            buf.write(align_kr(y_line, tw) + "\033[0m\n")
        else:
            buf.write(align_kr("\033[90m 📅 어제 추천 이력이 없습니다.", tw) + "\033[0m\n")
        buf.write("-" * tw + "\n")

        # --- 최하단 3단 랭킹 구성 (HOT | VOLUME | AI) ---
        col_w = (tw - 6) // 3
        
        # 1. 데이터 필터링 및 슬라이싱
        if _ranking_filter == "ALL":
            hot_list = _cached_hot_raw[:ranking_items_count]
            vol_list = _cached_vol_raw[:ranking_items_count]
        else:
            hot_list = [g for g in _cached_hot_raw if str(g.get('mkt','')).strip().upper() == _ranking_filter.strip().upper() or _ranking_filter == "ALL"][:ranking_items_count]
            vol_list = [l for l in _cached_vol_raw if str(l.get('mkt','')).strip().upper() == _ranking_filter.strip().upper() or _ranking_filter == "ALL"][:ranking_items_count]

        # 2. AI 추천 데이터 (3단 구성을 위해 슬라이싱)
        ai_recs = strategy.ai_recommendations[:ranking_items_count]
        ai_mode_txt = "AUTO" if strategy.auto_ai_trade else "MANUAL"
        ai_color = "\033[91m" if strategy.auto_ai_trade else "\033[93m"

        def format_rank(item, width=col_w):
            if not item: return " " * width
            rate = float(item['rate'])
            price = int(float(item.get('price', 0)))
            color = "\033[91m" if rate >= 0 else "\033[94m"
            
            # [코드] + (가격/등락%) 의 고정 너비 계산
            code_part = f"[{item['code']}] "
            price_part = f"({price:,}/{color}{rate:>+4.1f}%\033[0m)"
            fixed_w = get_visual_width(code_part) + get_visual_width(ANSI_ESCAPE.sub('', price_part))
            
            # 가용 이름 너비 계산
            avail_name_w = width - fixed_w - 1
            name_txt = item['name']
            if get_visual_width(name_txt) > avail_name_w:
                # 공간 부족 시 축약 (.. 포함)
                while get_visual_width(name_txt + "..") > avail_name_w and len(name_txt) > 1:
                    name_txt = name_txt[:-1]
                name_txt += ".."
            
            row = f"{code_part}{name_txt} {price_part}"
            return align_kr(row, width)

        def format_ai_rec(item, width=col_w):
            if not item: return " " * width
            rate = float(item.get('rate', 0))
            price = int(float(item.get('price', 0)))
            color = "\033[91m" if rate >= 0 else "\033[94m"
            
            # 테마 + [코드] + (가격/등락%) 고정 너비
            theme_txt = f"({item.get('theme','?')[0:2]})"
            code_part = f"[{item['code']}] "
            price_part = f"({price:,}/{color}{rate:>+4.1f}%\033[0m)"
            fixed_w = get_visual_width(theme_txt) + get_visual_width(code_part) + get_visual_width(ANSI_ESCAPE.sub('', price_part))
            
            avail_name_w = width - fixed_w - 1
            name_txt = item['name']
            if get_visual_width(name_txt) > avail_name_w:
                while get_visual_width(name_txt + "..") > avail_name_w and len(name_txt) > 1:
                    name_txt = name_txt[:-1]
                name_txt += ".."
                
            row = f"{theme_txt}{code_part}{name_txt} {price_part}"
            return align_kr(row, width)

        # 헤더 출력 (상태에 따라 색상 부여)
        ai_head_txt = f"✨ AI 추천 {ai_color}[{ai_mode_txt}]\033[1;92m"
        h_str = f"\033[1;93m{align_kr('🔥 HOT SEARCH', col_w)}\033[0m │ \033[1;96m{align_kr('📊 VOLUME TOP', col_w)}\033[0m │ \033[1;92m{align_kr(ai_head_txt, col_w)}\033[0m"
        buf.write(h_str + "\n")
        buf.write("─" * col_w + "─┼─" + "─" * col_w + "─┼─" + "─" * col_w + "\n")
        
        if not hot_list and not vol_list and not ai_recs:
            buf.write(align_kr("데이터 수집 중...", tw, 'center') + "\n")
        else:
            for i in range(ranking_items_count):
                row = f"{format_rank(hot_list[i] if i < len(hot_list) else None)} │ " + \
                      f"{format_rank(vol_list[i] if i < len(vol_list) else None)} │ " + \
                      f"{format_ai_rec(ai_recs[i] if i < len(ai_recs) else None)}"
                buf.write(row + "\n")
    
    # --- 하단 로그 및 상태창 배분 (로그 축약 로직 강화) ---
    line_count = buf.getvalue().count('\n')
    remaining = th - line_count
    
    if remaining > 0:
        if _status_msg and (time.time() - _status_time < 60): buf.write(f"\033[K {_status_msg}\n")
        else: buf.write("\033[K \n")
        remaining -= 1
    if remaining > 0:
        if _last_log_msg and (time.time() - _last_log_time < 60): buf.write(f"\033[K {_last_log_msg}\n")
        else: buf.write("\033[K \n")
        remaining -= 1

    # 트레이딩 로그 출력 (공간 부족 시 축약)
    if remaining > 0:
        if len(_trading_logs) > remaining:
            skip_count = len(_trading_logs) - (remaining - 1)
            buf.write(f"\033[K \033[90m... 외 {skip_count}건의 로그 생략됨\033[0m\n")
            display_logs = _trading_logs[-(remaining - 1):]
            remaining -= 1
        else:
            display_logs = _trading_logs
            
        for i, tl in enumerate(display_logs):
            if remaining <= 0: break
            buf.write(f"\033[K {tl}\n")
            remaining -= 1

    while remaining > 0:
        buf.write("\033[K\n")
        remaining -= 1
        
    # 터미널 스크롤 방지를 위한 최종 출력 제어
    content = buf.getvalue()
    lines = content.split('\n')
    if lines and not lines[-1]:
        lines.pop()
        
    # 출력: 마지막 줄에는 \n을 제거하여 화면 최상단이 밀려 올라가는 것을 원천 방지함
    sys.stdout.write("\033[H")
    for i in range(min(th, len(lines))):
        if i == th - 1 or i == len(lines) - 1:
            sys.stdout.write(lines[i] + "\033[K")
        else:
            sys.stdout.write(lines[i] + "\033[K\n")
            
    sys.stdout.flush()
    buf.close()

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

def draw_recommendation_report(strategy, tw, th):
    """AI 추천 종목(총 10개)의 상세 분석 정보를 전체 화면으로 출력"""
    buf = io.StringIO()
    buf.write("\033[H\033[2J") # 화면 전체 삭제
    header = " [AI DETAILED STRATEGY REPORT: TOP 10 RECOMMENDATIONS] "
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
        # 표 헤더 (10개 종목 출력을 위해 컴팩트하게 구성)
        h = f"{align_kr('테마', 10)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('현재가', 9)} | {align_kr('등락', 7)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('AI점수', 6)} | 발굴 근거"
        buf.write("\033[1m" + h + "\033[0m\n")
        buf.write("-" * tw + "\n")
        
        # 10개 종목 전체 출력
        for r in recs:
            code = r['code']
            rate = float(r['rate'])
            color = "\033[91m" if rate > 0 else "\033[94m" if rate < 0 else ""
            rate_txt = f"{color}{rate:+.1f}%\033[0m"
            gem_mark = "💎" if r.get('is_gem') else "  "
            if r.get('is_etf'): gem_mark = "📊"
            
            detail = strategy.api.get_naver_stock_detail(code)
            
            row = f"{align_kr(r['theme'], 8)} | {align_kr(code, 8)} | {align_kr(gem_mark + r['name'], 14)} | {align_kr(f'{int(float(r.get('price',0))):,}', 9, 'right')} | {align_kr(rate_txt, 7, 'right')} | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(f'{r['score']:.1f}', 6, 'right')} | {r['reason']}"
            buf.write(row + "\n")
            
    # --- AI 심층 투자 의견 (전략 리포트) ---
    buf.write("\n" + "-" * tw + "\n")
    buf.write("\033[1;92m" + " [AI 수석 전략가 입체 분석 및 대응 전략]" + "\033[0m\n")
    
    if strategy.ai_detailed_opinion:
        opinion_lines = [l.strip() for l in strategy.ai_detailed_opinion.split('\n') if l.strip()]
        # 10개 종목 출력 후 남은 공간에 최대한 출력
        for line in opinion_lines:
            buf.write(f" > {line}\n")
    else:
        buf.write(" ⚠️ 아직 생성된 상세 분석 의견이 없습니다. '8:시황'을 실행하세요.\n")
            
    buf.write("-" * tw + "\n")
    buf.write(align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue())
    sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()

def draw_holdings_detail(strategy, tw, th):
    """현재 보유 종목에 대한 AI 심층 진단 리포트를 전체 화면으로 출력"""
    buf = io.StringIO()
    buf.write("\033[H\033[2J")
    header = " [AI HOLDINGS PORTFOLIO REPORT] "
    buf.write("\033[44;37m" + align_kr(header, tw, 'center') + "\033[0m\n\n")
    
    # --- 자산 현황 요약 ---
    asset = _cached_asset
    # 컬러 로직: 양수(수익)는 빨강(91), 음수(손실)는 파랑(94)
    p_c = "\033[91m" if asset['pnl'] > 0 else "\033[94m" if asset['pnl'] < 0 else "\033[0m"
    p_rt = (asset['pnl'] / (asset['total_asset'] - asset['pnl']) * 100) if (asset['total_asset'] - asset['pnl']) > 0 else 0
    asset_line = f" [자산 요약] 총자산: {asset['total_asset']:,.0f} | 평가손익: {p_c}{int(asset['pnl']):+,} ({p_rt:+.2f}%)\033[0m | 현금: {asset['cash']:,.0f}"
    buf.write(align_kr(asset_line, tw) + "\n")
    buf.write("-" * tw + "\n\n")
    
    # --- 보유 종목별 지표 리스트 ---
    if not _cached_holdings:
        buf.write(align_kr("현재 보유 중인 종목이 없습니다.", tw, 'center') + "\n")
    else:
        h_line = f"{align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('수익률', 10)} | {align_kr('평가손액', 12)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('업종PER', 7)}"
        buf.write("\033[1m" + h_line + "\033[0m\n")
        buf.write("-" * tw + "\n")
        
        for h in _cached_holdings:
            code = h['pdno']
            pnl_rt = float(h.get('evlu_pfls_rt', 0))
            # API에서 추가된 evlu_pfls_amt 필드 사용
            pnl_amt = int(float(h.get('evlu_pfls_amt', 0)))

            # 컬러 로직: 양수(수익)는 빨강(91), 음수(손실)는 파랑(94)
            color = "\033[91m" if pnl_amt > 0 else "\033[94m" if pnl_amt < 0 else "\033[0m"

            detail = strategy.api.get_naver_stock_detail(code)

            # PnL 수치 및 수익률 출력 (부호 포함)
            pnl_rt_txt = f"{pnl_rt:+.2f}%"
            pnl_amt_txt = f"{pnl_amt:+,}"

            row = f"{align_kr(code, 8)} | {align_kr(h['prdt_name'], 14)} | {color}{align_kr(pnl_rt_txt, 10, 'right')}\033[0m | {color}{align_kr(pnl_amt_txt, 12, 'right')}\033[0m | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(detail.get('sector_per','N/A'), 7, 'right')}"
            buf.write(row + "\n")            
    # --- AI 심층 진단 의견 ---
    buf.write("\n" + "-" * tw + "\n")
    buf.write("\033[1;96m" + " [AI 포트폴리오 매니저의 실시간 진단 의견]" + "\033[0m\n")
    
    if strategy.ai_holdings_opinion:
        for line in strategy.ai_holdings_opinion.split('\n'):
            if line.strip(): buf.write(f"  {line.strip()}\n")
    else:
        buf.write(" ⚠️ 아직 생성된 보유 종목 분석 의견이 없습니다. '7:분석'을 실행하세요.\n")
        
    buf.write("\n" + "-" * tw + "\n")
    buf.write(align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue())
    sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()

def draw_hot_stocks_detail(strategy, tw, th):
    """실시간 인기 검색 종목 TOP 10에 대한 AI 트렌드 분석 리포트"""
    sys.stdout.write("\033[H\033[2J")
    header = " [AI HOT THEME TREND REPORT] "
    sys.stdout.write("\033[45;37m" + align_kr(header, tw, 'center') + "\033[0m\n\n")
    
    # --- 인기 테마 요약 ---
    if _cached_themes:
        theme_line = " [오늘의 인기 테마] "
        for t in _cached_themes[:8]:
            theme_line += f"{t['name']}({t['count']}) | "
        sys.stdout.write("\033[1;93m" + theme_line.rstrip(" | ") + "\033[0m\n")
    sys.stdout.write("-" * tw + "\n\n")
    
    # --- 인기 종목 리스트 ---
    hot = _cached_hot_raw[:10]
    if not hot:
        sys.stdout.write(align_kr("인기 검색 데이터가 없습니다.", tw, 'center') + "\n")
    else:
        h_line = f"{align_kr('NO', 4)} | {align_kr('코드', 8)} | {align_kr('종목명', 14)} | {align_kr('현재가', 10)} | {align_kr('등락률', 8)} | {align_kr('PER', 7)} | {align_kr('PBR', 6)} | {align_kr('업종PER', 7)}"
        sys.stdout.write("\033[1m" + h_line + "\033[0m\n")
        sys.stdout.write("-" * tw + "\n")
        
        for idx, item in enumerate(hot, 1):
            code = item.get('code', '')
            rate = float(item.get('rate', 0))
            color = "\033[91m" if rate >= 0 else "\033[94m"
            
            detail = strategy.api.get_naver_stock_detail(code)
            
            row = f"{align_kr(str(idx), 4)} | {align_kr(code, 8)} | {align_kr(item.get('name','')[:10], 14)} | {align_kr(f'{int(float(item.get("price",0))):,}', 10, 'right')} | {color}{align_kr(f'{rate:+.2f}%', 8, 'right')}\033[0m | {align_kr(detail.get('per','N/A'), 7, 'right')} | {align_kr(detail.get('pbr','N/A'), 6, 'right')} | {align_kr(detail.get('sector_per','N/A'), 7, 'right')}"
            sys.stdout.write(row + "\n")
    
    sys.stdout.flush()
    
    # --- AI 트렌드 분석 ---
    sys.stdout.write("\n" + "-" * tw + "\n")
    sys.stdout.write("\033[1;95m" + " [트렌드 분석 중... 잠시 기다려주세요]" + "\033[0m\n")
    sys.stdout.flush()
    
    report = strategy.ai_advisor.get_hot_stocks_report_advice(
        _cached_hot_raw[:10], _cached_themes, strategy.current_market_vibe
    )
    
    sys.stdout.write("\033[1;95m" + " [AI 트렌드 분석가의 인기 테마 진단]" + "\033[0m\n")
    if report:
        for line in report.split('\n'):
            if line.strip(): sys.stdout.write(f"  {line.strip()}\n")
    else:
        sys.stdout.write("  ⚠️ 리포트를 생성할 수 없습니다.\n")
    
    sys.stdout.write("\n" + "-" * tw + "\n")
    sys.stdout.write(align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)

def draw_manual_page(tw, th):
    """시스템 전략 및 사용법 매뉴얼 페이지 출력"""
    buf = io.StringIO()
    buf.write("\033[H\033[2J")
    header = " [KIS-VIBE-TRADER SYSTEM MANUAL] "
    buf.write("\033[46;37m" + align_kr(header, tw, 'center') + "\033[0m\n\n")

    # 1. 시간 페이즈 전략
    buf.write("\033[1;93m 1. 장중 시간 페이즈(Market Phase) 전략\033[0m\n")
    buf.write("  - \033[91m🔥 Phase 1 (09:00~10:00) [공격]\033[0m: 변동성 극대화 구간. 익절 상향(+2%), 손절 완화(-1%).\n")
    buf.write("  - \033[92m🧘 Phase 2 (10:00~14:30) [관리]\033[0m: 횡보 함정 구간. 익절/손절 강화(-1%)로 리스크 타이트하게 관리.\n")
    buf.write("  - \033[93m💰 Phase 3 (14:30~15:10) [확정]\033[0m: 당일 수익 확정. 수익권 종목 50% 분할 매도 및 잔량 본전 스탑.\n")
    buf.write("  - \033[96m🛒 Phase 4 (15:10~15:20) [준비]\033[0m: 익일 유망주 선취매. 시장 안심(Bull/Neutral) 시에만 신규 매수.\n\n")

    # 2. AI 동적 전략
    buf.write("\033[1;93m 2. AI 동적 리스크 관리 (Time-Stop)\033[0m\n")
    buf.write("  - \033[1m유효 시간(Lifetime)\033[0m: 전략 할당 시 AI가 종목의 모멘텀 수명을 예측하여 데드라인을 설정.\n")
    buf.write("  - \033[1m타임 스탑\033[0m: 데드라인(REM:EXP) 경과 시, 익절선을 현재 수익의 절반으로 낮춰 수익을 보존.\n")
    buf.write("  - \033[1m동적 보정\033[0m: 시장 Vibe(Bull/Bear)와 종목 변동성을 분석하여 TP/SL을 실시간으로 미세 조정.\n\n")

    # 3. 주요 단축키 및 팁
    buf.write("\033[1;93m 3. 핵심 운영 팁\033[0m\n")
    buf.write("  - \033[1m[3:자동]\033[0m: 번호 없이 'TP SL' 입력 시 보유 전 종목의 기본 익절/손절을 일괄 변경합니다.\n")
    buf.write("  - \033[1m[8:시황]\033[0m: AI가 제안하는 수치는 현재 Vibe가 반영된 최종 목표값이며 시스템이 역산 적용합니다.\n")
    buf.write("  - \033[1m[9:전략]\033[0m: 엔터만 입력 시 AI가 해당 종목에 가장 적합한 KIS 프리셋 전략을 자동 매칭합니다.\n")
    buf.write("  - \033[1m[Panic Alert]\033[0m: 미국 지수 급락 시 모든 신규 매수(신규/물타기/불타기)가 즉시 자동 차단됩니다.\n")

    buf.write("\n" + "-" * tw + "\n")
    buf.write(align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    
    sys.stdout.write(buf.getvalue())
    sys.stdout.flush()
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()

def draw_stock_analysis(strategy, code, tw, th):
    """특정 종목에 대한 AI 심층 분석 리포트를 실시간 단계별 출력"""
    # 1. 즉시 화면 초기화 및 초기 상태 표시
    sys.stdout.write("\033[H\033[2J")
    header = f" [AI STOCK ANALYSIS REPORT: {code}] "
    sys.stdout.write("\033[42;30m" + align_kr(header, tw, 'center') + "\033[0m\n\n")
    sys.stdout.write(f"\033[93m 🚀 {code} 종목 분석을 시작합니다. 잠시만 기다려주세요...\033[0m\n")
    sys.stdout.flush()
    
    # 2. 데이터 수집 (Naver)
    show_status(f"🔍 {code} 종목 상세 데이터를 수집 중입니다...")
    detail = strategy.api.get_naver_stock_detail(code)
    news = strategy.api.get_naver_stock_news(code)
    name = detail.get('name', '알 수 없는 종목')
    
    # 상단 요약 정보 즉시 출력
    color = "\033[91m" if detail.get('rate', 0) >= 0 else "\033[94m"
    sys.stdout.write(f"\n\033[1;93m [종목 정보] {name} ({code})\033[0m\n")
    sys.stdout.write(f"  * 실시간시세: {int(float(detail.get('price',0))):,}원 ({color}{detail.get('rate',0):+.2f}%\033[0m)\n")
    sys.stdout.write(f"  * 시가총액  : {detail.get('market_cap')}\n")
    sys.stdout.write(f"  * 펀더멘털  : PER {detail.get('per')} | PBR {detail.get('pbr')} | 배당 {detail.get('yield')} | 업종PER {detail.get('sector_per')}\n")
    
    sys.stdout.write("\n\033[1;96m [최신 소식 및 공시]\033[0m\n")
    if news:
        for n in news[:3]: sys.stdout.write(f"  - {n}\n")
    else:
        sys.stdout.write("  - 최근 소식 없음\n")
    sys.stdout.write("-" * tw + "\n\n")
    sys.stdout.flush()
    
    # 3. AI 분석 단계 (요청하신 메시지 2번 노출)
    show_status("🧠 AI가 분석을 위해 데이터를 확인 중입니다...")
    sys.stdout.write("\033[1;95m 🤖 AI가 확인 중입니다... (데이터 분석)\033[0m\n")
    sys.stdout.flush()
    time.sleep(0.5)
    
    sys.stdout.write("\033[1;95m 🤖 AI가 확인 중입니다... (리포트 생성)\033[0m\n")
    sys.stdout.flush()
    
    report = strategy.ai_advisor.get_stock_report_advice(code, name, detail, news)
    
    # 4. 최종 리포트 출력
    if report:
        sys.stdout.write("\033[1;92m [Gemini AI 심층 분석 의견]\033[0m\n")
        for line in report.split('\n'):
            if line.strip(): sys.stdout.write(f"  {line.strip()}\n")
    else:
        sys.stdout.write("  ⚠️ 리포트를 생성할 수 없습니다. API 키 또는 네트워크 상태를 확인하세요.\n")
            
    sys.stdout.write("\n" + "-" * tw + "\n")
    sys.stdout.write(align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.flush()
    
    # 키 대기
    while not get_key_immediate(): time.sleep(0.1)
    show_status("✅ 분석 완료")

def perform_interaction(key, api, strategy, cycle):
    global _ranking_filter, _status_msg, _last_log_msg, _cached_recommendations, _last_size
    flush_input()
    # 키 입력을 소문자로 통일하여 처리
    mode = (key[-1] if 'alt+' in key else key).lower()
    
    # 유효한 키 리스트에 'm' 포함
    if mode not in ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'a', 'b', 'd', 'h', 'm', 'q', 's']: return
    
    if mode == 'q':
        restore_terminal_settings()
        exit_alt_screen()
        print("\n[AI TRADING SYSTEM] 사용자에 의해 안전하게 종료되었습니다.")
        os._exit(0)

    if mode == 'm':
        restore_terminal_settings()
        draw_manual_page(os.get_terminal_size().columns, os.get_terminal_size().lines)
        enter_alt_screen()
        set_terminal_raw()
        flush_input()
        _last_size = (0, 0)
        return

    if mode == 'b':
        set_busy("보유 리포트 생성")
        try:
            restore_terminal_settings()
            draw_holdings_detail(strategy, os.get_terminal_size().columns, os.get_terminal_size().lines)
            enter_alt_screen()
            set_terminal_raw()
            flush_input()
            _last_size = (0, 0)
            time.sleep(0.2)
        finally: clear_busy()
        return

    if mode == 'd':
        set_busy("추천 리포트 생성")
        try:
            restore_terminal_settings()
            draw_recommendation_report(strategy, os.get_terminal_size().columns, os.get_terminal_size().lines)
            enter_alt_screen()
            set_terminal_raw()
            flush_input()
            _last_size = (0, 0)
            time.sleep(0.2)
        finally: clear_busy()
        return

    if mode == 'h':
        set_busy("인기 테마 분석")
        try:
            restore_terminal_settings()
            draw_hot_stocks_detail(strategy, os.get_terminal_size().columns, os.get_terminal_size().lines)
            enter_alt_screen()
            set_terminal_raw()
            flush_input()
            _last_size = (0, 0)
            time.sleep(0.2)
        finally: clear_busy()
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
        _last_size = (0, 0)
        show_status("✅ 환경 설정이 성공적으로 갱신되었습니다.")
        update_all_data(api, strategy, new_auth.is_virtual, force=True)
        return

    try:
        tw = os.get_terminal_size().columns
    except: tw = 110

    set_terminal_raw()
    try:
        m_label = '매도' if mode=='1' else '매수' if mode=='2' else '자동' if mode=='3' else '추천' if mode=='4' else '물타기' if mode=='5' else '불타기' if mode=='6' else 'AI분석' if mode=='7' else 'AI시황' if mode=='8' else '전략' if mode=='9' else '보유리포트' if mode=='b' else '추천리포트' if mode=='d' else '인기리포트' if mode=='h' else '메뉴얼' if mode=='m' else '셋업'
        
        # 즉시 실행형 키들은 프롬프트 모드 표시 최소화
        if mode not in ['a', 'd', '8']:
            draw_tui(strategy, cycle, prompt_mode=m_label)
        
        # 커서 위치 제어: 
        # 일반 모드는 8행(상단), AI 분석/시황 모드는 하단(th-5)에 프롬프트 배치
        try:
            th = os.get_terminal_size().lines
        except: th = 30
        
        if mode in ['a', '8']:
            prompt_row = max(8, th - 5)
            sys.stdout.write(f"\033[{prompt_row};1H\033[K")
        else:
            sys.stdout.write("\033[8;1H\033[K") 
        sys.stdout.flush()
        
        f_h = _cached_holdings if _ranking_filter == "ALL" else [h for h in _cached_holdings if get_market_name(h.get('pdno','')) == _ranking_filter]
        
        if mode == '1':
            res = input_with_esc("> 매도 [번호 수량 가격] 입력 (공백 구분, 가격 미입력시 시장가): ", tw)
            if res:
                inp = res.strip().split()
                if inp and inp[0].isdigit() and 0 < int(inp[0]) <= len(f_h):
                    h = f_h[int(inp[0])-1]
                    code = h['pdno']
                    name = h['prdt_name']
                    qty = int(float(inp[1])) if len(inp) > 1 and inp[1].replace('.','',1).isdigit() else int(float(h['hldg_qty']))
                    price = int(float(inp[2])) if len(inp) > 2 and inp[2].replace('.','',1).isdigit() else 0
                    
                    # 즉시 시도 로그 출력
                    price_display = f"{price:,}원" if price > 0 else "시장가"
                    add_trading_log(f"[{code}] {name} {price_display} {qty}주 매도시도")
                    
                    def run_sell():
                        set_busy("매도 처리")
                        try:
                            success, msg = api.order_market(code, qty, False, price)
                            if success: 
                                show_status(f"✅ 매도 성공: {name}")
                                add_trading_log(f"수동매도완료: {name} {qty}주 @ {price_display}")
                                draw_tui(strategy, cycle) # 결과 즉시 화면 반영
                                update_all_data(api, strategy, True, force=True)
                                draw_tui(strategy, cycle) # 잔고 갱신 후 다시 반영
                            else: 
                                show_status(f"❌ 매도 실패: {msg}", True)
                                draw_tui(strategy, cycle)
                        finally:
                            clear_busy()
                    
                    threading.Thread(target=run_sell, daemon=True).start()
                    
        elif mode == '2':
            res = input_with_esc("> 매수 [코드 수량 가격] 입력 (공백 구분, 가격 미입력시 시장가): ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 2:
                    code, qty = inp[0], int(inp[1])
                    price = int(inp[2]) if len(inp) > 2 and inp[2].isdigit() else 0
                    
                    # 매수 시 종목명 확인을 위해 캐시 또는 API 활용
                    name = "알수없음"
                    for h in _cached_holdings:
                        if h['pdno'] == code: name = h['prdt_name']; break
                    if name == "알수없음":
                        # 캐시에 없으면 네이버 상세 정보에서 가져옴 (동기적이지만 매수 시도 직전 1회만 수행)
                        detail = api.get_naver_stock_detail(code)
                        if detail: name = detail.get('name', code)

                    price_display = f"{price:,}원" if price > 0 else "시장가"
                    add_trading_log(f"[{code}] {name} {price_display} {qty}주 매입시도")

                    # 기존 보유 여부 확인 (신규 매수인지 추가 매수인지)
                    is_new_stock = not any(h['pdno'] == code for h in _cached_holdings)

                    def run_buy():
                        set_busy("매수 주문")
                        try:
                            success, msg = api.order_market(code, qty, True, price)
                            if success: 
                                show_status(f"✅ 매수 성공: {code}")
                                add_trading_log(f"수동매수완료: {name} {qty}주 @ {price_display}")
                                draw_tui(strategy, cycle)
                                
                                # 신규 종목 매수 시 전략 즉시 할당 (이 부분은 메인 스레드 입력이 필요하므로 예외적으로 동기 처리 고려 가능하나, 
                                # 여기서는 주문 완료 후 알림 정도로만 처리하고 필요시 사용자가 9번 메뉴를 쓰도록 유도하거나
                                # 혹은 주문 성공 후에만 프롬프트를 띄우는 현재 방식 유지)
                                # [주의] 백그라운드 스레드에서 input_with_esc를 호출하면 안 됨.
                                # 따라서 신규 종목 전략 할당은 '성공' 메시지 이후 사용자가 직접 9번을 누르도록 안내하거나
                                # 기존처럼 동기 방식으로 수행해야 함.
                                # 사용자 요청이 "프로그레스 바"이므로 주문 자체만 백그라운드로 돌리고 전략 할당은 나중에 개선.
                                
                                update_all_data(api, strategy, True, force=True)
                                draw_tui(strategy, cycle)
                            else: 
                                show_status(f"❌ 매수 실패: {msg}", True)
                                draw_tui(strategy, cycle)
                        finally:
                            clear_busy()

                    # [결정] 전략 할당 프롬프트 때문에 매수는 현재의 동기 방식을 유지하되, set_busy만 확실히 처리함.
                    # (백그라운드에서 입력을 받을 수 없기 때문)
                    set_busy("매수 처리")
                    try:
                        success, msg = api.order_market(code, qty, True, price)
                        if success:
                            show_status(f"✅ 매수 성공: {code}")
                            add_trading_log(f"수동매수완료: {name} {qty}주 @ {price_display}")
                            draw_tui(strategy, cycle)
                            if is_new_stock:
                                # (기존 전략 할당 로직 유지)
                                sys.stdout.write("\033[9;1H")
                                sys.stdout.write(f"\033[K  \033[96m[{code}] {name}\033[0m  00:표준 | 01:골든크로스 | 02:모멘텀 | 03:52주신고가 | 04:연속상승 | 05:이격도 | 06:돌파실패 | 07:강한종가 | 08:변동성확장 | 09:평균회귀 | 10:추세필터 | 엔터:AI\n")
                                sys.stdout.flush()
                                res_strat = input_with_esc("> 전략 번호 선택 (엔터=AI 자동추천, ESC=표준): ", tw)
                                if res_strat is not None:
                                    if res_strat.strip() == '':
                                        set_busy("AI 전략 분석")
                                        strategy.auto_assign_preset(code, name)
                                    else:
                                        sel_id = res_strat.strip().zfill(2)
                                        if sel_id in PRESET_STRATEGIES and sel_id != '00':
                                            set_busy("AI 수치 계산")
                                            detail_s = strategy.api.get_naver_stock_detail(code)
                                            news_s = strategy.api.get_naver_stock_news(code)
                                            result = strategy.ai_advisor.simulate_preset_strategy(code, name, strategy.current_market_vibe, detail_s, news_s)
                                            tp_use = result['tp'] if result else PRESET_STRATEGIES[sel_id]['default_tp']
                                            sl_use = result['sl'] if result else PRESET_STRATEGIES[sel_id]['default_sl']
                                            strategy.assign_preset(code, sel_id, tp_use, sl_use, result['reason'] if result else '')
                            update_all_data(api, strategy, True, force=True)
                        else:
                            show_status(f"❌ 매수 실패: {msg}", True)
                    finally:
                        clear_busy()
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
        elif mode == '7':
            res = input_with_esc("> 분석할 종목 코드(6자리) 입력: ", tw)
            if res and len(res.strip()) == 6:
                restore_terminal_settings()
                draw_stock_analysis(strategy, res.strip(), os.get_terminal_size().columns, os.get_terminal_size().lines)
                enter_alt_screen(); set_terminal_raw(); flush_input()
                _last_size = (0, 0)
        elif mode in ['a', '8']:
            if not os.getenv("GOOGLE_API_KEY"):
                show_status("⚠️ Gemini API Key가 없습니다. [S:셋업]에서 입력하세요.", True)
            else:
                last_draw_t = [0.0] # 클로저에서 수정 가능하도록 리스트 사용
                def progress_callback(curr, total, phase_msg="분석"):
                    show_status(f"[AI {phase_msg} 중... {curr}/{total}]")
                    # 진행 상황 표시도 0.2초 간격으로 제한하여 깜빡임 방지
                    if time.time() - last_draw_t[0] > 0.2:
                        draw_tui(strategy, cycle)
                        last_draw_t[0] = time.time()
                    
                def item_found_cb(item):
                    # 새로운 추천 종목이 발굴될 때마다 리스트에 추가하고 화면을 주기적으로 갱신
                    with _data_lock:
                        if not any(r['code'] == item['code'] for r in strategy.ai_recommendations):
                            strategy.ai_recommendations.append(item.copy())
                            strategy.ai_recommendations.sort(key=lambda x: x['score'], reverse=True)
                    
                    if time.time() - last_draw_t[0] > 0.3:
                        draw_tui(strategy, cycle)
                        last_draw_t[0] = time.time()

                show_status("🧠 Gemini AI가 시장 상황을 분석 중입니다. 잠시만 기다려주세요...")
                # 분석 시작 전 기존 추천 목록을 즉시 비워서 AI 검토 완료된 건만 보이게 함
                with _data_lock:
                    strategy.ai_recommendations = []
                draw_tui(strategy, cycle)
                set_busy("AI 시장 분석")
                try:
                    # Update recommendations first with progress and item_found callback
                    strategy.update_ai_recommendations(
                        _cached_themes, 
                        _cached_hot_raw, 
                        _cached_vol_raw, 
                        progress_cb=progress_callback,
                        on_item_found=item_found_cb
                    )
                    
                    advice = strategy.get_ai_advice(progress_cb=lambda c, t, p="심층분석": progress_callback(c, t, "종목 심층분석"))
                finally: clear_busy()
                if advice and "⚠️" not in advice:
                    show_status("✅ AI 분석 완료. 상단 브리핑을 확인하세요.")
                    draw_tui(strategy, cycle) # 브리핑 출력
                    
                    # 수치 파싱 시도 및 반영 여부 확인
                    if strategy.parse_and_apply_ai_strategy():
                        # 파싱 성공 시 확인 절차 (수동 확인용 메시지)
                        # [조정] 프롬프트 위치를 인기/거래 순위 밑으로 이동 (th - 10 내외)
                        try:
                            # 랭킹 데이터가 대략 25~30행쯤 끝나므로, 그 아래인 th-10 정도로 배치
                            prompt_row = max(15, os.get_terminal_size().lines - 10)
                            sys.stdout.write(f"\033[{prompt_row};1H\033[K")
                        except: pass
                        
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
            res = input_with_esc("> 수정 [번호 TP SL] 또는 [TP SL] 입력 (초기화는 '번호 r'): ", tw)
            if res:
                inp = res.strip().split()
                # 1. 특정 종목 설정 또는 초기화
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
                # 2. 번호 없이 입력 시 기본 전략(디폴트) 수정
                elif len(inp) == 2:
                    try:
                        tp, sl = float(inp[0]), float(inp[1])
                        strategy.exit_mgr.base_tp = tp
                        strategy.exit_mgr.base_sl = sl
                        strategy.save_manual_thresholds()
                        show_status(f"✅ 기본 전략 변경 완료: 익절 {tp}% / 손절 {sl}%")
                    except:
                        show_status("❌ 기본 전략 입력 오류", True)
                # 3. 전체 초기화 (r 하나만 입력 시)
                elif len(inp) == 1 and inp[0].lower() == 'r':
                    count = len(strategy.manual_thresholds)
                    strategy.manual_thresholds.clear()
                    strategy.save_manual_thresholds()
                    show_status(f"🔄 모든 종목 수동 전략 초기화 완료 ({count}건)")
        elif mode == '5':
            res = input_with_esc("> 물타기설정 [트리거% 금액(원) 한도(원) 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 4:
                    try:
                        trig, amt, lim = float(inp[0]), int(inp[1]), int(inp[2])
                        # [추가] 수동 입력 시 '만원' 입력 실수 방지 보정 (1000 미만 시 만원으로 간주)
                        if amt < 1000: amt *= 10000
                        if lim < 1000: lim *= 10000
                        auto = inp[3].lower() == 'y'
                        strategy.bear_config.update({"min_loss_to_buy": trig, "average_down_amount": amt, "max_investment_per_stock": lim, "auto_mode": auto})
                        strategy._save_all_states(); show_status(f"✅ 물타기 설정 저장 완료 (자동:{'ON' if auto else 'OFF'})")
                    except: show_status("❌ 입력 형식 오류", True)
        elif mode == '6':
            res = input_with_esc("> 불타기설정 [트리거% 금액(원) 한도(원) 자동(y/n)]: ", tw)
            if res:
                inp = res.strip().split()
                if len(inp) >= 4:
                    try:
                        trig, amt, lim = float(inp[0]), int(inp[1]), int(inp[2])
                        if amt < 1000: amt *= 10000
                        if lim < 1000: lim *= 10000
                        auto = inp[3].lower() == 'y'
                        strategy.bull_config.update({"min_profit_to_pyramid": trig, "average_down_amount": amt, "max_investment_per_stock": lim, "auto_mode": auto})
                        strategy._save_all_states(); show_status(f"✅ 불타기 설정 저장 완료 (자동:{'ON' if auto else 'OFF'})")
                    except: show_status("❌ 입력 형식 오류", True)
        elif mode == '9':
            # === 프리셋 전략 할당 메뉴 ===
            # 1단계: 종목 선택 (커서는 이미 8행에 위치)
            res_code = input_with_esc("> 전략 적용할 보유 종목 번호 입력: ", tw)
            if res_code and res_code.strip().isdigit():
                idx_num = int(res_code.strip())
                if 0 < idx_num <= len(f_h):
                    h = f_h[idx_num - 1]
                    code = h['pdno']
                    name = h['prdt_name']
                    current_preset = strategy.get_preset_label(code)
                    
                    # 2단계: 프리셋 목록 출력 (COMMAND 바로 아래 영역에 출력)
                    sys.stdout.write("\033[9;1H")  # 9행부터 출력
                    sys.stdout.write(f"\033[K  \033[96m[{code}] {name}\033[0m (현재: {current_preset if current_preset else '표준'})  00:표준 | 01:골든크로스 | 02:모멘텀 | 03:52주신고가 | 04:연속상승 | 05:이격도 | 06:돌파실패 | 07:강한종가 | 08:변동성확장 | 09:평균회귀 | 10:추세필터 | 엔터:AI\n")
                    sys.stdout.flush()
                    
                    res_strat = input_with_esc("> 전략 번호 선택 (엔터=AI 자동추천): ", tw)
                    
                    if res_strat is None:
                        # ESC 취소
                        pass
                    elif res_strat.strip() == '':
                        # 엔터 입력 → AI 자동 추천
                        show_status("🧠 AI가 최적 전략을 시뮬레이션 중입니다...")
                        draw_tui(strategy, cycle)
                        result = strategy.auto_assign_preset(code, name)
                        if result:
                            show_status(f"✅ [{name}] AI 추천 전략: [{result['preset_name']}] TP:{result['tp']:+.1f}% SL:{result['sl']:.1f}% ({result['reason']})")
                        else:
                            show_status(f"❌ AI 전략 추천 실패. 수동으로 선택해주세요.", True)
                    else:
                        # 수동 선택
                        sel_id = res_strat.strip().zfill(2)  # '1' → '01'
                        if sel_id in PRESET_STRATEGIES:
                            if sel_id == '00':
                                strategy.assign_preset(code, '00')
                                show_status(f"🔄 [{name}] 표준 전략으로 복귀 (기본 TP/SL 적용)")
                            else:
                                # 수동 선택도 AI가 동적 TP/SL을 계산해서 부여
                                show_status(f"🧠 [{PRESET_STRATEGIES[sel_id]['name']}] 전략 기반 동적 TP/SL 계산 중...")
                                draw_tui(strategy, cycle)
                                detail = strategy.api.get_naver_stock_detail(code)
                                news = strategy.api.get_naver_stock_news(code)
                                vibe = strategy.current_market_vibe
                                # AI에게 선택된 프리셋 기반으로 동적 수치 요청
                                result = strategy.ai_advisor.simulate_preset_strategy(code, name, vibe, detail, news)
                                if result and result['preset_id'] != sel_id:
                                    # AI가 다른 전략을 추천해도 사용자가 선택한 전략을 존중
                                    # 단, AI가 계산한 TP/SL은 활용
                                    tp_use = result['tp']
                                    sl_use = result['sl']
                                else:
                                    tp_use = result['tp'] if result else PRESET_STRATEGIES[sel_id]['default_tp']
                                    sl_use = result['sl'] if result else PRESET_STRATEGIES[sel_id]['default_sl']
                                
                                strategy.assign_preset(code, sel_id, tp_use, sl_use, 
                                                       result['reason'] if result else PRESET_STRATEGIES[sel_id]['desc'])
                                show_status(f"✅ [{name}] [{PRESET_STRATEGIES[sel_id]['name']}] 전략 적용 (TP:{tp_use:+.1f}% SL:{sl_use:.1f}%)")
                        else:
                            show_status("⚠️ 유효하지 않은 전략 번호입니다.", True)
                else:
                    show_status("⚠️ 유효하지 않은 종목 번호입니다.", True)
    except Exception as e:
        from src.logger import log_error
        log_error(f"Interaction Error: {e}"); show_status(f"오류: {e}", True)
    finally:
        # 종료/취소 시 입력하던 7~8행 영역만 정밀하게 지우기
        sys.stdout.write("\033[7;1H\033[K\033[8;1H\033[K")
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
