import os
import sys
import time
import threading
import io
import re
from src.utils import *
from src.theme_engine import get_cached_themes, get_theme_for_stock
from src.strategy import PRESET_STRATEGIES
from src.ui.renderer import truncate_log_line
from src.logger import trading_log

def draw_performance_report(strategy, dm):
    """시스템의 투자 성과를 다각도로 분석하여 보여주는 TUI 대시보드를 렌더링합니다.

    이 뷰는 종목별/모델별 누적 손익, 금일 매매 성과 복기, 그리고 장 마감 후 생성되는 
    투자 적중 분석 리포트를 통합하여 사용자가 투자 전략의 유효성을 검증하도록 돕습니다.

    Args:
        strategy: 트레이딩 전략 객체 (복기 엔진 및 AI 성과 트래킹 포함).
        dm: 데이터 매니저 객체 (실시간 지수 및 자산 데이터 참조용).

    Tabs:
        1. 수익 상위: 누적 수익금이 가장 높은 상위 10개 종목과 기여 모델(LLM/TP/SL) 상세.
        2. 손실 상위: 누적 손실이 가장 큰 상위 10개 종목 분석 (리스크 관리 대상).
        3. 금일 투자 성과: 오늘 집행된 매수/매도 내역을 좌우 테이블로 비교하며, 
           진입/청산 타이밍의 적절성을 'Alpha' 지표와 함께 진단합니다.
        4. 투자 적중: `RetrospectiveEngine`이 생성한 일자별 복기 리포트와 
           장기 승률/순이익 등 누적 통계를 보여줍니다.

    Logic:
        - `smart_align`: 종목명과 데이터를 터미널 너비에 맞춰 유동적으로 축약/정렬합니다.
        - `타이밍 진단`: 매도 후 가격 변동을 추적하여 '완벽/일찍/방어/손절' 등 4단계 피드백을 제공합니다.
        - `Alpha 분석`: 시장 수익률(KOSPI) 대비 내 수익률의 초과 달성 여부를 실시간 계산합니다.

    Controls:
        - [1~4]: 각 성과 분석 탭으로 전환.
        - [Q, ESC, SPACE]: 화면을 닫고 메인 대시보드로 복귀.
    """
    import io
    import os
    from src.logger import trading_log
    
    current_tab = 1
    while True:
        try:
            size = os.get_terminal_size()
            tw, th = size.columns, size.lines
        except:
            tw, th = 80, 24
        buf = io.StringIO()

        is_v = getattr(strategy.api.auth, 'is_virtual', True)
        header_bg = "45" if is_v else "44"
        buf.write(f"\033[{header_bg};37m" + align_kr(" [AI TRADING PERFORMANCE DASHBOARD] ", tw, 'center') + "\033[0m\n")
        
        # 탭 메뉴 바
        t1 = "\033[7m" if current_tab == 1 else ""
        t2 = "\033[7m" if current_tab == 2 else ""
        t3 = "\033[7m" if current_tab == 3 else ""
        t4 = "\033[7m" if current_tab == 4 else ""
        
        menu = f" {t1} 1.수익 상위(Top 10) \033[0m | {t2} 2.손실 상위(Shame 10) \033[0m | {t3} 3.금일 투자 성과 \033[0m | {t4} 4.투자 적중 \033[0m "
        buf.write(align_kr(menu, tw, 'center') + "\n")
        buf.write("=" * tw + "\n\n")

        if current_tab == 1:
            # 1. 수익금 TOP 10
            top_stocks = trading_log.get_top_profitable_stocks(10)
            buf.write("\033[1;93m" + " [종목별 누적 수익금 TOP 10 (Hall of Fame)]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            if not top_stocks:
                buf.write("  누적 수익 데이터를 수집 중입니다.\n")
            else:
                buf.write("\033[1m" + f" {align_kr('순위', 4)} | {align_kr('코드', 8)} | {align_kr('종목명', 12)} | {align_kr('TOTAL (회수)', 18)} | {align_kr('모델별 (회수)', 25)}" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 14)
                item_count = 0
                for i, (code, s) in enumerate(top_stocks, 1):
                    if item_count >= max_items: break
                    color = "\033[91m"
                    total_val = f"{int(s['total_profit']):+,} ({s['count']}회)"
                    buf.write(f" {align_kr(str(i), 4)} | {align_kr(code, 8)} | {align_kr(s['name'][:12], 12)} | {color}{align_kr(total_val, 18, 'right')}\033[0m | ")
                    m_items = list(s['models'].items())
                    if m_items:
                        first_m, first_s = m_items[0]
                        m_val = f"{first_m} {int(first_s['profit']):+,} ({first_s['count']}회)"
                        m_color = "\033[91m" if first_s['profit'] > 0 else "\033[94m" if first_s['profit'] < 0 else "\033[90m"
                        buf.write(f"{m_color}{align_kr(m_val, 25, 'left')}\033[0m\n")
                        item_count += 1
                        for m_name, m_stat in m_items[1:]:
                            if item_count >= max_items: break
                            m_val = f"{m_name} {int(m_stat['profit']):+,} ({m_stat['count']}회)"
                            m_color = "\033[91m" if m_stat['profit'] > 0 else "\033[94m" if m_stat['profit'] < 0 else "\033[90m"
                            buf.write(f" {' '*4} | {' '*8} | {' '*12} | {' '*18} | {m_color}{align_kr(m_val, 25, 'left')}\033[0m\n")
                            item_count += 1
                    else: buf.write("\n")
                    buf.write("-" * tw + "\n"); item_count += 1

        elif current_tab == 2:
            # 2. 손실금 TOP 10
            loss_stocks = trading_log.get_top_loss_stocks(10)
            buf.write("\033[1;91m" + " [종목별 누적 손실금 TOP 10 (Hall of Shame)]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            if not loss_stocks:
                buf.write("  누적 손실 데이터가 없습니다 (클린 포트폴리오!).\n")
            else:
                buf.write("\033[1m" + f" {align_kr('순위', 4)} | {align_kr('코드', 8)} | {align_kr('종목명', 12)} | {align_kr('TOTAL (회수)', 18)} | {align_kr('모델별 (회수)', 25)}" + "\033[0m\n")
                buf.write("-" * tw + "\n")
                max_items = max(3, th - 14)
                item_count = 0
                for i, (code, s) in enumerate(loss_stocks, 1):
                    if item_count >= max_items: break
                    color = "\033[94m"
                    total_val = f"{int(s['total_profit']):+,} ({s['count']}회)"
                    buf.write(f" {align_kr(str(i), 4)} | {align_kr(code, 8)} | {align_kr(s['name'][:12], 12)} | {color}{align_kr(total_val, 18, 'right')}\033[0m | ")
                    m_items = list(s['models'].items())
                    if m_items:
                        first_m, first_s = m_items[0]
                        m_val = f"{first_m} {int(first_s['profit']):+,} ({first_s['count']}회)"
                        m_color = "\033[91m" if first_s['profit'] > 0 else "\033[94m" if first_s['profit'] < 0 else "\033[90m"
                        buf.write(f"{m_color}{align_kr(m_val, 25, 'left')}\033[0m\n")
                        item_count += 1
                        for m_name, m_stat in m_items[1:]:
                            if item_count >= max_items: break
                            m_val = f"{m_name} {int(m_stat['profit']):+,} ({m_stat['count']}회)"
                            m_color = "\033[91m" if m_stat['profit'] > 0 else "\033[94m" if m_stat['profit'] < 0 else "\033[90m"
                            buf.write(f" {' '*4} | {' '*8} | {' '*12} | {' '*18} | {m_color}{align_kr(m_val, 25, 'left')}\033[0m\n")
                            item_count += 1
                    else: buf.write("\n")
                    buf.write("-" * tw + "\n"); item_count += 1

        elif current_tab == 3:
            # 3. 금일 투자 성과 (개편된 좌우 테이블 레이아웃)
            from datetime import datetime as dt_cls
            today = get_now().strftime('%Y-%m-%d')

            
            # --- 데이터 수집 ---
            buy_trades = []; sell_trades = []; sell_types = ["익절", "손절", "청산", "확정", "매도", "종료"]
            with trading_log.lock:
                for t in trading_log.data.get("trades", []):
                    if not t["time"].startswith(today): continue
                    t_type = t.get("type", "")
                    if "매수" in t_type: buy_trades.append(t)
                    elif any(x in t_type for x in sell_types): sell_trades.append(t)
            
            def get_current_price(code):
                for h in dm.cached_holdings:
                    if h.get("pdno") == code: return int(float(h.get("prpr", 0)))
                try:
                    detail = strategy.api.get_naver_stock_detail(code)
                    return int(float(detail.get("price", 0)))
                except: return 0

            kospi_rate = dm.cached_market_data.get("KOSPI", {}).get("rate", 0)
            kosdaq_rate = dm.cached_market_data.get("KOSDAQ", {}).get("rate", 0)
            realized_profit = trading_log.get_daily_profit()
            asset = dm.cached_asset
            daily_pnl_rate = asset.get('daily_pnl_rate', 0.0); daily_pnl_amt = asset.get('daily_pnl_amt', 0.0)

            # ① 브리핑 헤더
            r_color = "\033[91m" if realized_profit > 0 else "\033[94m" if realized_profit < 0 else "\033[93m"
            d_color = "\033[91m" if daily_pnl_rate > 0 else "\033[94m" if daily_pnl_rate < 0 else "\033[93m"
            k_color = "\033[91m" if kospi_rate >= 0 else "\033[94m"
            kd_color = "\033[91m" if kosdaq_rate >= 0 else "\033[94m"
            buf.write("\033[1;96m" + " [금일 투자 성과 브리핑]" + "\033[0m\n")
            buf.write(f" 📋 {today} | 실현: {r_color}{realized_profit:+,}원\033[0m | 일일(평가+실현): {d_color}{int(daily_pnl_amt):+,}원 ({abs(daily_pnl_rate):.2f}%)\033[0m | KOSPI: {k_color}{kospi_rate:+.2f}%\033[0m | KOSDAQ: {kd_color}{kosdaq_rate:+.2f}%\033[0m\n")
            buf.write("-" * tw + "\n")

            # ② [순서 변경] 투자 성과 진단 (2번째 배치)
            my_rate = daily_pnl_rate; market_rate = kospi_rate; alpha = my_rate - market_rate
            if my_rate > 0 and market_rate > 0:
                verdict_msg = f"\033[91m✅ 상승장 초과 수익! Alpha: +{alpha:.2f}%p\033[0m" if alpha >= 0 else f"\033[93m⚠️ 시장 대비 소폭 지체. Alpha: {alpha:.2f}%p\033[0m"
            elif my_rate > 0 and market_rate <= 0:
                verdict_msg = f"\033[91m🏆 하락장 수익! 탁월한 선정. Alpha: {alpha:+.2f}%p\033[0m"
            elif my_rate <= 0 and market_rate > 0:
                verdict_msg = f"\033[94m🚨 시장 소외! 전략 재점검 필요. Alpha: {alpha:+.2f}%p\033[0m"
            else:
                verdict_msg = f"\033[93m🛡️ 하락장 방어 성공. Alpha: {alpha:+.2f}%p\033[0m" if alpha >= 0 else f"\033[94m❌ 리스크 관리 강화 필요. Alpha: {alpha:+.2f}%p\033[0m"
            buf.write(f" \033[1;93m[📊 투자 성과 진단]\033[0m 내 수익률({d_color}{my_rate:+.2f}%\033[0m) vs KOSPI({k_color}{market_rate:+.2f}%\033[0m) → {verdict_msg}\n")
            buf.write("-" * tw + "\n")

            # ③ [좌우 배치] 매수/매도 테이블
            other_w = 57 # 가격(8)|현재(8)|평균(8)|손익(10)|방법(12)|평가(6) = 52 + 5 separators
            half_w = tw // 2
            name_w = max(12, half_w - other_w - 2)
            
            def smart_align(text, width):
                if get_visual_width(text) <= width:
                    return align_kr(text, width)
                t = str(text)
                while get_visual_width(t + "..") > width and len(t) > 0:
                    t = t[:-1]
                return align_kr(t + "..", width)

            def format_trade_row(info, is_buy):
                code = info['code']; name = info['name']
                # [개선] 오늘 매수평단가가 아닌, 계좌 실제 평단가(Cost Basis)를 우선 표시하여 사용자 혼선 방지
                price = info['avg_price'] 
                cur = get_current_price(code)
                ma_20 = info.get('ma_20', 0)
                # 기록된 값이 없으면 실시간 캐시에서 fallback (기존 로그 호환용)
                if ma_20 == 0:
                    ma_20 = dm.ma_20_cache.get(str(code).strip(), 0)
                
                # 손익 계산
                if is_buy:
                    # 매수 쪽은 현재 들고 있는 비중의 평가손익 (계좌 평단 기준)
                    pnl = (cur - price) * info['total_qty']
                else:
                    # 매도 쪽은 오늘 확정된 실현손익
                    pnl = info['total_pnl']
                
                p_color = "\033[91m" if pnl > 0 else "\033[94m" if pnl < 0 else ""
                
                # [개선] Verdict(평가) 로직 고도화: 단순 가격 비교가 아닌 손익과 시황을 결합하여 입체적 진단
                if is_buy:
                    # 매수(Entry) 평가: 현재 수익권인가?
                    if pnl > 0: verdict = "✅성공"
                    elif pnl < 0: verdict = "❌실패"
                    else: verdict = "➖보합"
                    v_color = "\033[91m" if pnl > 0 else ("\033[94m" if pnl < 0 else "")
                else:
                    # 매도(Exit) 평가: 타이밍이 적절했는가?
                    if pnl > 0:
                        if cur <= price: verdict = "✅완벽" # 최고가 매도 또는 매도 후 하락 (익절 성공)
                        else: verdict = "❌일찍" # 매도 후 더 오름 (수익 극대화 실패)
                    else:
                        if cur <= price: verdict = "🛡️방어" # 손절 후 더 하락 (추가 손실 방어 성공)
                        else: verdict = "❌손절" # 손절 후 반등 (최악의 타이밍 손절)
                    v_color = "\033[91m" if verdict in ["✅완벽", "🛡️방어"] else "\033[94m"
                
                ma_str = f"{int(ma_20):,}" if ma_20 > 0 else "-"
                
                row = (f"{smart_align(f'[{code}]{name}', name_w)}|"
                       f"{align_kr(f'{int(price):,}', 8, 'right')}|"
                       f"{align_kr(f'{int(cur):,}', 8, 'right')}|"
                       f"{align_kr(ma_str, 8, 'right')}|"
                       f"{p_color}{align_kr(f'{int(pnl):,}', 10, 'right')}\033[0m|"
                       f"{align_kr(info['type'][:6], 12)}|"
                       f"{v_color}{align_kr(verdict, 6)}\033[0m")
                return row

            # 데이터 요약 (계좌 평단가 및 실현 손익 기반 역추산 평단가 적용)
            buy_summary = {}
            for t in buy_trades:
                c = t['code']; q = int(t['qty']); p = float(t['price'])
                if c not in buy_summary:
                    # 계좌에서 실제 보유 중인 종목이라면 평단가(Cost Basis)를 가져옴
                    acc_avg = 0.0
                    for h in dm.cached_holdings:
                        if h.get('pdno') == c:
                            acc_avg = float(h.get('pchs_avg_pric', 0))
                            break
                    buy_summary[c] = {"name": t['name'], "code": c, "total_amt": 0, "total_qty": 0, "type": t['type'], "acc_avg": acc_avg, "ma_20": t.get('ma_20', 0)}
                
                buy_summary[c]["total_amt"] += p * q; buy_summary[c]["total_qty"] += q
                # 계좌 정보가 있으면 계좌 평단 사용, 없으면 오늘 매수 평균 사용
                if buy_summary[c]["acc_avg"] > 0:
                    buy_summary[c]["avg_price"] = buy_summary[c]["acc_avg"]
                else:
                    buy_summary[c]["avg_price"] = buy_summary[c]["total_amt"] / buy_summary[c]["total_qty"]

            sell_summary = {}
            for t in sell_trades:
                c = t['code']; q = int(t['qty']); p = float(t['price']); pr = float(t.get('profit', 0))
                if c not in sell_summary: 
                    sell_summary[c] = {"name": t['name'], "code": c, "total_amt": 0, "total_qty": 0, "total_pnl": 0, "type": t['type'], "ma_20": t.get('ma_20', 0)}
                sell_summary[c]["total_amt"] += p * q; sell_summary[c]["total_qty"] += q; sell_summary[c]["total_pnl"] += pr; sell_summary[c]["avg_price"] = sell_summary[c]["total_amt"] / sell_summary[c]["total_qty"]

            # [추가] 매도된 종목 중 오늘 매수 이력이 있는 경우, 매수 섹션의 평단가도 실현 손익 기준으로 보정 (이미 잔고에 없을 때)
            for c, b_info in buy_summary.items():
                if b_info["acc_avg"] == 0 and c in sell_summary:
                    # 실현 손익 기반으로 원래의 평단가 역추산: (매도가 - (수익금 / 수량))
                    s_info = sell_summary[c]
                    if s_info["total_qty"] > 0:
                        derived_buy_p = s_info["avg_price"] - (s_info["total_pnl"] / s_info["total_qty"])
                        b_info["avg_price"] = derived_buy_p
            
            buy_list = list(buy_summary.values()); sell_list = list(sell_summary.values()); max_rows = max(len(buy_list), len(sell_list))
            
            # 성과 계산
            buy_wins = 0
            for b in buy_list:
                cur = get_current_price(b['code'])
                if cur >= b['avg_price']: buy_wins += 1
            buy_rate = (buy_wins / len(buy_list) * 100) if buy_list else 0
            
            sell_wins = 0
            for s in sell_list:
                cur = get_current_price(s['code'])
                if cur <= s['avg_price']: sell_wins += 1
            sell_rate = (sell_wins / len(sell_list) * 100) if sell_list else 0

            h_buy = f"\033[1;42;1;37m{align_kr(f' [📈 매수 성과: {buy_wins}/{len(buy_list)} ({buy_rate:.0f}%)] ', half_w-1, 'center')}\033[0m"
            h_sell = f"\033[1;41;1;37m{align_kr(f' [📉 매도 성과: {sell_wins}/{len(sell_list)} ({sell_rate:.0f}%)] ', tw-half_w-1, 'center')}\033[0m"
            buf.write(f"{h_buy} {h_sell}\n")
            t_head = f"{smart_align('종목(코드)명', name_w)}|{align_kr('매수가', 8)}|{align_kr('현재가', 8)}|{align_kr('평균선', 8)}|{align_kr('평가손익', 10)}|{align_kr('방법', 12)}|{align_kr('평가', 6)}"
            t_head_s = f"{smart_align('종목(코드)명', name_w)}|{align_kr('매도가', 8)}|{align_kr('현재가', 8)}|{align_kr('평균선', 8)}|{align_kr('실현손익', 10)}|{align_kr('방법', 12)}|{align_kr('평가', 6)}"
            buf.write(f"\033[1m{align_kr(t_head, half_w-1)} \033[1m{align_kr(t_head_s, tw-half_w-1)}\033[0m\n")
            buf.write("-" * (half_w-1) + " " + "-" * (tw-half_w-1) + "\n")
            for i in range(max(1, max_rows)):
                b_row = format_trade_row(buy_list[i], True) if i < len(buy_list) else " " * (half_w - 1)
                s_row = format_trade_row(sell_list[i], False) if i < len(sell_list) else ""
                buf.write(f"{align_kr(b_row, half_w-1)} {s_row}\n")
            buf.write("-" * tw + "\n")
            
            # ④ 모델별 누적 성과 (축약)
            model_stats = trading_log.get_model_performance()
            if model_stats:
                buf.write("\033[1;95m [🤖 모델별 누적 성과]\033[0m ")
                m_line = ""
                for m, s in model_stats.items():
                    p_color = "\033[91m" if s['total_profit'] > 0 else "\033[94m"
                    m_line += f"{m}: {p_color}{int(s['total_profit']):+,}원\033[0m | "
                buf.write(m_line.rstrip(" | ") + "\n")

        elif current_tab == 4:
            # 4. 투자 적중 (매매 복기 누적 분석)
            retro = getattr(strategy, 'retrospective', None)
            buf.write("\033[1;95m" + " [투자 적중 분석 (매매 복기 누적 리포트)]" + "\033[0m\n")
            buf.write("-" * tw + "\n")
            if not retro: buf.write("  ⚠️ 투자 적중 엔진이 초기화되지 않았습니다.\n")
            else:
                stats = retro.get_cumulative_stats()
                if stats["total_days"] > 0:
                    net_color = "\033[91m" if stats["net_profit"] > 0 else "\033[94m"; wr_color = "\033[91m" if stats["win_rate"] >= 50 else "\033[94m"
                    buf.write(f" \033[1m[누적 {stats['total_days']}일]\033[0m 승률: {wr_color}{stats['win_rate']:.1f}%\033[0m | 수익종목: \033[91m{int(stats['total_profit']):+,}\033[0m | 손실종목: \033[94m{int(stats['total_loss']):+,}\033[0m | 순이익: {net_color}{int(stats['net_profit']):+,}\033[0m\n")
                    buf.write("-" * tw + "\n")
                reports = retro.get_reports(limit=3)
                if not reports:
                    buf.write("\n  📭 아직 생성된 복기 리포트가 없습니다.\n  ℹ️ 매일 오후 4시(16:00)에 자동 생성되며, 장 마감 후 30분마다 업데이트됩니다.\n")
                else:
                    max_l = max(5, th - 16); l_cnt = 0
                    for date_str, report in reports:
                        if l_cnt >= max_l: break
                        gen_t = report.get("generated_at", "?").split(' ')[-1]; vibe = report.get("market_vibe", "N/A")
                        buf.write(f"\n \033[1;93m📊 [{date_str}]\033[0m 생성: {gen_t} | 갱신: {report.get('update_count', 1)}회 | 장세: {vibe}\n"); l_cnt += 1
                        for s in report.get("top_profits", []):
                            if l_cnt >= max_l: break
                            buf.write(f"  \033[92m🟢 {s.get('name', '?')}\033[0m \033[91m{int(s.get('total_profit', 0)):+,}\033[0m원" + (f" (종가:{int(s['closing_price']):,}원)" if s.get("closing_price") else "") + "\n"); l_cnt += 1
                        for s in report.get("top_losses", []):
                            if l_cnt >= max_l: break
                            buf.write(f"  \033[91m🔴 {s.get('name', '?')}\033[0m \033[94m{int(s.get('total_profit', 0)):+,}\033[0m원" + (f" (종가:{int(s['closing_price']):,}원)" if s.get("closing_price") else "") + "\n"); l_cnt += 1
                        ai_text = report.get("ai_analysis", "")
                        if ai_text:
                            cleaned_ai = clean_ai_text(ai_text)
                            for line in cleaned_ai.split('\n'):
                                if l_cnt >= max_l: break
                                s_line = line.strip()
                                if s_line:
                                    if get_visual_width(s_line) > tw - 4:
                                        while get_visual_width(s_line) > tw - 6: s_line = s_line[:-1]
                                        s_line += ".."
                                    buf.write(f"  {s_line}\n"); l_cnt += 1
                        buf.write("-" * tw + "\n"); l_cnt += 1

        buf.write("\n" + "-" * tw + "\n")
        buf.write(align_kr(" [1, 2, 3, 4]: 탭 전환 | Q, ESC, SPACE: 종료 ", tw, 'center') + "\n")
        
        # [수정] 부드러운 화면 갱신
        sys.stdout.write("\033[H")
        content_lines = buf.getvalue().split('\n')
        for i in range(min(th, len(content_lines))):
            sys.stdout.write(content_lines[i] + "\033[K" + ("\n" if i < th-1 else ""))
        sys.stdout.write("\033[J")
        sys.stdout.flush()

        
        while True:
            k = get_key_immediate()
            if k:
                kl = k.lower()
                if kl == '1': current_tab = 1; break
                elif kl == '2': current_tab = 2; break
                elif kl == '3': current_tab = 3; break
                elif kl == '4': current_tab = 4; break
                elif kl in ['q', 'esc', ' ']:
                    buf.close()
                    return
            time.sleep(0.01)

