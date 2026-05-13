# <img src="assets/logo.png" width="48" height="48" valign="middle"> AI-Vibe-Trader

<p align="center">
  <a href="https://github.com/MS-Song/ai-tradding/actions/workflows/release.yml">
    <img src="https://github.com/MS-Song/ai-tradding/actions/workflows/release.yml/badge.svg" alt="Build and Release">
  </a>
  <img src="https://img.shields.io/badge/python-3.12%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/AI-Gemini%20|%20Groq-blueviolet.svg" alt="Powered by AI">
  <img src="https://img.shields.io/badge/Market-Korea%20Stock-red.svg" alt="Market">
  <a href="https://github.com/MS-Song/ai-tradding/releases">
    <img src="https://img.shields.io/badge/version-1.5.0-green.svg" alt="Version">
  </a>
</p>

> **"단순한 매매가 아닙니다. 시장의 흐름(Vibe)을 읽는 AI 자율 트레이딩 엔진입니다."**
> AI-Vibe-Trader는 시니어 아키텍트의 설계 사상이 반영된 객체지향형 트레이딩 시스템으로, 시장 감성(Vibe)과 AI 분석(Gemini/Groq)을 결합하여 최적의 매매 전략을 자율적으로 도출합니다.

---

## 🌌 Overview (프로젝트 소개)

**AI-Vibe-Trader**는 단순한 자동 매매 프로그램을 넘어, **시니어 아키텍트의 설계 사상**이 반영된 객체지향형 자율 트레이딩 엔진입니다. 

기존의 단순 지표 기반 트레이딩에서 벗어나, 시장 전체의 감성(Vibe)을 입체적으로 분석하고 Google Gemini와 Groq의 최첨단 AI 통찰을 결합하여 **"지키는 투자"**와 **"수익 극대화"** 사이의 완벽한 균형을 추구합니다.

### 🎯 핵심 가치
- **Contextual Awareness**: 가격 데이터만 보는 것이 아니라, 뉴스, 수급, 거시 지표(환율, 나스닥 등)를 통해 시장의 '분위기'를 읽습니다.
- **Architectural Excellence**: 6대 핵심 모듈(`Exit`, `Market`, `Recovery`, `Pyramiding`, `Alpha`, `Preset`)이 유기적으로 협력하는 견고한 아키텍처를 가집니다.
- **Proactive Risk Management**: 시장이 하락할 때는 즉시 '방어 모드'로 전환하여 자산을 보호하고, 상승장에서는 '불타기'를 통해 수익을 추종합니다.

---

## 🛠️ Core Trading Algorithm (트레이딩 알고리즘)

본 엔진은 다층적인 의사결정 프로세스를 통해 매매를 집행합니다.

### 1. Market Vibe Detection (장세 진단)
매초 단위로 나스닥 선물, 코스피/코스닥 지수, 달러 환율, 비트코인 프리미엄 등을 수집하여 시장을 4가지 상태로 정의합니다.
- **BULL**: 공격적 투자, 적극적 불타기 허용
- **NEUTRAL**: 표준 전략 유지
- **BEAR**: 현금 비중 확대, 물타기 간격 확대
- **DEFENSIVE**: 최우량주 1종목 집중 또는 전량 현금화 (극보수적 대응)

### 2. Vibe-Alpha Selection (AI 종목 발굴)
네이버 금융의 실시간 랭킹 데이터와 개별 종목의 펀더멘털(PER, PBR, 배당)을 결합하여 Quant 스코어를 산출합니다. 이후 Gemini/Groq AI가 최신 뉴스와 모멘텀을 2차 검증하여 최종 추천 리스트를 생성합니다.

### 3. Dynamic Strategy Execution (동적 전략 집행)
종목별로 고정된 수치가 아닌, **AI가 실시간으로 계산한 동적 TP/SL(익절/손절선)**을 적용합니다.
- **Preset Strategy**: 골든크로스, 모멘텀 등 10대 공식 전략을 AI가 시뮬레이션하여 종목 맞춤형으로 할당합니다.
- **Time-based Phase**: 장 초반(Offensive)부터 장 마감(Conclusion)까지 시간대별로 리스크 감수도를 자동 조절합니다.

---

## 🚀 Quick Start (시작하기)

### 📋 준비물
1. **한국투자증권(KIS) API 키**: 실전 또는 모의계좌 앱키/시크릿
2. **AI API 키**: Google Gemini (필수) 및 Groq (선택/Fail-over용)

### 💻 실행 방법

#### 1. EXE 실행 (일반 사용자)
- [Releases](https://github.com/MS-Song/ai-tradding/releases) 페이지에서 최신 버전의 `AI-Vibe-Trader.exe`와 `USER_MANUAL.pdf`를 다운로드하세요. 별도의 설치 없이 즉시 실행 가능합니다.

#### 2. 소스 코드 실행 (개발자)
```bash
# 레포지토리 클론
git clone https://github.com/MS-Song/ai-tradding.git

# 의존성 설치
pip install -r requirements.txt

# 프로그램 실행
python main.py
```

---

## 🏗️ System Pillars (6대 핵심 엔진)

| 모듈 | 역할 |
| :--- | :--- |
| **MarketAnalyzer** | 글로벌 지수 및 거시 지표 기반 시장 분위기(Vibe) 확정 |
| **VibeAlphaEngine** | 퀀트 + AI 분석을 통한 유망 종목 발굴 및 스코어링 |
| **ExitManager** | 장세와 시간대(Phase)에 따른 실시간 익절/손절선 교정 |
| **PresetStrategyEngine** | KIS 10대 공식 전략 기반 종목별 최적 매매 로직 할당 |
| **RecoveryEngine** | 하락 구간에서의 평단가 관리 및 지능적 물타기 수행 |
| **PyramidingEngine** | 상승 추세 종목의 비중 확대를 통한 수익 극대화 |

---

## 🛠️ Tech Stack (기술 스택)

- **API Integration**: 한국투자증권(KIS), Yahoo Finance, Naver Finance, Google Gemini, Groq
- **Language**: Python 3.12+
- **Automation**: GitHub Actions (Windows/Linux 병렬 빌드 및 Release 자동화)
- **Core Libraries**: `PyInstaller` (바이너리화), `ReportLab` (PDF 생성), `BeautifulSoup4` (데이터 스크래핑)

---

## 📄 Documentation (관련 문서)

| 문서 | 설명 |
| :--- | :--- |
| [📖 USER_MANUAL.md](docs/USER_MANUAL.md) | EXE 사용자를 위한 전체 기능 가이드 |
| [🏗️ SYSTEM_ARCH.md](docs/SYSTEM_ARCH.md) | 6대 모듈 아키텍처 상세 설계 |
| [🔌 API_INTEGRATION.md](docs/API_INTEGRATION.md) | 외부 API 연동 규격 및 데이터 흐름 |
| [✅ TEST_REPORT.md](docs/TEST_REPORT.md) | 테스트 명세 및 결과 보고서 |

---

## 🛡️ License & Disclaimer

- 본 프로젝트는 **MIT License**에 따라 배포됩니다.
- **주의**: 본 프로그램은 투자 판단의 보조 도구일 뿐입니다. 모든 투자에 대한 최종 책임은 사용자 본인에게 있으며, 시장 변동성에 따른 손실에 대해 개발자는 책임을 지지 않습니다.

---
<p align="right">Developed & Maintained by <b>MS-Song</b></p>
