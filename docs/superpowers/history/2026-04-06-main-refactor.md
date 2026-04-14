# main.py 리팩토링 구현 계획 (Refactoring Plan)

> **Agentic Workers를 위한 안내:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` (권장) 또는 `superpowers:executing-plans`를 사용하여 이 계획을 단계별로 실행하세요. 체크박스(`- [ ]`) 구문을 사용하여 진행 상황을 추적합니다.

**목표:** 1,600라인이 넘는 `main.py`를 기능별 모듈로 분리하여 가독성, 유지보수성 및 안정성을 높임. 이전 실패 사례를 거울삼아 단계적(Surgical) 접근을 취함.

**아키텍처:** 
- **Utilities (`src/utils.py`):** 터미널 제어, 문자열 너비 계산, 시장 상태 확인 등 순수 함수 및 유틸리티.
- **Theme Engine (`src/theme_engine.py`):** 테마 키워드 관리 및 인기 테마 분석 로직.
- **Data Manager (`src/data_manager.py`):** 전역 상태(Cache), 데이터 업데이트 스레드(Worker) 관리. 스레드 안전성 확보.
- **UI/TUI (`src/ui/`):** 렌더러(`renderer.py`)와 사용자 인터랙션(`interaction.py`) 로직 분리.
- **Main (`main.py`):** 애플리케이션 진입점, 초기화 및 메인 루프만 수행.

**기술 스택:** Python, threading, ANSI escape sequences, concurrent.futures.

---

### Task 1: 유틸리티 및 터미널 제어 분리

**파일:**
- 생성: `src/utils.py`
- 수정: `main.py`

- [ ] **Step 1: `src/utils.py` 생성 및 함수 이동**
    - `main.py`에서 터미널 설정 및 유틸리티 함수들을 이동함.
    - 대상: `init_terminal`, `restore_terminal_settings`, `set_terminal_raw`, `enter_alt_screen`, `exit_alt_screen`, `flush_input`, `is_market_open`, `is_us_market_open`, `get_visual_width`, `align_kr`, `get_market_name`

- [ ] **Step 2: `main.py`에서 `src.utils` 임포트 및 기존 코드 제거**

- [ ] **Step 3: 동작 확인 (TUI 렌더링 및 터미널 제어 정상 여부)**

---

### Task 2: 테마 분석 엔진 분리

**파일:**
- 생성: `src/theme_engine.py`
- 수정: `main.py`

- [ ] **Step 1: `src/theme_engine.py` 생성**
    - `THEME_KEYWORDS`와 `analyze_popular_themes` 함수 이동.
    - `_cached_themes` 상태 관리 로직 포함 (또는 Data Manager로 통합 검토).

- [ ] **Step 2: `main.py`에서 `src.theme_engine` 임포트 및 적용**

- [ ] **Step 3: 동작 확인 (인기 테마 분석 리포트 정상 작동 여부)**

---

### Task 3: 데이터 매니저 및 전역 상태 관리 (핵심)

**파일:**
- 생성: `src/data_manager.py`
- 수정: `main.py`

- [ ] **Step 1: `src/data_manager.py` 설계 및 생성**
    - `DataManager` 클래스(또는 싱글톤 모듈) 생성.
    - `_cached_*` 변수들, `_data_lock`, `_ui_lock`, `_last_times` 등을 캡슐화.
    - `update_all_data`, `index_update_worker`, `data_update_worker` 함수 이동.

- [ ] **Step 2: `main.py`와 `DataManager` 연결**
    - `main.py`에서 복잡한 스레드 생성 로직을 `DataManager.start_workers()` 등으로 단순화.

- [ ] **Step 3: 스레드 안정성 테스트**
    - 데이터 업데이트 중 TUI 렌더링 시 데드락이나 데이터 불일치 여부 확인.

---

### Task 4: UI 렌더러 및 인터랙션 로직 분리

**파일:**
- 생성: `src/ui/renderer.py`, `src/ui/interaction.py`
- 수정: `main.py`

- [ ] **Step 1: `src/ui/renderer.py` 생성**
    - `draw_tui` 함수 이동. `DataManager`를 통해 데이터를 조회하도록 수정.
    - (옵션) `draw_tui` 내부의 헤더, 마켓 정보, 잔고 정보 등을 하위 함수로 쪼갬.

- [ ] **Step 2: `src/ui/interaction.py` 생성**
    - `perform_interaction` 및 관련 입력 로직 이동.

- [ ] **Step 3: `main.py` 최종 정리**
    - `main()` 함수를 최적화하여 가독성 극대화.

---

### Task 5: 전체 통합 테스트 및 문서화

- [ ] **Step 1: 모든 기능(매수/매도, AI 분석, 물타기/불타기 설정 등) 전수 검사**
- [ ] **Step 2: `USER_MANUAL.md` 및 `gemini.md` 업데이트**
- [ ] **Step 3: 리팩토링 완료 보고**
