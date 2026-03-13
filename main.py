import os
import time
import yaml
import sys
from datetime import datetime, time as dtime, timedelta
from dotenv import load_dotenv

from src.logger import logger
from src.auth import KISAuth
from src.api import KISAPI
from src.strategy import VibeStrategy

def load_config():
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"❌ 설정 파일 로드 실패: {e}")
        return {}

def is_market_open():
    """한국 주식 시장 운영 시간(09:00 ~ 15:30) 여부 확인 (월~금)"""
    now = datetime.now()
    if now.weekday() >= 5: return False
    start_time = dtime(9, 0)
    end_time = dtime(15, 30)
    return start_time <= now.time() <= end_time

def is_us_market_open():
    """미국 주식 시장 운영 시간(22:30 ~ 05:00) 여부 확인"""
    now = datetime.now()
    if now.weekday() >= 5: return False
    current_time = now.time()
    start_time = dtime(22, 30)
    end_time = dtime(5, 0)
    if start_time <= current_time or current_time <= end_time: return True
    return False

def align_kr(text, width, align='right'):
    """한글 너비를 고려하여 문자열 정렬 (시각적 너비 기준)"""
    text = str(text)
    # 한글(유니코드) 개수 확인
    kor_count = len([c for c in text if ord('가') <= ord(c) <= ord('힣')])
    # 시각적 너비 = 글자 수 + 한글 개수
    visual_width = len(text) + kor_count
    pad_size = max(0, width - visual_width)
    
    if align == 'right':
        return ' ' * pad_size + text
    elif align == 'left':
        return text + ' ' * pad_size
    else: # center
        left = pad_size // 2
        right = pad_size - left
        return ' ' * left + text + ' ' * right

def get_market_name(stock_code):
    """종목코드를 기반으로 시장 소속 정밀 판별"""
    proxies = {"069500": "KOSPI", "150460": "KOSDAQ", "133690": "NASDAQ", "360750": "S&P500"}
    if stock_code in proxies: return proxies[stock_code]
    if len(stock_code) == 6 and stock_code.isdigit():
        kospi_starts = ['00', '01', '02', '03']
        if stock_code[:2] in kospi_starts: return "KOSPI"
        return "KOSDAQ"
    return "해외"

def show_surging_stocks(api):
    """급등주 5개와 급등 사유(뉴스) 출력"""
    try:
        gainers = api.get_top_gainers()
        print("\n" + " ✨ [실시간 급등주 탐색] " + "─"*70)
        if not gainers:
            print("  ℹ️ 현재 시장의 실시간 순위 데이터를 가져올 수 없습니다.")
        else:
            for i, g in enumerate(gainers, 1):
                name = g.get("hts_kor_isnm", "Unknown")
                code = g.get("stck_shrn_iscd", "")
                rate = g.get("data_rank_sort_val", "0.0")
                reason = api.get_stock_news(code)
                f_name = align_kr(name, 14, 'left')
                print(f"  {i}. {f_name} | \033[91m{rate:>6}%\033[0m | 사유: {reason[:50]}...")
        print("─"*95 + "\n")
        sys.stdout.flush()
    except Exception:
        pass

def show_portfolio_dashboard(api, strategy):
    """현재 자산, 보유 종목 및 전략 지표를 화면에 출력 (정렬 최적화)"""
    try:
        asset_info = api.get_deposit()
        holdings = api.get_balance()
        
        indices = strategy.current_market_data
        
        total_width = 165 
        print("\n" + "━"*total_width)
        
        # 1. 시장 지수 헤더
        idx_msg = " 📊 [실시간 시장 지수] "
        for name, data in indices.items():
            if data:
                trend = "\033[91m▲\033[0m" if data['rate'] >= 0 else "\033[94m▼\033[0m"
                idx_msg += f"{name}: {data['price']:,.2f} ({trend}{data['rate']:+0.2f}%)  "
        print(idx_msg)
        
        # 2. 장 상태 및 전략 지표
        kr_status = "☀️ 운영 중" if is_market_open() else "🌙 휴장"
        us_status = "☀️ 운영 중" if is_us_market_open() else "🌙 휴장"
        vibe_color = "\033[91m" if "Bull" in strategy.current_market_vibe else ("\033[94m" if "Bear" in strategy.current_market_vibe else "\033[93m")
        vibe_msg = f"{vibe_color}{strategy.current_market_vibe.upper()}\033[0m"
        panic_msg = " 🚨 \033[91m[GLOBAL PANIC DETECTED]\033[0m" if strategy.global_panic else ""
        print(f" 🕒 [장 상태] 한국: {kr_status} | 미국: {us_status} | 🎯 [Vibe]: {vibe_msg}{panic_msg}")
        
        # 3. 자산 현황
        print(f"\n 💰 [자산 현황]")
        print(f"   - 총 평가 자산: {asset_info['total_asset']:,}원 | 예수금: {asset_info['deposit']:,}원")
        print(f"   - 주문 가능액: \033[92m{asset_info['cash']:,}원\033[0m | 주식 평가액: {asset_info['stock_eval']:,}원")
        
        pnl = asset_info['pnl']
        pnl_label = "\033[91m▲ 이익\033[0m" if pnl >= 0 else "\033[94m▼ 손실\033[0m"
        print(f"   - 총 평가 손익: {pnl_label} {pnl:,}원 | 시각: {datetime.now().strftime('%H:%M:%S')}")
        
        print(f"\n 📋 [보유 종목 분석 및 매매 전략]")
        if holdings:
            # 컬럼 너비 설정 (종목명 20, 수익금 14 추가)
            col_widths = {'market': 10, 'name': 20, 'price': 12, 'qty': 8, 'eval': 14, 'rt': 10, 'pnl': 14, 'goal': 10}
            
            h_mkt  = align_kr("시장", col_widths['market'], 'left')
            h_name = align_kr("종목명", col_widths['name'], 'left')
            h_avg  = align_kr("평단가", col_widths['price'], 'right')
            h_curr = align_kr("현재가", col_widths['price'], 'right')
            h_qty  = align_kr("보유량", col_widths['qty'], 'right')
            h_eval = align_kr("평가액", col_widths['eval'], 'right')
            h_rt   = align_kr("수익률", col_widths['rt'], 'right')
            h_pnl_amt = align_kr("수익금", col_widths['pnl'], 'right')
            h_tp   = align_kr("목표TP", col_widths['goal'], 'right')
            h_sl   = align_kr("손절SL", col_widths['goal'], 'right')
            
            # 헤더 출력 (수익률 앞 4칸 여백으로 아이콘과 줄맞춤)
            print(f"    {h_mkt} | {h_name} | {h_avg} | {h_curr} | {h_qty} | {h_eval} |    {h_rt} | {h_pnl_amt} | {h_tp} | {h_sl}")
            print("─"*total_width)
            
            for h in holdings:
                code = h.get("pdno", "")
                name = h.get("prdt_name", "Unknown")[:18]
                mkt_name = get_market_name(code)
                tp_rate, sl_rate, is_spike = strategy.get_dynamic_thresholds(code, strategy.current_market_vibe.lower())
                
                avg_price = f"{int(float(h.get('pchs_avg_pric', 0))):,}"
                curr_price = f"{int(float(h.get('prpr', 0))):,}"
                qty = f"{int(float(h.get('hldg_qty', 0))):,}"
                eval_amt = f"{int(float(h.get('evlu_amt', 0))):,}"
                pnl_amt = f"{int(float(h.get('evlu_pfls_amt', 0))):,}"
                rt = f"{h.get('evlu_pfls_rt', '0.0')}%"
                
                is_plus = float(h.get('evlu_pfls_rt', '0.0')) >= 0
                status_icon = "\033[91m▲\033[0m" if is_plus else "\033[94m▼\033[0m"
                color = "\033[91m" if is_plus else "\033[94m"
                spike_mark = "🔥" if is_spike else "  "
                
                f_mkt  = align_kr(mkt_name, col_widths['market'], 'left')
                f_name = align_kr(name, col_widths['name'], 'left')
                f_avg  = align_kr(avg_price, col_widths['price'], 'right')
                f_curr = align_kr(curr_price, col_widths['price'], 'right')
                f_qty  = align_kr(qty, col_widths['qty'], 'right')
                f_eval = align_kr(eval_amt, col_widths['eval'], 'right')
                f_rt   = align_kr(rt, col_widths['rt'], 'right')
                f_pnl  = align_kr(pnl_amt, col_widths['pnl'], 'right')
                f_tp   = align_kr(f"{tp_rate:+}%", col_widths['goal'], 'right')
                f_sl   = align_kr(f"{sl_rate:+}%", col_widths['goal'], 'right')
                
                print(f"    {f_mkt} | {f_name}{spike_mark} | {f_avg} | {f_curr} | {f_qty} | {f_eval} | {status_icon} {f_rt} | {color}{f_pnl}\033[0m | {color}{f_tp}\033[0m | {color}{f_sl}\033[0m")
        else:
            print("    현재 보유 중인 종목이 없습니다.")
        print("━"*total_width + "\n")
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
            
            # [단계 1] 시장 트렌드 및 데이터 분석
            market_trend = strategy.determine_market_trend()
            
            # [단계 2] 요약 대시보드 출력
            show_portfolio_dashboard(api, strategy)
            
            # [단계 3] 실제 전략 실행 (매매 수행)
            strategy.run_cycle(market_trend=market_trend)
            
            # [단계 4] 급등주 및 카운트다운
            show_surging_stocks(api)
            
            logger.info(f"✅ [Cycle #{cycle_count}] 완료. 다음 감시까지 {interval}초 대기합니다.")
            sys.stdout.flush()
            
            for i in range(interval, 0, -1):
                if i % 10 == 0:
                    print(f"\r⏳ {i}초 후 갱신...", end="", flush=True)
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
