r"""Import CMDB dari Excel OSPLA ke ``cmdb.server_inventory`` (job manual, menggantikan import lama).

Contoh (PowerShell, dari root repo):
    .venv\Scripts\python.exe -m atlas.collectors.cmdb_import `
        --xlsx "C:\...\OSPLA Managed Server-03022026.xlsx"

Pengaman:
* Advisory lock — dua import bersamaan → yang kedua ``job_skipped_locked``.
* Satu transaksi — gagal di tengah = data lama utuh.
* Jumlah baris turun > 50% dibanding impor sebelumnya → ditolak (kemungkinan file salah/terpotong),
  kecuali ``--allow-shrink``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import psycopg

from atlas.collectors.runner import JobContext, JobOutcome, JobResult, run_job
from atlas.core.audit import start_audit
from atlas.core.config import load_settings
from atlas.core.db import Database
from atlas.core.errors import AtlasError, ValidationError
from atlas.core.logging import announce_startup, setup_logging
from atlas.repositories import cmdb as cmdb_repo
from atlas.repositories import inventory as inventory_repo
from atlas.services import cmdb as cmdb_service

SOURCE = "cmdb"
SHRINK_LIMIT = 0.5
logger = logging.getLogger("atlas.cmdb_import")


def import_cmdb(
    db: Database, xlsx: Path, *, sheet: str = cmdb_service.DEFAULT_SHEET, allow_shrink: bool = False
) -> JobOutcome:
    def work(conn: psycopg.Connection, ctx: JobContext) -> JobResult:
        parsed = cmdb_service.read_xlsx(xlsx, sheet)
        if not parsed.rows:
            raise ValidationError(f"tidak ada baris CMDB berhostname di {xlsx.name}")
        previous = cmdb_repo.count_source_rows(conn)
        if previous and parsed.source_rows < previous * SHRINK_LIMIT and not allow_shrink:
            raise ValidationError(
                f"jumlah baris turun dari {previous} ke {parsed.source_rows} (> {int(SHRINK_LIMIT * 100)}%); "
                "periksa file atau jalankan dengan --allow-shrink"
            )
        counts = cmdb_repo.sync_server_inventory(conn, (r.as_db_row() for r in parsed.rows), ctx.run_id)
        if counts.changed:
            cmdb_repo.analyze(conn)
            inventory_repo.refresh_search(conn)  # nama aplikasi/PIC di hasil pencarian ikut terbarui
            cmdb_repo.notify_changed(conn, ctx.run_id)
        return JobResult(
            total=len(parsed.rows),
            inserted=counts.inserted,
            updated=counts.updated,
            deleted=counts.deleted,
            details={
                "source_file": xlsx.name,
                "file_sha256": cmdb_service.file_sha256(xlsx),
                "sheet": sheet,
                "source_rows": parsed.source_rows,
                "unique_rows": len(parsed.rows),
                "duplicate_rows": parsed.duplicate_rows,
                "skipped_no_hostname": parsed.skipped_no_hostname,
                "previous_source_rows": previous,
            },
        )

    return run_job(db, SOURCE, work, details={"source_file": xlsx.name, "sheet": sheet})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import CMDB (Excel OSPLA) ke database ATLAS.")
    parser.add_argument("--xlsx", required=True, type=Path)
    parser.add_argument("--sheet", default=cmdb_service.DEFAULT_SHEET)
    parser.add_argument("--allow-shrink", action="store_true", help="Izinkan jumlah baris turun > 50%%")
    args = parser.parse_args(argv)

    settings = load_settings()
    log = setup_logging(settings, "cmdb_import", announce=False)
    audit = start_audit(settings, "cmdb_import", "app")
    announce_startup(settings, log)
    db = Database(settings, "app", "cmdb_import", min_size=1, max_size=2)
    try:
        db.open()
        outcome = import_cmdb(db, args.xlsx, sheet=args.sheet, allow_shrink=args.allow_shrink)
    except AtlasError as exc:
        print(f"GAGAL [{exc.error_id}]: {exc.message}")
        return 1
    finally:
        db.close()
        audit.close()

    if outcome.status == "skipped":
        print("Dilewati: import CMDB lain sedang berjalan.")
    elif outcome.status == "failed":
        print(f"GAGAL [{outcome.error_id}] run {outcome.run_id} — detail di logs/cmdb_import.log")
    else:
        r = outcome.result
        d = r.details
        print(
            f"Selesai run {outcome.run_id} ({outcome.duration_ms} ms): {d['source_rows']} baris sumber, "
            f"{d['unique_rows']} unik ({d['duplicate_rows']} kembar), dilewati tanpa hostname: "
            f"{d['skipped_no_hostname']}\n"
            f"Perubahan: +{r.inserted} baru, ~{r.updated} berubah, -{r.deleted} dihapus"
        )
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
