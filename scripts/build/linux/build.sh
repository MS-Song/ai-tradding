#!/bin/bash
echo "[*] Starting Linux Build Process..."

# 1. Move to project root
cd "$(dirname "$0")/../../.."

# 2. Setup Python Virtual Environment
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller xhtml2pdf markdown2 reportlab pillow

# 3. Run PyInstaller
echo "[*] Packaging KIS-Vibe-Trader for Linux..."
pyinstaller --onefile --clean --strip \
    --name KIS-Vibe-Trader-Linux \
    --exclude-module tkinter \
    --exclude-module tcl \
    --exclude-module tk \
    --exclude-module numpy \
    --exclude-module pandas \
    --exclude-module matplotlib \
    --exclude-module xhtml2pdf \
    --exclude-module reportlab \
    --exclude-module PIL \
    --exclude-module pillow \
    --exclude-module PyQt5 \
    --exclude-module PyQt6 \
    --exclude-module PySide2 \
    --exclude-module PySide6 \
    --exclude-module scipy \
    --exclude-module sqlalchemy \
    --exclude-module notebook \
    --exclude-module ipykernel \
    --exclude-module docutils \
    --hidden-import requests \
    --hidden-import yaml \
    --hidden-import python-dotenv \
    --hidden-import bs4 \
    --hidden-import lxml \
    main.py

# 4. Generate PDF Manual
echo "[*] Generating PDF User Manual..."
python3 scripts/build/gen_pdf.py

# 5. Move to target
mkdir -p target
mv dist/KIS-Vibe-Trader-Linux target/
cp fonts/D2Coding.ttf target/

# 6. Cleanup
rm -rf build dist KIS-Vibe-Trader-Linux.spec

echo "[V] Build Complete! Check target/ directory"
