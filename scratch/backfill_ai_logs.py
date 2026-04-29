import json
from datetime import datetime

LOG_FILE = 'trading_logs.json'
STATE_FILE = 'trading_state.json'

with open(LOG_FILE, 'r', encoding='utf-8') as f:
    data = json.load(f)

today = datetime.now().strftime('%Y-%m-%d')
print(f"Today: {today}")

existing_reasons = {r['time'] + r['code'] for r in data.get('buy_reasons', [])}
print(f"Existing reasons count: {len(existing_reasons)}")

new_reasons = []
for t in data.get('trades', []):
    # Debug: print trade time and type
    if t['time'].startswith(today):
        print(f"Found today trade: {t['time']} | {t['type']} | {t['name']}")
        if t['type'] in ["AI자율매수", "P4종가매수"]:
            key = t['time'] + t['code']
            if key not in existing_reasons:
                print(f"Adding new reason for {t['name']}")
                new_reasons.append({
                    "time": t['time'],
                    "code": t['code'],
                    "name": t['name'],
                    "reason": t.get('memo', ''),
                    "model_id": t.get('model_id', '')
                })

if new_reasons:
    if 'buy_reasons' not in data: data['buy_reasons'] = []
    data['buy_reasons'] = sorted(data['buy_reasons'] + new_reasons, key=lambda x: x['time'], reverse=True)
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print(f"Added {len(new_reasons)} buy reasons for today.")

# Replacement logic...
with open(STATE_FILE, 'r', encoding='utf-8') as f:
    state = json.load(f)

existing_replacements = {r['time'] + r['out_code'] for r in state.get('replacement_logs', [])}
new_replacements = []

trades = sorted(data.get('trades', []), key=lambda x: x['time'])
for i in range(len(trades) - 1):
    t1 = trades[i]
    t2 = trades[i+1]
    if t1['time'].startswith(today) and t1['type'] == "교체매도" and t2['type'] == "AI자율매수":
        dt = (datetime.strptime(t2['time'], '%Y-%m-%d %H:%M:%S') - datetime.strptime(t1['time'], '%Y-%m-%d %H:%M:%S')).total_seconds()
        if 0 <= dt <= 10:
            key = t1['time'] + t1['code']
            if key not in existing_replacements:
                new_replacements.append({
                    "time": t1['time'],
                    "out_code": t1['code'],
                    "out_name": t1['name'],
                    "in_code": t2['code'],
                    "in_name": t2['name'],
                    "reason": f"AI 교체 판단 (후보: {t2['name']})"
                })

if new_replacements:
    if 'replacement_logs' not in state: state['replacement_logs'] = []
    state['replacement_logs'] = sorted(state['replacement_logs'] + new_replacements, key=lambda x: x['time'], reverse=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=4, ensure_ascii=False)
    print(f"Added {len(new_replacements)} replacement logs for today.")
