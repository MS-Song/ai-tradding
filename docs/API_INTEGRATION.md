# 🔌 API 및 연동 규격서 (v2.4)

본 문서는 AI-Vibe-Trader 트레이딩 엔진에서 연동하는 외부 브로커 API, 금융 데이터 API, LLM API의 세부 규격을 정의합니다.

---

## 1. 한국투자증권 (KIS) Open API

국내 주식 주문 집행, 잔고 조회, 실시간 시세 조회를 위한 메인 브로커 API입니다.

### 인증 방식 (OAuth 2.0)
*   **엔드포인트**: `/oauth2/tokenP`
*   **헤더**: `content-type: application/json`
*   **토큰 수명**: 24시간 (자동 갱신 및 캐싱 지원)
*   **속도 제한**: 초당 15회 (`TokenBucketRateLimiter` 적용)

### 주요 트랜잭션 (TR_ID)
| 기능 | 엔드포인트 | TR_ID (실전 / 모의) |
| :--- | :--- | :--- |
| **주식 잔고 조회** | `/uapi/domestic-stock/v1/trading/inquire-balance` | `TTTC8434R` / `VTTC8434R` |
| **주식 현재가 시세** | `/uapi/domestic-stock/v1/quotations/inquire-price` | `FHKST01010100` |
| **주식 현금 매수** | `/uapi/domestic-stock/v1/trading/order-cash` | `TTTC0802U` / `VTTC0802U` |
| **주식 현금 매도** | `/uapi/domestic-stock/v1/trading/order-cash` | `TTTC0801U` / `VTTC0801U` |
| **투자자별 매매동향** | `/uapi/domestic-stock/v1/quotations/inquire-investor` | `FHKST01010900` |
| **실시간 체결 통보** | WebSocket (`ws://ops.koreainvestment.com:21000`) | `H0STCNI0` |

---

## 2. 키움증권 (Kiwoom Open API)

한국투자증권과 동일한 규격으로 완전 호환되는 듀얼 브로커 API입니다.

### 인증 및 통신 방식
*   **인증**: REST OAuth 2.0 토큰 발급 및 세션 유지 (`src/broker/kiwoom.py`)
*   **속도 제한**: 초당 5회 (키움 자체 레이트 리밋 규격 준수)
*   **실시간 웹소켓**: `kiwoom_ws_worker`를 통해 실시간 호가/체결 데이터 수신 및 인메모리 Hot-swap.

### 주요 기능
*   계좌 예수금 및 보유 종목 평가액 조회
*   국내 주식 시장가/지정가 매수 및 매도 주문
*   실시간 시세 피드 수신

---

## 3. 네이버 증권 (Naver Mobile Official JSON API)

네이버 금융 웹페이지 개편에 맞춰 기존 HTML 파싱을 폐기하고 전면 모바일 공식 REST API로 전환하여 초고속 동기화를 보장합니다.

### 주요 엔드포인트
| 기능 | 엔드포인트 | 반환 형태 | 비고 |
| :--- | :--- | :--- | :--- |
| **실시간 검색 상위** | `https://m.stock.naver.com/api/stocks/searchTop` | JSON | 실시간 관심/인기 TOP 20 |
| **거래량 상위** | `https://m.stock.naver.com/api/stocks/quantTop` | JSON | 거래량 폭발 종목군 |
| **거래대금 상위** | `https://m.stock.naver.com/api/stocks/priceTop` | JSON | 주도 시장 자금 유입 종목군 |
| **종목 상세/펀더멘털** | `https://m.stock.naver.com/api/stock/{code}/integration` | JSON | PER, PBR, EPS, BPS, 시가총액 |
| **종목별 뉴스** | `https://m.stock.naver.com/api/news/stock/{code}` | JSON | AI 감성 분석용 실시간 뉴스 |
| **테마 목록** | `https://m.stock.naver.com/api/stocks/theme` | JSON | 전체 264개 테마 및 등락률 |
| **테마별 구성 종목** | `https://m.stock.naver.com/api/stocks/theme/{themeCode}` | JSON | 테마 내 주도주 및 편입 종목 |

### 고속 병렬 처리
*   `ThreadPoolExecutor(max_workers=8)`를 활용하여 264개 전 테마 및 1,000여 개 구성 종목을 수 초 내에 비동기 수집.
*   캐시 정책: 테마/순위 데이터 60초 캐싱, 종목 상세 펀더멘털 3,600초 캐싱.

---

## 4. 야후 파이낸스 (Yahoo Finance)

글로벌 매크로 지표 및 환율 수집을 위한 백업 및 실시간 데이터 소스입니다.

*   **엔드포인트**: `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}`
*   **수집 지수**:
    *   국내 지수: `^KS11` (KOSPI), `^KQ11` (KOSDAQ)
    *   해외 지수: `^IXIC` (NASDAQ), `^DJI` (Dow Jones), `^GSPC` (S&P 500)
    *   변동성 및 환율: `^VIX`, `USDKRW=X`
    *   선물: `NQ=F` (나스닥 100 선물), `ES=F` (S&P 500 선물)
*   **스케줄러**: `IndexUpdateWorker`를 통해 5초 주기로 업데이트.

---

## 5. 인공지능 (LLM) 엔진 API

### Google Gemini API
*   **주요 모델**: 최신 `gemini-2.5-flash`, `gemini-2.5-pro` (또는 사용자 설정 Gemini 3 계열)
*   **역할**: 시장 VIBE 시황 브리핑, 최종 매수 컨펌(Buy Confirm), 종목 배치 리뷰(Batch Review), KIS 프리셋 최적 전략 추천, 당일 매매 사후 복기(Retrospective).
*   **라이브러리**: Google Gen AI SDK (`google-genai`)
*   **운영 시간 제한**: 불필요한 토큰 소모 방지를 위해 자동 분석은 장중(08:40~15:50)에만 구동.

### Groq API (Fail-over 백업)
*   **주요 모델**: `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`
*   **역할**: Gemini API 장애, 레이트 리밋, 네트워크 지연 시 0초 내 무중단 페일오버 추론 제공.
*   **엔드포인트**: `https://api.groq.com/openai/v1/chat/completions` (OpenAI 호환 포맷)
