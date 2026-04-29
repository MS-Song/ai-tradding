
import json
import os
from datetime import datetime

def migrate():
    logs_path = "trading_logs.json"
    if not os.path.exists(logs_path):
        print("trading_logs.json not found")
        return

    with open(logs_path, "r", encoding="utf-8") as f:
        logs = json.load(f)

    # 누락된 매도 데이터 (추정치)
    missing_sells = [
        {
            "type": "교체매도",
            "time": "2026-04-29 09:12:51",
            "code": "005490",
            "name": "POSCO홀딩스",
            "price": 470000.0,
            "qty": 1,
            "memo": "종목 교체 (마이그레이션 복구)",
            "profit": 0.0,
            "model_id": "AI"
        },
        {
            "type": "교체매도",
            "time": "2026-04-29 09:09:41",
            "code": "066570",
            "name": "LG전자",
            "price": 140000.0,
            "qty": 3,
            "memo": "종목 교체 (마이그레이션 복구)",
            "profit": 0.0,
            "model_id": "AI"
        },
        {
            "type": "교체매도",
            "time": "2026-04-29 09:04:57",
            "code": "009900",
            "name": "명신산업",
            "price": 13450.0,
            "qty": 37,
            "memo": "종목 교체 (마이그레이션 복구)",
            "profit": 0.0,
            "model_id": "AI"
        }
    ]

    added = 0
    for entry in missing_sells:
        # 중복 확인
        if not any(t['code'] == entry['code'] and t['time'] == entry['time'] for t in logs["trades"]):
            logs["trades"].append(entry)
            added += 1

    if added > 0:
        # 시간순 정렬 (내림차순)
        logs["trades"].sort(key=lambda x: x['time'], reverse=True)
        with open(logs_path, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=4, ensure_ascii=False)
        print(f"Successfully added {added} missing trades.")
    else:
        print("All trades already exist or nothing to add.")

if __name__ == "__main__":
    migrate()
