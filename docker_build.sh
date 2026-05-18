#!/bin/bash
# ==========================================================
# 🐳 AI-Vibe-Trader 리눅스 Docker 이미지 빌드 스크립트
# ==========================================================
# 실행 권한 설정: chmod +x docker_build.sh
# 실행 방법: ./docker_build.sh

# ANSI 색상 터미널 지원 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}[*] AI-Vibe-Trader 도커 이미지 빌드 작업을 시작합니다...${NC}"

# 1. 스크립트가 위치한 프로젝트 루트 디렉토리로 안전 이동
cd "$(dirname "$0")"

# 2. Docker 데몬 실행 여부 검증
if ! command -v docker &> /dev/null; then
    echo -e "${RED}[!] Docker 엔진이 시스템에 설치되어 있지 않거나 PATH 경로에 없습니다.${NC}"
    echo -e "${RED}[!] Docker를 설치한 후 다시 시도해 주세요.${NC}"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}[!] Docker 데몬이 실행 중이 아니거나 권한이 부족합니다.${NC}"
    echo -e "${RED}[!] 'sudo systemctl start docker' 명령 또는 'sudo usermod -aG docker $USER' 권한 부여를 검토하세요.${NC}"
    exit 1
fi

# 3. Docker 이미지 빌드 수행 (경량화 캐시 반영)
IMAGE_TAG="ai-vibe-trader:latest"
echo -e "${YELLOW}[*] 'Dockerfile'을 기반으로 최적화된 '${IMAGE_TAG}' 이미지 빌드 중...${NC}"
echo "=========================================================="

docker build -t ${IMAGE_TAG} .

BUILD_STATUS=$?
echo "=========================================================="

# 4. 빌드 결과 판단 및 사용자 피드백
if [ ${BUILD_STATUS} -eq 0 ]; then
    echo -e "${GREEN}[V] 성공: AI-Vibe-Trader 도커 이미지 빌드가 완료되었습니다!${NC}"
    echo -e "${GREEN}[V] 이미지명: ${IMAGE_TAG}${NC}"
    echo -e "${YELLOW}[*] 이제 './docker_run.sh' 스크립트를 실행하여 TUI 트레이딩 엔진을 구동할 수 있습니다.${NC}"
else
    echo -e "${RED}[!] 실패: 도커 빌드 중 오류가 발생했습니다. 로그 메시지를 확인해 주세요.${NC}"
    exit ${BUILD_STATUS}
fi
