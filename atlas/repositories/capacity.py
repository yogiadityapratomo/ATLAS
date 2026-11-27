"""SQL untuk ``capacity.*``."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

SOURCES = ("capacity", "tape")
# kolom snapshot (urutan = urutan kunci JSON V4 di services.capacity.DISK_KEYS / TAPE_KEYS)
DISK_COLUMNS = ("site", "master", "disk_pool_name", "usable_tb", "available_tb", "used_tb", "usage_pct")
TAPE_COLUMNS = (
    "site",
    "ip",
    "brand",
    "library_type",
    "model",
    "serial_number",
    "storage_name",
    "domain",
    "type_tape",
    "total_qty",
    "used_qty",
    "free_qty",
    "raw_capacity_tb",
    "used_capacity_tb",
    "used_pct",
    "free_pct",
)


@dataclass
class LatestRun:
    source: str
    run_id: int
    status: str
    finished_at: datetime
    collected_at: datetime | None
    details: dict[str, Any] = field(default_factory=dict)


def ensure_partitions(conn: psycopg.Connection) -> None:
    for table in ("capacity.disk_pool_snapshot", "capacity.tape_library_snapshot"):
        conn.execute("SELECT core.ensure_monthly_partitions(%s::regclass, 1, 3)", (table,))


def _copy(conn: psycopg.Connection, table: str, columns: Sequence[str], rows: Iterable[tuple]) -> int:
    count = 0
    cols = ", ".join(("run_id", "collected_at", *columns))
    with conn.cursor() as cur, cur.copy(f"COPY {table} ({cols}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def insert_disk_snapshot(
    conn: psycopg.Connection, run_id: int, collected_at: datetime, rows: Iterable[tuple]
) -> int:
    return _copy(
        conn, "capacity.disk_pool_snapshot", DISK_COLUMNS, ((run_id, collected_at, *r) for r in rows)
    )


def insert_tape_snapshot(
    conn: psycopg.Connection, run_id: int, collected_at: datetime, rows: Iterable[tuple]
) -> int:
    return _copy(
        conn, "capacity.tape_library_snapshot", TAPE_COLUMNS, ((run_id, collected_at, *r) for r in rows)
    )


def notify_changed(conn: psycopg.Connection, source: str, run_id: int) -> None:
    conn.execute(
        "SELECT pg_notify('atlas_data_changed', %s)", (json.dumps({"source": source, "run_id": run_id}),)
    )


def latest_runs(conn: psycopg.Connection) -> dict[str, LatestRun]:
    """Run terakhir berisi data per source, beserta waktu pengambilan data (collected_at)."""
    rows = conn.execute(
        """
        SELECT l.source, l.run_id, l.status, l.finished_at, l.details,
               CASE l.source
                 WHEN 'capacity' THEN (SELECT max(collected_at) FROM capacity.disk_pool_snapshot d
                                        WHERE d.run_id = l.run_id)
                 ELSE (SELECT max(collected_at) FROM capacity.tape_library_snapshot t
                        WHERE t.run_id = l.run_id)
               END AS collected_at
          FROM capacity.latest_run l
        """
    ).fetchall()
    return {r[0]: LatestRun(r[0], r[1], r[2], r[3], r[5], r[4] or {}) for r in rows}


def last_attempts(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    """Status run terakhir (apa pun hasilnya) per source — untuk peringatan "collect terakhir gagal"."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (source) source, id, status, started_at, finished_at, error_id, error_message
          FROM core.collect_run
         WHERE source = ANY(%s)
         ORDER BY source, started_at DESC, id DESC
        """,
        (list(SOURCES),),
    ).fetchall()
    return {
        r[0]: {
            "run_id": r[1],
            "status": r[2],
            "started_at": r[3],
            "finished_at": r[4],
            "error_id": r[5],
            "error_message": r[6],
        }
        for r in rows
    }


_DISK_SELECT = f"SELECT {', '.join(DISK_COLUMNS)} FROM capacity.disk_pool_snapshot"  # noqa: S608 — konstanta
_TAPE_SELECT = f"SELECT {', '.join(TAPE_COLUMNS)} FROM capacity.tape_library_snapshot"  # noqa: S608 — konstanta


def disk_rows(conn: psycopg.Connection, run_id: int) -> list[tuple]:
    return conn.execute(
        _DISK_SELECT + " WHERE run_id = %s ORDER BY master, disk_pool_name",
        (run_id,),
    ).fetchall()


def tape_rows(conn: psycopg.Connection, run_id: int) -> list[tuple]:
    return conn.execute(
        _TAPE_SELECT + " WHERE run_id = %s ORDER BY id",
        (run_id,),
    ).fetchall()
