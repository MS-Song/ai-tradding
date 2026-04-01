# 📄 GEMINI.md (KIS-Vibe-Trader Project)

## 1. Project Overview
* **Name:** KIS-Vibe-Trader
* **Goal:** 시니어 아키텍트의 설계 사상이 반영된 객체지향형 자율 트레이딩 엔진.
* **Architecture**: `ExitManager`, `MarketAnalyzer`, `RecoveryEngine`, `PyramidingEngine`, `VibeAlphaEngine` 5대 모듈 중심.
* **Response Policy**: 모든 답변과 설명은 반드시 **한국어**로 작성함.
* **Documentation Policy**: 
    *   모든 주요 기능 변경 및 추가 시 `gemini.md`와 관련 설계서(`specs/`)를 최신화함.
    *   사용자 인터페이스(UI) 및 단축키 변경 사항은 반드시 `USER_MANUAL.md`에 즉시 반영함.

---

## 2. Core Trading Logic

### A. 보유 종목 관리 (Exit Strategy)
*   **기본 임계치 (Base)**: 익절 **+5.0%**, 손절 **-5.0%** (사용자/AI 설정에 따라 가변 및 영속 저장).
*   **실시간 VIBE 보정 (Current Delta)**:
    *   **상승장(Bull)**: 익절 **+3.0%** (수익 극대화), 손절 **+1.0%** (완화).
    *   **하락장(Bear)**: 익절 **-2.0%** (짧은 익절), 손절 **-2.0%** (리스크 관리 강화).
    *   **방어모드(Defensive)**: 익절 **-3.0%**, 손절 **-3.0%** (극보수적 대응).
*   **개별 종목 변동성**: 거래량 폭발(전일 대비 1.5배) 시 익절 타겟 **+2.0% 추가 상향**.
*   **익절 Cooldown**: 부분 익절 발생 시 해당 종목은 **1시간 동안 추가 익절 제한**.

### B. 물타기 엔진 (Recovery Engine - 하락 대응)
*   **트리거**: 수익률 **현재 손절선(SL) + 1.0% 이상** 구간 & 현재가 < 매입평단.
    *   **CRITICAL (Logic Link)**: 물타기 트리거는 항상 실시간 손절선보다 최소 1.0% 높게 설정됨.
    *   설정값이 손절선보다 낮을 경우 시스템이 자동으로 `Current SL + 1.0%`로 보정하여 물타기 기회를 우선 확보함.
*   **조건**: 직전 물타기 가격 대비 **-2.0% 이상 추가 하락** 시에만 집행.
*   **설정 저장**: 트리거%, 회당 금액, 종목 한도 등은 `trading_state.json`에 영속 저장됨.
*   **TUI 표시**: `BEAR` 라인 (🔵 청색 계열) — 단축키 `5`

### C. 불타기 엔진 (Pyramiding Engine - 상승 추종)
*   **트리거**: 수익률이 설정된 `min_profit_to_pyramid`% 이상 & 현재가 > 매입평단.
    *   **CRITICAL (Logic Link: TP 충돌 방지)**: 불타기 트리거는 항상 현재 설정된 **익절선(TP) - 1.0%** 이하로 자동 제한됨.
    *   예) 익절 5.0%인데 불타기가 4.5%에 걸리면 매수 직후 익절에 걸리는 핑퐁 매매가 발생하므로 시스템이 원천 차단.
*   **조건**: 직전 불타기 매입가 대비 **+2.0% 이상 추가 상승** 시에만 재진입 허용.
*   **작동 조건**: 상승장(Bull) 또는 거래량 폭발(vol_spike) 시에만 작동. 하락장/방어모드에서는 자동 비활성화.
*   **설정**: `bull_config`로 물타기(`bear_config`)와 완전 독립 관리. `trading_state.json`에 영속 저장.
*   **TUI 표시**: `BULL` 라인 (🔴 적색 계열) — 단축키 `6`

### D. AI 자율 매매 및 입체 분석 (Vibe-Alpha & Insight Engine)
*   **데이터 소스**: KIS API(시세) + **Naver Finance(뉴스, PER, PBR, 업종 지표)** 통합 활용.
*   **입체 분석 (Insight Engine)**:
    *   단순 가격 분석이 아닌 **[시장 전망 + 펀더멘털(PER/PBR) + 뉴스 모멘텀]**을 결합한 3D 분석 수행.
    *   AI가 제안한 수치는 현재 VIBE를 반영한 **최종 목표값**이며, 시스템은 이를 **역산**하여 기본값(Base)으로 저장함.
*   **매수 트리거**: 
    *   AI 자율 매매 모드가 **[AUTO]** 상태일 때 작동.
    *   테마 밀집도 + 뉴스 감성 + 저평가 점수가 높은 상위 종목 대상.
    *   **진입 조건**: 당일 등락률 **-1.5% ~ +4.0%** 사이의 보합권/선취매 영역에서만 진입.
*   **매수 규모 및 빈도**: 1회 진입 시 설정 단위의 100% 집행, **당일 종목당 1회** 제한.

### E. AI 전략 파서 (Strategy Parser)
*   **프롬프트 양식**: `AI[전략]: 익절 +X.X%, 손절 -Y.Y%, 물타기 -Z.Z%, 불타기 +W.W%, 금액 N원`
*   **파싱 규칙**:
    *   핵심 4개 필드(익절/손절/물타기/불타기)는 **필수** — 하나라도 누락 시 전체 적용 거부.
    *   **금액 필드**는 선택적 — 파싱 실패 시(비정형 텍스트, 퍼센트 등) **기존 설정값 유지** + `error.log` 기록.
    *   금액이 1000 미만일 경우 **만원 단위로 자동 보정** (AI가 '50'이라 쓰면 500,000원으로 간주).
*   **호환성**: 구버전 AI 응답(`추매` 키워드)도 `불타기`로 자동 매핑 처리.

### F. 리포트 시스템 (Report Engine)
*   **보유 종목 리포트 (`B` 키)**: 현재 포트폴리오의 종목별 PER/PBR/뉴스 데이터를 수집하여 Gemini에게 종합 진단 요청.
    *   종목별 '유지(Hold) / 매도(Sell) / 비중확대(Add)' 전략 제시.
    *   전체 포트폴리오 건강 상태 한줄평 포함.
*   **추천 종목 리포트 (`D` 키)**: AI 추천 종목들의 상세 지표 + 뉴스 기반 입체 분석 리포트.
*   **인기 테마 리포트 (`H` 키)**: 실시간 인기 검색 TOP 10 종목의 테마 분석 및 AI 트렌드 진단.
    *   종목별 '주목(Watch) / 진입(Entry) / 관망(Wait)' 의견 제시.
    *   테마 지속성(단기/중장기) 판단 포함.
*   **개별 종목 분석 (`7` 키)**: 특정 종목 코드 입력 시 실시간 심층 분석 리포트 생성.

### G. 시스템 안전 및 영속성 (Safety & Persistence)
*   **글로벌 패닉 차단**: 미국 지수 -1.5% 이하 급락 시 **모든 매수(신규/물타기/불타기) 즉시 차단**.
*   **상태 저장 (State)**: `base_tp`, `base_sl`, `manual_thresholds`, `bear_config`, `bull_config` 등 모든 핵심 설정은 실시간으로 저장되어 재시작 시 자동 복구됨.
*   **AI Fallback**: Gemini API 장애(토큰 소진, 네트워크 에러, 타임아웃) 발생 시 **기존 알고리즘 모드로 자동 전환**하여 무중단 운영.
*   **리눅스 호환성**: 터미널 Raw 모드 및 ESC 키 인터랙션을 완벽 지원하여 환경에 구애받지 않는 안정적 제어 보장.

---

## 3. TUI 단축키 맵 (최신)

```
[COMMANDS] 1:매도 | 2:매수 | 3:전략 | 4:추천 | 5:물타기 6:불타기 | 7:분석 8:시황 | 리포트 B:보유 D:추천 H:인기 | S:셋업 | Q:종료
```

## 4. 설정 영속성 구조 (`trading_state.json`)

```json
{
    "base_tp": 5.0,
    "base_sl": -5.0,
    "manual_thresholds": {},
    "last_avg_down_prices": {},
    "last_buy_prices": {},
    "ai_config": { "amount_per_trade": 500000, "min_score": 60.0, "max_investment_per_stock": 2000000, "auto_mode": false },
    "bear_config": { "min_loss_to_buy": -3.0, "average_down_amount": 500000, "max_investment_per_stock": 2000000, "auto_mode": false },
    "bull_config": { "min_profit_to_pyramid": 3.0, "average_down_amount": 500000, "max_investment_per_stock": 25000000, "auto_mode": false },
    "recommendation_history": {}
}
```
