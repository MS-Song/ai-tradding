@echo off
echo [*] Starting Windows Build Process...

REM 1. Move to project root
cd /d "%~dp0..\..\.."

REM 2. 가상환경 또는 시스템 파이썬 확인
set PYTHON_EXE=python
set PYINSTALLER_EXE=pyinstaller

if exist .venv (
    echo [*] Local virtual environment found. Using .venv...
    set PYTHON_EXE=.\.venv\Scripts\python
    set PYINSTALLER_EXE=.\.venv\Scripts\pyinstaller
) else (
    echo [*] No .venv found. Using system environment (CI Mode).
)

REM 3. Run PyInstaller
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
    echo [!] PyInstaller failed.
    exit /b %ERRORLEVEL%
)

REM 4. Move to target
echo [*] Moving executable to target folder...
if not exist target mkdir target
move /y dist\KIS-Vibe-Trader.exe target\

REM 5. Generate PDF Manual
echo [*] Generating PDF User Manual...
%PYTHON_EXE% scripts/build/gen_pdf.py

REM 6. Cleanup
echo [*] Cleaning up temporary files...
rmdir /s /q build
rmdir /s /q dist
if exist KIS-Vibe-Trader.spec del /f /q KIS-Vibe-Trader.spec

echo [V] Build Complete! Check target/ directory
