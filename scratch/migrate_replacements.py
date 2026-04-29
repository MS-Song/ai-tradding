import json
from datetime import datetime

LOG_FILE = 'trading_logs.json'
STATE_FILE = 'trading_state.json'

def migrate_replacements():
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
    except Exception as e:
        print(f"Error loading files: {e}")
        return

    today = datetime.now().strftime('%Y-%m-%d')
    trades = [t for t in log_data.get('trades', []) if t['time'].startswith(today)]
    # Time desc 순이므로 뒤집어서 순차 분석
    trades = sorted(trades, key=lambda x: x['time'])

    new_replacements = []
    i = 0
    while i < len(trades):
        t = trades[i]
        if t['type'] == "교체매도":
            # 이 매도 이후 가장 가까운 AI자율매수 탐색 (최대 10분 이내)
            match_found = False
            for j in range(i + 1, len(trades)):
                next_t = trades[j]
                if next_t['type'] == "AI자율매수":
                    dt = (datetime.strptime(next_t['time'], '%Y-%m-%d %H:%M:%S') - 
                          datetime.strptime(t['time'], '%Y-%m-%d %H:%M:%S')).total_seconds()
                    if 0 <= dt <= 600: # 10분 이내
                        new_replacements.append({
                            "time": t['time'],
                            "out_code": t['code'],
                            "out_name": t['name'],
                            "in_code": next_t['code'],
                            "in_name": next_t['name'],
                            "reason": f"AI 교체 판단 (후보: {next_t['name']})"
                        })
                        match_found = True
                        break
            if not match_found:
                # 짝을 못찾은 경우라도 매도 기록은 남김
                new_replacements.append({
                    "time": t['time'],
                    "out_code": t['code'],
                    "out_name": t['name'],
                    "in_code": "-",
                    "in_name": "대기중/미체결",
                    "reason": "AI 교체 매도 집행 (신규 진입 대기)"
                })
        i += 1

    if new_replacements:
        # 중복 제거 (시간+종목코드 기준)
        existing = {r['time'] + r['out_code'] for r in state_data.get('replacement_logs', [])}
        unique_new = [r for r in new_replacements if (r['time'] + r['out_code']) not in existing]
        
        if unique_new:
            if 'replacement_logs' not in state_data: state_data['replacement_logs'] = []
            state_data['replacement_logs'] = sorted(state_data['replacement_logs'] + unique_new, 
                                                   key=lambda x: x['time'], reverse=True)
            
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=4, ensure_ascii=False)
            print(f"Successfully migrated {len(unique_new)} replacement logs.")
        else:
            print("No new replacements to migrate.")
    else:
        print("No replacement trades found in today's logs.")

if __name__ == "__main__":
    migrate_replacements()
