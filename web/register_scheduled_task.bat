@echo off
setlocal

net session >nul 2>&1
if not %errorlevel%==0 (
    echo This script must be run as Administrator.
    exit /b 1
)

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "TASK_NAME=NetBackupCapacityCollector"
set "PYTHON_EXE=%APP_DIR%\venv\Scripts\python.exe"
set "SCRIPT=%APP_DIR%\scheduled_collect.py"

if not exist "%PYTHON_EXE%" (
    echo FAILED: venv not found at %PYTHON_EXE% - run deploy_production.bat first.
    exit /b 1
)

echo Registering scheduled task "%TASK_NAME%" (every 10 minutes)...
schtasks /create /tn "%TASK_NAME%" ^
    /tr "\"%PYTHON_EXE%\" \"%SCRIPT%\"" ^
    /sc minute /mo 10 ^
    /ru SYSTEM /rl HIGHEST /f

if errorlevel 1 (
    echo FAILED: schtasks registration failed.
    exit /b 1
)

echo.
echo Done. Task "%TASK_NAME%" will run every 10 minutes.
echo Check status any time with: schtasks /query /tn "%TASK_NAME%"
echo Run it once immediately with: schtasks /run /tn "%TASK_NAME%"
endlocal
