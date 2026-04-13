import os
import sys
import io
import time
from datetime import datetime
from src.utils import is_market_open, is_us_market_open, get_visual_width, align_kr, ANSI_ESCAPE, get_market_name, get_key_immediate
from src.theme_engine import get_cached_themes

def draw_tui(strategy, dm, cycle_info, prompt_mode=None):
    with dm.ui_lock:
        try:
            size = os.get_terminal_size(); tw, th = size.columns, size.lines
        except: tw, th = 110, 30

        buf = io.StringIO()
        if (tw, th) != dm.last_size: buf.write("\033[2J"); dm.last_size = (tw, th)
        buf.write("\033[H")
    
    now_dt = datetime.now()
    k_st, u_st = ("OPEN" if is_market_open() else "CLOSED"), ("OPEN" if is_us_market_open() else "CLOSED")
    
    m_label = "ALL" if dm.ranking_filter == "ALL" else "KOSPI" if dm.ranking_filter == "KSP" else "KOSDAQ" if dm.ranking_filter == "KDQ" else "USA"
    h_l = f" [AI TRADING SYSTEM] | {now_dt.strftime('%Y-%m-%d %H:%M:%S')} | KR:{k_st} | US:{u_st}"
    h_r = f" ✅ LAST UPDATE: {dm.last_update_time} | FILTER: {m_label} "
    
    busy_txt = ""
    if dm.global_busy_msg:
        dm.busy_anim_step = (dm.busy_anim_step + 1) % 4
        dots = "." * (dm.busy_anim_step + 1)
        busy_txt = f"\033[1;33m{dm.global_busy_msg}{dots}\033[0;37;44m"
    
    total_h_w = get_visual_width(h_l) + get_visual_width(h_r)
    space_between = max(0, tw - total_h_w)
    
    if busy_txt:
        busy_plain = ANSI_ESCAPE.sub('', busy_txt)
        busy_w = get_visual_width(busy_plain)
        l_pad = max(0, (space_between - busy_w) // 2)
        r_pad = max(0, space_between - busy_w - l_pad)
        header_line = h_l + " " * l_pad + busy_txt + " " * r_pad + h_r
    else:
        header_line = h_l + " " * space_between + h_r

    final_w = get_visual_width(header_line)
    if final_w < tw: header_line += " " * (tw - final_w)
    buf.write("\033[44m" + header_line + "\033[0m\n")
    
    with dm.data_lock:
        k_mkt_l = " K Market: "
        for k in ["KOSPI", "KPI200", "KOSDAQ", "VOSPI"]:
            d = dm.cached_market_data.get(k)
            if d:
                color = "\033[91m" if d['rate'] >= 0 else "\033[94m"
                disp_map = {"KOSPI": "KSP", "KPI200": "K200F", "KOSDAQ": "KDQ", "VOSPI": "VIX"}
                k_mkt_l += f"{disp_map.get(k, k[:3])} {d['price']:,.2f}({color}{d['rate']:+0.2f}%\033[0m)  "
        usd_krw = dm.cached_market_data.get("FX_USDKRW")
        if usd_krw:
            color = "\033[91m" if usd_krw['rate'] >= 0 else "\033[94m"
            k_mkt_l += f"USDKRW {usd_krw['price']:,.1f}({color}{usd_krw['rate']:+0.2f}%\033[0m)  "
        buf.write(align_kr(k_mkt_l, tw) + "\n")

        u_mkt_l = " US Market: "
        for k in ["DOW", "NASDAQ", "NAS_FUT", "S&P500", "SPX_FUT"]:
            d = dm.cached_market_data.get(k)
            if d:
                color = "\033[91m" if d['rate'] >= 0 else "\033[94m"
                disp_map = {"DOW": "DOW", "NASDAQ": "NAS", "NAS_FUT": "NAS.F", "S&P500": "SPX", "SPX_FUT": "SPX.F"}
                u_mkt_l += f"{disp_map.get(k, k[:3])} {d['price']:,.1f}({color}{d['rate']:+0.2f}%\033[0m)  "
        buf.write(align_kr(u_mkt_l, tw) + "\n")

        btc_krw = dm.cached_market_data.get("BTC_KRW")
        btc_usd = dm.cached_market_data.get("BTC_USD")
        c_mkt_l = "\033[0m C Market:  "
        if btc_krw and btc_usd and usd_krw:
            k_color = "\033[91m" if btc_krw['rate'] >= 0 else "\033[94m"
            c_mkt_l += f"K-BTC {btc_krw['price']:,.0f}({k_color}{btc_krw['rate']:+0.2f}%\033[0m)   "
            usd_to_krw_price = btc_usd['price'] * usd_krw['price']
            u_color = "\033[91m" if btc_usd['rate'] >= 0 else "\033[94m"
            c_mkt_l += f"BTC {usd_to_krw_price:,.0f}({u_color}{btc_usd['rate']:+0.2f}%\033[0m)   "
            diff_amt = btc_krw['price'] - usd_to_krw_price
            k_prem = (diff_amt / usd_to_krw_price) * 100
            p_color = "\033[91m" if k_prem >= 0 else "\033[94m"
            c_mkt_l += f"PREM {int(diff_amt):+,}({p_color}{k_prem:+0.2f}%\033[0m)"
        buf.write(align_kr(c_mkt_l, tw) + "\n")

        v_c = "\033[91m" if "Bull" in dm.cached_vibe else ("\033[94m" if "Bear" in dm.cached_vibe else "\033[93m")
        panic_txt = " !!! PANIC !!!" if dm.cached_panic else ""
        b_cfg = strategy.bear_config; auto_st = "ON" if b_cfg.get("auto_mode") else "OFF"
        phase = strategy.get_market_phase(); phase_icons = {"P1": "🔥", "P2": "🧘", "P3": "💰", "P4": "🛒", "IDLE": "💤"}
        phase_txt = f" [PHASE: {phase_icons.get(phase['id'], '💤')}{phase['name']}]"
        vibe_desc = f"(하락장: 물타기 [\033[94m{b_cfg.get('min_loss_to_buy')}% / {b_cfg.get('average_down_amount')/10000:,.0f}만 / 자동:{auto_st}\033[0m])" if "Bear" in dm.cached_vibe else ("(\033[91m상승장: 익절 기준 상향 보정 [+3.0%]\033[0m)" if "Bull" in dm.cached_vibe else "(보합장: 기본 전략 유지)")
        ai_msg = strategy.analyzer.ai_override_msg if hasattr(strategy.analyzer, "ai_override_msg") else ""
        ai_msg_formatted = f" \033[92m{ai_msg}\033[0m" if "일치" in ai_msg else (f" \033[93m{ai_msg}\033[0m" if ai_msg else "")
        buf.write(align_kr(f" VIBE: {v_c}{dm.cached_vibe.upper()}\033[0m{phase_txt} {panic_txt} {vibe_desc}{ai_msg_formatted}", tw) + "\n")
        buf.write("\033[93m" + align_kr(f" [COMMANDS] 1:매도 | 2:매수 | 3:자동 | 4:추천 | 5:물타기 6:불타기 | AI 7:분석 8:시황 | 9:전략 | 리포트 B:보유 D:추천 H:인기 | M:메뉴얼 | S:셋업 | Q:종료", tw) + "\033[0m\n")
        
        if strategy.ai_briefing and not prompt_mode:
            all_lines = [line.strip() for line in strategy.ai_briefing.split('\n') if line.strip()]
            brief_map = {"시장": "", "전략": "", "액션": "", "추천": ""}
            for l in all_lines:
                for k in brief_map.keys():
                    if f"AI[{k}]:" in l: brief_map[k] = l; break
            for k in ["시장", "전략", "액션", "추천"]:
                buf.write("\033[1;95m" + align_kr(f" {brief_map[k] if brief_map[k] else f'AI[{k}]: 분석 데이터 없음'}", tw) + "\033[0m\n")
        elif prompt_mode: 
            buf.write("\033[1;33m" + align_kr(f" >>> [{prompt_mode} MODE] 입력 대기 중... (ESC 취소)", tw) + "\033[0m\n")
            buf.write("\n" * 3)
        else: buf.write("\n" * 4) 
        
        buf.write("=" * tw + "\n")
        asset = dm.cached_asset; tot_eval = asset.get('total_asset', 0); tot_prin = asset.get('total_principal', 0)
        tot_rt = ((tot_eval - tot_prin) / tot_prin * 100) if tot_prin > 0 else 0
        tot_color = "\033[91m" if tot_rt > 0 else "\033[94m" if tot_rt < 0 else "\033[0m"
        stk_eval = asset.get('stock_eval', 0); stk_prin = asset.get('stock_principal', 0)
        stk_rt = ((stk_eval - stk_prin) / stk_prin * 100) if stk_prin > 0 else 0
        stk_color = "\033[91m" if stk_rt > 0 else "\033[94m" if stk_rt < 0 else "\033[0m"
        buf.write(align_kr(f" Asset | 평가액: {tot_eval:,.0f} (원금: {tot_prin:,.0f}, {tot_color}{tot_rt:+.2f}%\033[0m) | 인출가능: {asset.get('cash', 0):,.0f} | 주식총액: {stk_eval:,.0f} ({stk_color}{stk_rt:+.2f}%\033[0m)", tw) + "\n")
        
        tp_cur, sl_cur, _ = strategy.get_dynamic_thresholds("BASE", dm.cached_vibe.lower())
        buf.write(align_kr(f"{'* STRAT' if strategy.is_modified('STRAT') else ' STRAT '} | 매입/수: 익절 {strategy.base_tp:+.1f}% (현재 {tp_cur:+.1f}%) | 손절 {strategy.base_sl:+.1f}% (현재 {sl_cur:+.1f}%)", tw) + "\n")
        buf.write(align_kr(f"{'* BEAR ' if strategy.is_modified('BEAR') else ' BEAR  '} | 물타기: 트리거 \033[94m{b_cfg.get('min_loss_to_buy'):+.1f}%\033[0m | 회당 {b_cfg.get('average_down_amount'):,}원 | 종목한도 {b_cfg.get('max_investment_per_stock'):,}원 | 자동: {auto_st} | PnL 하락 방어", tw) + "\n")
        u_cfg = strategy.bull_config; u_st = "ON" if u_cfg.get("auto_mode") else "OFF"
        buf.write(align_kr(f"{'* BULL ' if strategy.is_modified('BULL') else ' BULL  '} | 불타기: 트리거 \033[91m+{u_cfg.get('min_profit_to_pyramid'):.1f}%\033[0m | 회당 {u_cfg.get('average_down_amount'):,}원 | 종목한도 {u_cfg.get('max_investment_per_stock'):,}원 | 자동: {u_st} | 수익 비중 확대", tw) + "\n")
        a_cfg = strategy.ai_config; ai_st = "ON" if a_cfg.get("auto_mode") else "OFF"
        buf.write(align_kr(f"{'* ALGO ' if strategy.is_modified('ALGO') else ' ALGO  '} | 추천매매: 회당 {a_cfg.get('amount_per_trade'):,}원 | 종목한도 {a_cfg.get('max_investment_per_stock'):,}원 | 자동: {ai_st} | 테마 모멘텀", tw) + "\n")
        buf.write("-" * tw + "\n")

        eff_w = tw - 4; w = [max(4, int(eff_w * 0.03)), max(5, int(eff_w * 0.04)), max(15, int(eff_w * 0.15)), max(10, int(eff_w * 0.09)), max(14, int(eff_w * 0.12)), max(10, int(eff_w * 0.08)), max(8, int(eff_w * 0.07)), max(10, int(eff_w * 0.08)), max(18, int(eff_w * 0.12)), max(10, int(eff_w * 0.07)), max(10, int(eff_w * 0.10)), max(6, int(eff_w * 0.05))]
        buf.write("\033[1m" + align_kr(align_kr("NO",w[0])+align_kr("MKT",w[1])+align_kr("SYMBOL",w[2])+align_kr("CURR",w[3],'right')+align_kr("DAY",w[4],'right')+align_kr("AVG",w[5],'right')+align_kr("QTY",w[6],'right')+align_kr("EVAL",w[7],'right')+align_kr("PnL",w[8],'right')+"  "+align_kr("TP/SL",w[9],'right')+"  "+align_kr("전략",w[10],'center')+align_kr("남음",w[11],'right'), tw) + "\033[0m\n")
        
        f_h = dm.cached_holdings if dm.ranking_filter == "ALL" else [h for h in dm.cached_holdings if get_market_name(h.get('pdno','')) == dm.ranking_filter]
        base_fixed = 23; ranking_target = 10; asset_count = len(f_h); max_h_display = max(1, th - base_fixed - ranking_target)
        if asset_count < max_h_display: max_h_display = asset_count
        ranking_items_count = min(10, max(3, th - base_fixed - max_h_display))
        
        if not f_h: buf.write(align_kr(f"No active {dm.ranking_filter} holdings found.", tw, 'center') + "\n")
        else:
            for idx, h in enumerate(f_h[:max_h_display], 1):
                code, name = h.get("pdno", ""), h.get("prdt_name", "Unknown"); info = dm.cached_stock_info.get(code, {"tp": 0, "sl": 0, "spike": False})
                p_a, p_cu = float(h.get('pchs_avg_pric', 0)), float(h.get('prpr', 0)); d_v, d_r = info.get("day_val", float(h.get('prdy_vrss', 0))), info.get("day_rate", float(h.get('prdy_ctrt', 0)))
                pnl_amt = (p_cu - p_a) * float(h.get('hldg_qty', 0)); pnl_rt = float(h.get('evlu_pfls_rt', 0))
                pnl_txt = f"{int(pnl_amt):+,}({abs(pnl_rt):.2f}%)"; preset_label = strategy.get_preset_label(code); rem_txt = "-"
                p_strat = strategy.preset_strategies.get(code)
                if p_strat and p_strat.get('deadline'):
                    try: rem_mins = int((datetime.strptime(p_strat['deadline'], '%Y-%m-%d %H:%M:%S') - datetime.now()).total_seconds() / 60); rem_txt = f"{rem_mins}M" if rem_mins > 0 else "EXP"
                    except: rem_txt = "ERR"
                buf.write(align_kr(align_kr(str(idx), w[0]) + align_kr(get_market_name(code), w[1]) + align_kr(f"[{code}] {name[:(w[2]-10)//2*2]}" + (" *" if info['spike'] else ""), w[2]) + align_kr(f"{int(p_cu):,}", w[3], 'right') + ("\033[91m" if d_v > 0 else "\033[94m" if d_v < 0 else "") + align_kr(f"{int(d_v):+,}({abs(d_r):.1f}%)" if d_v != 0 else "-", w[4], 'right') + "\033[0m" + align_kr(f"{int(p_a):,}", w[5], 'right') + align_kr(f"{int(float(h.get('hldg_qty', 0))):,}", w[6], 'right') + align_kr(f"{int(float(h.get('evlu_amt', 0))):,}", w[7], 'right') + ("\033[91m" if pnl_amt >= 0 else "\033[94m") + align_kr(pnl_txt, w[8], 'right') + "\033[0m  " + align_kr(f"{info['tp']:+.1f}/{info['sl']:+.1f}%", w[9], 'right') + "  " + ("\033[96m" if preset_label else "\033[90m") + align_kr(preset_label if preset_label else "표준", w[10], 'center') + "\033[0m" + align_kr(rem_txt, w[11], 'right'), tw) + "\n")
            if len(f_h) > max_h_display: buf.write(align_kr(f"... 외 {len(f_h) - max_h_display}종목 생략됨", tw, 'center') + "\n")
        
        buf.write("-" * tw + "\n"); themes = get_cached_themes()
        if themes: buf.write("\033[93m" + align_kr(" 🔥 인기테마: " + " | ".join([f"{t['name']}({t['count']})" for t in themes[:8]]), tw) + "\033[0m\n")
        else: buf.write("\n")
        
        y_recs = strategy.yesterday_recs_processed
        if y_recs:
            # 최대 10개, 한 줄에 5개씩 표시
            recs_to_show = y_recs[:10]
            for i in range(0, len(recs_to_show), 5):
                line_parts = []
                chunk = recs_to_show[i:i+5]
                # 각 항목의 최대 너비 계산 (tw - 여백) / 5
                item_w = (tw - 10) // 5
                for r in chunk:
                    color = "\033[91m" if r['change'] >= 0 else "\033[94m"
                    name = r['name']
                    # [코드]이름(변동%) 형식으로 구성 후 너비 초과 시 이름 축약
                    tag = f"[{r['code']}]"
                    chg_tag = f"({color}{r['change']:+0.2f}%\033[0m)"
                    base_w = get_visual_width(tag) + 8 # 변동성 태그 너비 약 8
                    
                    while get_visual_width(name) + base_w > item_w and len(name) > 2:
                        name = name[:-1]
                    
                    if len(name) < len(r['name']): name += ".."
                    line_parts.append(f"{tag}{name}{chg_tag}")
                
                label = " 📅 어제 성과: " if i == 0 else " " * 14
                buf.write(align_kr(f"\033[90m{label}{' | '.join(line_parts)}", tw) + "\033[0m\n")
        else:
            buf.write(align_kr("\033[90m 📅 어제 추천 이력이 없습니다.", tw) + "\033[0m\n")

        buf.write("-" * tw + "\n")

        col_w = (tw - 6) // 3; hot_list = [g for g in dm.cached_hot_raw if str(g.get('mkt','')).strip().upper() == dm.ranking_filter or dm.ranking_filter == "ALL"][:ranking_items_count]
        vol_list = [l for l in dm.cached_vol_raw if str(l.get('mkt','')).strip().upper() == dm.ranking_filter or dm.ranking_filter == "ALL"][:ranking_items_count]; ai_recs = strategy.ai_recommendations[:ranking_items_count]

        def fmt_r(item, width=col_w):
            if not item: return " " * width
            r = float(item['rate']); p = int(float(item.get('price', 0))); c = "\033[91m" if r >= 0 else "\033[94m"
            name = item.get('name', 'Unknown')
            txt = f"[{item['code']}] {name} ({p:,}/{c}{r:>+4.1f}%\033[0m)"
            while get_visual_width(txt) > width:
                name = name[:-1]
                txt = f"[{item['code']}] {name}.. ({p:,}/{c}{r:>+4.1f}%\033[0m)"
            return align_kr(txt, width)

        def fmt_ai(item, width=col_w):
            if not item: return " " * width
            r = float(item.get('rate', 0)); p = int(float(item.get('price', 0))); c = "\033[91m" if r >= 0 else "\033[94m"
            name = item.get('name', 'Unknown')
            theme = item.get('theme','?')[0:2]
            txt = f"({theme})[{item['code']}] {name} ({p:,}/{c}{r:>+4.1f}%\033[0m)"
            while get_visual_width(txt) > width:
                name = name[:-1]
                txt = f"({theme})[{item['code']}] {name}.. ({p:,}/{c}{r:>+4.1f}%\033[0m)"
            return align_kr(txt, width)

        buf.write(f"\033[1;93m{align_kr('🔥 HOT SEARCH', col_w)}\033[0m │ \033[1;96m{align_kr('📊 VOLUME TOP', col_w)}\033[0m │ \033[1;92m{align_kr(f'✨ AI 추천 {'\033[91m' if strategy.auto_ai_trade else '\033[93m'}[{'AUTO' if strategy.auto_ai_trade else 'MANUAL'}]\033[1;92m', col_w)}\033[0m\n")
        buf.write("─" * col_w + "─┼─" + "─" * col_w + "─┼─" + "─" * col_w + "\n")
        for i in range(ranking_items_count): buf.write(f"{fmt_r(hot_list[i] if i < len(hot_list) else None)} │ {fmt_r(vol_list[i] if i < len(vol_list) else None)} │ {fmt_ai(ai_recs[i] if i < len(ai_recs) else None)}\n")
    
    rem = th - buf.getvalue().count('\n')
    if rem > 0: buf.write(f"\033[K {dm.status_msg if dm.status_msg and (time.time()-dm.status_time<60) else ''}\n"); rem -= 1
    if rem > 0: buf.write(f"\033[K {dm.last_log_msg if dm.last_log_msg and (time.time()-dm.last_log_time<60) else ''}\n"); rem -= 1
    if rem > 0:
        logs = dm.trading_logs; skip = len(logs) - (rem - 1)
        if skip > 0: buf.write(f"\033[K \033[90m... 외 {skip}건의 로그 생략됨\033[0m\n"); logs = logs[-(rem-1):]; rem -= 1
        for tl in logs:
            if rem <= 0: break
            buf.write(f"\033[K {tl}\n"); rem -= 1
    while rem > 0: buf.write("\033[K\n"); rem -= 1
    lines = buf.getvalue().split('\n')
    if lines and not lines[-1]: lines.pop()
    sys.stdout.write("\033[H")
    for i in range(min(th, len(lines))): sys.stdout.write(lines[i] + "\033[K" + ("\n" if i < th-1 and i < len(lines)-1 else ""))
    sys.stdout.flush(); buf.close()

def draw_manual_page(tw, th):
    buf = io.StringIO(); buf.write("\033[H\033[2J")
    buf.write("\033[46;37m" + align_kr(" [KIS-VIBE-TRADER SYSTEM MANUAL] ", tw, 'center') + "\033[0m\n\n")
    buf.write("\033[1;93m 1. 장중 시간 페이즈(Market Phase) 전략\033[0m\n")
    buf.write("  - \033[91m🔥 Phase 1 (09:00~10:00) [공격]\033[0m: 변동성 극대화 구간. 익절 상향(+2%), 손절 완화(-1%).\n")
    buf.write("  - \033[92m🧘 Phase 2 (10:00~14:30) [관리]\033[0m: 횡보 함정 구간. 익절/손절 강화(-1%)로 리스크 타이트하게 관리.\n")
    buf.write("  - \033[93m💰 Phase 3 (14:30~15:10) [확정]\033[0m: 당일 수익 확정. 수익권 종목 50% 분할 매도 및 잔량 본전 스탑.\n")
    buf.write("  - \033[96m🛒 Phase 4 (15:10~15:20) [준비]\033[0m: 익일 유망주 선취매. 시장 안심(Bull/Neutral) 시에만 신규 매수.\n\n")
    buf.write("\033[1;93m 2. AI 동적 리스크 관리 (Time-Stop)\033[0m\n")
    buf.write("  - \033[1m유효 시간(Lifetime)\033[0m: 전략 할당 시 AI가 종목의 모멘텀 수명을 예측하여 데드라인을 설정.\n")
    buf.write("  - \033[1m타임 스탑\033[0m: 데드라인(REM:EXP) 경과 시, 익절선을 현재 수익의 절반으로 낮춰 수익을 보존.\n")
    buf.write("  - \033[1m동적 보정\033[0m: 시장 Vibe(Bull/Bear)와 종목 변동성을 분석하여 TP/SL을 실시간으로 미세 조정.\n\n")
    buf.write("\033[1;93m 3. 핵심 운영 팁\033[0m\n")
    buf.write("  - \033[1m[3:자동]\033[0m: 번호 없이 'TP SL' 입력 시 보유 전 종목의 기본 익절/손절을 일괄 변경합니다.\n")
    buf.write("  - \033[1m[8:시황]\033[0m: AI가 제안하는 수치는 현재 Vibe가 반영된 최종 목표값이며 시스템이 역산 적용합니다.\n")
    buf.write("  - \033[1m[9:전략]\033[0m: 엔터만 입력 시 AI가 해당 종목에 가장 적합한 KIS 프리셋 전략을 자동 매칭합니다.\n\n")
    buf.write("-" * tw + "\n" + align_kr(" 아무 키나 누르면 메인 화면으로 돌아갑니다. ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue()); sys.stdout.flush()
    while not sys.stdin.read(1): time.sleep(0.1)
    buf.close()
