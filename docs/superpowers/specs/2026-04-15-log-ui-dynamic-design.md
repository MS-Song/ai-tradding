# Log UI Dynamic Resizing & Reverse Order Design

## 1. 개요
로그 시스템의 가독성을 높이기 위해 메인 화면과 상세 로그 화면(L)의 UI 레이아웃을 동적으로 개선합니다.

## 2. 주요 변경 사항
### A. 메인 화면 로그 역순 출력
- `src/ui/renderer.py`의 `draw_tui` 하단 로그 렌더링 로직에서 `reversed(logs)`를 사용하여 최신 로그가 하단 바 바로 위에 표시되도록 변경.

### B. 로그 화면(L) 동적 레이아웃
- `draw_trading_logs` 함수 내 출력 비율 최적화:
    - 거래(Trade) 영역: 전체 화면 높이(`th`)의 최대 70%까지 할당.
    - 로그(Config) 영역: `전체 높이 - 거래 영역 - 상단/하단 여백`으로 나머지 공간 전체 할당.
    - 거래 데이터가 적을 경우 거래 영역 높이를 유연하게 줄여 로그 영역이 확장되도록 구현.

## 3. 구현 로직 (Pseudocode)
```python
# 거래:로그 높이 동적 계산
total_height = th
trade_max_height = int(total_height * 0.7)
trade_count = len(trades)
trade_rows = min(trade_count, trade_max_height)

# 나머지 공간을 로그 영역으로 할당
log_rows = total_height - trade_rows - 헤더_푸터_여백
```

## 4. 기대 효과
- 최신 정보 확인 용이성 확보 (역순 정렬).
- 화면 공간 활용 최적화 (동적 레이아웃).
