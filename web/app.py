"""
NetBackup Capacity Report — FastAPI backend.

Serves the jQuery/HTML/CSS dashboard and exposes the generate/export API.

Jalankan dengan:
    uvicorn app:app --reload --port 8000
"""

import os
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import netbackup_core as core

STATIC_DIR = os.path.join(core.BASE_DIR, "static")

app = FastAPI(title="NetBackup Capacity Report")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/data")
def get_data():
    disk_rows = core.load_json(core.DISK_CACHE_FILE)
    tape_rows = core.load_json(core.TAPE_CACHE_FILE)
    last_updated = None
    if os.path.exists(core.DISK_CACHE_FILE):
        last_updated = datetime.fromtimestamp(os.path.getmtime(core.DISK_CACHE_FILE)).isoformat()
    tape_last_updated = None
    if os.path.exists(core.TAPE_CACHE_FILE):
        tape_last_updated = datetime.fromtimestamp(os.path.getmtime(core.TAPE_CACHE_FILE)).isoformat()
    return {
        "disk_pools": disk_rows,
        "tape_library": tape_rows,
        "last_updated": last_updated,
        "tape_last_updated": tape_last_updated,
    }


@app.post("/api/generate")
def generate():
    # DEV lokal: set ATLAS_ALLOW_LIVE_NBU=0 di web/.env agar tombol Generate tidak
    # menembak master NetBackup production. Default (tidak di-set) = diizinkan,
    # sama dengan perilaku production.
    if os.environ.get("ATLAS_ALLOW_LIVE_NBU", "1") != "1":
        return JSONResponse(
            {"error": "Generate live ke master NetBackup dinonaktifkan di environment ini "
                      "(ATLAS_ALLOW_LIVE_NBU=0). Dashboard memakai data cache terakhir."},
            status_code=403,
        )
    result = core.generate_all()
    return result


@app.get("/api/export")
def export_excel_file():
    if not os.path.exists(core.EXCEL_FILE):
        return JSONResponse({"error": "Belum ada data. Klik Generate Data terlebih dahulu."}, status_code=404)
    filename = f"capacity_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return FileResponse(
        core.EXCEL_FILE,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
