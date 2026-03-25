@echo off
echo [*] Starting Windows Build Process...

REM 1. 프로젝트 루트로 이동
cd /d "%~dp0..\..\.."

REM 2. 가상환경(.venv) 또는 시스템 파이썬(python) 경로 설정
set PYTHON_EXE=python
set PYINSTALLER_EXE=pyinstaller

if exist .venv (
    echo [*] Local virtual environment (.venv) found. Using it...
    set PYTHON_EXE=.\.venv\Scripts\python
    set PYINSTALLER_EXE=.\.venv\Scripts\pyinstaller
) else (
    echo [*] No .venv found. Using system environment (CI/GitHub Actions Mode).
)

REM 3. PyInstaller 실행 (EXE 패키징)
echo [*] Packaging KIS-Vibe-Trader into a single EXE...
%PYINSTALLER_EXE% --onefile --clean ^
    --name KIS-Vibe-Trader ^
    --add-data "src;src" ^
    --hidden-import requests ^
    --hidden-import yaml ^
    --hidden-import dotenv ^
    --hidden-import bs4 ^
    --hidden-import lxml ^
    main.py

if %ERRORLEVEL% neq 0 (
    echo [!] PyInstaller failed with error %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

REM 4. 결과물 이동
echo [*] Moving executable to target folder...
if not exist target mkdir target
move /y dist\KIS-Vibe-Trader.exe target\

REM 5. PDF 매뉴얼 생성
echo [*] Generating PDF User Manual...
%PYTHON_EXE% scripts/build/gen_pdf.py

REM 6. 정리
echo [*] Cleaning up temporary files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist KIS-Vibe-Trader.spec del /f /q KIS-Vibe-Trader.spec

echo [V] Build Complete! Check target/ directory
