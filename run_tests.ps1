# AI-Vibe-Trader Test Runner (PowerShell)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " AI-Vibe-Trader 통합 테스트 실행 중..." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

python run_all_tests.py

Write-Host "`n테스트가 완료되었습니다. 창을 닫으려면 아무 키나 누르세요..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
