# KIS-Vibe-Trader 대규모 모듈 리팩토링 최종 계획서 (Final)

## 1. 리팩토링 목적 및 배경
현재 `src/strategy.py`의 크기 비대화(약 1,500줄 이상, 84KB)로 인해 코드 수정 시 파급(Side-effect) 추적과 컨텍스트 유지가 매우 어려운 상태입니다.
본 리팩토링은 `GEMINI.md`에 정의된 **시니어 아키텍트의 6대 모듈 중심 객체지향 설계**를 파일 레벨로 분할(Divide and Conquer)하여, 유지보수성과 맥락 기반 AI 어시스턴트(Gemini) 코딩 효율을 극대화하는 데 목적이 있습니다.

## 2. 식별된 문제점 (코드 검수 결과)
1. **아키텍처 불일치**: `GEMINI.md`에는 `PresetStrategyEngine`이 6대 모듈 중 하나로 정의되어 있으나, 현재는 `strategy.py` 내부의 단순 딕셔너리(`PRESET_STRATEGIES`)와 Facade 내부 로직으로 파편화되어 있음.
2. **영속성 책무 혼재**: `trading_state.json`을 읽고 쓰는 영속성(Persistence) 상태 관리가 `VibeStrategy` 본체에 결합되어 있어 단일 책임 원칙(SRP) 위배.
3. **위험 범위 초과**: 한 번의 리팩토링에 `strategy.py` 분할과 `ui/` (TUI) 디렉토리 분할을 동시 진행할 경우 높은 회귀 버그(Regression Bug) 리스크 발생 가능. 전략 분할을 **최우선 1단계**로 국한하는 것이 안전함.

## 3. 최종 리팩토링 아키텍처 (To-Be)

우선순위가 가장 높은 `src/strategy.py`를 `src/engine/` 또는 `src/strategy/` 패키지로 분리합니다.

**📁 `src/strategy/` 내부 모듈 분할 계획**
- **`market_analyzer.py`**: `MarketAnalyzer` 분리 (지수/환율 수집, 위기 감지 및 Vibe 결정)
- **`exit_manager.py`**: `ExitManager` 분리 (익절/손절 계산 로직, Vibe 기반 동적 보정)
- **`recovery_engine.py`**: `RecoveryEngine` 분리 (하락장 대응 물타기 알고리즘)
- **`pyramiding_engine.py`**: `PyramidingEngine` 분리 (상승장 대응 불타기 알고리즘, TP 회피 로직)
- **`alpha_engine.py`**: `VibeAlphaEngine` 분리 (AI 테마 점수 계산, 자율 매매 종목 필터링)
- **`preset_engine.py` [신설]**: `PresetStrategyEngine` 분리 및 구체화 (10대 KIS 공식 전략 체계, `PRESET_STRATEGIES` 상수 및 시뮬레이션 매핑 로직 이관)
- **`advisor.py`**: `GeminiAdvisor` 분리 (LLM 호출, 프롬프트 생성, 결과 파싱/안전장치(Fallback) 전담)
- **`state_manager.py` [신설]**: `trading_state.json` Load/Save 및 메모리 스냅샷 관리 전담 클래스.
- **`facade.py`**: `VibeStrategy` 유지되나, 위 8개 모듈들의 **순수 오케스트레이션(조율) 객체**로 역할 축소. 개별 엔진들에 데이터를 주입하고 인터페이스만 외부에 제공.
- **`__init__.py`**: 기존 `data_manager.py` 및 `main.py`가 호환성 문제 없이 `from src.strategy import VibeStrategy` 형태로 호출 가능하도록 진입점 제공.

## 4. 진행 절차 가이드라인 (Gemini CLI 전용)

안정성을 보장하기 위해 아래 3단계로 **순차적 개발**을 진행합니다.

1. **[1단계] 순수 이관 (Pure Move)**:
   - 로직이나 변수명의 기능적 수정 없이, 클래스들을 그대로 복사하여 새 파일로 쪼개기만 수행.
   - 상태 관리를 `state_manager.py`로, 프리셋 로직을 `preset_engine.py`로 응집력 있게 이동.
2. **[2단계] 의존성 주입 연결 (Dependency Injection)**:
   - 분리된 엔진들이 필요로 하는 공통 모듈(`api`, `GeminiAdvisor`)을 `facade.py` 생성자에서 안전하게 주입.
   - 순환 참조(Circular Import) 발생 시 타입 힌트용 `TYPE_CHECKING`으로 우회.
3. **[3단계] 드라이 런 (Dry Run) 및 UI 후행 작업**:
   - `python main.py`를 실행하여 컴파일 및 임포트 오류가 발생하지 않는지 터미널단 검증.
   - (참고) `src/ui/`에 대한 분할은 본 전략 엔진 리팩토링이 완전무결하게 검증된 이후 **별도의 티켓**으로 진행할 것을 권장.

## 5. 변경 요약 (기존 계획 대비)
> [!IMPORTANT]
> - `PresetStrategyEngine` 모듈의 명확한 독립을 지시사항에 추가.
> - 상태 데이터 관리를 전담하는 `state_manager.py` 신설.
> - 위험 분산을 위해 TUI 리팩토링 범위를 이번 차수에서 제거(지연). 
> - **위 계획서 내용대로 `gemini cli`에 명령하면 설계 사상에 완벽히 부합하는 구조가 완성됩니다.**
