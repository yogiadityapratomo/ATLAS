r"""Job backup inventory: ``policy_cache.json`` → ``nbu.backup_inventory`` (pengganti loader ``dbbackup``).

Alur: baca & parse JSON di luar transaksi → COPY ke staging → upsert/hapus seperlunya (diff
``row_hash``) → refresh materialized view pencarian (CONCURRENTLY, pembaca tidak terblokir) →
``NOTIFY``. Advisory lock mencegah run ganda (akar masalah D3: loader berjalan 12–18× lebih sering).
``dbbackup`` lama tidak disentuh.

    .venv\Scripts\python.exe -m atlas.collectors.inventory_job --cache "D:\...\cache\policy_cache.json"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from atlas.collectors.runner import JobContext, JobOutcome, JobResult, run_job
from atlas.core.audit import start_audit
from atlas.core.config import load_settings
from atlas.core.db import Database
from atlas.core.errors import AtlasError, ValidationError
from atlas.core.logging import announce_startup, setup_logging
from atlas.repositories import inventory as inventory_repo
from atlas.services import policy_parser

SOURCE = "backup_inventory"
SHRINK_LIMIT = 0.5
TZ = ZoneInfo("Asia/Jakarta")


def load_inventory(db: Database, cache_path: Path, *, allow_shrink: bool = False) -> JobOutcome:
    def prepare(ctx: JobContext) -> tuple[policy_parser.ParsedInventory, datetime]:
        if not cache_path.is_file():
            raise ValidationError(f"policy cache tidak ditemukan: {cache_path}")
        collected_at = datetime.fromtimestamp(cache_path.stat().st_mtime, TZ)
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except ValueError as exc:  # file sedang ditulis collector / rusak
            raise ValidationError(f"policy cache bukan JSON valid: {exc}") from exc
        parsed = policy_parser.build_inventory(cache)
        if not parsed.rows:
            raise ValidationError("policy cache tidak menghasilkan baris inventory (kosong?)")
        return parsed, collected_at

    def work(conn: psycopg.Connection, ctx: JobContext) -> JobResult:
        parsed, collected_at = ctx.data
        previous = inventory_repo.count_rows(conn)
        if previous and len(parsed.rows) < previous * SHRINK_LIMIT and not allow_shrink:
            raise ValidationError(
                f"jumlah baris turun dari {previous} ke {len(parsed.rows)} (> 50%); "
                "periksa policy_cache.json atau jalankan dengan --allow-shrink"
            )
        counts = inventory_repo.sync(conn, ((r.row_hash, r.values) for r in parsed.rows), ctx.run_id)
        if counts.changed:
            inventory_repo.analyze(conn)
            inventory_repo.refresh_search(conn)
            inventory_repo.notify_changed(conn, ctx.run_id)
        details: dict[str, Any] = {
            "source_file": cache_path.name,
            "collected_at": collected_at.isoformat(),
            "policies": parsed.policies,
            "duplicate_keys": parsed.duplicates,
            "previous_rows": previous,
        }
        return JobResult(
            total=len(parsed.rows),
            inserted=counts.inserted,
            updated=counts.updated,
            deleted=counts.deleted,
            details=details,
        )

    return run_job(db, SOURCE, work, prepare=prepare, details={"source_file": cache_path.name})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Muat backup inventory dari policy_cache.json ke database ATLAS."
    )
    parser.add_argument("--cache", type=Path, help="Path policy_cache.json (default: ATLAS_POLICY_CACHE)")
    parser.add_argument("--allow-shrink", action="store_true")
    args = parser.parse_args(argv)

    settings = load_settings()
    cache_path = args.cache or settings.policy_cache_path
    if cache_path is None:
        print("Path policy_cache.json belum diisi (--cache atau ATLAS_POLICY_CACHE).")
        return 2
    log = setup_logging(settings, "inventory_job", announce=False)
    audit = start_audit(settings, "inventory_job", "app")
    announce_startup(settings, log)
    db = Database(settings, "app", "inventory_job", min_size=1, max_size=2)
    try:
        db.open()
        outcome = load_inventory(db, cache_path, allow_shrink=args.allow_shrink)
    except AtlasError as exc:
        print(f"GAGAL [{exc.error_id}]: {exc.message}")
        return 1
    finally:
        db.close()
        audit.close()

    if outcome.status == "skipped":
        print("Dilewati: job inventory lain masih berjalan.")
    elif outcome.status == "failed":
        print(f"GAGAL [{outcome.error_id}] run {outcome.run_id} — detail di logs/inventory_job.log")
    else:
        r = outcome.result
        print(
            f"Selesai run {outcome.run_id} ({outcome.duration_ms} ms): {r.total} baris dari "
            f"{r.details['policies']} policy | +{r.inserted} baru, ~{r.updated} berubah, -{r.deleted} dihapus"
        )
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
