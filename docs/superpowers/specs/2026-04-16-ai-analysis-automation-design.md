# 2026-04-16-ai-analysis-automation-design.md

## 1. 개요
프로그램 시작 시 시황 분석 선행 수행, 전략 만료 시 자동 갱신, AI 분석 실패 시 재시도 로직을 포함하는 매매 안정화 및 자동화 설계입니다.

## 2. 매매 시작 제어 (Initialization & Readiness)
- `VibeStrategy.is_ready`: AI 모드일 경우 초기값 `False`, 수동 모드일 경우 `True`.
- `main.py`: 프로그램 실행 직후 `perform_full_market_analysis()` 호출.
- `src/data_manager.py`: `run_cycle` 및 모든 매매 로직은 `strategy.is_ready`가 `True`일 때만 실행.
- **적용 실패 시 처리**: 시황 분석 데이터가 로드되고 `apply_strategy_config()`가 성공적으로 호출된 시점에 `is_ready = True`로 전환.

## 3. 주기적 시황 분석 (Market Analysis Scheduler)
- `VibeStrategy`에 `last_market_analysis_time` 및 `analysis_interval` 필드 추가.
- `main.py`의 메인 루프 또는 별도 스레드에서 주기 체크:
    - 실전 계좌: 20분 주기.
    - 모의 계좌: 60분 주기.
- 분석 수행 후 설정값이 변경되면 즉시 `trading_state.json`에 동기화.

## 4. 전략 자동 재수립 (Dynamic Re-assignment)
- `run_cycle` 내부 'Time-Stop' 체크 시:
    - 기존 로직: `deadline` 초과 시 단순히 수치 완화.
    - 변경 로직: `auto_assign_preset(code)`를 호출하여 실시간 AI 전략 재수립.
- 전략 수립 실패(`apply_strategy_config` 에러) 시:
    - 1회 즉시 재시도.
    - 재시도 후에도 실패 시: 
        - 매수/불타기/물타기: 진입 보류.
        - 손절(SL): 긴급 위험 상황으로 간주하여 **강제 집행**.

## 5. 구현 계획
1. `VibeStrategy` 내 제어 상태 플래그 및 주기 계산 변수 정의.
2. `perform_full_market_analysis` 로직 캡슐화 및 실패 시 재시도 래퍼 구현.
3. `main.py` 진입점 수정 및 워커 루프에 `is_ready` 체크 로직 삽입.
4. `run_cycle`의 만료 로직을 `auto_assign_preset` 호출로 리팩토링.
