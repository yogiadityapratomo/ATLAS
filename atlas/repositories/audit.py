"""SQL untuk ``audit.event``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

COLUMNS = (
    "occurred_at",
    "category",
    "event_type",
    "severity",
    "component",
    "actor",
    "request_id",
    "error_id",
    "message",
    "duration_ms",
    "details",
    "host",
    "pid",
    "app_version",
)

_COPY_SQL = f"COPY audit.event ({', '.join(COLUMNS)}) FROM STDIN"


def copy_events(conn: psycopg.Connection, rows: Sequence[Sequence[object]]) -> int:
    """Tulis batch event dengan COPY (satu round-trip, jauh lebih cepat dari INSERT per baris)."""
    with conn.cursor() as cur, cur.copy(_COPY_SQL) as copy:
        for row in rows:
            copy.write_row(row)
    return len(rows)


def ensure_partitions(conn: psycopg.Connection, months_ahead: int = 3) -> int:
    row = conn.execute(
        "SELECT core.ensure_monthly_partitions('audit.event'::regclass, 1, %s)", (months_ahead,)
    ).fetchone()
    return int(row[0]) if row else 0


def drop_old_partitions(conn: psycopg.Connection, table: str, older_than: datetime) -> list[str]:
    return [
        r[0] for r in conn.execute("SELECT core.drop_old_partitions(%s::regclass, %s)", (table, older_than))
    ]


# ---------------------------------------------------------------- baca (menu Audit Log)

SEVERITY_ORDER = ("debug", "info", "warning", "error", "critical")
EVENT_COLUMNS = ("id", *COLUMNS)


@dataclass(frozen=True)
class EventFilter:
    since: datetime
    until: datetime
    category: str | None = None
    min_severity: str | None = None
    component: str | None = None
    event_type: str | None = None
    request_id: str | None = None
    error_id: str | None = None
    q: str | None = None


def _where(f: EventFilter) -> tuple[str, dict[str, Any]]:
    """Filter menu → klausa WHERE terparameter (teks input user tidak pernah masuk ke SQL)."""
    clauses = ["occurred_at >= %(since)s", "occurred_at < %(until)s"]
    params: dict[str, Any] = {"since": f.since, "until": f.until}
    for field in ("category", "component", "event_type", "request_id", "error_id"):
        value = getattr(f, field)
        if value:
            clauses.append(f"{field} = %({field})s")
            params[field] = value
    if f.min_severity:
        clauses.append("severity = ANY(%(severities)s)")
        params["severities"] = list(SEVERITY_ORDER[SEVERITY_ORDER.index(f.min_severity) :])
    if f.q:
        clauses.append("message ILIKE %(q)s")
        escaped = f.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["q"] = f"%{escaped}%"
    return " AND ".join(clauses), params


def list_events(
    conn: psycopg.Connection, f: EventFilter, *, before: tuple[datetime, int] | None, limit: int
) -> list[dict[str, Any]]:
    """Keyset pagination (occurred_at, id) menurun memakai PK: halaman ke-100 secepat halaman ke-1."""
    where, params = _where(f)
    if before:
        where += " AND (occurred_at, id) < (%(before_at)s, %(before_id)s)"
        params.update(before_at=before[0], before_id=before[1])
    params["limit"] = limit
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            f"SELECT {', '.join(EVENT_COLUMNS)} FROM audit.event WHERE {where}"  # noqa: S608 — terparameter
            " ORDER BY occurred_at DESC, id DESC LIMIT %(limit)s",
            params,
        ).fetchall()


def summary(conn: psycopg.Connection, since: datetime) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT count(*),
               count(*) FILTER (WHERE severity IN ('error', 'critical')),
               count(*) FILTER (WHERE event_type = 'job_failed'),
               count(*) FILTER (WHERE event_type = 'db_connect_failed'),
               count(*) FILTER (WHERE category = 'security')
          FROM audit.event WHERE occurred_at >= %s
        """,
        (since,),
    ).fetchone()
    by_category = dict(
        conn.execute(
            "SELECT category, count(*) FROM audit.event WHERE occurred_at >= %s GROUP BY 1 ORDER BY 2 DESC",
            (since,),
        ).fetchall()
    )
    components = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT component FROM audit.event"
            " WHERE occurred_at >= now() - interval '30 days' ORDER BY 1"
        )
    ]
    return {
        "events": row[0],
        "errors": row[1],
        "job_failed": row[2],
        "db_connect_failed": row[3],
        "security": row[4],
        "by_category": by_category,
        "components": components,
    }
