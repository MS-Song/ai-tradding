# 📄 gemini.md

## 1. Project Overview

* **Name:** KIS-Vibe-Trader
* **Goal:** 한국투자증권(KIS) REST API를 활용하여 사용자의 'Vibe(의도)'에 따라 자산을 운용하는 CLI 기반 자동 매매 에이전트 구축.
* **Persona:** 팀장(민수)의 지시를 이해하고, 복잡한 UI 없이 효율적인 로직과 로그 중심의 프로그램을 지향함.

---

## 2. Core Vibe Logic (Strategy)

에이전트는 다음 규칙을 기본 매매 엔진에 반영한다.

### A. 보유 종목 관리 (Exit Strategy)

* **익절 (Take-Profit):** 수익률 **+5%** 도달 시, 보유 수량의 **30%**를 시장가 매도하여 수익 확정.
* **손절 (Stop-Loss):** 수익률 **-3%** 도달 시, 리스크 관리를 위해 **전량** 시장가 매도.

### B. 시장 상황 대응 (Market Adaptive)

* **상승장 (Bull Market):** 지수(KOSPI/KOSDAQ) 상승 시, 익절 기준을 **+3%**로 낮추어 빠르게 수익을 실현하는 방어적 포지션 취함.
* **하락장 (Bear Market):** 지수 하락 시, 우량주 또는 관심 종목을 설정 금액만큼 분할 **매수(추가 매입)** 하여 평단가를 낮춤.

---

## 3. Technical Stack

* **Language:** Python 3.10+
* **Library:** `python-kis` (Official/Community Wrapper), `python-dotenv`
* **Interface:** CLI (No UI required), Logging to Console
* **Environment:** Windows/Linux (Cloud-ready)

---

## 4. Data Structure & Authentication

* **Auth:** `.env` 파일의 환경변수(`KIS_APPKEY`, `KIS_SECRET`, `KIS_CANO`)를 로드하여 OAuth 2.0 토큰 발급.
* **Config:** 매매 기준값(수익률 등)은 외부 YAML 또는 환경변수에서 로드하여 코드 수정 없이 'Vibe' 변경 가능토록 설계.

---

## 5. Agent Instructions for Vibe Coding

에이전트는 코드를 생성하거나 수정할 때 다음 원칙을 따른다.

1. **Strict Error Handling:** API 호출 실패(네트워크 오류, 토큰 만료 등) 시 즉시 로그를 남기고 재시도 로직을 포함할 것.
2. **Simulation First:** 기본적으로 `is_virtual=True` 옵션을 활성화하여 모의투자 계좌에서 먼저 동작하게 할 것.
3. **Clean Logs:** 매수/매도 실행 시 종목명, 수익률, 실행 이유(Vibe Trigger)를 명확히 출력할 것.
4. **Modularization:** 인증, 잔고 조회, 매매 로직, 시장 분석 모듈을 분리하여 유지보수성을 높일 것.

---

## 6. Target API Endpoint (KIS Developers)

* **Domain:** `https://openapi.koreainvestment.com:9443` (실전) / `https://openapivts.koreainvestment.com:29443` (모의)
* **Key Functions:** * `get_balance()`: 계좌 잔고 및 종목별 수익률 확인
* `order_market()`: 시장가 주문 실행
* `get_inquire_price()`: 현재가 및 지수 정보 확인

# "모든 코드 생성 전에는 반드시 ### Thought Process 섹션을 만들어 논리적 근거를 설명할 것."