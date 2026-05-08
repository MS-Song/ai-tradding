# 🧪 KIS-Vibe-Trader 통합 테스트 시나리오

본 문서는 `LOGIC_TREE.md`를 기반으로 시스템의 안정성과 정확성을 검증하기 위한 상세 테스트 시나리오를 정의합니다.

## 1. 수동 커맨드 및 UI 상호작용 테스트 (Manual Interaction)
사용자의 키 입력에 따른 기능 수행 및 데이터 일관성을 검증합니다.

| ID | 테스트 항목 | 주입 상황 (Given) | 실행 동작 (When) | 기대 결과 (Then) |
| :--- | :--- | :--- | :--- | :--- |
| **TC-M01** | 수동 매수 (2) | 특정 종목 미보유 상태 | `2` 키로 종목/수량 입력 | 즉시 매수 주문 집행 및 신규 종목에 대한 AI 전략 자동 할당 확인 |
| **TC-M01-2** | 수동 매도 (1) | 특정 종목 10주 보유 상태 | `1` 키로 5주 매도 입력 | 5주 부분 매도 주문, 실시간 수익금 계산 및 로그 기록 확인 |
| **TC-M01-3** | 수동 매도 예외 | 10주 보유 중 20주 매도 입력 | `1` 키로 20주 매도 입력 | 보유 수량(10주)으로 자동 조정되어 전량 매도 집행 확인 |
| **TC-M02** | 임계치 수정 | 보유 종목 TP +5% 상태 | `3` 키로 TP +10% 변경 | `trading_state.json` 반영 및 다음 루프 적용 |
| **TC-M03** | 엔진 설정 변경 | AI 자율 매매 [AUTO] 상태 | `4` 키로 [AUTO] -> [OFF] | AI 추천 종목 발생 시 매수 집행 스킵 |
| **TC-M04** | 심층 분석 호출 | 특정 종목 코드 보유 | `7` 키로 종목 코드 입력 | Gemini 3D 분석 리포트 생성 및 TUI 출력 |
| **TC-M05** | 전략 프리셋 할당 | 표준 전략(00) 적용 중 | `9` 키로 '05(추세)' 할당 | 해당 종목의 TP/SL이 프리셋 값으로 갱신 |
| **TC-M06** | 시스템 설정(S) | 환경변수(.env) 변경 필요 | `S` 키 입력 후 설정 수정 | 데이터 재동기화 및 변경된 설정으로 엔진 재시작 |
| **TC-M07** | 수동 시황 분석 (8) | 분석 주기가 도래하지 않은 상태 | `8` 키 입력 | 즉시 분석 큐 삽입, 시황 진단 및 추천 종목 리스트 갱신 확인 |

## 2. 알고리즘 기반 자동 매매 테스트 (Algorithmic Trading)
사전에 정의된 수식과 조건(수익률, 시간, 현금 비중)에 따른 자동 체결을 검증합니다.

| ID | 테스트 항목 | 주입 상황 (Given) | 실행 동작 (When) | 기대 결과 (Then) |
| :--- | :--- | :--- | :--- | :--- |
| **TC-A01** | 물타기(Recovery) | 수익률 -6% (SL -5%), 현금 40% | `run_cycle` 실행 | 평단 낮추기 매수 집행 및 30분 손절 유예 적용 |
| **TC-A02** | 불타기(Pyramiding) | 수익률 +4% (TP +5%), Bull장 | `run_cycle` 실행 | 추가 매수 집행 및 익절 쿨다운 리셋 확인 |
| **TC-A03** | Phase 3 수익확정 | 14:30 경과, 수익률 +0.8% | Phase 3 진입 시점 | 보유 물량 50% 매도 주문 및 SL +0.2% 상향 |
| **TC-A04** | 익절 쿨다운 | 10분 전 분할 익절 발생 | 수익률 다시 TP 도달 | 매매 스킵 (1시간 쿨다운 이내) |
| **TC-A05** | 긴급 바이패스 | 수익률 +8% (TP +5%) | `run_cycle` 실행 | 쿨다운 무시하고 즉시 전량 익절 집행 |
| **TC-A06** | 현금 비중 보호 | Bear장, 현금 비중 20% 미만 | 물타기/AI매수 조건 충족 | 매매 스킵 (최소 현금 30% 유지 원칙) |

## 3. AI 기반 의사결정 테스트 (AI-Driven Logic)
Gemini의 분석 결과와 시장 상황에 따른 가변적 로직을 검증합니다.

| ID | 테스트 항목 | 주입 상황 (Given) | 실행 동작 (When) | 기대 결과 (Then) |
| :--- | :--- | :--- | :--- | :--- |
| **TC-I01** | VIBE 전환 | 지수 DEMA(20) 하단 이탈 | `determine_market_trend` | VIBE -> Bear/Defensive로 변경 및 TP/SL 보정 |
| **TC-I02** | 상투 매수 방어 | Bull장, 등락률 +7% 과열종목 | AI 매수 컨펌 단계 | `OVERBOUGHT` 판정으로 매수 최종 거절 |
| **TC-I03** | 종목 교체 매매 | 보유 한도(8개) 도달 상태 | 120점 신규 종목 발굴 | 최저점(85점) 종목 매도 후 신규 종목 교체 매수 |
| **TC-I04** | AI 선제 매도 | AI 배치 리뷰에서 'SELL' 판정 | TP/SL 도달 전 상태 | 전략 타이트닝(±0.1%) 또는 즉시 매도 실행 |
| **TC-I05** | 0원 데이터 보호 | 대형주 가격 0원 수신 | AI 분석/매매 호출 | 데이터 오류로 판단하여 기존 상태 유지(Skip) |
| **TC-I06** | 장 초반 안정화 필터 | 09:10 (Stabilizing), Vibe Neutral | AI 매수 시도 | `strict_min` 점수 미달 시 매수 차단 및 로그 기록 확인 |
| **TC-I07** | 수급 사이클 분석 | 매집 가속화(최근 2일 > 3일 평균) | AI 스코어링 단계 | 사이클 가점(+5~15pt) 반영 및 상승 사이클 초입 판정 확인 |
| **TC-I08** | 수급 데이터 2중화 | Naver 수집 성공 / KIS 실패 | `get_investor_trading_trend` | Naver 데이터 우선 채택 및 KIS 보완 데이터(연기금 등) 통합 확인 |

## 4. 인프라 및 워커 안정성 테스트 (Infrastructure)
백그라운드 워커와 데이터 소스의 신뢰성을 검증합니다.

| ID | 테스트 항목 | 주입 상황 (Given) | 실행 동작 (When) | 기대 결과 (Then) |
| :--- | :--- | :--- | :--- | :--- |
| **TC-F01** | API Fallback | KIS API 시세 호출 실패 | 데이터 수집 루프 | Naver XML/JSON 소스로 자동 전환 및 수집 성공 |
| **TC-F02** | 시장 상태 동기화 | 15:30 장 마감 시점 | `MarketWorker` 실행 | `is_market_open=False` 전환 및 매수 로직 중단 |
| **TC-F03** | 사후 복기 워커 | 16:00 장 종료 후 | `RetrospectiveWorker` | 당일 매매 분석 및 `trade_retrospective.json` 생성 |
| **TC-F04** | 상태 영속성 | 강제 종료 후 재시작 | 시스템 초기화 단계 | 이전의 `rejected_stocks`, `strategies` 로드 확인 |

## 5. 스케줄러 및 자동 실행 사이클 테스트 (Scheduled Automation)
사용자의 개입 없이 시간/주기에 의해 자동으로 실행되는 워커 로직을 검증합니다.

| ID | 테스트 항목 | 주입 상황 (Given) | 실행 동작 (When) | 기대 결과 (Then) |
| :--- | :--- | :--- | :--- | :--- |
| **TC-W01** | 자동 시황/전략 업데이트 | 프로그램 실행 중 | 설정 주기(20분) 도래 | 백그라운드 AI 분석 실행 및 `auto_apply` 전략 반영 확인 |
| **TC-W02** | 매매 사이클 (run_cycle) | 장중 실시간 루프 | 1초 주기로 반복 호출 | [매도 감시 -> 매수 엔진 -> AI 컨펌] 순차 실행 확인 |
| **TC-W03** | 자산 정보 동기화 | 장중 자산 변동 발생 | 1분 주기로 반복 호출 | `start_day_asset` 기준 당일 PnL% 및 총 자산 갱신 확인 |

---

## 💡 테스트 구현 가이드 (State Injection)

위 시나리오들을 테스트 코드로 구현할 때 아래의 **Mocking/Injection** 포인트를 활용하십시오.

1.  **시세 데이터 주입**: `api.get_naver_stock_detail` 등을 Mocking하여 특정 수익률(TP/SL 도달) 상황 연출.
2.  **시간 주입**: `datetime.now()`를 Mocking하여 특정 Phase(P1~P4) 상황 연출.
3.  **VIBE 주입**: `strategy.current_market_vibe`를 강제로 `Defensive` 등으로 설정하여 대응 로직 검증.
4.  **AI 응답 주입**: `strategy.ai_advisor.confirm_buy_decision`의 반환값을 `True/False`로 조절하여 매수/거절 로직 검증.

---

## 🛠️ 테스트 코드 매핑 현황 (이중 매핑)
각 시나리오 ID와 실제 구현된 테스트 코드를 매핑하여 관리합니다.

| 시나리오 ID | 테스트 파일명 | 매핑된 함수/클래스 | 비고 |
| :--- | :--- | :--- | :--- |
| **TC-M01** | `tests/test_purchase.py` | `test_buy_stocks` | 매수 API 기본 동작 |
| **TC-M01-2** | `tests/test_sell_logic.py` | `test_sell_api` | 매도 API 기본 동작 |
| **TC-M01-3** | `tests/test_advanced_integration.py` | `test_tc_m01_3_sell_qty_adjustment` | 수량 초과 조정 |
| **TC-M02** | `tests/test_advanced_integration.py` | `test_tc_m02_threshold_modification` | 수동 임계치 수정 |
| **TC-M03** | `tests/test_advanced_integration.py` | `test_tc_m03_ai_auto_toggle` | AI 자율 매매 ON/OFF |
| **TC-M05** | `tests/test_ai_parsers.py` | `test_parse_simulate_preset_strategy` | 전략 응답 파싱 |
| **TC-M07** | `tests/test_advanced_integration.py` | `test_tc_m07_manual_market_analysis` | 수동 시황 분석 |
| **TC-A01** | `tests/test_trading_engines.py` | `test_recovery_engine_trigger` | 물타기 트리거 |
| **TC-A02** | `tests/test_trading_engines.py` | `test_pyramiding_engine_trigger` | 불타기 트리거 |
| **TC-A03** | `tests/test_advanced_integration.py` | `test_tc_a03_phase3_profit_taking` | Phase 3 수익확정 |
| **TC-A04** | `tests/test_advanced_integration.py` | `test_tc_a04_partial_sell_cooldown` | 익절 쿨다운 |
| **TC-A05** | `tests/test_advanced_integration.py` | `test_tc_a05_emergency_bypass_cooldown` | 긴급 바이패스 |
| **TC-A06** | `tests/test_advanced_integration.py` | `test_tc_a06_cash_ratio_protection` | 현금 비중 보호 |
| **TC-I01** | `tests/test_market_analyzer.py` | `test_market_analyzer_bull/bear_vibe` | 장세 판정 로직 |
| **TC-I02** | `tests/test_ai_parsers.py` | `test_parse_final_buy_confirm` | 매수 컨펌 파싱 |
| **TC-I03** | `tests/test_advanced_integration.py` | `test_tc_i03_replacement_logic` | 종목 교체 매매 |
| **TC-I04** | `tests/test_ai_parsers.py` | `test_parse_portfolio_review_json` | 배치 리뷰 파싱 |
| **TC-I05** | `tests/test_advanced_integration.py` | `test_tc_i05_zero_price_protection` | 데이터 무결성 |
| **TC-F01** | `tests/test_fallback.py` | `test_fallback` | AI 장애 대응 로직 |
| **TC-F04** | `tests/test_advanced_integration.py` | `test_tc_f04_state_persistence` | 상태 영속성 (Save/Load) |
| **TC-B01** | `tests/test_exit_manager.py` | `test_exit_manager_vibe_modifiers` | VIBE별 TP/SL 보정 |
| **TC-B02** | `tests/test_exit_manager.py` | `test_exit_manager_phase_adjustment` | 페이즈별 보정 |

> [!NOTE]
> 위 표에 명시되지 않은 시나리오(TC-M04, TC-M06, TC-F02, TC-F03, TC-W계열)는 현재 수동 테스트 기반으로 검증되고 있으며, 향후 인프라 모킹 환경 구축 시 자동화 테스트가 보강될 예정입니다.
