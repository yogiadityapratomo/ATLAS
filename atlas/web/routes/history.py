"""Menu Historical Capacity — tren kapasitas disk pool per hari/minggu/bulan/kuartal/semester/tahun."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from atlas.core.logging import log_event
from atlas.repositories import capacity as capacity_repo
from atlas.services import capacity_history as svc
from atlas.services.excel_export import history_workbook
from atlas.web.deps import AppState, get_state

router = APIRouter(prefix="/api/capacity/history")
logger = logging.getLogger("atlas.web.history")
TZ = ZoneInfo("Asia/Jakarta")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _request(
    period: str = "month",
    group: str = "site",
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    sites: str | None = Query(None, max_length=200),
    masters: str | None = Query(None, max_length=200),
    appliances: str | None = Query(None, max_length=4000),
) -> svc.HistoryRequest:
    return svc.parse_request(
        today=datetime.now(TZ).date(),
        period=period,
        group=group,
        start=start,
        end=end,
        sites=sites,
        masters=masters,
        appliances=appliances,
    )


def _num(value: Any) -> float:
    return round(float(value), 2) if value is not None else 0.0


def _build(req: svc.HistoryRequest, state: AppState) -> dict[str, Any]:
    with state.connection() as conn:
        rows = capacity_repo.history(conn, req)
    buckets = sorted({r["bucket"] for r in rows})
    series: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = series.setdefault(
            r["key"], {"key": r["key"], "label": svc.series_label(req.group, r["key"]), "points": {}}
        )
        usable = _num(r["usable_tb"])
        used = _num(r["used_tb"])
        s["points"][r["bucket"].isoformat()] = {
            "used_tb": used,
            "usable_tb": usable,
            "free_tb": _num(r["available_tb"]),
            "usage_pct": round(used / usable * 100, 2) if usable else 0.0,
            "peak_pct": _num(r["peak_pct"]),
            "appliances": r["appliances"],
            "as_of": r["as_of"].isoformat(),
        }
    if req.group != "appliance" and len(series) > svc.MAX_SERIES:
        keep = sorted(series)[: svc.MAX_SERIES]
        series = {k: series[k] for k in keep}
    return {
        "period": req.period,
        "period_label": svc.PERIOD_LABEL[req.period],
        "group": req.group,
        "from": req.start.isoformat(),
        "to": req.end.isoformat(),
        "buckets": [{"start": b.isoformat(), "label": svc.bucket_label(req.period, b)} for b in buckets],
        "series": sorted(series.values(), key=lambda s: s["key"]),
        "has_demo": any(r["demo"] for r in rows),
    }


@router.get("")
def history(
    req: svc.HistoryRequest = Depends(_request), state: AppState = Depends(get_state)
) -> JSONResponse:
    return JSONResponse(_build(req, state))


@router.get("/options")
def options(state: AppState = Depends(get_state)) -> JSONResponse:
    with state.connection() as conn:
        body = capacity_repo.history_options(conn)
    for k in ("first_day", "last_day"):
        body[k] = body[k].isoformat() if body[k] else None
    body["periods"] = [{"key": p, "label": svc.PERIOD_LABEL[p]} for p in svc.PERIODS]
    body["max_series"] = svc.MAX_SERIES
    return JSONResponse(body)


@router.get("/export")
def export(req: svc.HistoryRequest = Depends(_request), state: AppState = Depends(get_state)) -> Response:
    data = _build(req, state)
    content = history_workbook(data)
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M")
    log_event(logger, "app", "export_excel", "Export Historical Capacity", period=req.period, group=req.group)
    return Response(
        content,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="capacity_history_{req.period}_{stamp}.xlsx"'},
    )
