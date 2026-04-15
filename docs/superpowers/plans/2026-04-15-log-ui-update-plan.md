# Log UI Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그 UI를 시간 역순으로 정렬하고, 로그 항목에 종목번호와 종목명을 함께 표시하도록 개선합니다.

**Architecture:** `src/ui/renderer.py`의 `draw_trading_logs` 함수 내에서 `trades` 리스트를 역순 정렬하고, 종목번호에 대응하는 종목명을 매핑하여 출력하도록 수정합니다.

**Tech Stack:** Python, TUI

---

### Task 1: Log UI 수정

**Files:**
- Modify: `src/ui/renderer.py`
- Test: 수동 실행 확인

- [ ] **Step 1: 시간 역순 정렬 및 종목명 표시 로직 구현**

```python
# src/ui/renderer.py의 draw_trading_logs 함수 내부 수정
# trades = trading_log.data.get("trades", [])
# 를 아래와 같이 수정
trades = list(reversed(trading_log.data.get("trades", [])))

# 루프 내부에서 종목명 표시
# 기존 line = f"{t.get('time', '-')} | {t_color}{align_kr(t_type, 10)}\033[0m | {align_kr(t.get('name','-'), 14)}..."
# name은 trading_log에 이미 포함되어 있을 가능성이 높음. 
# 만약 없다면 data_manager 등을 통해 조회하거나, 기존 데이터를 확인하여 매핑.
```

- [ ] **Step 2: 커밋**

```bash
git add src/ui/renderer.py
git commit -m "ui: reverse log order and show stock names"
```
