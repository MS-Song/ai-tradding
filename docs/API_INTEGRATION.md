# 🔌 API 및 연동 규격서

본 문서는 KIS-Vibe-Trader에서 사용하는 외부 API 및 연동 규격을 상세히 설명합니다.

## 1. 한국투자증권 (KIS) API

국내 주식 매매 및 계좌 관리를 위한 핵심 API입니다.

### 인증 방식 (Authentication)
*   **방식**: OAuth 2.0 (토큰 기반).
*   **헤더**: `authorization`, `appkey`, `appsecret`, `tr_id`.
*   **구현**: `src/auth.py`에서 토큰 발급 및 자동 갱신을 관리합니다.

### 주요 엔드포인트
| 기능 | 엔드포인트 | TR_ID |
| :--- | :--- | :--- |
| **잔고 조회** | `/uapi/domestic-stock/v1/trading/inquire-balance` | `VTTC8434R` (모의), `TTTC8434R` (실전) |
| **현재가 조회** | `/uapi/domestic-stock/v1/quotations/inquire-price` | `FHKST01010100` |
| **매수 주문** | `/uapi/domestic-stock/v1/trading/order-cash` | `VTTC0802U` (모의), `TTTC0802U` (실전) |
| **매도 주문** | `/uapi/domestic-stock/v1/trading/order-cash` | `VTTC0801U` (모의), `TTTC0801U` (실전) |

## 2. 네이버 금융 (Naver Finance)

실시간 시장 심리 분석 및 종목 펀더멘털 데이터 수집을 위해 활용합니다.

### 제공 기능
*   **인기 검색 종목**: `sise/lastsearch2.naver` (상위 20종목).
*   **거래량 상위 종목**: `sise/sise_quant.naver` (상위 40종목).
*   **종목 상세 정보**: PER, PBR, 배당수익률 및 업종 분석 데이터.
*   **뉴스 헤드라인**: 개별 종목의 실시간 뉴스 감성 분석을 위한 데이터.

### 구현 방식
*   **도구**: `requests` 및 `BeautifulSoup4`를 활용한 데이터 추출.
*   **캐싱**: `KISAPI` 클래스에서 순위 데이터(60초) 및 종목 상세(3600초) 캐시를 적용합니다.

## 3. 야후 파이낸스 (Yahoo Finance)

글로벌 시장 지수 및 환율 데이터 수집을 위해 활용합니다.

### 수집 지수
*   국내: `^KS11` (코스피), `^KQ11` (코스닥).
*   미국: `^IXIC` (나스닥), `^DJI` (다우), `^GSPC` (S&P500).
*   기타: `^VIX` (변동성 지수), `USDKRW=X` (환율).
*   선물: `NQ=F` (나스닥 선물), `ES=F` (S&P 선물).

### 구현 방식
*   **엔드포인트**: `query1.finance.yahoo.com/v8/finance/chart/{symbol}`.
*   **주기**: `index_update_worker` 스레드에서 5초마다 실시간 업데이트를 수행합니다.

## 4. Google Gemini API

고수준 전략 수립 및 종목 분석을 위한 생성형 AI API입니다.

### 활용 모델
*   **주요 모델**: `gemini-1.5-flash` 또는 `gemini-2.5-flash`.

### 제공 기능
*   **전략적 조언 (Advice)**: 시장 Vibe, 포트폴리오 상태를 반영한 3줄 요약 전략 제시.
*   **상세 분석 리포트**: AI가 발굴한 추천 종목에 대한 심층 투자 근거, 목표가, 리스크 분석.

### 구현 방식
*   **엔드포인트**: `generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent`.
*   **인증**: `.env` 파일의 `GOOGLE_API_KEY`를 사용합니다.
