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
    h_r = f" ??LAST UPDATE: {dm.last_update_time} | FILTER: {m_label} "
    
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
        phase = strategy.get_market_phase(); phase_icons = {"P1": "?î•", "P2": "?ßò", "P3": "?í∞", "P4": "?õí", "IDLE": "?í§"}
        phase_txt = f" [PHASE: {phase_icons.get(phase['id'], '?í§')}{phase['name']}]"
        vibe_desc = f"(?òÎùΩ?? Î¨ºÌ?Í∏?[\033[94m{b_cfg.get('min_loss_to_buy')}% / {b_cfg.get('average_down_amount')/10000:,.0f}Îß?/ ?êÎèô:{auto_st}\033[0m])" if "Bear" in dm.cached_vibe else ("(\033[91m?ÅÏäπ?? ?µÏ†à Í∏∞Ï? ?ÅÌñ• Î≥¥Ï†ï [+3.0%]\033[0m)" if "Bull" in dm.cached_vibe else "(Î≥¥Ìï©?? Í∏∞Î≥∏ ?ÑÎûµ ?†Ï?)")
        ai_msg = strategy.analyzer.ai_override_msg if hasattr(strategy.analyzer, "ai_override_msg") else ""
        ai_msg_formatted = f" \033[92m{ai_msg}\033[0m" if "?ºÏπò" in ai_msg else (f" \033[93m{ai_msg}\033[0m" if ai_msg else "")
        buf.write(align_kr(status_line, tw) + "\n")
        buf.write("\033[93m" + align_kr(f" [COMMANDS] 1:Îß§ÎèÑ | 2:Îß§Ïàò | 3:?êÎèô | 4:Ï∂îÏ≤ú | 5:Î¨ºÌ?Í∏?6:Î∂àÌ?Í∏?| AI 7:Î∂ÑÏÑù 8:?úÌô© | 9:?ÑÎûµ | Î¶¨Ìè¨??B:Î≥¥Ïú† D:Ï∂îÏ≤ú H:?∏Í∏∞ L:Î°úÍ∑∏ | M:Î©îÎâ¥??| S:?ãÏóÖ | Q:Ï¢ÖÎ£å", tw) + "\033[0m\n")
        
        if strategy.ai_briefing and not prompt_mode:
            all_lines = [line.strip() for line in strategy.ai_briefing.split('\n') if line.strip()]
            brief_map = {"?úÏû•": "", "?ÑÎûµ": "", "?°ÏÖò": "", "Ï∂îÏ≤ú": ""}
            for l in all_lines:
                for k in brief_map.keys():
                    if f"AI[{k}]:" in l: brief_map[k] = l; break
            for k in ["?úÏû•", "?ÑÎûµ", "?°ÏÖò", "Ï∂îÏ≤ú"]:
                buf.write("\033[1;95m" + align_kr(f" {brief_map[k] if brief_map[k] else f'AI[{k}]: Î∂ÑÏÑù ?∞Ïù¥???ÜÏùå'}", tw) + "\033[0m\n")
        elif prompt_mode: 
            buf.write("\033[1;33m" + align_kr(f" >>> [{prompt_mode} MODE] ?ÖÎ†• ?ÄÍ∏?Ï§?.. (ESC Ï∑®ÏÜå)", tw) + "\033[0m\n")
            buf.write("\n" * 3)
        else: buf.write("\n" * 4) 
        
        buf.write("=" * tw + "\n")
        asset = dm.cached_asset; tot_eval = asset.get('total_asset', 0); tot_prin = asset.get('total_principal', 0)
        tot_rt = ((tot_eval - tot_prin) / tot_prin * 100) if tot_prin > 0 else 0
        tot_color = "\033[91m" if tot_rt > 0 else "\033[94m" if tot_rt < 0 else "\033[0m"
        stk_eval = asset.get('stock_eval', 0); stk_prin = asset.get('stock_principal', 0)
        stk_rt = ((stk_eval - stk_prin) / stk_prin * 100) if stk_prin > 0 else 0
        stk_color = "\033[91m" if stk_rt > 0 else "\033[94m" if stk_rt < 0 else "\033[0m"
        
        # Í∏àÏùº ?ÑÏ†Å ?òÏùµÍ∏?(Group 2 Î∞òÏòÅ)
        from src.logger import trading_log
        daily_p = trading_log.get_daily_profit()
        daily_c = "\033[91m" if daily_p > 0 else "\033[94m" if daily_p < 0 else "\033[0m"
        daily_txt = f" | Í∏àÏùº: {daily_c}{daily_p:+,}??033[0m"
        
        buf.write(align_kr(f" Asset | ?âÍ??? {tot_eval:,.0f} (?êÍ∏à: {tot_prin:,.0f}, {tot_color}{tot_rt:+.2f}%\033[0m) | ?ÑÍ∏à: {asset.get('cash', 0):,.0f} | Ï£ºÏãùÏ¥ùÏï°: {stk_eval:,.0f} ({stk_color}{stk_rt:+.2f}%\033[0m){daily_txt}", tw) + "\n")
        
        tp_cur, sl_cur, _ = strategy.get_dynamic_thresholds("BASE", dm.cached_vibe.lower())
        buf.write(align_kr(f"{'* STRAT' if strategy.is_modified('STRAT') else ' STRAT '} | Îß§ÏûÖ/?? ?µÏ†à {strategy.base_tp:+.1f}% (?ÑÏû¨ {tp_cur:+.1f}%) | ?êÏ†à {strategy.base_sl:+.1f}% (?ÑÏû¨ {sl_cur:+.1f}%)", tw) + "\n")
        buf.write(align_kr(f"{'* BEAR ' if strategy.is_modified('BEAR') else ' BEAR  '} | Î¨ºÌ?Í∏? ?∏Î¶¨Í±?\033[94m{b_cfg.get('min_loss_to_buy'):+.1f}%\033[0m | ?åÎãπ {b_cfg.get('average_down_amount'):,}??| Ï¢ÖÎ™©?úÎèÑ {b_cfg.get('max_investment_per_stock'):,}??| ?êÎèô: {auto_st} | PnL ?òÎùΩ Î∞©Ïñ¥", tw) + "\n")
        u_cfg = strategy.bull_config; u_st = "ON" if u_cfg.get("auto_mode") else "OFF"
        buf.write(align_kr(f"{'* BULL ' if strategy.is_modified('BULL') else ' BULL  '} | Î∂àÌ?Í∏? ?∏Î¶¨Í±?\033[91m+{u_cfg.get('min_profit_to_pyramid'):.1f}%\033[0m | ?åÎãπ {u_cfg.get('average_down_amount'):,}??| Ï¢ÖÎ™©?úÎèÑ {u_cfg.get('max_investment_per_stock'):,}??| ?êÎèô: {u_st} | ?òÏùµ ÎπÑÏ§ë ?ïÎ?", tw) + "\n")
        a_cfg = strategy.ai_config; ai_st = "ON" if a_cfg.get("auto_mode") else "OFF"
        buf.write(align_kr(f"{'* ALGO ' if strategy.is_modified('ALGO') else ' ALGO  '} | Ï∂îÏ≤úÎß§Îß§: ?åÎãπ {a_cfg.get('amount_per_trade'):,}??| Ï¢ÖÎ™©?úÎèÑ {a_cfg.get('max_investment_per_stock'):,}??| ?êÎèô: {ai_st} | ?åÎßà Î™®Î©ò?Ä", tw) + "\n")
        buf.write("-" * tw + "\n")

        eff_w = tw - 4; w = [max(4, int(eff_w * 0.03)), max(5, int(eff_w * 0.04)), max(15, int(eff_w * 0.15)), max(10, int(eff_w * 0.09)), max(14, int(eff_w * 0.12)), max(10, int(eff_w * 0.08)), max(8, int(eff_w * 0.07)), max(10, int(eff_w * 0.08)), max(18, int(eff_w * 0.12)), max(10, int(eff_w * 0.07)), max(10, int(eff_w * 0.10)), max(6, int(eff_w * 0.05))]
        buf.write("\033[1m" + align_kr(align_kr("NO",w[0])+align_kr("MKT",w[1])+align_kr("SYMBOL",w[2])+align_kr("CURR",w[3],'right')+align_kr("DAY",w[4],'right')+align_kr("AVG",w[5],'right')+align_kr("QTY",w[6],'right')+align_kr("EVAL",w[7],'right')+align_kr("PnL",w[8],'right')+"  "+align_kr("TP/SL",w[9],'right')+"  "+align_kr("?ÑÎûµ",w[10],'center')+align_kr("?®Ïùå",w[11],'right'), tw) + "\033[0m\n")
        
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
                buf.write(align_kr(align_kr(str(idx), w[0]) + align_kr(get_market_name(code), w[1]) + align_kr(f"[{code}] {name[:(w[2]-10)//2*2]}" + (" *" if info['spike'] else ""), w[2]) + align_kr(f"{int(p_cu):,}", w[3], 'right') + ("\033[91m" if d_v > 0 else "\033[94m" if d_v < 0 else "") + align_kr(f"{int(d_v):+,}({abs(d_r):.1f}%)" if d_v != 0 else "-", w[4], 'right') + "\033[0m" + align_kr(f"{int(p_a):,}", w[5], 'right') + align_kr(f"{int(float(h.get('hldg_qty', 0))):,}", w[6], 'right') + align_kr(f"{int(float(h.get('evlu_amt', 0))):,}", w[7], 'right') + ("\033[91m" if pnl_amt >= 0 else "\033[94m") + align_kr(pnl_txt, w[8], 'right') + "\033[0m  " + align_kr(f"{info['tp']:+.1f}/{info['sl']:+.1f}%", w[9], 'right') + "  " + ("\033[96m" if preset_label else "\033[90m") + align_kr(preset_label if preset_label else "?úÏ?", w[10], 'center') + "\033[0m" + align_kr(rem_txt, w[11], 'right'), tw) + "\n")
            if len(f_h) > max_h_display: buf.write(align_kr(f"... ??{len(f_h) - max_h_display}Ï¢ÖÎ™© ?ùÎûµ??, tw, 'center') + "\n")
        
        buf.write("-" * tw + "\n"); themes = get_cached_themes()
        if themes: buf.write("\033[93m" + align_kr(" ?î• ?∏Í∏∞?åÎßà: " + " | ".join([f"{t['name']}({t['count']})" for t in themes[:8]]), tw) + "\033[0m\n")
        else: buf.write("\n")
        
        y_recs = strategy.yesterday_recs_processed
        if y_recs:
            # ÏµúÎ? 10Í∞? ??Ï§ÑÏóê 5Í∞úÏî© ?úÏãú
            recs_to_show = y_recs[:10]
            for i in range(0, len(recs_to_show), 5):
                line_parts = []
                chunk = recs_to_show[i:i+5]
                # Í∞???™©??ÏµúÎ? ?àÎπÑ Í≥ÑÏÇ∞ (tw - ?¨Î∞±) / 5
                item_w = (tw - 10) // 5
                for r in chunk:
                    color = "\033[91m" if r['change'] >= 0 else "\033[94m"
                    name = r['name']
                    # [ÏΩîÎìú]?¥Î¶Ñ(Î≥Ä??) ?ïÏãù?ºÎ°ú Íµ¨ÏÑ± ???àÎπÑ Ï¥àÍ≥º ???¥Î¶Ñ Ï∂ïÏïΩ
                    tag = f"[{r['code']}]"
                    chg_tag = f"({color}{r['change']:+0.2f}%\033[0m)"
                    base_w = get_visual_width(tag) + 8 # Î≥Ä?ôÏÑ± ?úÍ∑∏ ?àÎπÑ ??8
                    
                    while get_visual_width(name) + base_w > item_w and len(name) > 2:
                        name = name[:-1]
                    
                    if len(name) < len(r['name']): name += ".."
                    line_parts.append(f"{tag}{name}{chg_tag}")
                
                label = " ?ìÖ ?¥Ï†ú ?±Í≥º: " if i == 0 else " " * 14
                buf.write(align_kr(f"\033[90m{label}{' | '.join(line_parts)}", tw) + "\033[0m\n")
        else:
            buf.write(align_kr("\033[90m ?ìÖ ?¥Ï†ú Ï∂îÏ≤ú ?¥Î†•???ÜÏäµ?àÎã§.", tw) + "\033[0m\n")

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

        buf.write(f"\033[1;93m{align_kr('?î• HOT SEARCH', col_w)}\033[0m ??\033[1;96m{align_kr('?ìä VOLUME TOP', col_w)}\033[0m ??\033[1;92m{align_kr(f'??AI Ï∂îÏ≤ú {'\033[91m' if strategy.auto_ai_trade else '\033[93m'}[{'AUTO' if strategy.auto_ai_trade else 'MANUAL'}]\033[1;92m', col_w)}\033[0m\n")
        buf.write("?Ä" * col_w + "?Ä?º‚?" + "?Ä" * col_w + "?Ä?º‚?" + "?Ä" * col_w + "\n")
        for i in range(ranking_items_count): buf.write(f"{fmt_r(hot_list[i] if i < len(hot_list) else None)} ??{fmt_r(vol_list[i] if i < len(vol_list) else None)} ??{fmt_ai(ai_recs[i] if i < len(ai_recs) else None)}\n")
    
    rem = th - buf.getvalue().count('\n')
    if rem > 0: buf.write(f"\033[K {dm.status_msg if dm.status_msg and (time.time()-dm.status_time<60) else ''}\n"); rem -= 1
    if rem > 0: buf.write(f"\033[K {dm.last_log_msg if dm.last_log_msg and (time.time()-dm.last_log_time<60) else ''}\n"); rem -= 1
    if rem > 0:
        logs = dm.trading_logs; skip = len(logs) - (rem - 1)
        if skip > 0: buf.write(f"\033[K \033[90m... ??{skip}Í±¥Ïùò Î°úÍ∑∏ ?ùÎûµ??033[0m\n"); logs = logs[-(rem-1):]; rem -= 1
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
    buf.write("\033[1;93m 1. ?•Ï§ë ?úÍ∞Ñ ?òÏù¥Ï¶?Market Phase) ?ÑÎûµ\033[0m\n")
    buf.write("  - \033[91m?î• Phase 1 (09:00~10:00) [Í≥µÍ≤©]\033[0m: Î≥Ä?ôÏÑ± Í∑πÎ???Íµ¨Í∞Ñ. ?µÏ†à ?ÅÌñ•(+2%), ?êÏ†à ?ÑÌôî(-1%).\n")
    buf.write("  - \033[92m?ßò Phase 2 (10:00~14:30) [Í¥ÄÎ¶?\033[0m: ?°Î≥¥ ?®Ï†ï Íµ¨Í∞Ñ. ?µÏ†à/?êÏ†à Í∞ïÌôî(-1%)Î°?Î¶¨Ïä§???Ä?¥Ìä∏?òÍ≤å Í¥ÄÎ¶?\n")
    buf.write("  - \033[93m?í∞ Phase 3 (14:30~15:10) [?ïÏ†ï]\033[0m: ?πÏùº ?òÏùµ ?ïÏ†ï. ?òÏùµÍ∂?Ï¢ÖÎ™© 50% Î∂ÑÌï† Îß§ÎèÑ Î∞??îÎüâ Î≥∏Ï†Ñ ?§ÌÉë.\n")
    buf.write("  - \033[96m?õí Phase 4 (15:10~15:20) [Ï§ÄÎπ?\033[0m: ?µÏùº ?†ÎßùÏ£??†Ï∑®Îß? ?úÏû• ?àÏã¨(Bull/Neutral) ?úÏóêÎß??†Í∑ú Îß§Ïàò.\n\n")
    buf.write("\033[1;93m 2. AI ?ôÏ†Å Î¶¨Ïä§??Í¥ÄÎ¶?(Time-Stop)\033[0m\n")
    buf.write("  - \033[1m?†Ìö® ?úÍ∞Ñ(Lifetime)\033[0m: ?ÑÎûµ ?†Îãπ ??AIÍ∞Ä Ï¢ÖÎ™©??Î™®Î©ò?Ä ?òÎ™Ö???àÏ∏°?òÏó¨ ?∞Îìú?ºÏù∏???§Ï†ï.\n")
    buf.write("  - \033[1m?Ä???§ÌÉë\033[0m: ?∞Îìú?ºÏù∏(REM:EXP) Í≤ΩÍ≥º ?? ?µÏ†à?†ÏùÑ ?ÑÏû¨ ?òÏùµ???àÎ∞ò?ºÎ°ú ??∂∞ ?òÏùµ??Î≥¥Ï°¥.\n")
    buf.write("  - \033[1m?ôÏ†Å Î≥¥Ï†ï\033[0m: ?úÏû• Vibe(Bull/Bear)?Ä Ï¢ÖÎ™© Î≥Ä?ôÏÑ±??Î∂ÑÏÑù?òÏó¨ TP/SL???§ÏãúÍ∞ÑÏúºÎ°?ÎØ∏ÏÑ∏ Ï°∞Ï†ï.\n\n")
    buf.write("\033[1;93m 3. ?µÏã¨ ?¥ÏòÅ ??033[0m\n")
    buf.write("  - \033[1m[3:?êÎèô]\033[0m: Î≤àÌò∏ ?ÜÏù¥ 'TP SL' ?ÖÎ†• ??Î≥¥Ïú† ??Ï¢ÖÎ™©??Í∏∞Î≥∏ ?µÏ†à/?êÏ†à???ºÍ¥Ñ Î≥ÄÍ≤ΩÌï©?àÎã§.\n")
    buf.write("  - \033[1m[8:?úÌô©]\033[0m: AIÍ∞Ä ?úÏïà?òÎäî ?òÏπò???ÑÏû¨ VibeÍ∞Ä Î∞òÏòÅ??ÏµúÏ¢Ö Î™©ÌëúÍ∞íÏù¥Î©??úÏä§?úÏù¥ ??Ç∞ ?ÅÏö©?©Îãà??\n")
    buf.write("  - \033[1m[9:?ÑÎûµ]\033[0m: ?îÌÑ∞Îß??ÖÎ†• ??AIÍ∞Ä ?¥Îãπ Ï¢ÖÎ™©??Í∞Ä???ÅÌï©??KIS ?ÑÎ¶¨???ÑÎûµ???êÎèô Îß§Ïπ≠?©Îãà??\n\n")
    buf.write("-" * tw + "\n" + align_kr(" ?ÑÎ¨¥ ?§ÎÇò ?ÑÎ•¥Î©?Î©îÏù∏ ?îÎ©¥?ºÎ°ú ?åÏïÑÍ∞ëÎãà?? ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue()); sys.stdout.flush()
    while not sys.stdin.read(1): time.sleep(0.1)
    buf.close()

def draw_trading_logs(strategy, dm, tw, th):
    """?∏Î†à?¥Îî© Î°úÍ∑∏ ?ÅÏÑ∏ ?îÎ©¥ (Group 2 ?†ÏÑ§)"""
    import io
    from src.logger import trading_log
    buf = io.StringIO(); buf.write("\033[H\033[2J")
    buf.write("\033[44;37m" + align_kr(" [TRADING HISTORY & SYSTEM LOGS] ", tw, 'center') + "\033[0m\n\n")
    
    # 1. TRADE Î°úÍ∑∏ ?πÏÖò
    buf.write("\033[1;93m [ÏµúÍ∑º Í±∞Îûò ?¥Ïó≠ (TRADE)]\033[0m\n")
    trades = trading_log.data.get("trades", [])
    if not trades:
        buf.write("  ÏµúÍ∑º Í±∞Îûò ?¥Ïó≠???ÜÏäµ?àÎã§.\n")
    else:
        header = f"{align_kr('?úÍ∞Ñ', 20)} | {align_kr('Íµ¨Î∂Ñ', 10)} | {align_kr('Ï¢ÖÎ™©Î™?, 14)} | {align_kr('Ï≤¥Í≤∞Í∞Ä', 10)} | {align_kr('?òÎüâ', 6)} | {align_kr('?òÏùµÍ∏?, 12)} | Î©îÎ™®"
        buf.write("\033[1m" + header + "\033[0m\n" + "-" * tw + "\n")
        # ?îÎ©¥ ?íÏù¥ Í≥†Î†§?òÏó¨ ÏµúÎ? 15Í∞??úÏãú
        for t in trades[:15]:
            t_type = t.get('type', 'Unknown')
            t_color = "\033[91m" if "Îß§Ïàò" in t_type else "\033[94m" if "Îß§ÎèÑ" in t_type or "?µÏ†à" in t_type or "?êÏ†à" in t_type else ""
            p_val = t.get('profit', 0)
            p_color = "\033[91m" if p_val > 0 else "\033[94m" if p_val < 0 else ""
            p_str = f"{p_color}{int(p_val):+,}??033[0m" if p_val != 0 else "-"
            
            line = f"{t.get('time', '-')} | {t_color}{align_kr(t_type, 10)}\033[0m | {align_kr(t.get('name','-'), 14)} | {align_kr(f'{int(t.get('price',0)):,}', 10, 'right')} | {align_kr(str(t.get('qty',0)), 6, 'right')} | {align_kr(p_str, 12, 'right')} | {t.get('memo', '')}"
            buf.write(line + "\n")
            
    buf.write("\n" + "=" * tw + "\n\n")
    
    # 2. CONFIG Î°úÍ∑∏ ?πÏÖò
    buf.write("\033[1;96m [?úÏä§???§Ï†ï Î∞??ÑÎûµ Î≥ÄÍ≤?(CONFIG)]\033[0m\n")
    configs = trading_log.data.get("configs", [])
    if not configs:
        buf.write("  Î≥ÄÍ≤??¥Î†•???ÜÏäµ?àÎã§.\n")
    else:
        for c in configs[:10]: # ÏµúÍ∑º 10Í∞?
            buf.write(f"  [{c.get('time', '-')}] {c.get('content', '')}\n")
            
    buf.write("\n" + "-" * tw + "\n" + align_kr(" ?ÑÎ¨¥ ?§ÎÇò ?ÑÎ•¥Î©?Î©îÏù∏ ?îÎ©¥?ºÎ°ú ?åÏïÑÍ∞ëÎãà?? ", tw, 'center') + "\n")
    sys.stdout.write(buf.getvalue()); sys.stdout.flush()
    
    # ?ÑÎ¨¥ ?§ÎÇò ?ÖÎ†• ?ÄÍ∏?
    while not get_key_immediate(): time.sleep(0.1)
    buf.close()
