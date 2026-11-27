"""Menu Historical Capacity — tren & perbandingan kapasitas disk pool / appliance."""

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


def _today() -> date:
    return datetime.now(TZ).date()


def _request(
    period: str = "month",
    group: str = "site",
    start: date | None = Query(None, alias="from"),
    end: date | None = Query(None, alias="to"),
    sites: str | None = Query(None, max_length=1000),
    masters: str | None = Query(None, max_length=1000),
    appliances: str | None = Query(None, max_length=8000),
) -> svc.HistoryRequest:
    return svc.parse_request(
        today=_today(),
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


def _point(r: dict[str, Any]) -> dict[str, Any]:
    used, usable = _num(r["used_tb"]), _num(r["usable_tb"])
    return {
        "used_tb": used,
        "usable_tb": usable,
        "free_tb": _num(r["available_tb"]),
        "usage_pct": round(used / usable * 100, 2) if usable else 0.0,
        "appliances": r["appliances"],
        "pools": r["pools"],
        "as_of": r["as_of"].isoformat(),
    }


def _build(req: svc.HistoryRequest, state: AppState) -> dict[str, Any]:
    with state.connection() as conn:
        rows = capacity_repo.history(conn, req)
    buckets = sorted({r["bucket"] for r in rows})
    series: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = series.setdefault(r["key"], {"key": r["key"], "label": r["key"], "points": {}})
        s["points"][r["bucket"].isoformat()] = {**_point(r), "peak_pct": _num(r["peak_pct"])}
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
    body["compare_periods"] = [{"key": p, "label": " vs ".join(svc.COMPARE_LABEL[p])} for p in svc.PERIODS]
    body["max_series"] = svc.MAX_SERIES
    return JSONResponse(body)


@router.get("/compare")
def compare(
    mode: str = "period",
    compare_period: str = Query("week", alias="compare_period"),
    ref: date | None = None,
    a: date | None = None,
    b: date | None = None,
    req: svc.HistoryRequest = Depends(_request),
    state: AppState = Depends(get_state),
) -> JSONResponse:
    """Kenaikan/penurunan: periode ini vs sebelumnya, atau tanggal A vs tanggal B."""
    base_w, cur_w = svc.compare_windows(today=_today(), mode=mode, period=compare_period, ref=ref, a=a, b=b)
    with state.connection() as conn:
        base_rows = capacity_repo.values_at(conn, req, base_w.start, base_w.end)
        cur_rows = capacity_repo.values_at(conn, req, cur_w.start, cur_w.end)
    base = {r["key"]: _point(r) for r in base_rows}
    current = {r["key"]: _point(r) for r in cur_rows}
    rows = svc.compare_rows(base, current)
    total_base, total_cur = svc.totals(list(base.values())), svc.totals(list(current.values()))
    total = svc.compare_rows(
        {"TOTAL": total_base} if total_base else {}, {"TOTAL": total_cur} if total_cur else {}
    )
    return JSONResponse(
        {
            "mode": mode,
            "group": req.group,
            "base": {"label": base_w.label, "start": base_w.start.isoformat(), "end": base_w.end.isoformat()},
            "current": {"label": cur_w.label, "start": cur_w.start.isoformat(), "end": cur_w.end.isoformat()},
            "rows": rows,
            "total": total[0] if total else None,
            "counts": {
                t: sum(1 for r in rows if r["trend"] == t)
                for t in ("naik", "turun", "tetap", "baru", "hilang")
            },
            "has_demo": any(r["demo"] for r in base_rows + cur_rows),
        }
    )


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
