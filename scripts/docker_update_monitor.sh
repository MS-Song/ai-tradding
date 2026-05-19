#!/bin/bash
# ==============================================================================
# 🐳 AI-Vibe-Trader Docker 호스트 자동 업데이트 모니터 스크립트 (Linux용)
# ==============================================================================
# 이 스크립트는 호스트 서버의 백그라운드에서 실행되며,
# TUI 또는 텔레그램을 통해 컨테이너에서 발생한 'update_trigger' 신호를 감시합니다.
# 신호가 감지되면 자동으로 최신 코드를 다운로드하고 도커 컨테이너를 안전하게 재기동합니다.
#
# [실행 방법]
# chmod +x docker_update_monitor.sh
# nohup ./docker_update_monitor.sh > docker_update.log 2>&1 &
# ==============================================================================

# ANSI 색상 출력 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 스크립트 위치 기준 프로젝트 루트 디렉터리로 이동
cd "$(dirname "$0")/.." || exit 1

TRIGGER_FILE="./update_trigger"
CHECK_INTERVAL_SECONDS=10

echo -e "${GREEN}[*] AI-Vibe-Trader Docker 업데이트 모니터 데몬 기동 완료!${NC}"
echo -e "[*] 감시 대상 파일: ${TRIGGER_FILE} (감시 주기: ${CHECK_INTERVAL_SECONDS}초)"

while true; do
    # 트리거 파일이 존재하고 파일 크기가 0보다 크거나 내용이 채워진 경우 감지
    if [ -f "${TRIGGER_FILE}" ] && [ -s "${TRIGGER_FILE}" ]; then
        echo -e "\n${YELLOW}🚨 [$(date '+%Y-%m-%d %H:%M:%S')] 업데이트 요청 신호 감지!${NC}"
        cat "${TRIGGER_FILE}"
        
        # 1. 트리거 파일 초기화 (중복 트리거 방지)
        > "${TRIGGER_FILE}"
        
        echo -e "${YELLOW}[1/3] 최신 코드 Pull 수행 중... (Git Repo Update)${NC}"
        git pull
        
        # docker-compose 구비 확인 및 재배포 수행
        USE_COMPOSE=false
        if command -v docker-compose &> /dev/null || docker compose version &> /dev/null; then
            USE_COMPOSE=true
        fi
        
        echo -e "${YELLOW}[2/3] Docker 컨테이너 재부팅 및 빌드 수행 중...${NC}"
        if [ "${USE_COMPOSE}" = true ]; then
            if docker compose version &> /dev/null; then
                docker compose down
                docker compose build --no-cache ai-vibe-trader
                docker compose up -d
            else
                docker-compose down
                docker-compose build --no-cache ai-vibe-trader
                docker-compose up -d
            fi
        else
            # docker-compose가 없는 경우 기본 docker CLI로 이미지 재빌드 및 run
            echo -e "${RED}[!] docker-compose 미감지. 수동 docker run 모드로 재시작합니다.${NC}"
            CONTAINER_NAME="ai-vibe-trader-app"
            docker stop ${CONTAINER_NAME} 2>/dev/null
            docker rm ${CONTAINER_NAME} 2>/dev/null
            docker build --no-cache -t ai-vibe-trader:latest .
            
            # 백그라운드로 TUI 컨테이너 재실행 (필요시 사용자가 docker attach ai-vibe-trader-app 로 진입 가능)
            docker run -d \
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
                --restart unless-stopped \
                ai-vibe-trader:latest
        fi
        
        echo -e "${GREEN}✅ [$(date '+%Y-%m-%d %H:%M:%S')] Docker 자동 업데이트 및 재기동이 성공적으로 완료되었습니다!${NC}"
    fi
    sleep ${CHECK_INTERVAL_SECONDS}
done
