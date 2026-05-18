@echo off
REM ==========================================================
REM 🐳 AI-Vibe-Trader Windows Docker Image Build Batch File
REM ==========================================================
REM 실행 방법: 더블 클릭하거나 cmd에서 docker_build.bat 실행

echo [*] 파워쉘 스크립트를 통해 도커 빌드를 안전하게 실행합니다...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0docker_build.ps1"
if %errorlevel% neq 0 (
    echo [!] 빌드 도중 에러가 발생했습니다. (Error Code: %errorlevel%)
    pause
    exit /b %errorlevel%
)
pause
