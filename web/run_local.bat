@echo off
title NetBackup Capacity Report (Local Test - V4)
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Venv belum ada di folder ini. Buat dulu dengan:
    echo   python -m venv venv
    echo   venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Menjalankan NetBackup Capacity Report (V4 - local test, port 8791)...
echo.

start "" cmd /c "timeout /t 2 >nul & start http://localhost:8791"

venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8791

echo.
echo Server berhenti. Tekan tombol apa saja untuk menutup jendela ini.
pause >nul
