@echo off
echo [*] Starting Windows Build Process...

REM 1. Move to project root
cd /d "%~dp0..\..\.."

REM 2. Set Python paths
set PYTHON_EXE=python
set PYINSTALLER_EXE=pyinstaller

if exist .venv (
    echo [*] Local virtual environment found. Using .venv...
    set PYTHON_EXE=.\.venv\Scripts\python
    set PYINSTALLER_EXE=.\.venv\Scripts\pyinstaller
) else (
    echo [*] No .venv found. Using system environment.
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
    echo [!] PyInstaller failed with error %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

REM 4. Move output
echo [*] Moving executable to target folder...
if not exist target mkdir target
move /y dist\KIS-Vibe-Trader.exe target\

REM 5. Generate PDF
echo [*] Generating PDF User Manual...
%PYTHON_EXE% scripts/build/gen_pdf.py

if %ERRORLEVEL% neq 0 (
    echo [!] PDF Generation failed.
)

REM 6. Cleanup
echo [*] Cleaning up...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist KIS-Vibe-Trader.spec del /f /q KIS-Vibe-Trader.spec

echo [V] Build Complete! Check target directory.
