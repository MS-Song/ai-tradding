# 🤖 KIS-Vibe-Trader: The Intelligent AI Trading Engine

[![Build and Release](https://github.com/MS-Song/ai-tradding/actions/workflows/release.yml/badge.svg)](https://github.com/MS-Song/ai-tradding/actions/workflows/release.yml)
[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Powered by Gemini](https://img.shields.io/badge/AI-Gemini%202.5%20Flash-blueviolet.svg)](https://aistudio.google.com/)
[![Market](https://img.shields.io/badge/Market-Korea%20Stock-red.svg)](https://apiportal.koreainvestment.com/)
[![Version](https://img.shields.io/badge/version-1.2.1-green.svg)](https://github.com/MS-Song/ai-tradding/releases)

> **"단순한 매매가 아닙니다. 시장의 흐름(Vibe)을 읽는 AI 자율 트레이딩 엔진입니다."**
> KIS-Vibe-Trader는 시니어 아키텍트의 설계 사상이 반영된 객체지향형 트레이딩 시스템으로, 시장 감성(Vibe)과 AI 분석(Gemini)을 결합하여 최적의 매매 전략을 자율적으로 도출합니다.

---

## 🌟 Key Features (핵심 기능)

- **🧠 Vibe-Alpha Engine**: 단순히 가격만 보는 것이 아니라, 시장 전체의 분위기(Vibe)를 분석합니다. 상승장, 하락장, 패닉 상태를 스스로 판단하여 리스크를 동적으로 제어합니다.
- **✨ AI-Driven Decision Support**: Google Gemini API를 통해 월스트리트 수석 전략가 수준의 시장 브리핑과 종목별 입체 분석 보고서를 실시간으로 생성합니다.
- **📋 Preset Strategy Engine**: KIS 공식 10대 매매 전략(골든크로스, 모멘텀, 52주신고가 등)을 내장하여 종목별로 최적의 전략을 AI가 시뮬레이션하고, 각 종목의 변동성/체력에 맞춰 **동적 TP/SL을 실시간 계산**하여 개별 최적화합니다.
- **🛡️ 6-Pillar Architecture**: `ExitManager`, `MarketAnalyzer`, `RecoveryEngine`, `PyramidingEngine`, `VibeAlphaEngine`, `PresetStrategyEngine` 6대 핵심 모듈이 독립적이면서도 유기적으로 협력하여 자산을 안전하게 관리합니다.
- **🕒 Time-based Market Phase**: 장 시작부터 마감까지 시간대별로 최적화된 매매 리듬(OFFENSIVE/CONVERGENCE 등 4단계)을 적용합니다. 익절/손절선을 시간대에 맞춰 자동으로 미세 보정합니다.
- **🚀 Autonomous Trading (AUTO)**: AI가 발굴한 저평가/모멘텀 종목을 보합권 선취매 영역에서 스스로 매집하고, 동적 익절/손절 전략에 따라 자동으로 엑시트합니다.
- **🔒 Anti-Ping-Pong Cooldown**: 익절/손절 후 **2시간 재진입 금지**, 매수 직후 **1시간 P4 장마감 청산 보호(종가베팅 보호)**, 물타기 후 **30분 손절 유예** 로직으로 연속 핑퐁 매매를 원천 차단합니다.
- **📊 Real-time TUI Interface**: 터미널 기반의 직관적인 UI(TUI)를 통해 국내/해외 지수, 포트폴리오 상태, AI 추천 종목을 한눈에 파악할 수 있으며 누적 시드머니(Seed) 설정 기반의 **정확한 누적 수익률 평가**가 가능합니다.

---

## 🏗️ System Architecture (시스템 아키텍처)

KIS-Vibe-Trader는 **Research → Strategy → Execution**의 라이프사이클을 엄격히 따릅니다.

1. **MarketAnalyzer**: 나스닥, 코스피, 환율 등 글로벌 지수와 선물 데이터를 통해 시장의 '분위기'를 진단합니다.
2. **ExitManager**: 현재 분위기에 맞춰 익절(+3% 상향 등) 및 손절선을 실시간으로 보정합니다.
3. **RecoveryEngine**: 손실 발생 시 손절선과의 격차를 분석하여 전략적인 물타기를 수행합니다. 물타기 직후 30분 손절 유예 및 긴급 조건 즉시 손절을 지원합니다.
4. **PyramidingEngine**: 상승 추세 시 수익 비중을 확대하기 위한 불타기 전략을 수행합니다. 불타기 직후 익절 쿨다운을 자동 리셋하여 즉각 익절을 허용합니다.
5. **VibeAlphaEngine**: 네이버 금융 랭킹과 펀더멘털 데이터를 AI 점수로 환산하여 유망 종목을 발굴합니다.
6. **PresetStrategyEngine**: KIS 10대 공식 전략을 AI 시뮬레이션하여 종목별 최적 전략과 동적 TP/SL을 할당합니다.

---

## 🔒 Anti-Ping-Pong System (핑퐁 방지 체계)

자동 매매의 가장 큰 함정인 **익절→불타기→손절→물타기 연속 핑퐁**을 방지하기 위해 4단계 안전 장치를 구현했습니다.

| 시나리오 | 방어 로직 |
|---|---|
| **익절 → 불타기** | 익절 후 2시간 자동 재진입 차단 |
| **손절 → 물타기** | 손절 후 2시간 자동 재진입 차단 |
| **불타기 → 즉시익절** | 불타기 시 익절 쿨다운 자동 리셋 → 새 포지션 즉시 익절 허용 |
| **물타기 → 즉시손절** | 30분 유예 + 긴급조건(급락/패닉/방어모드/장마감) 시 즉시 손절 |

모든 스킵 이벤트는 `trading.log`에 종목별로 상세 기록됩니다.
```
⏸ 스킵(익절쿨다운/불타기직후): GS건설(006360) 수익률 +6.2% / TP +5.0% / 잔여 43분
⏸ 스킵(물타기유예): 대우건설(047040) 수익률 -5.3% / SL -5.0% / 잔여 18분
⏸ 스킵(재진입쿨다운/익절후): GS건설(006360) 불타기 조건충족 / 잔여 97분
```

---

## 🛠️ Tech Stack & Integration (기술 스택)

- **API Integration**: 한국투자증권(KIS), Yahoo Finance, Naver Finance, Google Gemini
- **Language**: Python 3.12+
- **Automation**: GitHub Actions (Windows/Linux 병렬 빌드 및 Release 자동화)
- **Core Libraries**: `PyInstaller` (바이너리화), `ReportLab` (PDF 생성), `BeautifulSoup4` (데이터 스크래핑)

---

## 🚀 Quick Start (빠른 시작)

### EXE 실행 파일 사용 (추천)
[Releases](https://github.com/MS-Song/ai-tradding/releases) 페이지에서 최신 버전의 `KIS-Vibe-Trader.exe`와 `USER_MANUAL.pdf`를 다운로드하세요. 별도의 설치 없이 즉시 실행 가능합니다.

### 소스 코드 실행
```bash
git clone https://github.com/MS-Song/ai-tradding.git
pip install -r requirements.txt
python main.py
```
실행 후 **`S` 키**를 눌러 API 키와 계좌 정보를 설정하세요.

---

## 📄 Documentation (문서화)

| 문서 | 설명 |
|---|---|
| [📖 USER_MANUAL.md](docs/USER_MANUAL.md) | EXE 사용자를 위한 전체 기능 가이드 |
| [🏗️ SYSTEM_ARCH.md](docs/SYSTEM_ARCH.md) | 6대 모듈 아키텍처 상세 설계 |
| [🔌 API_INTEGRATION.md](docs/API_INTEGRATION.md) | KIS/Gemini API 연동 규격 |
| [✅ TEST_REPORT.md](docs/TEST_REPORT.md) | 테스트 명세 및 결과 보고서 |

---

## 📝 Changelog

### v1.2.1 (2026-04-17)
- **자산 트래킹 개편**: 누적 입금액(Seed) 기반으로 정확한 누적 수익금과 수익률(%) 자동 계산 로직 도입 (`S` 셋업 메뉴 통합).
- **P4 핑퐁 보호 로직**: 장 후반 매수한 '종가 베팅' 종목이 1시간 내 P4 마감 청산 대상에 편입되어 즉각 매도되는 모순을 해결하는 방어 로직 설계.
- **스레드 안정성 확보**: 임시 로그 기록 파일 이름에 UUID 기반 Random Number를 덧붙여 다수 스레드(Data Fetch, UI Rendering, Log)에서 발생하는 동시 기록 충돌(Race Condition) 방지.

### v1.1.24 (2026-04-16)
- **핑퐁 매매 방지 시스템 구현**: 익절/손절 후 2시간 재진입 쿨다운 (`last_sell_times`, `last_sl_times`, `last_buy_times`)
- **긴급 바이패스 로직 추가**: 급등·거래량폭발·장마감 시 쿨다운 우회 익절 (`_is_emergency_exit`)
- **물타기 손절 유예**: 물타기 직후 30분 유예 + 긴급 즉시 손절 4가지 조건 (`_is_emergency_sl`)
- **쿨다운 자동 리셋**: 불타기/물타기 발생 시 익절 쿨다운 자동 해제 (`_is_in_partial_sell_cooldown`)
- **스킵 로그 강화**: 종목별·이유별 스킵 내역을 `trading.log`에 영속 기록
- **영속성 확장**: `trading_state.json`에 `last_sl_times`, `last_buy_times` 추가 → 재시작 후에도 쿨다운 유지

### v1.0 (2026-04-03)
- 초기 릴리즈: 6대 모듈 아키텍처 구축
- KIS 10대 프리셋 전략 엔진 + AI 동적 TP/SL
- Gemini 기반 AI 자율 매매 (AUTO 모드)
- 시장 페이즈(Phase 1~4) 기반 익절/손절 자동 보정

---

## 🛡️ License

본 프로젝트는 **MIT License**에 따라 배포됩니다.

## ⚠️ Disclaimer
본 프로그램은 투자 판단의 보조 도구이며, 모든 투자에 대한 최종 책임은 사용자 본인에게 있습니다.

---
*Created and maintained by [MS-Song](https://github.com/MS-Song).*
