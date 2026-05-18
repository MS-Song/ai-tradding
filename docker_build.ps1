# ==========================================================
# 🐳 AI-Vibe-Trader Windows Docker Image Build Script
# ==========================================================
# 실행 방법: PowerShell을 열고 .\docker_build.ps1 실행
# (실행 정책 문제 발생 시: powershell -ExecutionPolicy Bypass -File .\docker_build.ps1)

$ErrorActionPreference = "Stop"

Write-Host "[*] AI-Vibe-Trader 도커 이미지 빌드 작업을 시작합니다..." -ForegroundColor Cyan

# 1. 스크립트가 위치한 프로젝트 루트 디렉터리로 안전 이동
$ScriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($ScriptPath) {
    Set-Location $ScriptPath
}

# 2. Docker 엔진 실행 여부 검증
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "[!] Docker 엔진이 시스템에 설치되어 있지 않거나 PATH 경로에 없습니다." -ForegroundColor Red
    Write-Host "[!] Docker Desktop을 설치하고 실행해 주세요." -ForegroundColor Red
    Exit 1
}

try {
    $null = & docker info 2>&1
} catch {
    Write-Host "[!] Docker 데몬이 실행 중이 아니거나 권한이 부족합니다." -ForegroundColor Red
    Write-Host "[!] Docker Desktop이 정상적으로 켜져 있는지 확인해 주세요." -ForegroundColor Red
    Exit 1
}

# 3. Docker 이미지 빌드 수행 (경량화 캐시 반영)
$ImageTag = "ai-vibe-trader:latest"
Write-Host "[*] 'Dockerfile'을 기반으로 최적화된 '$ImageTag' 이미지 빌드 중..." -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Gray

& docker build -t $ImageTag .

$BuildStatus = $LASTEXITCODE
Write-Host "==========================================================" -ForegroundColor Gray

# 4. 빌드 결과 판단 및 사용자 피드백
if ($BuildStatus -eq 0) {
    Write-Host "[V] 성공: AI-Vibe-Trader 도커 이미지 빌드가 완료되었습니다!" -ForegroundColor Green
    Write-Host "[V] 이미지명: $ImageTag" -ForegroundColor Green
    Write-Host "[*] 이제 '.\docker_run.ps1' 스크립트를 실행하여 TUI 트레이딩 엔진을 구동할 수 있습니다." -ForegroundColor Yellow
} else {
    Write-Host "[!] 실패: 도커 빌드 중 오류가 발생했습니다. 로그 메시지를 확인해 주세요." -ForegroundColor Red
    Exit $BuildStatus
}
