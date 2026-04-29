import json
with open('trading_logs.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
print(f"Keys: {list(data.keys())}")
for k in data:
    print(f"{k}: {len(data[k])}")
