# Advanced Strategy & UI Clarification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 고급 전략 설정 편의성 증대, 시장 상황(VIBE)과 시간대별 전략(PHASE) 표시 명확화, 매뉴얼 최적화.

**Architecture:** `StrategyManager`에서 프리셋 자동 할당 로직 구현, `Renderer`에서 UI 표시 항목 개선, `Manual` 데이터 정리.

**Tech Stack:** Python, TUI (curses/custom renderer)

---

### Task 1: StrategyManager - 일괄 AI 전략 할당 로직

**Files:**
- Modify: `src/strategy.py`
- Test: `tests/unit_test_logic.py`

- [ ] **Step 1: `apply_ai_strategy_to_all` 함수 구현 (src/strategy.py)**

```python
def apply_ai_strategy_to_all(self, data_manager):
    """보유한 모든 종목에 AI 최적 전략 자동 할당"""
    portfolio = data_manager.get_portfolio()
    for code in portfolio:
        strategy = self.ai_engine.suggest_strategy(code)
        data_manager.update_preset_strategy(code, strategy)
```

- [ ] **Step 2: 테스트 코드 작성 및 검증**

```python
def test_apply_ai_strategy_to_all():
    strategy_mgr = StrategyManager()
    # Mock data_manager...
    strategy_mgr.apply_ai_strategy_to_all(mock_data_manager)
    # Assert strategies updated...
```

- [ ] **Step 3: 커밋**

```bash
git add src/strategy.py tests/unit_test_logic.py
git commit -m "feat: add apply_ai_strategy_to_all"
```

---

### Task 2: Renderer - VIBE & PHASE 표시 변경

**Files:**
- Modify: `src/ui/renderer.py`

- [ ] **Step 1: UI 렌더링 로직 수정 (src/ui/renderer.py)**

```python
# 기존
# status_line = f"VIBE: {vibe} | PHASE: {phase}"

# 변경
status_line = f"VIBE: {vibe_code} ({vibe_desc}) [AI: {ai_status}] | PHASE: {phase_code} ({phase_desc})"
```

- [ ] **Step 2: 변경 사항 검증 (터미널 렌더링 확인)**

- [ ] **Step 3: 커밋**

```bash
git add src/ui/renderer.py
git commit -m "ui: update vibe and phase display"
```

---

### Task 3: Manual - 매뉴얼 내용 최적화

**Files:**
- Modify: `docs/USER_MANUAL.md`

- [ ] **Step 1: 매뉴얼 정리**
    - 기술적 동기화 내용 삭제
    - 커맨드 명령어, 발동 조건, 자동 매매 규칙 중심 재구성.

- [ ] **Step 2: 커밋**

```bash
git add docs/USER_MANUAL.md
git commit -m "docs: optimize user manual"
```
