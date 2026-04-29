import json
from datetime import datetime

LOG_FILE = 'trading_logs.json'
STATE_FILE = 'trading_state.json'

def final_backfill():
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 1. Load data
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
    except Exception as e:
        print(f"Error: {e}")
        return

    # 2. Extract today's AI trades for buy_reasons
    existing_reasons = {r['time'] + r['code'] for r in log_data.get('buy_reasons', [])}
    new_reasons = []
    for t in log_data.get('trades', []):
        if t['time'].startswith(today) and t['type'] in ["AI자율매수", "P4종가매수"]:
            if (t['time'] + t['code']) not in existing_reasons:
                new_reasons.append({
                    "time": t['time'], "code": t['code'], "name": t['name'],
                    "reason": t.get('memo', ''), "model_id": t.get('model_id', '')
                })
    if new_reasons:
        log_data['buy_reasons'] = sorted(log_data.get('buy_reasons', []) + new_reasons, key=lambda x: x['time'], reverse=True)

    # 3. Extract today's replacements for replacement_logs
    existing_repl = {r['time'] + r['out_code'] for r in state_data.get('replacement_logs', [])}
    trades = sorted([t for t in log_data.get('trades', []) if t['time'].startswith(today)], key=lambda x: x['time'])
    new_repl = []
    for i, t in enumerate(trades):
        if t['type'] == "교체매도":
            for next_t in trades[i+1:]:
                if next_t['type'] == "AI자율매수":
                    dt = (datetime.strptime(next_t['time'], '%Y-%m-%d %H:%M:%S') - 
                          datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S')).total_seconds()
                    if 0 <= dt <= 600:
                        if (t['time'] + t['code']) not in existing_repl:
                            new_repl.append({
                                "time": t['time'], "out_code": t['code'], "out_name": t['name'],
                                "in_code": next_t['code'], "in_name": next_t['name'],
                                "reason": f"AI 교체 판단 (후보: {next_t['name']})"
                            })
                        break
    if new_repl:
        state_data['replacement_logs'] = sorted(state_data.get('replacement_logs', []) + new_repl, key=lambda x: x['time'], reverse=True)

    # 4. Save
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, indent=4, ensure_ascii=False)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state_data, f, indent=4, ensure_ascii=False)
    
    print(f"Final Backfill: {len(new_reasons)} reasons, {len(new_repl)} replacements added.")

if __name__ == "__main__":
    final_backfill()
