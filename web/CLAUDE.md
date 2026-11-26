# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Internal dashboard for monitoring NetBackup storage capacity (disk pool + tape library) across three master servers — TBS, BSD, BRN. FastAPI backend, vanilla jQuery frontend (no build step). UI text is in Bahasa Indonesia.

## Running

- `run.bat` — starts the server on port 8000 and opens the browser (Windows). Requires VPN connected to reach the NetBackup master servers.
- Manually: `python -m uvicorn app:app --reload --port 8000`
- No `requirements.txt` in the repo — dependencies are `fastapi`, `uvicorn`, `requests`, `openpyxl` (install manually if missing).
- No test suite or lint config exists in this repo.

## Architecture

- `app.py` — FastAPI app with 4 routes: `/` (serves `static/index.html`), `GET /api/data` (reads last cached JSON, no live fetch), `POST /api/generate` (triggers a live fetch from all masters), `GET /api/export` (downloads the generated xlsx).
- `netbackup_core.py` — shared fetch/transform/export logic for both disk pool and tape library. Imports `capacity_cache_V2_patched.py` as `legacy` for master URLs/tokens and the disk-pool fetch — that file is the single source of truth for master config, don't duplicate it elsewhere.
- `capacity_cache_V2_patched.py` — **gitignored**, contains hardcoded base URLs + bearer tokens for the 3 masters. It's the original standalone script (has its own `main()` for CLI use) that `netbackup_core.py` wraps/extends rather than replaces. Keep it out of git.
- Masters are fetched **sequentially, not in parallel** — firing concurrent requests over the VPN tunnel was found to make all masters fail together (see comments in `generate_all()` in `netbackup_core.py`).
- Disk pool and tape library have separate timeout budgets (45s vs 180s per master) — tape inventory is cursor-paginated and can span dozens of pages per master, while disk-pool result sets are small.
- Tape robot→site mapping (`ROBOT_SITE_MAP`) and tape library metadata (`TAPE_LIBRARY_INFO`) in `netbackup_core.py` are hardcoded per master — exhaustive by design, not auto-discovered.
- Data flow: `POST /api/generate` → `netbackup_core.generate_all()` → live fetch from all 3 masters → writes `cache/capacity_cache.json` + `cache/tape_cache.json` → exports `report/capacity_report.xlsx` → returns fresh data to the frontend. Page load (`GET /api/data`) only reads the cached JSON, so the dashboard shows the last-generated data until the user clicks Generate.
- Frontend is `static/index.html` + `static/app.js` (jQuery, no bundler) + `static/style.css`. Two views (Disk Pool / Tape Library) toggled via the sidebar, with all client state in a single `state` object in `app.js`. `static/vendor/html2canvas.min.js` powers the "capture as image" button, which screenshots specific DOM cards to PNG.

## Conventions

- Master color coding is consistent across the UI: purple/pink/orange gradients keyed by master (BRN/BSD/TBS) — see `THEME` in `app.js`.
- Keep new user-facing strings in Bahasa Indonesia, consistent with the existing UI text.
- Past feature design docs (superpowers plans/specs) live under `docs/superpowers/plans/` and `docs/superpowers/specs/` — check there for rationale behind existing chart/table layouts before redesigning them.
