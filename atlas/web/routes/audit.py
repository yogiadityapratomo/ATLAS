"""Menu Audit Log — semua event ATLAS (web, DB, job, keamanan, sistem) dari ``audit.event``."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from atlas.repositories import audit as audit_repo
from atlas.services import audit_query as svc
from atlas.web.deps import AppState, get_state

router = APIRouter(prefix="/api/audit")
TZ = ZoneInfo("Asia/Jakarta")


def _filter(
    range_: str = Query("24h", alias="range"),
    category: str | None = None,
    severity: str | None = None,
    component: str | None = Query(None, max_length=100),
    event_type: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=200),
    request_id: str | None = Query(None, max_length=64),
    error_id: str | None = Query(None, max_length=16),
) -> audit_repo.EventFilter:
    return svc.parse_filter(
        now=datetime.now(TZ),
        range_=range_,
        category=category,
        severity=severity,
        component=component,
        event_type=event_type,
        q=q,
        request_id=request_id,
        error_id=error_id,
    )


@router.get("/events")
def events(
    f: audit_repo.EventFilter = Depends(_filter),
    cursor: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=svc.MAX_PAGE),
    state: AppState = Depends(get_state),
) -> JSONResponse:
    with state.connection() as conn:
        rows = audit_repo.list_events(conn, f, before=svc.decode_cursor(cursor), limit=limit + 1)
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = svc.encode_cursor(rows[-1]["occurred_at"], rows[-1]["id"]) if more and rows else None
    return JSONResponse({"items": [svc.to_json(r, TZ) for r in rows], "next_cursor": next_cursor})


@router.get("/summary")
def summary(range_: str = Query("24h", alias="range"), state: AppState = Depends(get_state)) -> JSONResponse:
    f = svc.parse_filter(now=datetime.now(TZ), range_=range_)
    with state.connection() as conn:
        body = audit_repo.summary(conn, f.since)
    return JSONResponse({**body, "range": range_})


@router.get("/export")
def export(f: audit_repo.EventFilter = Depends(_filter), state: AppState = Depends(get_state)) -> Response:
    """CSV (UTF-8 BOM agar terbaca benar di Excel), maksimal 50.000 event sesuai filter."""
    with state.connection() as conn:
        rows = audit_repo.list_events(conn, f, before=None, limit=svc.EXPORT_LIMIT)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(audit_repo.EVENT_COLUMNS)
    for row in rows:
        item = svc.to_json(row, TZ)
        item["details"] = json.dumps(item["details"], ensure_ascii=False)
        writer.writerow([item[c] for c in audit_repo.EVENT_COLUMNS])
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M")
    return Response(
        "﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="atlas_audit_{stamp}.csv"'},
    )
