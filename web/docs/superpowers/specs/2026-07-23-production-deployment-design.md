# Production Deployment Design — NetBackup Capacity Dashboard (V4)

## Context

`NetbackupBotV3` currently only runs on the developer's local machine, reachable only when connected to VPN. Goal: run an independent, always-on instance on a production Windows server so the whole team can reach it over VPN, without disturbing anything else already running on that server.

## Decisions

- **Snapshot first.** `D:\NetbackupBotV3` is copied wholesale to a new sibling folder `D:\NetbackupBotV4`. `V3` is left untouched as a safety backup; `V4` is the copy that gets adjusted for production and is the one copy-pasted to the server.
- **Server facts (as given by the user):** Python is already installed; NSSM is already installed; a separate, unrelated FastAPI app is already running there on port 8443.
- **Full isolation from the existing app.** V4 gets its own virtual environment and its own NSSM-managed Windows Service — no shared Python environment, no shared port, no code merged into the existing 8443 app. Reason: installing packages into a shared/global Python environment risks silently upgrading or downgrading a dependency (e.g. `fastapi`) that the other app also relies on.
- **Port:** `8791` (chosen only to avoid colliding with the existing 8443 app; the user can pick a different number later without any other design change).
- **No authentication layer.** VPN + internal network access is treated as the trust boundary, consistent with how the dashboard already worked locally.
- **Deployment method: manual folder copy** (zip / network share / RDP), not a git-based deploy. This means `capacity_cache_V2_patched.py` (gitignored, holds the per-master bearer tokens) is carried along automatically as part of the filesystem copy — gitignore only affects `git` operations, not a plain folder copy.
- **Process supervision: NSSM Windows Service**, so the app auto-starts if the server reboots and auto-restarts if the process crashes, without anyone needing to log in and start it manually.

## What gets added to V4

1. **`requirements.txt`** — pins `fastapi`, `uvicorn`, `requests`, `openpyxl` to the versions the app is currently developed against, so `pip install -r requirements.txt` on the server reproduces the same environment instead of pulling arbitrary latest versions.
2. **`deploy_production.bat`** — one-time setup script, run as Administrator on the production server after the folder is copied there. It:
   - creates a `venv/` inside the app folder (if not already present),
   - installs `requirements.txt` into that venv,
   - registers the app as an NSSM service (name: `NetBackupCapacityV4`) running `venv\Scripts\python.exe -m uvicorn app:app --host 0.0.0.0 --port 8791` with the app folder as its working directory,
   - sets the service to auto-start, and starts it immediately.

No changes are made to `app.py`, `netbackup_core.py`, or `capacity_cache_V2_patched.py` — the port and host are supplied as service arguments, not hardcoded into the app.

## Out of scope

- Authentication / access control on the API or dashboard.
- Portable/bundled Python distribution or a PyInstaller-compiled executable (unnecessary — Python is already on the server).
- Automated updates (e.g. `git pull` on the server). Future code updates mean re-copying the `V4` folder and restarting the NSSM service manually; that's an accepted trade-off for now.
- Any change to `NetbackupBotV3` — it stays exactly as-is, as the backup copy.
