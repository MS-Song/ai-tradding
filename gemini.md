# 📄 GEMINI.md (KIS-Vibe-Trader Project)

## 1. Project Overview
* **Name:** KIS-Vibe-Trader
* **Goal:** 시니어 아키텍트의 설계 사상이 반영된 객체지향형 자동 매매 엔진.
* **Architecture**: `ExitManager`, `MarketAnalyzer`, `RecoveryEngine` 3대 모듈 중심의 책임 분리.

---

## 2. Core Vibe Logic (Strategy)

### A. 보유 종목 관리 (Exit Strategy)
* **기본 임계치**: 익절 **+5.0%** (30% 매도), 손절 **-5.0%** (전량 매도).
    *   **CRITICAL**: 손절선을 -5%로 설정하여 물타기(-3%) 구간과의 겹침(Race Condition)을 원천 차단.
* **동적 보정**:
    *   **상승장(Bull)**: 익절 타겟 **+3.0% 상향**.
    *   **거래량 폭발**: 익절 타겟 **+3.0% 상향**. 단, **손절선(-5.0%)은 절대 줄이지 않고 보수적으로 유지**.
* **수동 오버라이드**: 사용자 지정 설정이 시스템 계산값보다 항상 최우선.

### B. 시장 상황 대응 (Market Adaptive)
* **Vibe 감지**: 오직 **국내 지수(KOSPI, KOSDAQ)**만을 기준으로 시장 분위기 판별.
* **Global Panic**: 미국 3대 지수 및 선물 중 하나라도 **-1.5% 이하** 시 `is_panic = True`.
    *   **Panic 상태 시 모든 신규 매수 및 물타기 매수를 전면 차단하여 현금 보존.**

### C. 물타기 엔진 (Recovery Engine)
* **트리거 조건**: 수익률이 **-3.0% 이하**이면서 현재가 < 매입평단인 경우.
    *   **동작 구간**: -3.0% ~ -5.0% (손절선 도달 전까지만 작동).
* **가격 기반 쿨다운 (Price-based)**:
    *   시간(10분) 기준 폐기. **"직전 물타기 매수 단가 대비 -2.0% 이상 추가 하락"** 시에만 다음 차수 승인.
* **평단 시뮬레이션**: 매수 전 예상 평단가 인하폭(금액/비율) 계산 및 고지.

---

## 3. Technical Standards & Rules
* **Modularity**: 모든 코어 로직은 `src/strategy.py` 내의 독립된 매니저 클래스에서 관리.
* **Mandatory Rate-Limit**: KIS API 호출 시 전역 Lock 기반 **최소 1.1초 간격** 유지.
* **State Persistence**: 수동 설정 및 마지막 물타기 가격은 `trading_state.json`에 영구 저장.

# "모든 매매는 논리적으로 완결되어야 하며, 데이터는 항상 칼정렬 상태를 유지한다."
