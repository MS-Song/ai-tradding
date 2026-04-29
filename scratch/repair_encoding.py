import json

STATE_FILE = 'trading_state.json'

def repair_encoding():
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # 오늘 날짜 데이터만 찾아서 한글 수정
        for log in data.get('replacement_logs', []):
            if log['time'].startswith('2026-04-29'):
                if '005930' in log.get('out_code', ''): log['out_name'] = "삼성전자"
                if '005930' in log.get('in_code', ''): log['in_name'] = "삼성전자"
                if '003230' in log.get('in_code', ''): log['in_name'] = "삼양식품"
                if '060980' in log.get('out_code', ''): log['out_name'] = "HL만도"
                if "AI 교체" in log['reason'] or "?" in log['reason']:
                    log['reason'] = "AI 종목 교체 판단 (포트폴리오 최적화)"
        
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print("Encoding repair completed successfully.")
    except Exception as e:
        print(f"Repair failed: {e}")

if __name__ == "__main__":
    repair_encoding()
