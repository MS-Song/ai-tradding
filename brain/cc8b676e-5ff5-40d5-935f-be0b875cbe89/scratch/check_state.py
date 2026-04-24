import json
try:
    with open('trading_state.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        holdings = data.get('cached_holdings', [])
        strategies = data.get('preset_strategies', {})
        print(f"Holdings: {len(holdings)}")
        for h in holdings:
            print(f" - {h.get('pdno')} : {h.get('prdt_name')}")
        print(f"Strategies (Tracked): {len(strategies)}")
except Exception as e:
    print(f"Error: {e}")
