"""SQL untuk ``cmdb.*``: sinkronisasi berbasis diff (COPY → staging → upsert/hapus seperlunya)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import psycopg

# kolom bisnis cmdb.server_inventory (urutan = urutan nilai di setiap baris & di row_hash)
FIELDS: tuple[str, ...] = (
    "hostname",
    "ip_oam",
    "ip_service",
    "app_name",
    "pic",
    "app_priority",
    "environment",
    "vm_baremetal",
    "site",
)
_STAGE_COLUMNS = ("row_hash", "occurrences", *FIELDS)


@dataclass(frozen=True)
class SyncCounts:
    inserted: int
    updated: int
    deleted: int

    @property
    def changed(self) -> int:
        return self.inserted + self.updated + self.deleted


def count_source_rows(conn: psycopg.Connection) -> int:
    """Jumlah baris asli (dengan duplikat) dari impor terakhir."""
    return int(conn.execute("SELECT coalesce(sum(occurrences), 0) FROM cmdb.server_inventory").fetchone()[0])


def sync_server_inventory(
    conn: psycopg.Connection, rows: Iterable[tuple[str, int, Sequence[str | None]]], run_id: int
) -> SyncCounts:
    """Samakan isi tabel dengan ``rows`` = (row_hash, occurrences, nilai sesuai FIELDS).

    Harus dipanggil di dalam transaksi.

    Hanya baris yang berubah yang ditulis: baris baru di-INSERT, perubahan jumlah kemunculan di-UPDATE,
    baris yang hilang dari sumber di-DELETE. File yang sama diimpor ulang → 0 penulisan.
    """
    columns = ", ".join(_STAGE_COLUMNS)
    conn.execute(
        "CREATE TEMP TABLE cmdb_stage (row_hash text PRIMARY KEY, occurrences integer NOT NULL, "
        + ", ".join(f"{c} text" for c in FIELDS)
        + ") ON COMMIT DROP"
    )
    with conn.cursor() as cur, cur.copy(f"COPY cmdb_stage ({columns}) FROM STDIN") as copy:
        for row_hash, occurrences, values in rows:
            copy.write_row((row_hash, occurrences, *values))
    conn.execute("ANALYZE cmdb_stage")

    inserted, updated = conn.execute(
        f"""
        WITH upserted AS (
            INSERT INTO cmdb.server_inventory AS t ({columns}, run_id)
            SELECT {columns}, %s FROM cmdb_stage
            ON CONFLICT (row_hash) DO UPDATE
               SET occurrences = EXCLUDED.occurrences, run_id = EXCLUDED.run_id, updated_at = now()
             WHERE t.occurrences IS DISTINCT FROM EXCLUDED.occurrences
            RETURNING (xmax = 0) AS is_insert
        )
        SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) FROM upserted
        """,  # noqa: S608 — nama kolom dari konstanta FIELDS, bukan input user
        (run_id,),
    ).fetchone()
    deleted = conn.execute(
        "DELETE FROM cmdb.server_inventory t WHERE NOT EXISTS "
        "(SELECT 1 FROM cmdb_stage s WHERE s.row_hash = t.row_hash)"
    ).rowcount
    conn.execute("DROP TABLE cmdb_stage")
    return SyncCounts(int(inserted), int(updated), int(deleted))


def analyze(conn: psycopg.Connection) -> None:
    conn.execute("ANALYZE cmdb.server_inventory")


def notify_changed(conn: psycopg.Connection, run_id: int) -> None:
    """Diterima web (LISTEN) saat transaksi commit → cache dibuang (plan 04 §3.3)."""
    conn.execute(
        "SELECT pg_notify('atlas_data_changed', %s)", (json.dumps({"source": "cmdb", "run_id": run_id}),)
    )
