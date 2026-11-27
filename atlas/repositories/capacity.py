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


# ---------------------------------------------------------------- riwayat (Historical Capacity)

# ekspresi awal periode — dipilih dari daftar tetap (bukan input user)
BUCKET_SQL = {
    "day": "d.day",
    "week": "date_trunc('week', d.day)::date",
    "month": "date_trunc('month', d.day)::date",
    "quarter": "date_trunc('quarter', d.day)::date",
    "semester": (
        "make_date(extract(year FROM d.day)::int,"
        " CASE WHEN extract(month FROM d.day) <= 6 THEN 1 ELSE 7 END, 1)"
    ),
    "year": "date_trunc('year', d.day)::date",
}
GROUP_SQL = {"site": "b.site", "master": "b.master", "appliance": "b.master || '/' || b.disk_pool_name"}


def rollup_daily(conn: psycopg.Connection, start, end) -> int:
    return int(conn.execute("SELECT capacity.rollup_disk_pool_daily(%s, %s)", (start, end)).fetchone()[0])


def history(conn: psycopg.Connection, req) -> list[dict[str, Any]]:
    """Agregat per (periode, grup): nilai akhir periode tiap appliance dijumlahkan per grup."""
    where = ["d.day BETWEEN %(start)s AND %(end)s"]
    params: dict[str, Any] = {"start": req.start, "end": req.end}
    if req.sites:
        where.append("d.site = ANY(%(sites)s)")
        params["sites"] = list(req.sites)
    if req.masters:
        where.append("d.master = ANY(%(masters)s)")
        params["masters"] = list(req.masters)
    if req.appliances:
        where.append("(d.master, d.disk_pool_name) IN (SELECT * FROM unnest(%(am)s::text[], %(ap)s::text[]))")
        params["am"] = [m for m, _ in req.appliances]
        params["ap"] = [p for _, p in req.appliances]
    bucket = BUCKET_SQL[req.period]
    sql = f"""
        WITH b AS (
            SELECT d.*, {bucket} AS bucket,
                   row_number() OVER (PARTITION BY d.master, d.disk_pool_name, {bucket}
                                      ORDER BY d.day DESC) AS rn,
                   max(d.max_usage_pct) OVER (PARTITION BY d.master, d.disk_pool_name, {bucket}) AS peak_pct
              FROM capacity.disk_pool_daily d
             WHERE {" AND ".join(where)}
        )
        SELECT b.bucket, {GROUP_SQL[req.group]} AS key,
               sum(b.used_tb) AS used_tb, sum(b.usable_tb) AS usable_tb, sum(b.available_tb) AS available_tb,
               max(b.peak_pct) AS peak_pct, count(*) AS appliances, max(b.day) AS as_of,
               bool_or(b.source = 'demo') AS demo
          FROM b
         WHERE b.rn = 1
         GROUP BY b.bucket, key
         ORDER BY b.bucket, key
    """  # noqa: S608 — bucket & grup dari kamus tetap; nilai lewat parameter
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(sql, params).fetchall()


def history_options(conn: psycopg.Connection) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        appliances = cur.execute(
            """
            SELECT DISTINCT ON (master, disk_pool_name) master, disk_pool_name, site
              FROM capacity.disk_pool_daily
             ORDER BY master, disk_pool_name, day DESC
            """
        ).fetchall()
        span = cur.execute(
            "SELECT min(day) AS first_day, max(day) AS last_day, bool_or(source = 'demo') AS has_demo"
            " FROM capacity.disk_pool_daily"
        ).fetchone()
    return {
        "appliances": [
            {
                "key": f"{a['master']}/{a['disk_pool_name']}",
                "name": a["disk_pool_name"],
                "master": a["master"],
                "site": a["site"],
            }
            for a in appliances
        ],
        "sites": sorted({a["site"] for a in appliances}),
        "masters": sorted({a["master"] for a in appliances}),
        "first_day": span["first_day"],
        "last_day": span["last_day"],
        "has_demo": bool(span["has_demo"]),
    }
