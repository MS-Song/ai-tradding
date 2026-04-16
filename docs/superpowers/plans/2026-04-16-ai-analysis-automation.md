# AI 매매 시작 제어 및 전략 자동 갱신 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로그램 시작 시 시황 분석을 선행하고, 주기적인 분석 및 전략 만료 시 AI 기반 전략 갱신을 통해 매매 안정성을 확보합니다.

**Architecture:** 
1. `VibeStrategy`에 상태 관리 플래그와 주기적 분석 로직 추가.
2. 매매 진입 조건에 `is_ready` 플래그 체크 로직 추가.
3. 전략 만료 시 `auto_assign_preset` 재호출 연동.

**Tech Stack:** Python (KIS API, Gemini API, JSON 상태 관리)

---

### Task 1: VibeStrategy 상태 관리 및 주기적 분석 기능 구현

**Files:**
- Modify: `src/strategy.py`

- [ ] **Step 1: VibeStrategy 클래스 필드 추가**
```python
# src/strategy.py 내 VibeStrategy 클래스 __init__
self.is_ready = False  # AI 모드 시 False, 아니면 True
self.last_market_analysis_time = None
self.analysis_interval = 20  # 기본 20분
```

- [ ] **Step 2: perform_full_market_analysis 성공 시 is_ready 전환 및 재시도 로직 추가**
```python
def perform_full_market_analysis(self, retry=True):
    try:
        # 기존 8번 분석 로직 호출
        self.apply_strategy_config(...) # 설정 적용
        self.is_ready = True
        return True
    except Exception as e:
        if retry:
            return self.perform_full_market_analysis(retry=False)
        return False
```

- [ ] **Step 3: run_cycle 내 전략 만료 시 auto_assign_preset 호출 수정**
```python
# run_cycle 로직 중 타임스탑 체크 블록
if self.is_deadline_expired(code):
    success = self.auto_assign_preset(code) # 기존 하향 로직을 AI 재분석으로 대체
    if not success:
        # 1회 재시도 (내부 처리)
        self.handle_critical_sell(code) # 실패 시 강제 손절
```

### Task 2: 매매 진입 루프에 상태 체크 적용

**Files:**
- Modify: `src/data_manager.py`

- [ ] **Step 1: DataManager 내 매매 로직에 is_ready 체크**
```python
# src/data_manager.py의 data_update_worker 루프
if not self.strategy.is_ready:
    print("시장 분석 중... 대기 중입니다.")
    continue
# 이후 기존 매매 루프 실행
```

### Task 3: 메인 루프에 분석 스케줄러 통합

**Files:**
- Modify: `main.py`

- [ ] **Step 1: main 함수 시작 시 분석 실행**
```python
# main.py의 main 함수 시작부
strategy = VibeStrategy()
# 계좌 타입 확인 후 분석 수행
strategy.perform_full_market_analysis()
```

- [ ] **Step 2: 주기적 분석 업데이트 루프 추가**
```python
# main 루프 내
if (time.time() - strategy.last_market_analysis_time) > (strategy.analysis_interval * 60):
    strategy.perform_full_market_analysis()
```

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-16-ai-analysis-automation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
