# 🤖 KIS-Vibe-Trader: The Intelligent AI Trading Engine

[![Build and Release](https://github.com/MS-Song/ai-tradding/actions/workflows/release.yml/badge.svg)](https://github.com/MS-Song/ai-tradding/actions/workflows/release.yml)
[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Powered by Gemini](https://img.shields.io/badge/AI-Gemini%202.5%20Flash-blueviolet.svg)](https://aistudio.google.com/)
[![Market](https://img.shields.io/badge/Market-Korea%20Stock-red.svg)](https://apiportal.koreainvestment.com/)

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
- **📊 Real-time TUI Interface**: 터미널 기반의 직관적인 UI(TUI)를 통해 국내/해외 지수, 포트폴리오 상태, AI 추천 종목을 한눈에 파악할 수 있습니다.

---

## 🏗️ System Architecture (시스템 아키텍처)

KIS-Vibe-Trader는 **Research -> Strategy -> Execution**의 라이프사이클을 엄격히 따릅니다.

1.  **MarketAnalyzer**: 나스닥, 코스피, 환율 등 글로벌 지수와 선물 데이터를 통해 시장의 '분위기'를 진단합니다.
2.  **ExitManager**: 현재 분위기에 맞춰 익절(+3% 상향 등) 및 손절선을 실시간으로 보정합니다.
3.  **RecoveryEngine**: 손실 발생 시 손절선과의 격차를 분석하여 전략적인 물타기(Averaging Down)를 수행합니다.
4.  **PyramidingEngine**: 상승 추세 시 수익 비중을 확대하기 위한 불타기(Pyramiding) 전략을 수행합니다.
5.  **VibeAlphaEngine**: 네이버 금융 랭킹과 펀더멘털 데이터를 AI 점수로 환산하여 유망 종목을 발굴합니다.
6.  **PresetStrategyEngine**: KIS 10대 공식 전략을 AI 시뮬레이션하여 종목별 최적 전략과 동적 TP/SL을 할당합니다.

---

## 🛠️ Tech Stack & Integration (기술 스택)

- **API Integration**: 한국투자증권(KIS), Yahoo Finance, Naver Finance, Google Gemini.
- **Language**: Python 3.12+
- **Automation**: GitHub Actions (Windows/Linux 병렬 빌드 및 Release 자동화).
- **Core Libraries**: `PyInstaller` (바이너리화), `ReportLab` (PDF 생성), `BeautifulSoup4` (데이터 스크래핑).

---

## 🚀 Quick Start (빠른 시작)

### EXE 실행 파일 사용 (추천)
- [Releases](https://github.com/MS-Song/ai-tradding/releases) 페이지에서 최신 버전의 `KIS-Vibe-Trader.exe`와 `USER_MANUAL.pdf`를 다운로드하세요. 별도의 설치 없이 즉시 실행 가능합니다.

### 소스 코드 실행
1.  저장소 클론: `git clone https://github.com/MS-Song/ai-tradding.git`
2.  의존성 설치: `pip install -r requirements.txt`
3.  프로그램 실행: `python main.py`
4.  **`S` 키**를 눌러 API 키와 계좌 정보를 설정하세요.

---

## 📄 Documentation (문서화)

상세한 개발 산출물 및 매뉴얼은 `docs/` 디렉토리에 포함되어 있습니다.

- [📖 사용자 매뉴얼 (EXE 버전)](docs/USER_MANUAL.md)
- [🏗️ 시스템 아키텍처 정의서](docs/SYSTEM_ARCH.md)
- [🔌 API 및 연동 규격서](docs/API_INTEGRATION.md)
- [✅ 테스트 명세 및 결과 보고서](docs/TEST_REPORT.md)

---

## 🛡️ License

본 프로젝트는 **MIT License**에 따라 배포됩니다. 자유롭게 사용 및 수정이 가능합니다.

## ⚠️ Disclaimer
본 프로그램은 투자 판단의 보조 도구이며, 모든 투자에 대한 최종 책임은 사용자 본인에게 있습니다.

---
*Created and maintained by [MS-Song](https://github.com/MS-Song).*
