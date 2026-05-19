# ==========================================================
# 🐳 AI-Vibe-Trader Windows Docker Run Script
# ==========================================================
# 실행 방법: PowerShell을 열고 .\docker_run.ps1 실행
# (실행 정책 문제 발생 시: powershell -ExecutionPolicy Bypass -File .\docker_run.ps1)

$ErrorActionPreference = "Stop"

Write-Host "[*] AI-Vibe-Trader Windows 도커 TUI 컨테이너 구동을 시작합니다..." -ForegroundColor Cyan

# 1. 스크립트가 위치한 프로젝트 루트 디렉터리로 안전 이동
$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($ScriptPath) {
    Set-Location $ScriptPath
}

# 2. 필수 영속성 파일 호스트 측 사전 존재 검증 및 자동 초기화
# (도커 파일 볼륨 마운트 시, 파일 미존재 시 호스트에 디렉토리를 자동 생성해 버려
#  파이썬 코드 내에서 json 읽기/쓰기 실패 및 크래시가 발생하는 버그를 원천 차단합니다.)
function Touch-File-If-Not-Exists {
    param (
        [string]$TargetFile,
        [string]$InitialContent
    )
    
    $FullPath = Join-Path (Resolve-Path .).Path $TargetFile
    
    if (Test-Path $FullPath) {
        # 만약 디렉터리로 잘못 생성되어 있다면 청소
        if ((Get-Item $FullPath) -is [System.IO.DirectoryInfo]) {
            Write-Host "[⚠️ 오류 복구] 디렉터리로 오인 생성된 '$TargetFile' 폴더 제거..." -ForegroundColor Red
            Remove-Item -Recurse -Force $FullPath
            
            Write-Host "[*] 신규 영속 파일 자동 생성: $TargetFile" -ForegroundColor Yellow
            if ($InitialContent) {
                $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
                [System.IO.File]::WriteAllText($FullPath, $InitialContent, $Utf8NoBom)
            } else {
                $null = New-Item -Path $FullPath -ItemType File -Force
            }
        }
    } else {
        Write-Host "[*] 신규 영속 파일 자동 생성: $TargetFile" -ForegroundColor Yellow
        if ($InitialContent) {
            # BOM이 없는 UTF-8 파일로 저장하여 파이썬 json 파서 에러 방지
            $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($FullPath, $InitialContent, $Utf8NoBom)
        } else {
            $null = New-Item -Path $FullPath -ItemType File -Force
        }
    }
}

# 필수 JSON 영속 파일 및 기본 템플릿 주입
Touch-File-If-Not-Exists -TargetFile "trading_state.json" -InitialContent "{}"
Touch-File-If-Not-Exists -TargetFile "trade_retrospective.json" -InitialContent "{}"
Touch-File-If-Not-Exists -TargetFile "theme_data.json" -InitialContent "{}"

# 필수 텍스트 로그 파일 초기화
Touch-File-If-Not-Exists -TargetFile "trading.log" -InitialContent ""
Touch-File-If-Not-Exists -TargetFile "telegram.log" -InitialContent ""
Touch-File-If-Not-Exists -TargetFile "error.log" -InitialContent ""
Touch-File-If-Not-Exists -TargetFile "update_trigger" -InitialContent ""

# 환경 설정 파일(.env) 존재 유무 확인 및 Fallback
if (-not (Test-Path ".env")) {
    Write-Host "[⚠️ 경고] .env 환경 변수 파일이 프로젝트 루트에 존재하지 않습니다." -ForegroundColor Red
    if (Test-Path ".env.bak") {
        Copy-Item ".env.bak" ".env"
        Write-Host "[*] 백업 파일 '.env.bak'을 복사하여 '.env' 파일을 복원/초기화했습니다." -ForegroundColor Green
        Write-Host "[!] 주의: 실거래를 위해 .env 파일 내의 API Key 및 텔레그램 설정을 반드시 확인해 주세요." -ForegroundColor Yellow
    } else {
        $null = New-Item -Path ".env" -ItemType File -Force
        Write-Host "[*] 빈 '.env' 파일을 임시 생성했습니다. API 키 등 설정을 채워 넣어야 정상 작동합니다." -ForegroundColor Yellow
    }
}

# 3. 기존에 중복 가동 중인 동일 컨테이너 존재 시 종료 및 파괴
# (멀티 브로커 동시 가동 시, 동일 계좌의 중복 로그인/API 충돌 및 Rate Limiter 무력화 리스크 방지)
$ContainerName = "ai-vibe-trader-app"
$ExistingContainer = & docker ps -aq -f "name=^/${ContainerName}$"

if ($ExistingContainer) {
    Write-Host "[*] 기존에 실행 중이거나 정지된 동일 컨테이너($ContainerName) 정리 중..." -ForegroundColor Yellow
    & docker stop $ContainerName > $null 2>&1
    & docker rm $ContainerName > $null 2>&1
}

# 4. TUI 대화형 모드로 Docker 기동
Write-Host "[V] 준비 완료! AI-Vibe-Trader 컨테이너로 진입합니다 (TUI 모드)." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " 💡 TUI 사용법 꿀팁:"
Write-Host "   - 터미널 창의 글꼴을 'D2Coding' 또는 한글 폰트로 적용해야 깨짐이 방지됩니다."
Write-Host "   - 화면 상에서 'Q' 키를 누르면 시스템을 안전하게 종료하고 빠져나옵니다."
Write-Host "   - TUI의 백그라운드 운용을 그대로 둔 채 터미널 접속만 해제하려면"
Write-Host "     'Ctrl+P, Ctrl+Q' 단축키를 연속으로 눌러 디태치(Detach)할 수 있습니다."
Write-Host "==========================================================" -ForegroundColor Cyan
Start-Sleep -Seconds 2

# Docker Compose 유틸리티 사용 가능 여부 확인
$UseCompose = $false
if ((Get-Command docker-compose -ErrorAction SilentlyContinue) -or ((& docker compose version 2>$null) -ne $null)) {
    $UseCompose = $true
}

# 현재 작업 경로 (도커 마운트에 사용)
$CurrentDir = (Resolve-Path .).Path

if ($UseCompose) {
    Write-Host "[*] docker compose 모드로 TUI 애플리케이션을 구동합니다..." -ForegroundColor Blue
    
    # docker compose V2 혹은 V1 실행
    try {
        & docker compose run --rm ai-vibe-trader
    } catch {
        & docker-compose run --rm ai-vibe-trader
    }
} else {
    Write-Host "[!] docker compose 미감지. 기본 'docker run' 명령으로 Fallback 실행..." -ForegroundColor Yellow
    
    # 윈도우 환경에 맞는 docker run 커맨드 실행 (마운트 경로 매핑 최적화)
    & docker run -it --rm `
        --name $ContainerName `
        --network host `
        -e TZ=Asia/Seoul `
        -e PYTHONUNBUFFERED=1 `
        -v "${CurrentDir}/.env:/app/.env:ro" `
        -v "${CurrentDir}/trading_state.json:/app/trading_state.json" `
        -v "${CurrentDir}/trade_retrospective.json:/app/trade_retrospective.json" `
        -v "${CurrentDir}/theme_data.json:/app/theme_data.json" `
        -v "${CurrentDir}/trading.log:/app/trading.log" `
        -v "${CurrentDir}/telegram.log:/app/telegram.log" `
        -v "${CurrentDir}/error.log:/app/error.log" `
        -v "${CurrentDir}/update_trigger:/app/update_trigger" `
        ai-vibe-trader:latest
}
