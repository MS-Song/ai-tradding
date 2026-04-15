# Log UI Layout & Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 메인 화면 및 로그 화면의 UI 가독성과 사용성을 개선합니다.

**Architecture:** `renderer.py`의 TUI 렌더링 로직을 수정하여 정렬 순서와 데이터 높이 비율을 동적으로 계산합니다.

**Tech Stack:** Python, TUI

---

### Task 1: 메인 화면 로그 순서 수정

**Files:**
- Modify: `src/ui/renderer.py`

- [ ] **Step 1: 메인 루프 로그 역순 출력 구현**

```python
# src/ui/renderer.py의 draw_tui 함수 하단부
# logs = dm.trading_logs 수정
logs = list(reversed(dm.trading_logs))
# 이후 loop에서 역순으로 순회
for tl in logs:
    if rem <= 0: break
    buf.write(f"\033[K {tl}\n"); rem -= 1
```

- [ ] **Step 2: 커밋**

```bash
git add src/ui/renderer.py
git commit -m "ui: reverse log order on main screen"
```

---

### Task 2: 로그 화면(L) UI 동적 레이아웃 수정

**Files:**
- Modify: `src/ui/renderer.py`

- [ ] **Step 1: draw_trading_logs 내 높이 계산 로직 추가**

```python
# draw_trading_logs 내부
trade_count = len(trading_log.data.get("trades", []))
trade_max_height = int(th * 0.7)
trade_rows = min(trade_count, trade_max_height)
# 로그 화면 렌더링 시 trade_rows를 기준으로 슬라이싱 및 출력
```

- [ ] **Step 2: 커밋**

```bash
git add src/ui/renderer.py
git commit -m "ui: implement dynamic layout for L-log screen"
```
