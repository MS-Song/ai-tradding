# 🐳 도커 및 배포 가이드 (Deployment & Container Guide)

> **문서 버전:** v2.4.1  
> **최종 수정일:** 2026-10-11  
> **관련 파일:** `Dockerfile`, `docker-compose.yml`, `scripts/build/`, `.github/workflows/release.yml`

---

## 1. 개요 (Overview)

AI-Vibe-Trader는 리눅스 배포판 및 커널 환경(glibc 호환성)에 구애받지 않고 무중단 실행 환경을 제공하기 위해 **Docker 컨테이너** 방식을 정식 지원합니다. 윈도우 환경은 PyInstaller 기반의 단일 실행 파일(`.exe`) 또는 PowerShell 스크립트를 통해 지원하며, 리눅스 서버 환경은 Docker를 통해 완벽히 가상화합니다.

---

## 2. Docker 핵심 설계 사상

1.  **TUI 대화형 모드 완벽 연동**:
    *   `tty: true`, `stdin_open: true`를 강제 설정하여 컨테이너 내부 터미널에서의 키 입력(`get_key_immediate`)과 화면 정렬이 깨지지 않도록 설계.
2.  **호스트 영속성 볼륨 설계 및 디렉토리 오인 버그 방지**:
    *   `.env`, `trading_state.json`, `trade_retrospective.json`, `theme_data.json` 및 `*.log` 파일들은 호스트와 1:1 바인드 마운트하여 컨테이너 재생성 시에도 상태 유지.
    *   실행 스크립트(`docker_run.sh` / `.ps1`)에 필수 영속/로그 파일 부재 시 자동 생성(`touch`) 로직을 포함시켜 도커 엔진이 호스트에 파일 대신 폴더를 무단 생성하는 마운트 에러 방지.
3.  **한국 시간대 및 한글 로케일 고정**:
    *   `TZ=Asia/Seoul`, `LANG=C.UTF-8` 고정을 통해 스케줄 주기 일치와 TUI 깨짐을 근본 해결.
4.  **중복 가동 차단**:
    *   `ai-vibe-trader-app` 기동 전 기존 컨테이너를 안전하게 자동 청소하여 중복 로그인에 의한 API 충돌 및 Rate Limiter 정합성 리스크 방어.

---

## 3. 원클릭 빌드 및 가동 명령어

### A. 빌드 (Build)

*   **Linux / macOS (Bash)**:
    ```bash
    chmod +x docker_build.sh
    ./docker_build.sh
    ```
*   **Windows (PowerShell)**:
    ```powershell
    .\docker_build.ps1
    ```
*   **Windows (CMD / 더블 클릭)**:
    ```cmd
    docker_build.bat
    ```

### B. 실행 (Run)

*   **Linux / macOS (Bash)**:
    ```bash
    chmod +x docker_run.sh
    ./docker_run.sh
    ```
*   **Windows (PowerShell)**:
    ```powershell
    .\docker_run.ps1
    ```
*   **Windows (CMD / 더블 클릭)**:
    ```cmd
    docker_run.bat
    ```

---

## 4. TUI 운용 및 단축키 팁

*   **백그라운드 전환 (Detach)**: TUI 프로세스를 끄지 않고 호스트 쉘로 빠져나가려면 **`Ctrl + P`를 누른 뒤 `Ctrl + Q`**를 순차적으로 입력.
*   **터미널 재접속 (Attach)**: 백그라운드 운용 중인 TUI 화면에 다시 연결하려면:
    ```bash
    docker attach ai-vibe-trader-app
    ```
*   **글꼴 권장**: 한글 표 및 TUI 레이아웃의 정확한 정렬을 위해 터미널 글꼴을 **`D2Coding`**으로 설정하는 것을 강력 권장합니다.

---

## 5. Docker 환경 자동 업데이트 아키텍처

도커 배포 환경 하에서 불변 컨테이너 사상을 준수하고 실시간 트레이딩의 정합성을 수호하기 위해 이중 자동 업데이트 모델을 운영합니다.

1.  **Watchtower 기반 새벽 완전 자동 업데이트 (Docker-Native)**:
    *   `docker-compose.yml` 내 `watchtower` 서비스 활성화를 통해 매일 새벽 **03:30**에 Registry의 신규 이미지를 검사 및 자동 다운로드하여 컨테이너 재생성.
2.  **볼륨 공유 트리거 및 호스트 모니터 헬퍼 (TUI 핫키 연동)**:
    *   TUI 화면에서 단축키 `U`를 누르거나 텔레그램 `/update` 명령어 전송 시, 컨테이너 내 `updater.py`가 외부 볼륨과 공유된 `./update_trigger` 파일에 타임스탬프 신호를 주입하고 안전 종료(Self-Exit).
    *   호스트 측 백그라운드 셸 스크립트(`scripts/docker_update_monitor.sh` / `.ps1`)가 이를 감지하여 `git pull && docker-compose build --no-cache && docker-compose up -d`를 대신 수행.
    *   `docker.sock` 마운트 권한 노출에 따른 보안 취약점(Privilege Escalation)을 원천 방지.

---

## 6. GitHub Actions CI/CD 자동화 파이프라인

*   **워크플로우 경로**: `.github/workflows/release.yml`
*   **배포 파이프라인 단계**:
    1.  **테스트 (`test`)**: pytest 기반 유닛/통합 테스트 64종 전수 검증 및 `TEST_REPORT.md` 아티팩트 발행.
    2.  **바이너리 빌드**: Windows EXE 및 Linux 바이너리를 자동 빌드하여 GitHub Release에 첨부.
    3.  **Docker Build & Push**: 최적화된 Docker 이미지를 빌드하여 Docker Hub (`song7749/ai-tradding:latest`)로 자동 푸시.
