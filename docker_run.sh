#!/bin/bash
# ==========================================================
# 🐳 AI-Vibe-Trader 리눅스 Docker 실행 스크립트
# ==========================================================
# 실행 권한 설정: chmod +x docker_run.sh
# 실행 방법: ./docker_run.sh

# ANSI 색상 터미널 지원 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}[*] AI-Vibe-Trader 리눅스 도커 TUI 컨테이너 구동을 시작합니다...${NC}"

# 1. 스크립트가 위치한 프로젝트 루트 디렉토리로 이동
cd "$(dirname "$0")"

# 2. 필수 영속성 파일 호스트 측 사전 존재 검증 및 자동 초기화
# (도커 파일 볼륨 마운트 시, 파일 미존재 시 호스트에 디렉토리를 자동 생성해 버려
#  파이썬 코드 내에서 json 읽기/쓰기 실패 및 크래시가 발생하는 버그를 원천 차단합니다.)
touch_file_if_not_exists() {
    local target_file="$1"
    local initial_content="$2"
    
    if [ ! -f "${target_file}" ]; then
        # 만약 디렉토리로 잘못 생성되어 있다면 청소
        if [ -d "${target_file}" ]; then
            echo -e "${RED}[⚠️ 오류 복구] 디렉토리로 오인 생성된 '${target_file}' 폴더 제거...${NC}"
            rm -rf "${target_file}"
        fi
        
        echo -e "${YELLOW}[*] 신규 영속 파일 자동 생성: ${target_file}${NC}"
        if [ -n "${initial_content}" ]; then
            echo "${initial_content}" > "${target_file}"
        else
            touch "${target_file}"
        fi
    fi
}

# 필수 JSON 영속 파일 및 기본 템플릿 주입
touch_file_if_not_exists "trading_state.json" "{}"
touch_file_if_not_exists "trade_retrospective.json" "{}"
touch_file_if_not_exists "theme_data.json" "{}"
touch_file_if_not_exists "update_trigger" ""

# 필수 텍스트 로그 파일 초기화
touch_file_if_not_exists "trading.log" ""
touch_file_if_not_exists "telegram.log" ""
touch_file_if_not_exists "error.log" ""

# 환경 설정 파일(.env) 존재 유무 확인 및 Fallback
if [ ! -f ".env" ]; then
    echo -e "${RED}[⚠️ 경고] .env 환경 변수 파일이 프로젝트 루트에 존재하지 않습니다.${NC}"
    if [ -f ".env.bak" ]; then
        cp .env.bak .env
        echo -e "${GREEN}[*] 백업 파일 '.env.bak'을 복사하여 '.env' 파일을 복원/초기화했습니다.${NC}"
        echo -e "${YELLOW}[!] 주의: 실거래를 위해 .env 파일 내의 API Key 및 텔레그램 설정을 반드시 확인해 주세요.${NC}"
    else
        touch .env
        echo -e "${YELLOW}[*] 빈 '.env' 파일을 임시 생성했습니다. API 키 등 설정을 채워 넣어야 정상 작동합니다.${NC}"
    fi
fi

# 3. 기존에 중복 가동 중인 동일 컨테이너 존재 시 종료 및 파괴
# (멀티 브로커 동시 가동 시, 동일 계좌의 중복 로그인/API 충돌 및 Rate Limiter 무력화 리스크 방지)
CONTAINER_NAME="ai-vibe-trader-app"
if [ "$(docker ps -aq -f name=^/${CONTAINER_NAME}$)" ]; then
    echo -e "${YELLOW}[*] 기존에 실행 중이거나 정지된 동일 컨테이너(${CONTAINER_NAME}) 정리 중...${NC}"
    docker stop ${CONTAINER_NAME} 2>/dev/null
    docker rm ${CONTAINER_NAME} 2>/dev/null
fi

# 4. TUI 대화형 모드로 Docker 기동
echo -e "${GREEN}[V] 준비 완료! AI-Vibe-Trader 컨테이너로 진입합니다 (TUI 모드).${NC}"
echo -e "${CYAN}=========================================================="
echo " 💡 TUI 사용법 꿀팁:"
echo "   - 터미널 창의 글꼴을 'D2Coding'으로 적용해야 한글 정렬 및 라인이 정상 출력됩니다."
echo "   - 화면 상에서 'Q' 키를 누르면 시스템을 안전하게 종료하고 빠져나옵니다."
echo "   - TUI의 백그라운드 운용을 그대로 둔 채 터미널 접속만 해제하려면"
echo "     'Ctrl+P, Ctrl+Q' 단축키를 연속으로 눌러 디태치(Detach)할 수 있습니다."
echo -e "==========================================================${NC}"
sleep 1.5

# Docker Compose 유틸리티 사용 가능 여부 확인
USE_COMPOSE=false
if command -v docker-compose &> /dev/null || docker compose version &> /dev/null; then
    USE_COMPOSE=true
fi

if [ "${USE_COMPOSE}" = true ]; then
    # Docker Compose V2 또는 V1 호환 실행 (대화형 TUI 기동을 위해 run --rm 사용)
    echo -e "${BLUE}[*] docker compose 모드로 TUI 애플리케이션을 구동합니다...${NC}"
    if docker compose version &> /dev/null; then
        docker compose run --rm ai-vibe-trader
    else
        docker-compose run --rm ai-vibe-trader
    fi
else
    # docker-compose가 없는 리눅스 환경에서도 단일 docker run 명령어로 완벽히 fallback 작동
    echo -e "${YELLOW}[!] docker compose 미감지. 기본 'docker run' 명령으로 Fallback 실행...${NC}"
    docker run -it --rm \
        --name "${CONTAINER_NAME}" \
        --network host \
        -e TZ=Asia/Seoul \
        -e PYTHONUNBUFFERED=1 \
        -v "$(pwd)/.env:/app/.env:ro" \
        -v "$(pwd)/trading_state.json:/app/trading_state.json" \
        -v "$(pwd)/trade_retrospective.json:/app/trade_retrospective.json" \
        -v "$(pwd)/theme_data.json:/app/theme_data.json" \
        -v "$(pwd)/trading.log:/app/trading.log" \
        -v "$(pwd)/telegram.log:/app/telegram.log" \
        -v "$(pwd)/error.log:/app/error.log" \
        -v "$(pwd)/update_trigger:/app/update_trigger" \
        ai-vibe-trader:latest
fi
