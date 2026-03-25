@echo off
echo [*] Starting Windows Build Process...

REM 1. Move to project root
cd /d "%~dp0..\..\.."

REM 2. Check for virtual environment
if not exist .venv (
    echo [!] .venv not found. Please set up the environment first.
    exit /b 1
)

REM 3. Run PyInstaller
echo [*] Packaging KIS-Vibe-Trader into a single EXE...
.\.venv\Scripts\pyinstaller --onefile --clean ^
    --name KIS-Vibe-Trader ^
    --add-data "src;src" ^
    --hidden-import requests ^
    --hidden-import yaml ^
    --hidden-import dotenv ^
    --hidden-import bs4 ^
    --hidden-import lxml ^
    main.py

REM 4. Move to target
echo [*] Moving executable to target folder...
if not exist target mkdir target
move /y dist\KIS-Vibe-Trader.exe target\

REM 5. Cleanup
echo [*] Cleaning up temporary files...
rmdir /s /q build
rmdir /s /q dist
del /f /q KIS-Vibe-Trader.spec

echo [V] Build Complete! Check target/KIS-Vibe-Trader.exe
pause
