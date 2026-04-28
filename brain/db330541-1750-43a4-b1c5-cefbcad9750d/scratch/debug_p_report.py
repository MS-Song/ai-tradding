
import json
import os
from datetime import datetime

class MockDM:
    def __init__(self):
        self.cached_holdings = []
        self.ma_20_cache = {}

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

def test_performance_report():
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
    
    print(f"Buy Trades found: {len(buy_trades)}")
    print(f"Sell Trades found: {len(sell_trades)}")
    
    sell_summary = {}
    for t in sell_trades:
        c = t['code']; q = int(t['qty']); p = float(t['price']); pr = float(t.get('profit', 0))
        if c not in sell_summary: 
            sell_summary[c] = {"name": t['name'], "code": c, "total_amt": 0, "total_qty": 0, "total_pnl": 0, "type": t['type']}
        sell_summary[c]["total_amt"] += p * q
        sell_summary[c]["total_qty"] += q
        sell_summary[c]["total_pnl"] += pr
        sell_summary[c]["avg_price"] = sell_summary[c]["total_amt"] / sell_summary[c]["total_qty"]

    print("\nSell Summary:")
    for c, info in sell_summary.items():
        print(f"Code: {c}, Name: {info['name']}, PnL: {info['total_pnl']}, Type: {info['type']}")

    # Hall of Shame Check
    stock_stats = {}
    for t in data.get("trades", []):
        code = t.get("code")
        if not code: continue
        if code not in stock_stats:
            stock_stats[code] = {"name": t.get("name", "Unknown"), "total_profit": 0.0}
        
        t_type = t.get("type", "")
        if any(x in t_type for x in ["익절", "손절", "청산", "확정", "매도", "종료"]):
            profit = t.get("profit", 0.0)
            stock_stats[code]["total_profit"] += profit
    
    sorted_stats = sorted(stock_stats.items(), key=lambda x: x[1]["total_profit"], reverse=False)
    losses = [s for s in sorted_stats if s[1]["total_profit"] < 0]
    
    print("\nHall of Shame (Top Losses):")
    for code, info in losses[:5]:
        print(f"Code: {code}, Name: {info['name']}, Total Profit: {info['total_profit']}")

if __name__ == "__main__":
    test_performance_report()
