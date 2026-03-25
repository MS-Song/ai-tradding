#!/bin/bash
echo "[*] Starting Linux Build Process..."

# 1. Move to project root
cd "$(dirname "$0")/../../.."

# 2. Check for virtual environment
if [ ! -d ".venv" ]; then
    echo "[!] .venv not found. Please set up the environment first."
    exit 1
fi

# 3. Run PyInstaller
echo "[*] Packaging KIS-Vibe-Trader into a binary..."
source .venv/bin/activate
pyinstaller --onefile --clean \
    --name KIS-Vibe-Trader \
    --add-data "src:src" \
    --hidden-import requests \
    --hidden-import yaml \
    --hidden-import dotenv \
    --hidden-import bs4 \
    --hidden-import lxml \
    main.py

# 4. Move to target
echo "[*] Moving binary to target folder..."
mkdir -p target
mv dist/KIS-Vibe-Trader target/

# 5. Cleanup
echo "[*] Cleaning up temporary files..."
rm -rf build dist KIS-Vibe-Trader.spec

echo "[V] Build Complete! Check target/KIS-Vibe-Trader"
