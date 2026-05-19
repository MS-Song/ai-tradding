# 📄 AI-Vibe-Trader Program Specifications (v2.3.260518)







## 1. 개요 (Overview)



본 시스템은 국내 주요 증권사(KIS/Kiwoom) API와 네이버 금융 데이터를 결합하여, 시장의 분위기(VIBE)를 진단하고 AI 기반의 자율 트레이딩을 수행하는 엔진입니다. 본 명세서는 시스템의 모든 물리적 구성 파일(Total 71 Files)과 각 파일의 상세 역할을 전수 기술합니다. v2.0에서는 멀티 브로커(KIS/Kiwoom) 통합 지원, 중앙 집중식 API 속도 제한(Rate Limiting), 그리고 강화된 자율 매매 로직이 적용되었습니다. v2.2부터는 리눅스 호환성 극대화를 위한 Docker 배포판이 전격 추가되었으며, v2.3부터는 컨테이너 외부 볼륨 트리거 및 호스트 모니터 헬퍼 기반의 Docker 안전 자동 업데이트 시스템이 추가되었습니다.







---







## 2. 프로젝트 디렉토리 구조 (Directory Structure)







```text



AI-Vibe-Trader/



├── .github/

│   └── workflows/

│       └── release.yml     # GitHub Actions 자동 CI/CD 배포 파이프라인

├── main.py                 # 프로그램 진입점 및 시스템 오케스트레이션



├── Dockerfile              # 리눅스 Docker 컨테이너 사양서



├── docker-compose.yml      # Docker Compose 대화형(TUI) 서비스 정의서



├── docker_build.sh         # 리눅스 Docker 이미지 빌드 스크립트



├── docker_run.sh           # 리눅스 Docker TUI 컨테이너 가동 스크립트

├── docker_build.ps1        # Windows Docker 이미지 빌드 파워쉘 스크립트

├── docker_build.bat        # Windows Docker 이미지 빌드 배치 파일

├── docker_run.ps1          # Windows Docker TUI 컨테이너 가동 파워쉘 스크립트 (볼륨 버그 방어)

├── docker_run.bat          # Windows Docker TUI 컨테이너 가동 배치 파일



├── src/



│   ├── api/                # 외부 연동 (KIS, Kiwoom, 네이버, 야후)



│   ├── data/               # 데이터 스키마 및 상태



│   ├── strategy/           # 핵심 연산 및 매매 엔진



│   │   ├── advisors/       # LLM 전략 자문



│   │   └── vibe/           # Vibe 기반 실행 믹스인



│   ├── ui/                 # 인터페이스 및 렌더링



│   │   └── views/          # 탭별 독립 화면 모듈



│   ├── utils/              # 알림 및 유틸리티



│   └── workers/            # 백그라운드 워커



├── scripts/



│   ├── build/              # OS별 빌드 및 배포 자동화 스크립트
│   ├── docker_update_monitor.sh  # Docker 자동 업데이트 감시 Linux 호스트 헬퍼
│   └── docker_update_monitor.ps1 # Docker 자동 업데이트 감시 Windows 호스트 헬퍼



└── tests/                  # 테스트 스위트



```







---







## 3. 파일별 상세 명세 (Exhaustive File List)







### 📂 Root Files



- **`main.py`**: 프로그램 진입점. 시스템 초기화 및 모든 백그라운드 워커를 가동합니다.



- **`Dockerfile`**: 리눅스 환경 가상화를 위한 파이썬 3.11-slim 기반 경량 컨테이너 정의서. 타임존(KST) 및 한글 로케일(C.UTF-8)을 영속 세팅하여 TUI가 깨지지 않게 보장합니다.



- **`docker-compose.yml`**: TUI 대화형 가동을 위한 Pseudo-TTY 설정, 호스트 볼륨 바인드 및 host 네트워크 구성이 선언된 컴포즈 설정서.



- **`docker_build.sh`**: 리눅스 터미널에서 이미지를 한 번에 최적화하여 빌드해 주는 쉘 스크립트.



- **`docker_run.sh`**: 파일 볼륨 마운트 오작동을 방지하는 사전 touch 로직 및 중복 컨테이너 제거 기능을 담은 대화형 TUI 구동 스크립트.

- **`docker_build.ps1`**: Windows PowerShell 환경에서 Docker Desktop 기반으로 최적화된 이미지를 안전하게 빌드해 주는 스크립트.

- **`docker_build.bat`**: Windows cmd 및 더블 클릭 환경에서 편리하게 빌드를 실행할 수 있도록 `docker_build.ps1`을 호출해 주는 배치 파일.

- **`docker_run.ps1`**: Windows PowerShell 환경에서 볼륨 마운트 시 발생할 수 있는 '폴더/파일 오인 마운트 버그'를 사전에 방지(touch 로직)하고, 중복 가동 중인 컨테이너를 정리하여 대화형 TUI 환경을 안전하게 열어주는 구동 스크립t.

- **`docker_run.bat`**: Windows cmd 및 더블 클릭 환경에서 편리하게 TUI 컨테이너를 구동할 수 있도록 `docker_run.ps1`을 호출해 주는 배치 파일.



- **`run_all_tests.py`**: 프로젝트 내 모든 `pytest` 기반 테스트를 일괄 실행하는 파이썬 스크립트.



- **`run_tests.bat`**: Windows CMD 환경에서 테스트를 간편하게 실행하기 위한 배치 파일.



- **`run_tests.ps1`**: Windows PowerShell 환경에서 테스트를 간편하게 실행하기 위한 스크립트.



- **`src/auth.py`**: KIS API 인증 토큰 관리 및 보안 헤더 생성을 담당합니다.



- **`src/config_init.py`**: `.env` 설정 로드 및 시스템 환경 변수 초기화를 수행합니다.



- **`src/data_manager.py`**: 메모리 상의 전역 데이터를 관리하며, 영속성 저장소와 실시간 동기화합니다.



- **`src/logger.py`**: 거래 내역 및 AI 활동을 기록하는 통합 로깅 시스템입니다.



- **`src/theme_engine.py`**: 실시간 인기 테마 및 업종 데이터를 분석하여 정제합니다.



- **`src/updater.py`**: GitHub 릴리스 기반의 자동 업데이트 및 버전 관리 유틸리티입니다.



- **`src/usage_tracker.py`**: 일일 API 호출 횟수 및 토큰 사용량을 추적합니다.
- **`scripts/docker_update_monitor.sh`**: Docker 배포판 자동 업데이트를 백그라운드에서 감시하고 호스트 측에서 재빌드/재기동해 주는 Linux 호스트용 쉘 스크립트.
- **`scripts/docker_update_monitor.ps1`**: Docker 배포판 자동 업데이트를 백그라운드에서 감시하고 호스트 측에서 재빌드/재기동해 주는 Windows 호스트용 PowerShell 스크립트.

- **`.github/workflows/release.yml`**: GitHub Actions 기반의 자동 통합 테스트 실행, Windows/Linux 바이너리 자동 빌드 및 릴리즈 첨부, 그리고 최적화된 Docker TUI 이미지를 빌드하여 Docker Hub(`song7749/ai-tradding`)로 자동 배포(latest & 버전 태그 부여)하는 핵심 CI/CD 워크플로우 정의서.







### 📂 `src/api/` (External APIs)



- **`base.py`**: API 클라이언트의 베이스 추상 클래스 및 Token Bucket 기반 Rate Limiter 포함.



- **`kis.py`**: 한국투자증권 실시간 시세, 투자자 매매동향(수급) 조회 및 주문 집행 핵심 모듈.트를 간편하게 실행하기 위한 배치 파일.



- **`run_tests.ps1`**: Windows PowerShell 환경에서 테스트를 간편하게 실행하기 위한 스크립트.



- **`src/auth.py`**: KIS API 인증 토큰 관리 및 보안 헤더 생성을 담당합니다.



- **`src/config_init.py`**: `.env` 설정 로드 및 시스템 환경 변수 초기화를 수행합니다.



- **`src/data_manager.py`**: 메모리 상의 전역 데이터를 관리하며, 영속성 저장소와 실시간 동기화합니다.



- **`src/logger.py`**: 거래 내역 및 AI 활동을 기록하는 통합 로깅 시스템입니다.



- **`src/theme_engine.py`**: 실시간 인기 테마 및 업종 데이터를 분석하여 정제합니다.



- **`src/updater.py`**: GitHub 릴리스 기반의 자동 업데이트 및 버전 관리 유틸리티입니다.



- **`src/usage_tracker.py`**: 일일 API 호출 횟수 및 토큰 사용량을 추적합니다.
- **`scripts/docker_update_monitor.sh`**: Docker 배포판 자동 업데이트를 백그라운드에서 감시하고 호스트 측에서 재빌드/재기동해 주는 Linux 호스트용 쉘 스크립트.
- **`scripts/docker_update_monitor.ps1`**: Docker 배포판 자동 업데이트를 백그라운드에서 감시하고 호스트 측에서 재빌드/재기동해 주는 Windows 호스트용 PowerShell 스크립트.







### 📂 `src/api/` (External APIs)



- **`base.py`**: API 클라이언트의 베이스 추상 클래스 및 Token Bucket 기반 Rate Limiter 포함.



- **`kis.py`**: 한국투자증권 실시간 시세, 투자자 매매동향(수급) 조회 및 주문 집행 핵심 모듈.



- **`kiwoom.py`**: 키움증권 REST API 기반 잔고/체결/주문 연동 모듈.



- **`naver.py`**: 네이버 금융 뉴스, 상세 시세, 랭킹 수집.



- **`yahoo.py`**: 글로벌 지수(NASDAQ 등) 및 해외 시세 수집.



- **`__init__.py`**: API 팩토리 및 초기화.







### 📂 `src/data/` (Data Models)



- **`state.py`**: 시스템의 영속적 상태를 정의하는 데이터 모델 및 초기값 설정.







### 📂 `src/strategy/` (Analysis & Calculation)



- **`alpha_engine.py`**: AI 추천 점수와 퀀트 지표를 결합한 최종 매수 점수 산출. 시총 1000억 미만 및 ETF를 원천 제외하는 필터링 로직 포함.



- **`chart_renderer.py`**: TUI 내에서 간단한 텍스트 기반 차트 렌더링 지원.



- **`constants.py`**: 전략 전반에서 사용하는 고정 상수(타임아웃, 임계치 등) 정의.



- **`exit_manager.py`**: Vibe와 Phase에 따른 실시간 TP/SL 보정 로직 총괄. 사용자가 0으로 설정한 경우 보정 및 Guard를 생략하는 'Zero Threshold' 정책 적용.



- **`indicator_engine.py`**: RSI, BB, MA 등 기술적 지표 계산 전문 엔진.



- **`market_analyzer.py`**: 지수 DEMA 분석 및 장세(Vibe) 판정 로직.



- **`preset_engine.py`**: 종목별 전략 프리셋(01~09) 관리 및 자동 할당.



- **`pyramiding_engine.py`**: 상승 추세에서의 추가 매수(불타기) 로직.



- **`rebalance_engine.py`**: 포트폴리오 비중 조절 및 자산 재배분 제안 로직.



- **`recovery_engine.py`**: 하락장에서의 평단가 낮추기(물타기) 로직.



- **`retrospective_engine.py`**: 장 마감 후 성과 분석 및 통계 산출.



- **`risk_manager.py`**: 서킷 브레이커 감시 및 리스크 차단 로직.



- **`state_manager.py`**: `trading_state.json` 파일의 입출력 및 무결성 관리.



- **`__init__.py`**: 전략 모듈 패키지 초기화.







### 📂 `src/strategy/advisors/` (AI Intelligence)



- **`base.py`**: LLM 어드바이저 공통 인터페이스.



- **`gemini.py`**: Google Gemini API 기반의 핵심 전략 수립 어드바이저.



- **`groq.py`**: Llama 3.1 모델을 활용한 장애 대비용 백업 어드바이저.



- **`multi.py`**: 여러 LLM 모델 간의 우선순위 및 Fallback 관리.



- **`__init__.py`**: 어드바이저 패키지 초기화.







### 📂 `src/strategy/vibe/` (Vibe Framework)



- **`analysis.py`**: Vibe 기반의 시장 시황 분석 보조 로직.



- **`execution.py`**: `ExecutionMixin` 클래스. 7단계 매매 사이클의 상세 실행 흐름. 시스템 시작 초기 보호(Startup Protection) 및 비활성(0) 처리 로직 포함.



- **`mock_tester.py`**: 테스트 환경을 위한 가상 시간 및 가상 주문 인터셉터.



- **`strategy.py`**: `VibeStrategy` 메인 클래스. 모든 로직을 통합하는 전략 오케스트레이터.



- **`__init__.py`**: Vibe 프레임워크 초기화.







### 📂 `src/ui/` (Presentation & Input)



- **`interaction.py`**: 사용자 키보드 입력 매핑 및 비동기 작업 큐 처리.



- **`renderer.py`**: TUI 대시보드의 메인 프레임워크 및 전역 레이아웃 관리.



- **`views/ai_logs_view.py`**: AI의 판단 사유와 활동 내역을 상세히 표시.



- **`views/dashboard_view.py`**: 실시간 자산, 지수, 인기 종목 랭킹 요약 표시.



- **`views/holdings_view.py`**: 현재 보유 중인 종목의 통합 정보(현재가, 등락률, PER, PBR, 시총, 거래량, 거래금액, 외국인/기관 수급, 수익률, 평가손액) 표시.



- **`views/hot_stocks_view.py`**: 실시간 인기 종목 및 테마 분석 결과를 통합 포맷으로 표시. 배당% 포함.



- **`views/manual_view.py`**: 사용자가 직접 조작할 수 있는 설정 및 제어 가이드 표시.



- **`views/performance_view.py`**: 수익/손실 상위 종목 및 모델별 성과 통계 표시.



- **`views/recommendation_view.py`**: AI가 선정한 당일 추천 종목을 통합 포맷으로 표시. 테마, AI점수, 발굴근거 전용 컬럼 포함.



- **`views/stock_analysis_view.py`**: 특정 종목에 대한 심층 분석 리포트 표시.



- **`views/stock_table_renderer.py`**: D/B/H 3대 리포트 공통 종목 테이블 렌더링 유틸리티. 11개 Core 컬럼(코드, 종목명, 현재가, 등락률, PER, PBR, 시총, 거래량, 거래금액, 외국인, 기관) 통합 포맷 제공.



- **`views/trading_logs_view.py`**: 실제 체결된 매매 내역 리스트 가시화.



- **`views/__init__.py`**: 뷰 패키지 초기화.







### 📂 `src/utils/` (Utilities)



- **`notifier.py`**: 텔레그램 메시지 발송 핵심 모듈.



- **`telegram_receiver.py`**: 텔레그램을 통한 원격 명령어 수신 및 처리.



- **`__init__.py`**: ANSI 색상 상수 및 공통 텍스트 처리 유틸리티 정의.







### 📂 `src/workers/` (Background Process)



- **`base.py`**: 모든 비동기 워커의 베이스 클래스 정의.



- **`kis_ws_worker.py`**: 한국투자증권 WebSocket 기반 실시간 호가/체결 데이터 수신 워커.



- **`kiwoom_ws_worker.py`**: 키움증권 WebSocket 기반 실시간 호가/체결 데이터 수신 워커.



- **`market_worker.py`**: 시황 분석 및 테마 갱신을 담당하는 주기적 워커.



- **`recommendation_worker.py`**: 수동 전환된 추천 종목을 감시하여 자동 모드로 복구하는 워커.



- **`report_worker.py`**: 주기적 상태 보고 및 텔레그램 전송 워커.



- **`retrospective_worker.py`**: 장 마감 후 성과 복기 및 자동 분석 워커.



- **`sync_worker.py`**: 시세 데이터 및 잔고를 실시간으로 동기화하는 핵심 워커.



- **`trade_worker.py`**: 매매 전략(`run_cycle`)을 반복적으로 실행하는 워커.







---







## 4. 핵심 데이터 흐름 (Core Data Flow)



1. **Sync Stage**: `sync_worker`가 KIS/Kiwoom/Naver에서 최신 시세를 수집하여 `DataManager`에 업데이트.



2. **Analysis Stage**: `market_worker`가 현재 장세를 진단하고 AI가 추천 종목 점수를 갱신.



3. **Execution Stage**: `trade_worker`가 `run_cycle`을 주기적으로 실행하여 매매 조건 검토.



4. **Action Stage**: 조건 충족 시 `ExitManager` 또는 `AI_Confirm`을 거쳐 실제 주문이 활성 브로커(KIS/Kiwoom)로 전송됨.



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



> 본 명세서는 v2.0.260518 기준으로 작성되었으며, 모든 수정 사항은 `GEMINI.md`의 문서 관리 정책을 따릅니다.



