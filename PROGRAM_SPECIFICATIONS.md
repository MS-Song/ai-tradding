# 📄 KIS-Vibe-Trader Program Specifications (v1.6.5)

## 1. 개요 (Overview)
본 시스템은 한국투자증권(KIS) API와 네이버 금융 데이터를 결합하여, 시장의 분위기(VIBE)를 진단하고 AI 기반의 자율 트레이딩을 수행하는 엔진입니다. 본 명세서는 시스템의 모든 물리적 구성 파일(Total 58 Files)과 각 파일의 상세 역할을 전수 기술합니다.

---

## 2. 프로젝트 디렉토리 구조 (Directory Structure)

```text
KIS-Vibe-Trader/
├── main.py                 # 프로그램 진입점 및 시스템 오케스트레이션
├── src/
│   ├── api/                # 외부 연동 (KIS, 네이버, 야후)
│   ├── data/               # 데이터 스키마 및 상태
│   ├── strategy/           # 핵심 연산 및 매매 엔진
│   │   ├── advisors/       # LLM 전략 자문
│   │   └── vibe/           # Vibe 기반 실행 믹스인
│   ├── ui/                 # 인터페이스 및 렌더링
│   │   └── views/          # 탭별 독립 화면 모듈
│   ├── utils/              # 알림 및 유틸리티
│   └── workers/            # 백그라운드 워커
└── tests/                  # 테스트 스위트
```

---

## 3. 파일별 상세 명세 (Exhaustive File List)

### 📂 Root Files (`src/`)
- **`main.py`**: 프로그램 진입점. 시스템 초기화 및 모든 백그라운드 워커를 가동합니다.
- **`src/auth.py`**: KIS API 인증 토큰 관리 및 보안 헤더 생성을 담당합니다.
- **`src/config_init.py`**: `.env` 설정 로드 및 시스템 환경 변수 초기화를 수행합니다.
- **`src/data_manager.py`**: 메모리 상의 전역 데이터를 관리하며, 영속성 저장소와 실시간 동기화합니다.
- **`src/logger.py`**: 거래 내역 및 AI 활동을 기록하는 통합 로깅 시스템입니다.
- **`src/theme_engine.py`**: 실시간 인기 테마 및 업종 데이터를 분석하여 정제합니다.
- **`src/updater.py`**: GitHub 릴리스 기반의 자동 업데이트 및 버전 관리 유틸리티입니다.
- **`src/usage_tracker.py`**: 일일 API 호출 횟수 및 토큰 사용량을 추적합니다.

### 📂 `src/api/` (External APIs)
- **`base.py`**: API 클라이언트의 베이스 추상 클래스.
- **`kis.py`**: 한국투자증권 실시간 시세 및 주문 집행 핵심 모듈.
- **`naver.py`**: 네이버 금융 뉴스, 상세 시세, 랭킹 수집.
- **`yahoo.py`**: 글로벌 지수(NASDAQ 등) 및 해외 시세 수집.

### 📂 `src/data/` (Data Models)
- **`state.py`**: 시스템의 영속적 상태를 정의하는 데이터 모델 및 초기값 설정.

### 📂 `src/strategy/` (Analysis & Calculation)
- **`alpha_engine.py`**: AI 추천 점수와 퀀트 지표를 결합한 최종 매수 점수 산출.
- **`chart_renderer.py`**: TUI 내에서 간단한 텍스트 기반 차트 렌더링 지원.
- **`constants.py`**: 전략 전반에서 사용하는 고정 상수(타임아웃, 임계치 등) 정의.
- **`exit_manager.py`**: Vibe와 Phase에 따른 실시간 TP/SL 보정 로직 총괄.
- **`indicator_engine.py`**: RSI, BB, MA 등 기술적 지표 계산 전문 엔진.
- **`market_analyzer.py`**: 지수 DEMA 분석 및 장세(Vibe) 판정 로직.
- **`preset_engine.py`**: 종목별 전략 프리셋(01~09) 관리 및 자동 할당.
- **`pyramiding_engine.py`**: 상승 추세에서의 추가 매수(불타기) 로직.
- **`rebalance_engine.py`**: 포트폴리오 비중 조절 및 자산 재배분 제안 로직.
- **`recovery_engine.py`**: 하락장에서의 평단가 낮추기(물타기) 로직.
- **`retrospective_engine.py`**: 장 마감 후 성과 분석 및 통계 산출.
- **`risk_manager.py`**: 서킷 브레이커 감시 및 리스크 차단 로직.
- **`state_manager.py`**: `trading_state.json` 파일의 입출력 및 무결성 관리.

### 📂 `src/strategy/advisors/` (AI Intelligence)
- **`base.py`**: LLM 어드바이저 공통 인터페이스.
- **`gemini.py`**: Google Gemini API 기반의 핵심 전략 수립 어드바이저.
- **`groq.py`**: Llama 3.1 모델을 활용한 장애 대비용 백업 어드바이저.
- **`multi.py`**: 여러 LLM 모델 간의 우선순위 및 Fallback 관리.

### 📂 `src/strategy/vibe/` (Vibe Framework)
- **`analysis.py`**: Vibe 기반의 시장 시황 분석 보조 로직.
- **`execution.py`**: `ExecutionMixin` 클래스. 7단계 매매 사이클의 상세 실행 흐름.
- **`mock_tester.py`**: 테스트 환경을 위한 가상 시간 및 가상 주문 인터셉터.
- **`strategy.py`**: `VibeStrategy` 메인 클래스. 모든 로직을 통합하는 전략 오케스트레이터.

### 📂 `src/ui/` (Presentation & Input)
- **`interaction.py`**: 사용자 키보드 입력 매핑 및 비동기 작업 큐 처리.
- **`renderer.py`**: TUI 대시보드의 메인 프레임워크 및 전역 레이아웃 관리.
- **`views/ai_logs_view.py`**: AI의 판단 사유와 활동 내역을 상세히 표시.
- **`views/dashboard_view.py`**: 실시간 자산, 지수, 인기 종목 랭킹 요약 표시.
- **`views/holdings_view.py`**: 현재 보유 중인 종목 리스트와 상세 수익률 표시.
- **`views/hot_stocks_view.py`**: 실시간 인기 종목 및 테마 분석 결과 표시.
- **`views/manual_view.py`**: 사용자가 직접 조작할 수 있는 설정 및 제어 가이드 표시.
- **`views/performance_view.py`**: 수익/손실 상위 종목 및 모델별 성과 통계 표시.
- **`views/recommendation_view.py`**: AI가 선정한 당일 추천 종목 리스트 가시화.
- **`views/stock_analysis_view.py`**: 특정 종목에 대한 심층 분석 리포트 표시.
- **`views/trading_logs_view.py`**: 실제 체결된 매매 내역 리스트 가시화.

### 📂 `src/utils/` (Utilities)
- **`notifier.py`**: 텔레그램 메시지 발송 핵심 모듈.
- **`telegram_receiver.py`**: 텔레그램을 통한 원격 명령어 수신 및 처리.
- **`__init__.py`**: ANSI 색상 상수 및 공통 텍스트 처리 유틸리티 정의.

### 📂 `src/workers/` (Background Process)
- **`base.py`**: 모든 비동기 워커의 베이스 클래스 정의.
- **`market_worker.py`**: 시황 분석 및 테마 갱신을 담당하는 주기적 워커.
- **`report_worker.py`**: 주기적 상태 보고 및 텔레그램 전송 워커.
- **`retrospective_worker.py`**: 장 마감 후 성과 복기 및 자동 분석 워커.
- **`sync_worker.py`**: 시세 데이터 및 잔고를 실시간으로 동기화하는 핵심 워커.
- **`trade_worker.py`**: 매매 전략(`run_cycle`)을 반복적으로 실행하는 워커.

---

## 4. 핵심 데이터 흐름 (Core Data Flow)
1. **Sync Stage**: `sync_worker`가 KIS/Naver에서 최신 시세를 수집하여 `DataManager`에 업데이트.
2. **Analysis Stage**: `market_worker`가 현재 장세를 진단하고 AI가 추천 종목 점수를 갱신.
3. **Execution Stage**: `trade_worker`가 1초 주기로 `run_cycle` 실행.
4. **Action Stage**: 조건 충족 시 `ExitManager` 또는 `AI_Confirm`을 거쳐 실제 주문이 `KISAPI`로 전송됨.
5. **Report Stage**: 모든 활동이 `TradingLogManager`를 통해 기록되고 UI와 텔레그램으로 전송됨.

---
## 5. 유지보수 및 갱신 규칙 (Maintenance Rules)

본 문서는 프로젝트의 물리적 구조를 대변하며, 파일 구성이 변경될 경우 반드시 최신화되어야 합니다.

1.  **갱신 트리거**: `src/` 디렉토리 내 파일의 추가, 삭제, 이동 또는 이름 변경 시.
2.  **전수 조사 명령어**: 파일 누락 방지를 위해 반드시 아래 파워쉘 명령어를 실행하여 목록을 대조합니다.
    ```powershell
    Get-ChildItem -Path src -Filter *.py -Recurse | Resolve-Path -Relative
    ```
3.  **정합성 유지**: 신규 파일 추가 시 해당 파일의 `Role`과 `핵심 로직`을 본 문서에 즉시 기술합니다.

---
> [!IMPORTANT]
> 본 명세서는 v1.6.5 기준으로 작성되었으며, 모든 수정 사항은 `GEMINI.md`의 문서 관리 정책을 따릅니다.
