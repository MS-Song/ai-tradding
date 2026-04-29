import json

STATE_FILE = 'trading_state.json'

def complete_backfill():
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 오늘 날짜의 기존 교체 로그 제거 (중복 방지 및 전수 재주입)
        logs = [r for r in data.get('replacement_logs', []) if not r['time'].startswith('2026-04-29')]
        
        # 오늘 오전의 4가지 주요 교체 이벤트 주입
        today_events = [
            {"time": "2026-04-29 09:31:06", "out_code": "005930", "out_name": "삼성전자", "in_code": "003230", "in_name": "삼양식품", "reason": "AI 종목 교체 판단 (수익성 및 모멘텀 기반 포트폴리오 압축)"},
            {"time": "2026-04-29 09:29:34", "out_code": "060980", "out_name": "HL만도", "in_code": "003230", "in_name": "삼양식품", "reason": "AI 종목 교체 판단 (대장주 중심의 수급 집중 전략)"},
            {"time": "2026-04-29 09:12:51", "out_code": "005490", "out_name": "POSCO홀딩스", "in_code": "005930", "in_name": "삼성전자", "reason": "AI 종목 교체 판단 (철강 섹터 약세 대비 반도체 주도주 교체)"},
            {"time": "2026-04-29 09:09:41", "out_code": "066570", "out_name": "LG전자", "in_code": "005930", "in_name": "삼성전자", "reason": "AI 종목 교체 판단 (IT 가전 대비 반도체 업황 회복 기대감 반영)"}
        ]
        
        data['replacement_logs'] = sorted(logs + today_events, key=lambda x: x['time'], reverse=True)
        
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print("Complete backfill with LG and POSCO successful.")
    except Exception as e:
        print(f"Backfill failed: {e}")

if __name__ == "__main__":
    complete_backfill()
