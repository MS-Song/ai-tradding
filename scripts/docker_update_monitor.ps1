# ==============================================================================
# 🐳 AI-Vibe-Trader Docker 호스트 자동 업데이트 모니터 스크립트 (Windows용)
# ==============================================================================
# 이 스크립트는 Windows 호스트 OS의 백그라운드 PowerShell에서 실행되며,
# TUI 또는 텔레그램을 통해 컨테이너에서 발생한 'update_trigger' 신호를 감시합니다.
# 신호가 감지되면 자동으로 최신 코드를 다운로드하고 도커 컨테이너를 안전하게 재기동합니다.
#
# [실행 방법]
# PowerShell을 열고 scripts/ 디렉터리로 이동 후 실행:
# .\docker_update_monitor.ps1
# (실행 권한 우회 필요 시: powershell -ExecutionPolicy Bypass -File .\docker_update_monitor.ps1)
# ==============================================================================

$ErrorActionPreference = "Continue"

# 스크립트 위치 기준 프로젝트 루트 디렉터리로 안전 이동
$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($ScriptPath) {
    Set-Location (Join-Path $ScriptPath "..")
}

$TriggerFile = "./update_trigger"
$CheckIntervalSeconds = 10

Write-Host "[*] AI-Vibe-Trader Windows Docker 업데이트 모니터 데몬 기동 완료!" -ForegroundColor Green
Write-Host "[*] 감시 대상 파일: $TriggerFile (감시 주기: ${CheckIntervalSeconds}초)" -ForegroundColor White

while ($true) {
    $FullPath = (Resolve-Path $TriggerFile -ErrorAction SilentlyContinue).Path
    
    if ($FullPath -and (Test-Path $FullPath)) {
        $FileInfo = Get-Item $FullPath
        # 파일이 존재하고 크기가 0보다 큰 경우 (신호 수신 상태)
        if ($FileInfo.Length -gt 0) {
            $TimeStr = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            Write-Host "`n🚨 [$TimeStr] 업데이트 요청 신호 감지!" -ForegroundColor Yellow
            Get-Content $FullPath
            
            # 1. 트리거 파일 초기화 (중복 트리거 방지)
            [System.IO.File]::WriteAllText($FullPath, "")
            
            Write-Host "[1/3] 최신 코드 Pull 수행 중... (Git Repo Update)" -ForegroundColor Yellow
            git pull
            
            # docker-compose 구비 확인 및 재배포 수행
            $UseCompose = $false
            if ((Get-Command docker-compose -ErrorAction SilentlyContinue) -or ((& docker compose version 2>$null) -ne $null)) {
                $UseCompose = $true
            }
            
            Write-Host "[2/3] Docker 컨테이너 재부팅 및 빌드 수행 중..." -ForegroundColor Yellow
            if ($UseCompose) {
                try {
                    & docker compose down
                    & docker compose build --no-cache ai-vibe-trader
                    & docker compose up -d
                } catch {
                    & docker-compose down
                    & docker-compose build --no-cache ai-vibe-trader
                    & docker-compose up -d
                }
            } else {
                # docker-compose가 없는 경우 기본 docker CLI로 이미지 재빌드 및 run
                Write-Host "[!] docker-compose 미감지. 수동 docker run 모드로 재시작합니다." -ForegroundColor Red
                $ContainerName = "ai-vibe-trader-app"
                & docker stop $ContainerName > $null 2>&1
                & docker rm $ContainerName > $null 2>&1
                & docker build --no-cache -t ai-vibe-trader:latest .
                
                $CurrentDir = (Resolve-Path .).Path
                & docker run -d `
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
                    --restart unless-stopped `
                    ai-vibe-trader:latest
            }
            
            $EndTimeStr = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            Write-Host "✅ [$EndTimeStr] Docker 자동 업데이트 및 재기동이 성공적으로 완료되었습니다!" -ForegroundColor Green
        }
    }
    Start-Sleep -Seconds $CheckIntervalSeconds
}
