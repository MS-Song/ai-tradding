# AI Trading Engine Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 추천 종목 시스템 최적화(5+1), 어제 추천 성과 트래킹, 그리고 개별 종목 심층 AI 분석 기능을 구현하여 사용자 매매 결정을 돕는 인텔리전스 강화.

**Architecture:** KIS API 의존성을 낮추기 위해 Naver Finance 데이터를 수집 엔진으로 활용하며, VibeStrategy가 추천 이력을 관리하고 Gemini AI가 매수/매도 고민 해결사 관점의 리포트를 생성하도록 설계함.

**Tech Stack:** Python, Requests (Naver/Yahoo), Gemini AI API, JSON (Persistence)

---

### Task 1: 추천 종목 추출 로직 최적화 (5+1 구조)

**Files:**
- Modify: `src/strategy.py:270-320` (VibeAlphaEngine.analyze)

- [ ] **Step 1: 일반 종목 5개와 ETF 1개를 분리하여 반환하도록 수정**
```python
        # 기존: final_stocks(6개) + final_etfs(3개)
        # 수정: final_stocks[:5] + (final_etfs[:1] if final_etfs else [])
        final_list = final_stocks[:5]
        if final_etfs:
            final_list.append(final_etfs[0])
        return final_list
```
- [ ] **Step 2: Commit**
```bash
git add src/strategy.py
git commit -m "feat: optimize AI recommendation to 5 stocks + 1 ETF structure"
```

### Task 2: 어제 추천 종목 트래킹 및 영속성 구현

**Files:**
- Modify: `src/strategy.py` (VibeStrategy 클래스)
- Modify: `trading_state.json`

- [ ] **Step 1: VibeStrategy.__init__ 및 _load_all_states에 이력 관리 필드 추가**
```python
        self.recommendation_history = {} # {date: [recs]}
        # _load_all_states 내부
        self.recommendation_history = d.get("recommendation_history", {})
```
- [ ] **Step 2: 일자 변경 감지 및 '어제 추천' 로드 로직 추가**
```python
    def update_yesterday_recs(self):
        today = datetime.now().strftime('%Y-%m-%d')
        # 저장된 마지막 날짜가 오늘이 아니면 history에서 가져옴
        dates = sorted(self.recommendation_history.keys())
        if dates and dates[-1] < today:
            return self.recommendation_history[dates[-1]]
        return []
```
- [ ] **Step 3: Commit**
```bash
git add src/strategy.py
git commit -m "feat: add recommendation history tracking logic"
```

### Task 3: TUI 레이아웃 개편 (2줄 추천 + 어제 성과)

**Files:**
- Modify: `main.py:draw_tui`

- [ ] **Step 1: AI 추천 섹션 2줄 배치로 수정**
- [ ] **Step 2: 네이버 랭킹 하단에 '어제 추천' 변동성 상위 3개 표시 로직 추가**
- [ ] **Step 3: 메뉴 단축키 변경 (7: AI분석, 8: AI시황, 9: 제거)**
- [ ] **Step 4: Commit**
```bash
git add main.py
git commit -m "ui: redesign TUI with 2-row recommendations and yesterday's tracking"
```

### Task 4: 7번 'AI 종목분석' 기능 구현

**Files:**
- Modify: `src/strategy.py` (GeminiAdvisor 클래스 추가)
- Modify: `main.py:perform_interaction`, `draw_stock_analysis`

- [ ] **Step 1: GeminiAdvisor에 get_stock_report_advice 메서드 추가**
```python
    def get_stock_report_advice(self, code, name, detail, news):
        # "매수/매도 고민 해결사" 관점의 프롬프트 구성
        prompt = f"종목 {name}({code}) 분석... 왜 올랐나/내렸나? 내일은 어떨까?..."
```
- [ ] **Step 2: main.py에 draw_stock_analysis 전체 화면 UI 구현**
- [ ] **Step 3: 7번 키 입력 처리 로직 연결**
- [ ] **Step 4: Commit**
```bash
git add src/strategy.py main.py
git commit -m "feat: implement 7:AI Stock Analysis with full-screen report"
```

### Task 5: 문서화 및 최종 검증

**Files:**
- Modify: `gemini.md`
- Modify: `docs/USER_MANUAL.md`

- [ ] **Step 1: USER_MANUAL.md의 단축키 및 신규 기능 설명 업데이트**
- [ ] **Step 2: 실제 종목 코드를 입력하여 7번 기능 테스트 (구문 및 API 호출 확인)**
- [ ] **Step 3: Commit**
```bash
git add gemini.md docs/USER_MANUAL.md
git commit -m "docs: update manual and design specs for AI enhancement"
```
