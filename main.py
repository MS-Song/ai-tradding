import os
import time
import yaml
import sys
import unicodedata
from datetime import datetime, time as dtime, timedelta
from dotenv import load_dotenv

from src.logger import logger
from src.auth import KISAuth
from src.api import KISAPI
from src.strategy import VibeStrategy

# --- OS 호환성 래퍼 ---
def get_line_sep():
    return os.linesep

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def fix_windows_ansi():
    if sys.platform == "win32":
        os.system('')

fix_windows_ansi()

def load_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"❌ 설정 파일 로드 실패: {e}")
        return {}

def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5: return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)

def is_us_market_open():
    now = datetime.now()
    if now.weekday() >= 5: return False
    current_time = now.time()
    return dtime(22, 30) <= current_time or current_time <= dtime(5, 0)

def get_visual_width(text):
    """문자열의 실제 시각적 너비 계산 (한글/특수문자 2칸, 영문/숫자 1칸)"""
    w = 0
    for c in str(text):
        if unicodedata.east_asian_width(c) in ['W', 'F', 'A']:
            w += 2
        else:
            w += 1
    return w

def align_kr(text, width, align='right'):
    """시각적 너비 기준 정렬"""
    text = str(text)
    visual_w = get_visual_width(text)
    pad_size = max(0, width - visual_w)
    if align == 'right': return ' ' * pad_size + text
    elif align == 'left': return text + ' ' * pad_size
    else:
        left = pad_size // 2
        right = pad_size - left
        return ' ' * left + text + ' ' * right

def get_market_name(stock_code):
    proxies = {"069500": "KOSPI", "150460": "KOSDAQ", "133690": "NASDAQ", "360750": "S&P500"}
    if stock_code in proxies: return proxies[stock_code]
    if len(stock_code) == 6 and stock_code.isdigit():
        if stock_code[:2] in ['00', '01', '02', '03']: return "KOSPI"
        return "KOSDAQ"
    return "해외"

def show_surging_stocks(api):
    try:
        gainers = api.get_top_gainers()
        sep = get_line_sep()
        print(f"{sep} ✨ [실시간 급등주 탐색] " + "─"*70)
        if not gainers:
            print("  ℹ️ 현재 시장의 실시간 순위 데이터를 가져올 수 없습니다.")
        else:
            for i, g in enumerate(gainers, 1):
                name = g.get("hts_kor_isnm", "Unknown")
                rate = g.get("data_rank_sort_val", "0.0")
                reason = api.get_stock_news(g.get("stck_shrn_iscd", ""))
                print(f"  {i}. {align_kr(name, 14, 'left')} | \033[91m{rate:>6}%\033[0m | 사유: {reason[:50]}...")
        print("─"*95 + sep)
        sys.stdout.flush()
    except Exception: pass

def show_portfolio_dashboard(api, strategy):
    """현재 자산, 보유 종목 및 전략 지표를 화면에 출력 (최종 완성본)"""
    try:
        asset_info = api.get_deposit()
        holdings = api.get_balance()
        indices = strategy.current_market_data
        sep = get_line_sep()
        
        # 1. 데이터 가공 및 너비 계산
        processed_data = []
        widths = {
            'market': get_visual_width("시장"), 'name': get_visual_width("종목명"),
            'price': get_visual_width("현재가"), 'qty': get_visual_width("보유량"),
            'eval': get_visual_width("평가액"), 'rt': get_visual_width("수익률"),
            'pnl': get_visual_width("수익금"), 'goal': get_visual_width("목표TP")
        }

        for h in holdings:
            code = h.get("pdno", "")
            name = h.get("prdt_name", "Unknown")[:18]
            mkt = get_market_name(code)
            tp_rate, sl_rate, is_spike = strategy.get_dynamic_thresholds(code, strategy.current_market_vibe.lower())
            
            row = {
                'mkt': mkt, 'name': name,
                'avg': f"{int(float(h.get('pchs_avg_pric', 0))):,}",
                'curr': f"{int(float(h.get('prpr', 0))):,}",
                'qty': f"{int(float(h.get('hldg_qty', 0))):,}",
                'eval': f"{int(float(h.get('evlu_amt', 0))):,}",
                'pnl': f"{int(float(h.get('evlu_pfls_amt', 0))):,}",
                'rt': f"{h.get('evlu_pfls_rt', '0.0')}%",
                'tp': f"{tp_rate:+}%", 'sl': f"{sl_rate:+}%",
                'is_plus': float(h.get('evlu_pfls_rt', '0.0')) >= 0,
                'spike': "🔥" if is_spike else ""
            }
            processed_data.append(row)
            for k in ['market', 'name', 'price', 'qty', 'eval', 'rt', 'pnl', 'goal']:
                if k == 'name': val = get_visual_width(row['name'] + row['spike'])
                elif k == 'price': val = max(get_visual_width(row['avg']), get_visual_width(row['curr']))
                elif k == 'goal': val = max(get_visual_width(row['tp']), get_visual_width(row['sl']))
                else: val = get_visual_width(row.get(k, ''))
                widths[k] = max(widths[k], val)

        # 2. 상단 정보 섹션 출력 (복구됨)
        # 헤더 조립 후 너비 측정
        header_row = f"    {align_kr('시장', widths['market'], 'left')} | {align_kr('종목명', widths['name'], 'left')} | {align_kr('평단가', widths['price'], 'right')} | {align_kr('현재가', widths['price'], 'right')} | {align_kr('보유량', widths['qty'], 'right')} | {align_kr('평가액', widths['eval'], 'right')} |    {align_kr('수익률', widths['rt'], 'right')} | {align_kr('수익금', widths['pnl'], 'right')} | {align_kr('목표TP', widths['goal'], 'right')} | {align_kr('손절SL', widths['goal'], 'right')}"
        total_width = get_visual_width(header_row) + 2
        
        print(sep + "━"*total_width)
        
        # [복구] 실시간 시장 지수
        idx_msg = " 📊 [실시간 시장 지수] "
        for name, data in indices.items():
            if data:
                trend = "\033[91m▲\033[0m" if data['rate'] >= 0 else "\033[94m▼\033[0m"
                idx_msg += f"{name}: {data['price']:,.2f} ({trend}{data['rate']:+0.2f}%)  "
        print(idx_msg)
        
        # [복구] 장 상태 및 Vibe
        kr_status = "☀️ 운영 중" if is_market_open() else "🌙 휴장"
        us_status = "☀️ 운영 중" if is_us_market_open() else "🌙 휴장"
        v_color = "\033[91m" if "Bull" in strategy.current_market_vibe else ("\033[94m" if "Bear" in strategy.current_market_vibe else "\033[93m")
        panic = " 🚨 \033[91m[GLOBAL PANIC DETECTED]\033[0m" if strategy.global_panic else ""
        print(f" 🕒 [장 상태] 한국: {kr_status} | 미국: {us_status} | 🎯 [Vibe]: {v_color}{strategy.current_market_vibe.upper()}\033[0m{panic}")
        
        # [복구] 자산 현황
        print(f"{sep} 💰 [자산 현황]")
        print(f"   - 총 평가 자산: {asset_info['total_asset']:,}원 | 예수금 잔량: {asset_info['deposit']:,}원")
        print(f"   - 주문 가능액: \033[92m{asset_info['cash']:,}원\033[0m | 주식 평가액: {asset_info['stock_eval']:,}원")
        pnl_val = asset_info['pnl']
        pnl_lbl = "\033[91m▲ 이익\033[0m" if pnl_val >= 0 else "\033[94m▼ 손실\033[0m"
        print(f"   - 총 평가 손익: {pnl_lbl} {pnl_val:,}원 | 시각: {datetime.now().strftime('%H:%M:%S')}")
        
        # 3. 보유 종목 분석 섹션
        print(f"{sep} 📋 [보유 종목 분석 및 매매 전략]")
        if processed_data:
            print("━"*total_width)
            print(header_row)
            print("─"*total_width)
            
            for row in processed_data:
                icon = "\033[91m▲\033[0m" if row['is_plus'] else "\033[94m▼\033[0m"
                color = "\033[91m" if row['is_plus'] else "\033[94m"
                print(f"    {align_kr(row['mkt'], widths['market'], 'left')} | {align_kr(row['name'] + row['spike'], widths['name'], 'left')} | "
                      f"{align_kr(row['avg'], widths['price'], 'right')} | {align_kr(row['curr'], widths['price'], 'right')} | "
                      f"{align_kr(row['qty'], widths['qty'], 'right')} | {align_kr(row['eval'], widths['eval'], 'right')} | "
                      f"{icon} {align_kr(row['rt'], widths['rt'], 'right')} | {color}{align_kr(row['pnl'], widths['pnl'], 'right')}\033[0m | "
                      f"{color}{align_kr(row['tp'], widths['goal'], 'right')}\033[0m | {color}{align_kr(row['sl'], widths['goal'], 'right')}\033[0m")
        else:
            print("━"*total_width)
            print("    현재 보유 중인 종목이 없습니다.")
        
        print("━"*total_width + sep)
        sys.stdout.flush()
    except Exception as e:
        logger.error(f"대시보드 출력 에러: {e}")

def main():
    load_dotenv()
    config = load_config()
    interval = config.get("vibe_strategy", {}).get("check_interval", 60)
    if interval < 60: interval = 60
    auth = KISAuth(is_virtual=True)
    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            if not auth.is_token_valid(): auth.generate_token()
            api = KISAPI(auth)
            strategy = VibeStrategy(api, config)
            market_trend = strategy.determine_market_trend()
            show_portfolio_dashboard(api, strategy)
            strategy.run_cycle(market_trend=market_trend)
            show_surging_stocks(api)
            logger.info(f"✅ [Cycle #{cycle_count}] 완료. 다음 감시까지 {interval}초 대기합니다.")
            for i in range(interval, 0, -1):
                if i % 10 == 0: print(f"\r⏳ {i}초 후 갱신...", end="", flush=True)
                time.sleep(1)
            print("\r" + " "*30 + "\r", end="")
        except KeyboardInterrupt:
            print("\n👋 프로그램을 종료합니다.")
            break
        except Exception as e:
            logger.error(f"💥 시스템 에러: {e}")
            auth.access_token = None 
            time.sleep(10) 
            continue

if __name__ == "__main__":
    main()
