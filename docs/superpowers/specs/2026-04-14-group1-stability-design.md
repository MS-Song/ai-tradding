# 📑 Spec: Group 1 - AI Stability & Resilience (Verified ID Mapping)

## 1. 개요
실제 API 테스트 결과(2026-04-14)를 바탕으로 Gemini v3.x/v2.x 모델의 실제 호출 ID를 정의하고, 부하(Timeout) 발생 시의 대응 시나리오를 구체화합니다.

## 2. 검증된 Gemini 모델 매핑 및 비용 최적화 순위 (요구사항 1)

비용 효율성을 극대화하기 위해 상대적으로 저렴한 **Lite 모델을 1순위**로 사용하고, 실패 시에만 고성능 Pro 모델로 Fallback합니다.

| 순위 | 모델 표시명 (UI) | **실제 API 호출 ID (Model ID)** | 상태 |
| :--- | :--- | :--- | :--- |
| **1** | **Gemini 3.1 Lite** | `gemini-3.1-flash-lite-preview` | **기본값 (비용 효율적)** |
| **2** | **Gemini 3.1 Pro** | `gemini-3.1-pro-preview` | **1순위 Fallback (고성능)** |
| **3** | **Gemini 3.0 Pro** | `gemini-3-pro-preview` | **2순위 Fallback** |
| **4** | **Gemini 3.0 Lite** | `gemini-3-flash-preview` | |
| **5** | **Gemini 2.5 Pro** | `gemini-2.5-pro` | |
| **6** | **Gemini 2.5 Lite** | `gemini-2.5-flash-lite` | **최후 보루** |

## 3. 타임아웃 및 Fallback 상세 전략
- **기본 모델**: 호출 빈도가 가장 높은 시황 분석 및 리포트 생성에 `3.1 Lite`를 기본 적용하여 비용 절감.
- **타임아웃 설정**: 모든 Gemini 모델 호출 시 최대 대기 시간을 **60초**로 설정하여 부하 시에도 충분한 응답 대기 시간을 확보.
- **순차 전환**: 60초 초과(Timeout) 또는 API 에러 발생 시 즉시 리스트의 다음 모델로 교체하여 재시도.
- **데이터 영속성 (`trading_state.json`)**:
```json
{
    "ai_config": {
        "preferred_model": "gemini-3.1-flash-lite-preview",
        "fallback_sequence": [
            "gemini-3.1-flash-lite-preview",
            "gemini-3.1-pro-preview",
            "gemini-3-pro-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite"
        ]
    }
}
```
