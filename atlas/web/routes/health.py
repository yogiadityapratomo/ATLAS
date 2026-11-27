"""``GET /api/health`` — status DB & kesegaran data per sumber (dasar halaman healthcheck nanti)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from atlas import __version__
from atlas.core.errors import DatabaseError
from atlas.web.deps import AppState, get_state

router = APIRouter()
TZ = ZoneInfo("Asia/Jakarta")
# batas umur data sebelum dianggap basi (menit); kapasitas dikumpulkan tiap 10 menit.
# Umur dihitung dari waktu data diambil (details.collected_at), bukan waktu run selesai.
STALE_AFTER_MIN = {"capacity": 30, "tape": 30, "backup_inventory": 60, "cmdb": None}


@router.get("/api/health")
def health(state: AppState = Depends(get_state)) -> JSONResponse:
    now = datetime.now(TZ)
    try:
        with state.connection() as conn:
            rows = conn.execute(
                """
                SELECT s.source,
                       ok.finished_at, ok.status,
                       last.status, last.started_at, last.error_id
                  FROM unnest(ARRAY['capacity', 'tape', 'backup_inventory', 'cmdb']) AS s(source)
                  LEFT JOIN LATERAL (
                        SELECT coalesce((details->>'collected_at')::timestamptz, finished_at) AS finished_at,
                               status
                          FROM core.collect_run r
                         WHERE r.source = s.source AND r.status IN ('success', 'partial')
                         ORDER BY r.finished_at DESC LIMIT 1) ok ON true
                  LEFT JOIN LATERAL (
                        SELECT status, started_at, error_id FROM core.collect_run r
                         WHERE r.source = s.source ORDER BY started_at DESC LIMIT 1) last ON true
                """
            ).fetchall()
    except DatabaseError as exc:
        body = {"status": "down", "db": "down", "error_id": exc.error_id, "version": __version__}
        return JSONResponse(body, status_code=503)

    sources = {}
    degraded = False
    for source, ok_at, ok_status, last_status, last_at, last_error in rows:
        age_min = round((now - ok_at).total_seconds() / 60, 1) if ok_at else None
        limit = STALE_AFTER_MIN.get(source)
        stale = ok_at is None if limit is None else (age_min is None or age_min > limit)
        if source in ("capacity", "tape") and (stale or last_status == "failed"):
            degraded = True
        sources[source] = {
            "last_success_at": ok_at.astimezone(TZ).isoformat(timespec="seconds") if ok_at else None,
            "last_success_status": ok_status,
            "age_minutes": age_min,
            "stale": stale,
            "last_attempt_status": last_status,
            "last_attempt_at": last_at.astimezone(TZ).isoformat(timespec="seconds") if last_at else None,
            "last_error_id": last_error,
        }
    body = {
        "status": "degraded" if degraded else "ok",
        "db": "ok",
        "version": __version__,
        "checked_at": now.isoformat(timespec="seconds"),
        "sources": sources,
    }
    return JSONResponse(body)
