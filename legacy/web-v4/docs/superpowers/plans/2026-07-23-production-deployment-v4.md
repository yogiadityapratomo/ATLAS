# Production Deployment (V4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a `D:\NetbackupBotV4` folder that is a full, working copy of `D:\NetbackupBotV3` plus everything needed to stand it up as an independent, always-on production service — so the user can copy-paste that folder to the production server and run one script.

**Architecture:** `V3` is copied wholesale to `V4` as a safety snapshot (V3 stays untouched). `V4` gains a pinned `requirements.txt` and a `deploy_production.bat` that creates an isolated venv, installs dependencies, and registers the app as an NSSM Windows Service bound to `0.0.0.0:8791` — fully isolated from the unrelated FastAPI app already running on the server's port 8443.

**Tech Stack:** Python 3.13 (matches the dev machine), FastAPI, Uvicorn, NSSM (Windows service manager, already installed on the target server), Windows batch script.

## Global Constraints

- Port: `8791` (must not collide with the existing app on `8443`).
- Service name: `NetBackupCapacityV4`.
- Host binding: `0.0.0.0` (so the service is reachable over the network/VPN, not just localhost).
- Dependency versions pinned exactly to what's installed in dev: `fastapi==0.115.13`, `uvicorn==0.34.3`, `requests==2.32.3`, `openpyxl==3.1.5`.
- No authentication/access-control changes — VPN is the trust boundary.
- Deployment is a manual folder copy, not git-based — `capacity_cache_V2_patched.py` (gitignored, holds master tokens) must travel with the copy.
- `NetbackupBotV3` must remain byte-for-byte untouched — all new/changed files go into `V4` only.
- Do not `git commit` any changes automatically — leave that for the user to request explicitly.

---

### Task 1: Snapshot-copy V3 into V4

**Files:**
- Create: `D:\NetbackupBotV4\` (recursive copy of everything under `D:\NetbackupBotV3\`, including `.git`, `.claude`, `.superpowers`, `cache/`, `logs/`, `report/`, `__pycache__/`)
- Test: none (filesystem operation) — verified by diffing the two trees

**Interfaces:**
- Produces: `D:\NetbackupBotV4` as the working directory every later task in this plan writes into.

- [ ] **Step 1: Confirm V4 doesn't already exist**

Run: `ls -d /d/NetbackupBotV4 2>&1`
Expected: `ls: cannot access '/d/NetbackupBotV4': No such file or directory` (if it already exists, stop and check with the user before overwriting anything).

- [ ] **Step 2: Copy the whole tree**

Run:
```bash
cp -r "/d/NetbackupBotV3" "/d/NetbackupBotV4"
```

- [ ] **Step 3: Verify the copy is identical**

Run:
```bash
diff -rq /d/NetbackupBotV3 /d/NetbackupBotV4
```
Expected: no output (empty diff — the two trees are identical right after the copy).

---

### Task 2: Add `requirements.txt` to V4 and verify it installs cleanly

**Files:**
- Create: `D:\NetbackupBotV4\requirements.txt`
- Modify: `D:\NetbackupBotV4\.gitignore` (add `venv/`, since `deploy_production.bat` in Task 3 will create one inside this folder on the server)
- Test: throwaway venv under the scratchpad directory, deleted at the end of this task

**Interfaces:**
- Consumes: `D:\NetbackupBotV4` from Task 1.
- Produces: `D:\NetbackupBotV4\requirements.txt`, which Task 3's `deploy_production.bat` installs via `pip install -r requirements.txt`.

- [ ] **Step 1: Write `requirements.txt`**

```
fastapi==0.115.13
uvicorn==0.34.3
requests==2.32.3
openpyxl==3.1.5
```

- [ ] **Step 2: Add `venv/` to V4's `.gitignore`**

Append to `D:\NetbackupBotV4\.gitignore`:
```
venv/
```

- [ ] **Step 3: Build a throwaway venv and install from the new file**

Run (use the session scratchpad directory so this never touches V4 itself):
```bash
python -m venv "$SCRATCH/v4_reqs_test_venv"
"$SCRATCH/v4_reqs_test_venv/Scripts/pip.exe" install -r /d/NetbackupBotV4/requirements.txt
```
Expected: pip reports all 4 packages (plus their transitive deps) installed successfully, no errors.

- [ ] **Step 4: Verify the installed packages actually import**

Run:
```bash
"$SCRATCH/v4_reqs_test_venv/Scripts/python.exe" -c "import fastapi, uvicorn, requests, openpyxl; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Clean up the throwaway venv**

Run:
```bash
rm -rf "$SCRATCH/v4_reqs_test_venv"
```

---

### Task 3: Add `deploy_production.bat` to V4 and smoke-test the command it runs

**Files:**
- Create: `D:\NetbackupBotV4\deploy_production.bat`
- Test: throwaway venv under the scratchpad directory, running the actual `app:app` on port 8791, deleted at the end of this task

**Interfaces:**
- Consumes: `D:\NetbackupBotV4\requirements.txt` from Task 2; `D:\NetbackupBotV4\app.py` (unmodified, exposes the `app` FastAPI instance uvicorn needs).
- Produces: `D:\NetbackupBotV4\deploy_production.bat`, the single script the user runs (as Administrator) on the production server after copy-pasting the `V4` folder there.

- [ ] **Step 1: Write `deploy_production.bat`**

```bat
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

echo === NetBackup Capacity Dashboard - Production Setup ===
echo App dir: %APP_DIR%
echo Service: %SERVICE_NAME%
echo Port:    %PORT%
echo.

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo FAILED: could not create venv. Is Python installed and on PATH?
        exit /b 1
    )
) else (
    echo Virtual environment already exists, skipping creation.
)

echo Installing dependencies...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip >nul
"%VENV_DIR%\Scripts\pip.exe" install -r "%APP_DIR%\requirements.txt"
if errorlevel 1 (
    echo FAILED: pip install failed.
    exit /b 1
)

if not exist "%APP_DIR%\logs" mkdir "%APP_DIR%\logs"

echo Registering Windows service via NSSM...
nssm install %SERVICE_NAME% "%VENV_DIR%\Scripts\python.exe" "-m uvicorn app:app --host 0.0.0.0 --port %PORT%"
nssm set %SERVICE_NAME% AppDirectory "%APP_DIR%"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout "%APP_DIR%\logs\service_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%APP_DIR%\logs\service_stderr.log"

echo Starting service...
nssm start %SERVICE_NAME%

echo.
echo Done. Dashboard should be reachable at http://<this-server-ip>:%PORT%
echo Check status any time with: nssm status %SERVICE_NAME%
endlocal
```

- [ ] **Step 2: Smoke-test the exact command the script will run (everything except the NSSM registration, since NSSM isn't installed on this dev machine — only on the production server)**

Build a throwaway venv the same way `deploy_production.bat` would, install into it, then run the literal `python -m uvicorn app:app --host 0.0.0.0 --port 8791` command against V4's real code:
```bash
python -m venv "$SCRATCH/v4_smoke_test_venv"
"$SCRATCH/v4_smoke_test_venv/Scripts/pip.exe" install -r /d/NetbackupBotV4/requirements.txt
```

- [ ] **Step 3: Start the app in the background on the production port**

Run in `D:\NetbackupBotV4` (background):
```bash
"$SCRATCH/v4_smoke_test_venv/Scripts/python.exe" -m uvicorn app:app --host 0.0.0.0 --port 8791
```
(run with `run_in_background: true`, working directory `D:\NetbackupBotV4`)

- [ ] **Step 4: Verify it actually serves the dashboard on 8791**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8791/api/data
```
Expected: `200`

- [ ] **Step 5: Stop the background process and clean up**

Stop the uvicorn process started in Step 3, then:
```bash
rm -rf "$SCRATCH/v4_smoke_test_venv"
```

- [ ] **Step 6: Note the untestable part for the user**

`deploy_production.bat`'s `nssm install/set/start` lines cannot be executed on this dev machine (NSSM isn't installed here — only on the production server). Flag this clearly in the final report: the script has been written and the app-startup command it uses has been verified end-to-end, but the NSSM service-registration lines will run for the first time on the actual production server and should be watched during that first run.
