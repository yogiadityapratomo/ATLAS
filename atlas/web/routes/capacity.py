"""Menu Disk Pool & Tape Library — kontrak JSON sama dengan web V4 (design 03 §5)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from atlas.core.errors import NotFoundError
from atlas.core.logging import log_event
from atlas.repositories import capacity as capacity_repo
from atlas.services import capacity as capacity_service
from atlas.services.excel_export import capacity_workbook
from atlas.web.deps import AppState, get_state

router = APIRouter()
logger = logging.getLogger("atlas.web.capacity")
TZ = ZoneInfo("Asia/Jakarta")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _version(state: AppState) -> tuple[int | None, int | None]:
    def load() -> tuple[int | None, int | None]:
        with state.connection() as conn:
            runs = conn.execute("SELECT source, run_id FROM capacity.latest_run").fetchall()
        ids = dict(runs)
        return ids.get("capacity"), ids.get("tape")

    return state.versions.get(load)


def _etag(version: tuple[int | None, int | None]) -> str:
    return f'W/"cap-{version[0] or 0}-{version[1] or 0}"'


def _build_payload(state: AppState) -> dict[str, Any]:
    with state.connection() as conn:
        latest = capacity_repo.latest_runs(conn)
        attempts = capacity_repo.last_attempts(conn)
        disk = tape = []
        if "capacity" in latest:
            disk = [
                capacity_service.disk_row_from_db(r)
                for r in capacity_repo.disk_rows(conn, latest["capacity"].run_id)
            ]
        if "tape" in latest:
            tape = [
                capacity_service.tape_row_from_db(r)
                for r in capacity_repo.tape_rows(conn, latest["tape"].run_id)
            ]

    def iso(source: str) -> str | None:
        run = latest.get(source)
        when = run.collected_at or run.finished_at if run else None
        return when.astimezone(TZ).isoformat(timespec="seconds") if when else None

    def status(source: str) -> dict[str, Any]:
        run, attempt = latest.get(source), attempts.get(source, {})
        return {
            "data_run_id": run.run_id if run else None,
            "data_status": run.status if run else None,
            "errors": (run.details or {}).get("errors") or {} if run else {},
            "last_attempt_status": attempt.get("status"),
            "last_attempt_at": attempt["started_at"].astimezone(TZ).isoformat(timespec="seconds")
            if attempt.get("started_at")
            else None,
            "last_error_id": attempt.get("error_id"),
        }

    return {
        "disk_pools": disk,
        "tape_library": tape,
        "last_updated": iso("capacity"),
        "tape_last_updated": iso("tape"),
        "collect_status": {"capacity": status("capacity"), "tape": status("tape")},
    }


@router.get("/api/data")
def get_data(request: Request, state: AppState = Depends(get_state)) -> Response:
    """Data dashboard terbaru. ``ETag`` = versi data → browser yang sudah punya data dapat 304."""
    version = _version(state)
    etag = _etag(version)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    payload = state.cache.get_or_build(("api_data", version), lambda: _build_payload(state))
    return JSONResponse(payload, headers={"ETag": etag, "Cache-Control": "no-cache"})


@router.get("/api/export")
def export_excel(state: AppState = Depends(get_state)) -> Response:
    """Excel kapasitas 3 sheet (format V4), dibuat sekali per versi data."""
    version = _version(state)
    if version == (None, None):
        raise NotFoundError(
            "belum ada data kapasitas", user_message="Belum ada data. Tunggu proses pengumpulan berikutnya."
        )

    def build() -> bytes:
        payload = state.cache.get_or_build(("api_data", version), lambda: _build_payload(state))
        return capacity_workbook(payload["disk_pools"], payload["tape_library"], now=datetime.now(TZ))

    content = state.cache.get_or_build(("export_xlsx", version), build)
    filename = f"capacity_report_{datetime.now(TZ).strftime('%Y%m%d_%H%M')}.xlsx"
    log_event(
        logger, "app", "export_excel", "Export Excel kapasitas", bytes=len(content), version=list(version)
    )
    return Response(
        content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/api/generate")
def generate() -> JSONResponse:
    """V4: memicu fetch live dari web. ATLAS: web tidak pernah menembak master NBU (job terjadwal)."""
    log_event(
        logger,
        "security",
        "live_nbu_blocked",
        "POST /api/generate ditolak: pengambilan data dilakukan job terjadwal",
        severity="warning",
    )
    return JSONResponse(
        {
            "error": "Generate manual dari web tidak tersedia. Data diperbarui otomatis oleh job terjadwal "
            "setiap 10 menit."
        },
        status_code=403,
    )
