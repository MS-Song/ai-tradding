@echo off
REM ==========================================================
REM 🐳 AI-Vibe-Trader Windows Docker Run Batch File
REM ==========================================================
REM 실행 방법: 더블 클릭하거나 cmd에서 docker_run.bat 실행

echo [*] 파워쉘 스크립트를 통해 도커 TUI 컨테이너를 안전하게 가동합니다...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker_run.ps1"
if %errorlevel% neq 0 (
    echo [!] 실행 도중 에러가 발생했습니다. (Error Code: %errorlevel%)
    pause
    exit /b %errorlevel%
)
pause
