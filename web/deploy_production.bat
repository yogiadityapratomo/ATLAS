@echo off
setlocal

net session >nul 2>&1
if not %errorlevel%==0 (
    echo This script must be run as Administrator.
    exit /b 1
)

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "SERVICE_NAME=NetBackupCapacityV4"
set "PORT=8791"
set "VENV_DIR=%APP_DIR%\venv"
set "NSSM=C:\nssm-2.24\win64\nssm.exe"

if not exist "%NSSM%" (
    echo FAILED: nssm.exe not found at %NSSM% - edit the NSSM path at the top of this script.
    exit /b 1
)

echo === NetBackup Capacity Dashboard - Production Setup ===
echo App dir: %APP_DIR%
echo Service: %SERVICE_NAME%
echo Port:    %PORT%
echo.

if exist "%VENV_DIR%\Scripts\python.exe" (
    "%VENV_DIR%\Scripts\python.exe" -c "" >nul 2>&1
    if errorlevel 1 (
        echo Existing venv is broken ^(likely copied from another machine^) - removing it...
        rmdir /s /q "%VENV_DIR%"
    )
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo FAILED: could not create venv. Is Python installed and on PATH?
        exit /b 1
    )
) else (
    echo Virtual environment already exists and works, skipping creation.
)

echo Installing dependencies (offline, from wheels_offline\ - no internet required)...
"%VENV_DIR%\Scripts\pip.exe" install --no-index --find-links="%APP_DIR%\wheels_offline" -r "%APP_DIR%\requirements.txt"
if errorlevel 1 (
    echo FAILED: pip install failed.
    exit /b 1
)

if not exist "%APP_DIR%\logs" mkdir "%APP_DIR%\logs"

echo Registering Windows service via NSSM...
"%NSSM%" install %SERVICE_NAME% "%VENV_DIR%\Scripts\python.exe" "-m uvicorn app:app --host 0.0.0.0 --port %PORT%"
if errorlevel 1 (
    echo FAILED: nssm install failed - see output above.
    exit /b 1
)
"%NSSM%" set %SERVICE_NAME% AppDirectory "%APP_DIR%"
"%NSSM%" set %SERVICE_NAME% Start SERVICE_AUTO_START
"%NSSM%" set %SERVICE_NAME% AppStdout "%APP_DIR%\logs\service_stdout.log"
"%NSSM%" set %SERVICE_NAME% AppStderr "%APP_DIR%\logs\service_stderr.log"

echo Starting service...
"%NSSM%" start %SERVICE_NAME%
if errorlevel 1 (
    echo FAILED: could not start the service - check %APP_DIR%\logs\service_stderr.log
    exit /b 1
)

echo.
echo Done. Dashboard should be reachable at http://<this-server-ip>:%PORT%
echo Check status any time with: "%NSSM%" status %SERVICE_NAME%
endlocal
