@echo off
title NetBackup Capacity Report
cd /d "%~dp0"

echo Menjalankan NetBackup Capacity Report...
echo Pastikan VPN sudah connect sebelum klik "Generate Data".
echo.

start "" cmd /c "timeout /t 2 >nul & start http://localhost:8000"

python -m uvicorn app:app --host 0.0.0.0 --port 8000

echo.
echo Server berhenti. Tekan tombol apa saja untuk menutup jendela ini.
pause >nul
