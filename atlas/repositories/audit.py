"""SQL untuk ``audit.event``."""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

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
