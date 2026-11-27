"""Menu Backup Inventory — cari per hostname (sebagian, sama dengan bot) atau per aplikasi (CMDB)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from atlas.core.logging import log_event
from atlas.repositories import inventory as inventory_repo
from atlas.services import inventory_search as svc
from atlas.services.excel_export import inventory_workbook
from atlas.web.deps import AppState, get_state

router = APIRouter(prefix="/api/backup-inventory")
logger = logging.getLogger("atlas.web.inventory")
TZ = ZoneInfo("Asia/Jakarta")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _run(req: svc.SearchRequest, state: AppState) -> dict[str, Any]:
    with state.connection() as conn:
        run = inventory_repo.latest_run(conn)
        no_backup: list[dict[str, Any]] = []
        not_found: list[str] = []
        host_count = None
        if req.mode == "hostname":
            rows, total, not_found = inventory_repo.search_hosts(
                conn,
                req.terms,
                master=req.master,
                policy_type=req.policy_type,
                limit=req.limit,
                offset=req.offset,
            )
        else:
            rows, total, hosts, host_count = inventory_repo.search_app(
                conn,
                req.app or "",
                exact=req.app_exact,
                master=req.master,
                policy_type=req.policy_type,
                limit=req.limit,
                offset=req.offset,
            )
            no_backup = svc.no_backup_rows(hosts)
    return {
        "mode": req.mode,
        "items": svc.with_status(rows),
        "total": total,
        "limit": req.limit,
        "offset": req.offset,
        "truncated": req.offset + len(rows) < total,
        "not_found": not_found,
        "not_found_items": svc.not_found_rows(not_found),
        "no_backup_items": no_backup,
        "app_host_count": host_count,
        "cutoff": run.collected_at.astimezone(TZ).isoformat(timespec="seconds") if run.collected_at else None,
        "last_run_status": run.last_attempt_status,
        "last_error_id": run.last_error_id,
        "columns": [{"key": k, "label": label} for k, label in svc.COLUMNS],
    }


@router.get("/search")
def search(
    hostnames: str | None = Query(None, max_length=20_000),
    app: str | None = Query(None, max_length=svc.MAX_APP_LENGTH),
    app_exact: bool = False,
    master: str | None = Query(None, max_length=100),
    policy_type: str | None = Query(None, max_length=100),
    limit: int = svc.DEFAULT_LIMIT,
    offset: int = 0,
    state: AppState = Depends(get_state),
) -> JSONResponse:
    req = svc.parse_request(
        hostnames=hostnames,
        app=app,
        app_exact=app_exact,
        master=master,
        policy_type=policy_type,
        limit=limit,
        offset=offset,
    )
    result = _run(req, state)
    log_event(
        logger,
        "app",
        "inventory_search",
        f"Cari backup inventory ({req.mode}): {result['total']} baris",
        mode=req.mode,
        terms=len(req.terms),
        app=req.app,
        master=req.master,
        policy_type=req.policy_type,
        total=result["total"],
        not_found=len(result["not_found"]),
        no_backup=len(result["no_backup_items"]),
    )
    return JSONResponse(result)


@router.get("/apps")
def apps(
    q: str = Query("", max_length=svc.MAX_APP_LENGTH), state: AppState = Depends(get_state)
) -> JSONResponse:
    q = q.strip()
    if len(q) < 2:
        return JSONResponse([])
    with state.connection() as conn:
        return JSONResponse(inventory_repo.suggest_apps(conn, q))


@router.get("/filters")
def filters(state: AppState = Depends(get_state)) -> JSONResponse:
    with state.connection() as conn:
        return JSONResponse(inventory_repo.filter_options(conn))


@router.get("/export")
def export(
    hostnames: str | None = Query(None, max_length=20_000),
    app: str | None = Query(None, max_length=svc.MAX_APP_LENGTH),
    app_exact: bool = False,
    master: str | None = Query(None, max_length=100),
    policy_type: str | None = Query(None, max_length=100),
    state: AppState = Depends(get_state),
) -> Response:
    req = svc.parse_request(
        hostnames=hostnames,
        app=app,
        app_exact=app_exact,
        master=master,
        policy_type=policy_type,
        limit=svc.EXPORT_LIMIT,
        offset=0,
        max_limit=svc.EXPORT_LIMIT,
    )
    result = _run(req, state)
    rows = result["items"] + result["no_backup_items"] + result["not_found_items"]
    cutoff = result["cutoff"] or "Unknown"
    content = inventory_workbook(rows, svc.COLUMNS, cutoff=cutoff)
    stamp = datetime.now(TZ).strftime("%d%m%Y%H%M%S")
    kind = "SearchByHostname" if req.mode == "hostname" else "SearchByApplication"
    filename = f"SBM - BackupReport - {kind} - {stamp}.xlsx"
    log_event(
        logger, "app", "export_excel", f"Export backup inventory ({req.mode})", rows=len(rows), mode=req.mode
    )
    return Response(
        content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
