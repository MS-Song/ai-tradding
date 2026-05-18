# ==========================================
# 🐳 AI-Vibe-Trader Dockerfile
# ==========================================
# 리눅스 배포판 버전과 관계없이 완벽한 호환성을 제공하는
# 파이썬 3.11-slim 기반의 객체지향형 자율 트레이딩 엔진 TUI 컨테이너 이미지입니다.

# 1. 베이스 이미지 선택 (안정성 및 경량화 확보)
FROM python:3.11-slim

# 2. 메타데이터 정의
LABEL maintainer="AI-Vibe-Trader Team"
LABEL version="2.0.260518"
LABEL description="AI-Vibe-Trader TUI Trading Engine Docker Image"

# 3. 환경 변수 설정
# PYTHONUNBUFFERED=1: 파이썬의 표준 출력 버퍼링을 제거하여 실시간 TUI 렌더링 및 로그 유출 방지
# TZ=Asia/Seoul: 컨테이너 시스템 시간대를 KST로 고정
# LANG/LC_ALL=C.UTF-8: 터미널에서의 한글 정렬 및 문자열 시각 너비 출력 깨짐 현상 원천 차단
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive

# 4. 필수 시스템 패키지 설치 및 타임존/로케일 갱신
# build-essential 및 xml 라이브러리는 lxml, bs4 등의 파이썬 라이브러리가 
# 특정 아키텍처에서 C 휠 빌드를 요구할 경우를 완벽 대비하기 위함입니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 5. 작업 디렉토리 설정
WORKDIR /app

# 6. 파이썬 의존성 설치 (의존성 캐시 활용 최적화)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 7. 프로젝트 소스 코드 및 폰트 파일 복사
COPY main.py .
COPY src/ ./src/
COPY fonts/ ./fonts/

# 8. 컨테이너 기본 실행 명령 정의 (TUI 진입점)
CMD ["python", "main.py"]
