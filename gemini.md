# 📄 GEMINI.md (KIS-Vibe-Trader Project)

## 1. Project Overview
* **Name:** KIS-Vibe-Trader
* **Goal:** 한국투자증권(KIS) REST API를 활용하여 사용자의 'Vibe(의도)'에 따라 자산을 운용하는 CLI 기반 자동 매매 에이전트.
* **Persona:** 팀장(민수)의 지시를 이해하고, 복잡한 UI 대신 효율적인 로직과 로그 중심, 그리고 칼정렬된 시각적 대시보드를 지향함.

---

## 2. Core Vibe Logic (Strategy)

### A. 보유 종목 관리 (Exit Strategy)
* **기본 익절 (Take-Profit):** 수익률 **+5%** 도달 시 보유 수량의 **30%** 시장가 매도.
* **기본 손절 (Stop-Loss):** 수익률 **-3%** 도달 시 **전량** 시장가 매도.
* **동적 보정:**
    *   **거래량 폭발**: 전일 대비 거래량 1.5배 이상 시, 익절 기준 **+3% 상향**, 손절 기준 **절반으로 단축** (빠른 탈출).
    *   **상승장(Bull)**: 익절 기준을 기존 값에서 **+3% 상향**하여 수익 극대화. (예: 기본 5% -> 8%)

### B. 시장 상황 대응 (Market Adaptive)
* **글로벌 연동**: KOSPI, KOSDAQ뿐만 아니라 NASDAQ, S&P 500 지수를 실시간 모니터링.
* **Global Panic 감지**: 미국 주요 지수가 **-1.5% 이하** 급락 시 즉시 **Bear Market** 모드로 전환.
* **동적 물타기 (Averaging Down)**:
    *   하락장(`Bear`)에서 **현재 손실 중인 보유 종목**만 타겟팅.
    *   **안전장치**: 한 종목당 최대 투자 한도(**300만 원**) 및 최소 하락폭(**-3%**) 준수.
    *   **10분 쿨다운**: 한 번 물타기 한 종목은 10분간 재매수 금지 (파일 기반 상태 저장).

---

## 3. Technical Standards & Rules

### A. Authentication & API Control
* **토큰 캐싱**: `.token_cache.json`을 통해 발급된 토큰을 **10분간 모든 프로그램이 공유**. (API 호출 제한 방지)
* **하이브리드 지수 조회**: KIS 공식 API를 우선 사용하되, 모의투자 서버 장애 시 네이버/야후 금융 API로 자동 백업.
* **예수금 반영**: `dnca_tot_amt`(D+2)가 아닌 실시간 필드(`prvs_rcdl_exca_amt`, `nll_amt`)를 사용하여 주식 매수 즉시 잔액 차감 표시.

### B. Dashboard & Visualization
* **칼정렬 시스템**: `get_visual_width` 함수를 통해 한글 및 특수기호(`▲`, `▼`, `🔥`)의 너비를 정확히 2칸으로 계산하여 수직 정렬 완벽 보장.
* **동적 너비 레이아웃**: 보유 종목 데이터 길이에 맞춰 컬럼 폭과 가로 구분선(`━`) 길이를 실시간으로 계산.
* **한국식 색상 적용**: 상승/수익은 **빨강 ▲**, 하락/손실은 **파랑 ▼** 적용 (ANSI 색상 코드 활용).
* **장 상태 시각화**: 운영 중(**☀️**), 휴장(**🌙**) 아이콘 분리.

### C. Human-in-the-loop (Confirmation)
* **매수 승인**: 물타기 실행 전 사용자에게 `y/n` 질문을 던짐.
* **타임아웃**: **50초** 동안 응답이 없으면 안전을 위해 매수를 자동으로 스킵.

---

## 4. Environment & Deployment
* **Cross-Platform**: Windows(CMD/PowerShell)와 Linux(Ubuntu) 환경을 모두 지원.
* **OS 래퍼**: 줄바꿈(`os.linesep`), 화면 클리어(`cls/clear`), 비차단 입력(`msvcrt/select`)을 OS에 따라 자동 전환.
* **Git Management**:
    *   환경 변수(`.env`), 토큰 캐시(`.token_cache.json`), 매매 상태(`.trading_state.json`)는 반드시 **.gitignore**에 포함.
    *   민감한 정보 노출 절대 금지.

---

## 5. Development Instructions
1. **Simulation First**: 기본적으로 `is_virtual=True` 설정을 유지하거나, `.env`의 `KIS_IS_VIRTUAL` 설정을 따를 것.
2. **Modularization**: 인증(`auth.py`), API 연동(`api.py`), 매매 로직(`strategy.py`), 로깅(`logger.py`) 모듈화 유지.
3. **Tools & Tests Management**: 
    *   메인 로직(`main.py`) 외의 모든 보조 도구, 테스트 스크립트, 유틸리티는 반드시 **`tools/`** 디렉토리에 위치시킨다.
    *   `tools/` 내의 스크립트가 `src/` 모듈을 참조할 수 있도록 파일 상단에 `sys.path.append` 로직을 포함한다.
4. **Thought Process**: 모든 코드 수정 전에는 반드시 `### Thought Process` 섹션을 만들어 논리적 근거를 설명할 것.
5. **Validation**: 수정 후에는 반드시 가로바 정렬, 데이터 누락 여부, API 호출 안정성을 검증할 것.

# "팀장의 지시는 곧 법이며, 모든 수치는 정렬되어야 하고 모든 로그는 이유가 있어야 하며 반드시 한글로 한다."
