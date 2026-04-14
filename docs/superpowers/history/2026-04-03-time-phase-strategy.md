# AI-Linked Time-Phase Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 트레이딩 엔진에 시간 개념을 도입하여 장중 시간대별 가중치 조절, AI 기반 데드라인(Time-Stop), 그리고 시장 상황에 따른 조건부 종가 베팅 기능을 구현함.

**Architecture:** `VibeStrategy` 내부에 시간 페이즈 판정 로직을 추가하고, `ExitManager`의 동적 임계치 계산에 시간 가중치를 통합함. AI 프롬프트를 확장하여 종목별 수명을 관리하고, `run_cycle`에서 시간 기반 자동 매매 액션을 수행함.

**Tech Stack:** Python 3.12, Google Gemini API, KIS API, threading

---

### Task 1: 데이터 구조 확장 및 영속성 처리

**Files:**
- Modify: `src/strategy.py`

- [ ] **Step 1: VibeStrategy._load_all_states 및 _save_all_states 수정**
`preset_strategies` 내부에 `buy_time`, `deadline`, `is_p3_processed` 필드를 추가로 처리하도록 수정합니다.

```python
# src/strategy.py 내부 _load_all_states 수정부
# preset_strategies 로드 시 새로운 필드들(buy_time, deadline, is_p3_processed)을 안전하게 읽어옴
if "preset_strategies" in d:
    self.preset_strategies = d["preset_strategies"]
    # 하위 호환성을 위해 누락된 필드 초기화
    for code, s in self.preset_strategies.items():
        if 'buy_time' not in s: s['buy_time'] = None
        if 'deadline' not in s: s['deadline'] = None
        if 'is_p3_processed' not in s: s['is_p3_processed'] = False
```

- [ ] **Step 2: VibeStrategy.assign_preset 및 record_buy 수정**
전략 할당이나 매수 시점에 `buy_time`을 기록하는 로직을 추가합니다.

```python
# assign_preset 메서드 수정
def assign_preset(self, code: str, preset_id: str, tp: float = None, sl: float = None, reason: str = '', lifetime_mins: int = None):
    # ... 기존 로직 ...
    from datetime import datetime
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    self.preset_strategies[code] = {
        "preset_id": preset_id, "name": PRESET_STRATEGIES[preset_id]['name'],
        "tp": tp, "sl": sl, "reason": reason,
        "buy_time": now_str,
        "deadline": self._calculate_deadline(now_str, lifetime_mins),
        "is_p3_processed": False
    }
    self._save_all_states()
```

- [ ] **Step 3: 데드라인 계산 헬퍼 함수 추가**
```python
def _calculate_deadline(self, start_time_str, lifetime_mins):
    if not start_time_str or not lifetime_mins: return None
    from datetime import datetime, timedelta
    start_dt = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
    deadline_dt = start_dt + timedelta(minutes=lifetime_mins)
    return deadline_dt.strftime('%Y-%m-%d %H:%M:%S')
```

- [ ] **Step 4: Commit**
```bash
git add src/strategy.py
git commit -m "feat: extend data structure for time-based strategy"
```

---

### Task 2: 장중 시간 페이즈(Market Phase) 로직 구현

**Files:**
- Modify: `src/strategy.py`

- [ ] **Step 1: 현재 시간 페이즈 판정 메서드 추가**
```python
def get_market_phase(self) -> dict:
    from datetime import datetime
    now = datetime.now().time()
    # Phase 1: 09:00~10:00 (공격)
    if dtime(9, 0) <= now < dtime(10, 0):
        return {"id": "P1", "name": "OFFENSIVE", "tp_delta": 2.0, "sl_delta": -1.0}
    # Phase 3: 14:30~15:10 (결과확정)
    elif dtime(14, 30) <= now < dtime(15, 10):
        return {"id": "P3", "name": "CONCLUSION", "tp_delta": 0.0, "sl_delta": 0.0}
    # Phase 4: 15:10~15:20 (익일준비)
    elif dtime(15, 10) <= now < dtime(15, 20):
        return {"id": "P4", "name": "PREPARATION", "tp_delta": 0.0, "sl_delta": 0.0}
    # Phase 2: 그 외 (수렴/관리)
    elif dtime(10, 0) <= now < dtime(14, 30):
        return {"id": "P2", "name": "CONVERGENCE", "tp_delta": -1.0, "sl_delta": -1.0}
    return {"id": "IDLE", "name": "IDLE", "tp_delta": 0.0, "sl_delta": 0.0}
```

- [ ] **Step 2: ExitManager.get_thresholds에 시간 가중치 통합**
```python
# get_thresholds 메서드 내부 수정
def get_thresholds(self, code: str, kr_vibe: str, price_data: Optional[dict] = None, phase_cfg: dict = None) -> Tuple[float, float, bool]:
    # ... 기본 Vibe 보정 ...
    tp_mod, sl_mod = self._get_vibe_modifiers(kr_vibe)
    
    # 시간 페이즈 보정 합산
    if phase_cfg:
        tp_mod += phase_cfg.get('tp_delta', 0)
        # 하락장 예외: Bear/Defensive일 때는 P1의 SL 완화 적용 안 함
        if not (kr_vibe.upper() in ["BEAR", "DEFENSIVE"] and phase_cfg['id'] == "P1"):
            sl_mod += phase_cfg.get('sl_delta', 0)
```

- [ ] **Step 3: Commit**
```bash
git add src/strategy.py
git commit -m "feat: implement market phase detection and weight integration"
```

---

### Task 3: AI 프롬프트 및 파서 고도화 (수명 지정)

**Files:**
- Modify: `src/strategy.py`

- [ ] **Step 1: simulate_preset_strategy 프롬프트 수정**
AI에게 '유효시간(분)'을 응답하도록 지시를 추가합니다.

```python
# simulate_preset_strategy 내부 prompt 수정
prompt = f"""
...
[KIS 공식 프리셋 전략 목록]
...
[판단 가이드라인]
1. ...
2. ...
3. 이 종목의 현재 모멘텀 지속 시간을 예측하여 '유효시간(분)'을 제안하세요. (예: 급등주는 60~120분, 완만한 추세주는 240~360분)

[필수 응답 형식]
전략번호: XX
익절: +X.X%
손절: -X.X%
유효시간: N분
근거: 한줄 설명
"""
```

- [ ] **Step 2: AI 응답 파서 수정**
```python
# 파싱 로직에 유효시간 추출 추가
lifetime_match = re.search(r"유효시간[:\s]*(\d+)", answer)
lifetime = int(lifetime_match.group(1)) if lifetime_match else 120 # 기본 120분
```

- [ ] **Step 3: Commit**
```bash
git add src/strategy.py
git commit -m "feat: enhance AI prompt and parser for strategy lifetime"
```

---

### Task 4: 자동 매매 액션 구현 (Phase 3 & Time-Stop)

**Files:**
- Modify: `src/strategy.py`

- [ ] **Step 1: run_cycle 메서드에 시간 기반 액션 추가**
매 루프마다 데드라인 초과 및 Phase 3 진입 여부를 체크합니다.

```python
# run_cycle 내부 로직 추가
phase = self.get_market_phase()
now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

for h in holdings:
    code = h['pdno']
    p_strat = self.preset_strategies.get(code)
    if not p_strat: continue
    
    # 1. Time-Stop 체크 (데드라인 초과 시 TP 하향)
    if p_strat.get('deadline') and now_str > p_strat['deadline']:
        # 현재 수익률의 절반으로 TP 강제 하향 (수익 보존 모드)
        curr_profit = float(h.get('evlu_pfls_rt', 0))
        if curr_profit > 0.5:
            p_strat['tp'] = max(0.5, curr_profit / 2.0)
            p_strat['deadline'] = None # 한 번만 적용
            
    # 2. Phase 3: 수익권 50% 분할 매도
    if phase['id'] == "P3" and not p_strat.get('is_p3_processed'):
        curr_profit = float(h.get('evlu_pfls_rt', 0))
        if curr_profit >= 0.5:
            qty = int(float(h['hldg_qty'])) // 2
            if qty > 0:
                success, msg = self.api.order_market(code, qty, False)
                if success:
                    p_strat['is_p3_processed'] = True
                    # 남은 수량의 SL을 본전으로 상향
                    p_strat['sl'] = 0.2 
                    results.append(f"P3 수익확정(50%): {h['prdt_name']}")
```

- [ ] **Step 2: Commit**
```bash
git add src/strategy.py
git commit -m "feat: implement Time-Stop and Phase 3 automated actions"
```

---

### Task 5: 조건부 종가 베팅 구현 (Phase 4)

**Files:**
- Modify: `src/strategy.py`

- [ ] **Step 1: Phase 4 종가 베팅 로직 추가**
```python
# run_cycle 내부 Phase 4 처리
if phase['id'] == "P4" and self.auto_ai_trade:
    # 시장 안정성 체크 (Panic X, Bull/Neutral O)
    if not self.global_panic and self.current_market_vibe.upper() in ["BULL", "NEUTRAL"]:
        if self.ai_recommendations:
            top_stock = self.ai_recommendations[0]
            # 이미 오늘 종가베팅을 했는지 체크 (전역 변수 활용)
            if not getattr(self, '_last_closing_bet_date', None) == datetime.now().date():
                p = self.api.get_inquire_price(top_stock['code'])
                qty = math.floor(self.ai_config["amount_per_trade"] / p['price'])
                if qty > 0:
                    success, msg = self.api.order_market(top_stock['code'], qty, True)
                    if success:
                        self._last_closing_bet_date = datetime.now().date()
                        results.append(f"P4 익일준비 매수: {top_stock['name']}")
```

- [ ] **Step 2: Commit**
```bash
git add src/strategy.py
git commit -m "feat: implement Phase 4 conditional closing bet"
```

---

### Task 6: TUI 및 UI 반영

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 상태바에 현재 페이즈 표시**
```python
# draw_tui 수정
phase = strategy.get_market_phase()
phase_icon = "🔥" if phase['id']=="P1" else "🧘" if phase['id']=="P2" else "💰" if phase['id']=="P3" else "🛒" if phase['id']=="P4" else "💤"
buf.write(align_kr(f" VIBE: {v_c}{_cached_vibe.upper()}\033[0m {panic_txt} [PHASE: {phase_icon}{phase['name']}]", tw) + "\n")
```

- [ ] **Step 2: 자산 리스트에 남은 시간 표시**
'STGY' 컬럼 옆에 데드라인까지 남은 분(Mins)을 표시합니다.

- [ ] **Step 3: 최종 테스트 및 검증**
장중 시간대를 가상으로 설정하여 각 페이즈가 올바르게 작동하는지 테스트합니다.

- [ ] **Step 4: Commit**
```bash
git add main.py
git commit -m "ui: reflect market phase and time deadlines in TUI"
```
