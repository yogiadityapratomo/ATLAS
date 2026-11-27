"""SQL untuk ``nbu.backup_inventory`` & ``report.backup_inventory_search``."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

# kolom bisnis (urutan = services.policy_parser.FIELDS)
FIELDS = (
    "master_server",
    "policy_name",
    "policy_type",
    "client_host",
    "client_os",
    "client_hw",
    "storage",
    "volume_pool",
    "backup_selections",
    "schedule_name",
    "schedule_days",
    "backup_type",
    "start_times",
    "retention_period",
)
SEARCH_COLUMNS = (
    "client_host",
    "app_names",
    "pics",
    "environments",
    "sites",
    "policy_name",
    "policy_type",
    "schedule_name",
    "schedule_days",
    "start_times",
    "retention_period",
    "backup_type",
    "storage",
    "volume_pool",
    "backup_selections",
    "client_os",
    "client_hw",
    "master_server",
)
_UPDATE_SET = ", ".join(f"{c} = EXCLUDED.{c}" for c in FIELDS if c != "client_host")


@dataclass(frozen=True)
class SyncCounts:
    inserted: int
    updated: int
    deleted: int

    @property
    def changed(self) -> int:
        return self.inserted + self.updated + self.deleted


def count_rows(conn: psycopg.Connection) -> int:
    return int(conn.execute("SELECT count(*) FROM nbu.backup_inventory").fetchone()[0])


def sync(conn: psycopg.Connection, rows: Iterable[tuple[str, Sequence[str]]], run_id: int) -> SyncCounts:
    """Samakan tabel dengan ``rows`` = (row_hash, nilai sesuai FIELDS). Di dalam transaksi."""
    cols = ", ".join(FIELDS)
    conn.execute(
        "CREATE TEMP TABLE inventory_stage (row_hash text NOT NULL, "
        + ", ".join(f"{c} text NOT NULL" for c in FIELDS)
        + ") ON COMMIT DROP"
    )
    with conn.cursor() as cur, cur.copy(f"COPY inventory_stage (row_hash, {cols}) FROM STDIN") as copy:
        for row_hash, values in rows:
            copy.write_row((row_hash, *values))
    conn.execute("ANALYZE inventory_stage")
    inserted, updated = conn.execute(
        f"""
        WITH upserted AS (
            INSERT INTO nbu.backup_inventory AS t ({cols}, row_hash, run_id)
            SELECT {cols}, row_hash, %s FROM inventory_stage
            ON CONFLICT (master_server, policy_name, client_host_norm, schedule_name) DO UPDATE
               SET {_UPDATE_SET}, row_hash = EXCLUDED.row_hash, run_id = EXCLUDED.run_id, updated_at = now()
             WHERE t.row_hash IS DISTINCT FROM EXCLUDED.row_hash
            RETURNING (xmax = 0) AS is_insert
        )
        SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) FROM upserted
        """,  # noqa: S608 — kolom dari konstanta FIELDS
        (run_id,),
    ).fetchone()
    deleted = conn.execute(
        """
        DELETE FROM nbu.backup_inventory t
         WHERE NOT EXISTS (
               SELECT 1 FROM inventory_stage s
                WHERE s.master_server = t.master_server AND s.policy_name = t.policy_name
                  AND lower(btrim(s.client_host)) = t.client_host_norm AND s.schedule_name = t.schedule_name)
        """
    ).rowcount
    conn.execute("DROP TABLE inventory_stage")
    return SyncCounts(int(inserted), int(updated), int(deleted))


def refresh_search(conn: psycopg.Connection) -> None:
    """Hitung ulang join backup ↔ CMDB. CONCURRENTLY: pembaca tidak terblokir selama refresh."""
    conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY report.backup_inventory_search")


def analyze(conn: psycopg.Connection) -> None:
    conn.execute("ANALYZE nbu.backup_inventory")


def notify_changed(conn: psycopg.Connection, run_id: int) -> None:
    conn.execute(
        "SELECT pg_notify('atlas_data_changed', %s)",
        (json.dumps({"source": "backup_inventory", "run_id": run_id}),),
    )


# ---------------------------------------------------------------- baca (web)


def like_pattern(term: str) -> str:
    """Pola "mengandung" untuk LIKE; ``%``, ``_``, ``\\`` di input diperlakukan sebagai huruf biasa."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filters(master: str | None, policy_type: str | None) -> tuple[str, dict[str, Any]]:
    sql = ""
    params: dict[str, Any] = {}
    if master:
        sql += " AND s.master_server = %(master)s"
        params["master"] = master
    if policy_type:
        sql += " AND s.policy_type = %(policy_type)s"
        params["policy_type"] = policy_type
    return sql, params


_SELECT = ", ".join(f"s.{c}" for c in SEARCH_COLUMNS)


def search_hosts(
    conn: psycopg.Connection,
    terms: Sequence[str],
    *,
    master: str | None,
    policy_type: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Cari sebagian per hostname (sama dengan bot). Return (baris, total, term yang tidak ditemukan)."""
    patterns = [like_pattern(t) for t in terms]
    where, params = _filters(master, policy_type)
    params.update(patterns=patterns, limit=limit, offset=offset)
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"""
            SELECT {_SELECT}, count(*) OVER () AS total
              FROM report.backup_inventory_search s
             WHERE s.client_host_norm LIKE ANY (%(patterns)s){where}
             ORDER BY s.client_host_norm, s.policy_name, s.schedule_name, s.id
             LIMIT %(limit)s OFFSET %(offset)s
            """,  # noqa: S608 — potongan SQL dari konstanta
            params,
        ).fetchall()
        found = cur.execute(
            """
            SELECT t.term FROM unnest(%(terms)s::text[], %(patterns)s::text[]) AS t(term, pattern)
             WHERE EXISTS (SELECT 1 FROM report.backup_inventory_search s
                            WHERE s.client_host_norm LIKE t.pattern)
            """,
            {"terms": list(terms), "patterns": patterns},
        ).fetchall()
    total = rows[0].pop("total") if rows else 0
    for row in rows[1:]:
        row.pop("total")
    found_terms = {r["term"] for r in found}
    return rows, int(total), [t for t in terms if t not in found_terms]


def search_app(
    conn: psycopg.Connection,
    app: str,
    *,
    exact: bool,
    master: str | None,
    policy_type: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]], int]:
    """Semua host aplikasi (CMDB) + konfigurasi backup-nya.

    Return (baris, total, host tanpa backup, jumlah host aplikasi).
    """
    where, params = _filters(master, policy_type)
    app_cond = "lower(app_name) = lower(%(app)s)" if exact else "lower(app_name) LIKE %(app_pattern)s"
    params.update(app=app, app_pattern=like_pattern(app.lower()), limit=limit, offset=offset)
    hosts_cte = f"WITH hosts AS (SELECT DISTINCT hostname_norm FROM cmdb.server_inventory WHERE {app_cond})"  # noqa: S608
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"""
            {hosts_cte}
            SELECT {_SELECT}, count(*) OVER () AS total
              FROM report.backup_inventory_search s
              JOIN hosts h ON h.hostname_norm = s.client_host_norm
             WHERE true{where}
             ORDER BY s.client_host_norm, s.policy_name, s.schedule_name, s.id
             LIMIT %(limit)s OFFSET %(offset)s
            """,  # noqa: S608 — potongan SQL dari konstanta
            params,
        ).fetchall()
        no_backup = cur.execute(
            f"""
            {hosts_cte}
            SELECT c.hostname AS client_host, c.app_names, c.pics, c.environments, c.sites
              FROM report.cmdb_host c
              JOIN hosts h ON h.hostname_norm = c.hostname_norm
             WHERE NOT EXISTS (SELECT 1 FROM nbu.backup_inventory b
                                WHERE b.client_host_norm = c.hostname_norm)
             ORDER BY c.hostname_norm
            """,  # noqa: S608 — potongan SQL dari konstanta
            params,
        ).fetchall()
        host_count = cur.execute(f"{hosts_cte} SELECT count(*) AS n FROM hosts", params).fetchone()["n"]  # noqa: S608
    total = rows[0].pop("total") if rows else 0
    for row in rows[1:]:
        row.pop("total")
    return rows, int(total), no_backup, int(host_count)


def suggest_apps(conn: psycopg.Connection, query: str, limit: int = 20) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT app_name, host_count FROM report.app_list
             WHERE app_name_norm LIKE %(pattern)s
             ORDER BY (app_name_norm = %(q)s) DESC, (app_name_norm LIKE %(prefix)s) DESC,
                      host_count DESC, app_name
             LIMIT %(limit)s
            """,
            {
                "pattern": like_pattern(query.lower()),
                "q": query.lower(),
                "prefix": like_pattern(query.lower())[1:],
                "limit": limit,
            },
        ).fetchall()


def filter_options(conn: psycopg.Connection) -> dict[str, list[str]]:
    masters = [
        r[0] for r in conn.execute("SELECT DISTINCT master_server FROM nbu.backup_inventory ORDER BY 1")
    ]
    types = [r[0] for r in conn.execute("SELECT DISTINCT policy_type FROM nbu.backup_inventory ORDER BY 1")]
    return {"masters": masters, "policy_types": types}


@dataclass
class InventoryRun:
    run_id: int | None
    status: str | None
    collected_at: datetime | None
    last_attempt_status: str | None
    last_error_id: str | None


def latest_run(conn: psycopg.Connection) -> InventoryRun:
    ok = conn.execute(
        """
        SELECT id, status, coalesce((details->>'collected_at')::timestamptz, finished_at)
          FROM core.collect_run
         WHERE source = 'backup_inventory' AND status IN ('success', 'partial')
         ORDER BY finished_at DESC LIMIT 1
        """
    ).fetchone()
    last = conn.execute(
        "SELECT status, error_id FROM core.collect_run WHERE source = 'backup_inventory'"
        " ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return InventoryRun(
        ok[0] if ok else None,
        ok[1] if ok else None,
        ok[2] if ok else None,
        last[0] if last else None,
        last[1] if last else None,
    )


def data_version(conn: psycopg.Connection) -> tuple[int | None, int | None]:
    """(run backup_inventory, run cmdb) terakhir yang sukses — kunci cache pencarian & saran aplikasi."""
    rows = dict(
        conn.execute(
            """
            SELECT DISTINCT ON (source) source, id FROM core.collect_run
             WHERE source IN ('backup_inventory', 'cmdb') AND status IN ('success', 'partial')
             ORDER BY source, finished_at DESC
            """
        ).fetchall()
    )
    return rows.get("backup_inventory"), rows.get("cmdb")
