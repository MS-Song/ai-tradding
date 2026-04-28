
import json
import os
from datetime import datetime
import io

class MockDM:
    def __init__(self):
        self.cached_holdings = []
        self.ma_20_cache = {}
        self.cached_prices = {}

def get_visual_width(text):
    width = 0
    for char in str(text):
        if ord(char) > 0x7F:
            width += 2
        else:
            width += 1
    return width

def align_kr(text, width, align='left'):
    text = str(text)
    curr_w = get_visual_width(text)
    if curr_w >= width:
        return text
    
    pad = width - curr_w
    if align == 'left':
        return text + " " * pad
    elif align == 'right':
        return " " * pad + text
    else:
        left_pad = pad // 2
        right_pad = pad - left_pad
        return " " * left_pad + text + " " * right_pad

def smart_align(text, width):
    if get_visual_width(text) <= width:
        return align_kr(text, width)
    t = str(text)
    while get_visual_width(t + "..") > width and len(t) > 0:
        t = t[:-1]
    return align_kr(t + "..", width)

def test_full_p_report():
    log_file = "trading_logs.json"
    with open(log_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    today = "2026-04-28"
    buy_trades = []; sell_trades = []; sell_types = ["익절", "손절", "청산", "확정", "매도", "종료"]
    
    for t in data.get("trades", []):
        if not t["time"].startswith(today): continue
        t_type = t.get("type", "")
        if "매수" in t_type: buy_trades.append(t)
        elif any(x in t_type for x in sell_types): sell_trades.append(t)
    
    dm = MockDM()
    
    buy_summary = {}
    for t in buy_trades:
        c = t['code']; q = int(t['qty']); p = float(t['price'])
        if c not in buy_summary:
            buy_summary[c] = {"name": t['name'], "code": c, "total_amt": 0, "total_qty": 0, "type": t['type'], "acc_avg": 0}
        buy_summary[c]["total_amt"] += p * q
        buy_summary[c]["total_qty"] += q
        buy_summary[c]["avg_price"] = buy_summary[c]["total_amt"] / buy_summary[c]["total_qty"]

    sell_summary = {}
    for t in sell_trades:
        c = t['code']; q = int(t['qty']); p = float(t['price']); pr = float(t.get('profit', 0))
        if c not in sell_summary: 
            sell_summary[c] = {"name": t['name'], "code": c, "total_amt": 0, "total_qty": 0, "total_pnl": 0, "type": t['type']}
        sell_summary[c]["total_amt"] += p * q
        sell_summary[c]["total_qty"] += q
        sell_summary[c]["total_pnl"] += pr
        sell_summary[c]["avg_price"] = sell_summary[c]["total_amt"] / sell_summary[c]["total_qty"]

    # Derived logic
    for c, b_info in buy_summary.items():
        if b_info["acc_avg"] == 0 and c in sell_summary:
            s_info = sell_summary[c]
            if s_info["total_qty"] > 0:
                derived_buy_p = s_info["avg_price"] - (s_info["total_pnl"] / s_info["total_qty"])
                b_info["avg_price"] = derived_buy_p

    buy_list = list(buy_summary.values())
    sell_list = list(sell_summary.values())
    max_rows = max(len(buy_list), len(sell_list))
    
    print(f"Max Rows: {max_rows}")
    print(f"Buy List size: {len(buy_list)}")
    print(f"Sell List size: {len(sell_list)}")
    
    print("\n[TABLE CONTENT]")
    for i in range(max_rows):
        b_name = buy_list[i]['name'] if i < len(buy_list) else "-"
        s_name = sell_list[i]['name'] if i < len(sell_list) else "-"
        s_pnl = f"{int(sell_list[i]['total_pnl']):,}" if i < len(sell_list) else "-"
        s_type = sell_list[i]['type'] if i < len(sell_list) else "-"
        print(f"Row {i:2}: BUY[{b_name:12}] | SELL[{s_name:12}] PNL:{s_pnl:>10} TYPE:{s_type}")

if __name__ == "__main__":
    test_full_p_report()
