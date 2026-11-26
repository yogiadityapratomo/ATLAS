"""SQL untuk ``core.collect_run``."""

from __future__ import annotations

import json
from typing import Any

import psycopg


def start_run(conn: psycopg.Connection, source: str, *, request_id: str, host: str, details: dict) -> int:
    row = conn.execute(
        "INSERT INTO core.collect_run (source, request_id, host, details)"
        " VALUES (%s, %s, %s, %s::jsonb) RETURNING id",
        (source, request_id, host, json.dumps(details, default=str)),
    ).fetchone()
    return int(row[0])


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    *,
    status: str,
    counts: dict[str, int | None] | None = None,
    error_id: str | None = None,
    error_message: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    counts = counts or {}
    conn.execute(
        """
        UPDATE core.collect_run
           SET status = %s,
               finished_at = now(),
               rows_total = %s, rows_inserted = %s, rows_updated = %s, rows_deleted = %s,
               error_id = %s, error_message = %s,
               details = details || %s::jsonb
         WHERE id = %s
        """,
        (
            status,
            counts.get("total"),
            counts.get("inserted"),
            counts.get("updated"),
            counts.get("deleted"),
            error_id,
            error_message,
            json.dumps(details or {}, default=str),
            run_id,
        ),
    )


def fail_orphaned_runs(conn: psycopg.Connection, source: str, *, error_id: str) -> int:
    """Tutup run ``running`` yang tertinggal (proses mati). Hanya aman dipanggil saat memegang lock source."""
    cur = conn.execute(
        """
        UPDATE core.collect_run
           SET status = 'failed', finished_at = now(), error_id = %s,
               error_message = 'run terputus sebelum selesai (ditandai oleh run berikutnya)'
         WHERE source = %s AND status = 'running'
        """,
        (error_id, source),
    )
    return cur.rowcount


def try_advisory_lock(conn: psycopg.Connection, key: str) -> bool:
    """Lock tingkat sesi; otomatis lepas bila koneksi putus."""
    return bool(conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (key,)).fetchone()[0])


def advisory_unlock(conn: psycopg.Connection, key: str) -> None:
    conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,))
