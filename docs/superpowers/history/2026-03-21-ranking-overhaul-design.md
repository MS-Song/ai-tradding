# Design Spec: Ranking System Overhaul (Naver Finance Integration)

## 1. 개요 (Overview)
- **목적**: 기존 KIS 증권 API의 상승/하락률 랭킹을 제거하고, 네이버 금융의 실시간 인기 검색 및 거래량 상위 종목 데이터로 교체.
- **주요 변경 사항**:
    - KIS API 기반의 `_get_ranking` 메서드 삭제.
    - 네이버 금융 크롤링 기반의 `_get_naver_hot_stocks` 메서드 추가.
    - 데이터 수집량 확대 (100개) 및 화면 출력 제한 (10개).
    - 상장폐지 위험 종목(관리/정지 등) 필터링 로직 도입.
    - 하단 TUI 레이아웃 변경 (Hot Stocks / Volume Stocks).

## 2. 데이터 수집 상세 (Data Collection)

### 2.1 대상 소스
1. **실시간 인기 검색어**: `https://finance.naver.com/sise/last_7.naver` (Top 20 내외)
2. **거래량 상위 (코스피/코스닥)**: `https://finance.naver.com/sise/sise_quant.naver` (Top 100)

### 2.2 필터링 규칙 (Filtering)
- 다음 키워드가 종목명에 포함된 경우 수집 리스트에서 즉시 제외:
    - `관리`, `정지`, `환기`, `정리매매`, `단기과열`
- 우선주 제외 (기존 로직 유지): `우`, `우A`, `우B` 등.

### 2.3 데이터 구조 (Interface)
```python
{
    "mkt": str,      # "KSP" | "KDQ"
    "code": str,     # 6자리 종목 코드
    "name": str,     # 종목명
    "price": float,  # 현재가
    "rate": float,   # 등락률 (%)
    "vol": int       # 거래량
}
```

## 3. 아키텍처 및 구현 설계 (Architecture)

### 3.1 `src/api.py` 변경
- **삭제**: `_get_ranking`, `get_top_gainers`, `get_top_losers`
- **추가**: `get_naver_hot_stocks()`, `get_naver_volume_stocks()`
- **기술**: `requests` + `BeautifulSoup` (또는 정규식)을 활용한 크롤링.
- **캐싱**: 120초(2분) 동안 수집 데이터 캐시 유지.

### 3.2 `main.py` 변경
- **전역 변수 변경**:
    - `_cached_gains_raw`, `_cached_loses_raw` 삭제.
    - `_cached_hot_raw`, `_cached_vol_raw` 추가.
- **`draw_tui` 레이아웃 수정**:
    - 하단 랭킹 섹션의 'TOP GAINERS' -> '🔥 HOT SEARCH (10)'로 변경.
    - 하단 랭킹 섹션의 'TOP LOSERS' -> '📊 VOLUME TOP (10)'으로 변경.
    - 출력 개수를 5개에서 10개로 확대 (터미널 높이에 따라 유연하게 조절).

## 4. 예외 처리 및 안정성 (Error Handling)
- 네이버 서버 응답 지연 시 타임아웃(3초) 처리 및 빈 리스트 반환.
- 크롤링 실패 시 `logger.error` 기록 및 이전 캐시 데이터 유지.
- KIS API Rate Limit(1.1초)과는 별개로 동작하므로 지연 시간 최소화.

## 5. 성공 기준 (Success Criteria)
1. 실시간 인기 검색어와 거래량 상위 종목이 네이버 금융과 일치하게 표시됨.
2. 관리종목 등이 화면에 노출되지 않음.
3. 100개를 수집하더라도 TUI 성능 저하가 없어야 함.
