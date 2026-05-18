#!/bin/bash
# ==========================================================
# 🐳 AI-Vibe-Trader Linux Docker Build Helper
# ==========================================================
# 이 스크립트는 기존 scripts/build/ 디렉토리 구조와의 
# 일관성을 제공하기 위해 제공되는 Docker 빌드 위임 헬퍼입니다.

# 스크립트의 디렉토리 경로 계산
SCRIPT_DIR="$(dirname "$0")"

# 프로젝트 루트의 메인 docker_build.sh 실행
if [ -f "${SCRIPT_DIR}/../../../docker_build.sh" ]; then
    echo "[*] scripts/build/linux/build_docker.sh -> 루트 docker_build.sh 호출 위임"
    bash "${SCRIPT_DIR}/../../../docker_build.sh"
else
    echo "[!] 루트 디렉토리의 docker_build.sh 파일을 찾을 수 없습니다."
    exit 1
fi
