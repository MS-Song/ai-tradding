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
pyinstaller --onefile --clean \
    --name KIS-Vibe-Trader-Linux \
    --add-data "src:src" \
    main.py

# 4. Generate PDF Manual
echo "[*] Generating PDF User Manual..."
python3 scripts/build/gen_pdf.py

# 5. Move to target
mkdir -p target
mv dist/KIS-Vibe-Trader-Linux target/
cp target/USER_MANUAL.pdf target/

# 6. Cleanup
rm -rf build dist KIS-Vibe-Trader-Linux.spec

echo "[V] Build Complete! Check target/ directory"
