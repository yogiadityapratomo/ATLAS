r"""Job maintenance harian: siapkan partisi bulan depan & buang partisi lama (retensi).

* Partisi bulanan ``audit.event`` dan ``capacity.*_snapshot`` dibuat 3 bulan ke depan (idempoten).
* Retensi audit: partisi yang seluruh isinya lebih tua dari ``ATLAS_AUDIT_RETENTION_DAYS`` (default 180)
  di-DROP lewat ``core.drop_old_partitions`` (SECURITY DEFINER; aplikasi sendiri tidak punya hak DROP).
* Retensi kapasitas: ``ATLAS_CAPACITY_RETENTION_DAYS`` (default 0 = simpan semua; ±2 juta baris/tahun).

    .venv\Scripts\python.exe -m atlas.collectors.maintenance_job
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg

from atlas.collectors.runner import JobContext, JobOutcome, JobResult, run_job
from atlas.core.audit import start_audit
from atlas.core.config import Settings, load_settings
from atlas.core.db import Database
from atlas.core.errors import AtlasError
from atlas.core.logging import announce_startup, setup_logging
from atlas.repositories import audit as audit_repo

TZ = ZoneInfo("Asia/Jakarta")
PARTITIONED = ("audit.event", "capacity.disk_pool_snapshot", "capacity.tape_library_snapshot")


def run_maintenance(db: Database, settings: Settings, *, now: datetime | None = None) -> JobOutcome:
    now = now or datetime.now(TZ)

    def work(conn: psycopg.Connection, ctx: JobContext) -> JobResult:
        created = {}
        for table in PARTITIONED:
            created[table] = conn.execute(
                "SELECT core.ensure_monthly_partitions(%s::regclass, 1, 3)", (table,)
            ).fetchone()[0]
        dropped: list[str] = []
        if settings.audit_retention_days:
            cutoff = now - timedelta(days=settings.audit_retention_days)
            dropped += audit_repo.drop_old_partitions(conn, "audit.event", cutoff)
        if settings.capacity_retention_days:
            cutoff = now - timedelta(days=settings.capacity_retention_days)
            for table in PARTITIONED[1:]:
                dropped += audit_repo.drop_old_partitions(conn, table, cutoff)
        return JobResult(
            total=len(dropped),
            deleted=len(dropped),
            details={"partitions_created": created, "partitions_dropped": dropped},
        )

    return run_job(db, "maintenance", work)


def main() -> int:
    settings = load_settings()
    log = setup_logging(settings, "maintenance_job", announce=False)
    audit = start_audit(settings, "maintenance_job", "app")
    announce_startup(settings, log)
    db = Database(settings, "app", "maintenance_job", min_size=1, max_size=1)
    try:
        db.open()
        outcome = run_maintenance(db, settings)
    except AtlasError as exc:
        print(f"GAGAL [{exc.error_id}]: {exc.message}")
        return 1
    finally:
        db.close()
        audit.close()
    if outcome.result:
        d = outcome.result.details
        print(f"Maintenance run {outcome.run_id}: partisi baru {d['partitions_created']}")
        print(f"Partisi dibuang: {d['partitions_dropped'] or 'tidak ada'}")
    else:
        print(f"Maintenance: {outcome.status} {outcome.error_id or ''}")
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
