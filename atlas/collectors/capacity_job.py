r"""Job kapasitas: disk pool & tape library → ``capacity.*`` (pengganti ``scheduled_collect.py`` V4).

Dua run terpisah (source ``capacity`` dan ``tape``), masing-masing dengan advisory lock sendiri,
sama urutannya dengan V4: semua disk pool dulu, lalu tape. Status run:

* ``success`` — semua master berhasil;
* ``partial`` — sebagian master gagal (data master yang berhasil tetap disimpan, error per master di
  ``details.errors``), sama dengan V4 yang tetap menulis JSON dari master yang berhasil;
* ``failed``  — tidak ada data sama sekali. **Beda dari V4:** V4 menimpa JSON dengan daftar kosong;
  di sini data terakhir tetap tampil dan dashboard memberi peringatan.

Mode:
    .venv\Scripts\python.exe -m atlas.collectors.capacity_job              # live (ATLAS_ALLOW_LIVE_NBU=1)
    .venv\Scripts\python.exe -m atlas.collectors.capacity_job --from-json legacy\web-v4\cache
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from atlas.collectors.nbu_client import NbuClient, NbuError
from atlas.collectors.runner import JobContext, JobOutcome, JobResult, run_job
from atlas.core.audit import start_audit
from atlas.core.config import Settings, load_settings
from atlas.core.db import Database
from atlas.core.errors import AtlasError, ValidationError
from atlas.core.logging import announce_startup, log_event, setup_logging
from atlas.repositories import capacity as capacity_repo
from atlas.services import capacity as capacity_service
from atlas.services.excel_export import capacity_workbook

logger = logging.getLogger("atlas.capacity_job")
TZ = ZoneInfo("Asia/Jakarta")
DISK_DEADLINE_S = 45  # sama dengan V4
TAPE_DEADLINE_S = 360  # sama dengan V4
DISK_FILE = "capacity_cache.json"
TAPE_FILE = "tape_cache.json"

Fetch = Callable[[], tuple[list[dict[str, Any]], dict[str, str]]]


def _source_job(
    db: Database,
    source: str,
    fetch: Fetch,
    *,
    collected_at: Callable[[], datetime],
    details: dict[str, Any],
) -> JobOutcome:
    insert = (
        capacity_repo.insert_disk_snapshot if source == "capacity" else capacity_repo.insert_tape_snapshot
    )
    to_db = capacity_service.disk_row_to_db if source == "capacity" else capacity_service.tape_row_to_db

    def prepare(ctx: JobContext) -> tuple[list[dict[str, Any]], dict[str, str], datetime]:
        rows, errors = fetch()
        if not rows:
            raise NbuError(f"tidak ada data {source} dari master mana pun: {errors or 'data kosong'}")
        return rows, errors, collected_at()

    def work(conn: psycopg.Connection, ctx: JobContext) -> JobResult:
        rows, errors, when = ctx.data
        capacity_repo.ensure_partitions(conn)
        written = insert(conn, ctx.run_id, when, (to_db(r) for r in rows))
        capacity_repo.notify_changed(conn, source, ctx.run_id)
        return JobResult(
            total=written,
            inserted=written,
            status="partial" if errors else "success",
            details={"errors": errors, "collected_at": when.isoformat()},
        )

    return run_job(db, source, work, prepare=prepare, details=details)


# ---------------------------------------------------------------- live dari master NBU


def collect_live(
    db: Database, settings: Settings, *, client_factory: Callable[..., NbuClient] = NbuClient
) -> list[JobOutcome]:
    if not settings.allow_live_nbu:
        log_event(
            logger,
            "security",
            "live_nbu_blocked",
            "Collect live ke master NBU diblok (ATLAS_ALLOW_LIVE_NBU=0)",
            severity="warning",
        )
        raise ValidationError(
            "collect live ke master NBU dinonaktifkan (ATLAS_ALLOW_LIVE_NBU=0); pakai --from-json di DEV"
        )
    clients: dict[str, NbuClient] = {}

    def client(master) -> NbuClient:
        if master.key not in clients:
            clients[master.key] = client_factory(
                master,
                timeout_s=settings.nbu_timeout_s,
                min_interval_s=settings.nbu_min_interval_ms / 1000,
                max_retries=settings.nbu_max_retries,
            )
        return clients[master.key]

    def fetch_disk() -> tuple[list[dict[str, Any]], dict[str, str]]:
        rows: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for master in settings.nbu_masters:  # berurutan, tidak paralel
            try:
                items = client(master).disk_pools(deadline_s=DISK_DEADLINE_S)
                rows.extend(capacity_service.disk_pool_rows(master.name, items))
            except Exception as exc:
                errors[master.name] = str(exc)
                _log_master_failure("capacity", master.name, exc)
        return capacity_service.sort_disk_rows(rows), errors

    def fetch_tape() -> tuple[list[dict[str, Any]], dict[str, str]]:
        items_by_master: dict[str, list[dict[str, Any]]] = {}
        errors: dict[str, str] = {}
        for master in settings.nbu_masters:
            try:
                items_by_master[master.key] = client(master).tape_media(
                    deadline_s=TAPE_DEADLINE_S, resume_dir=settings.cache_dir
                )
            except Exception as exc:
                errors[master.name] = str(exc)
                _log_master_failure("tape", master.name, exc)
        return capacity_service.build_tape_rows(items_by_master), errors

    def now() -> datetime:
        return datetime.now(TZ)

    outcomes = [
        _source_job(db, "capacity", fetch_disk, collected_at=now, details={"mode": "live"}),
        _source_job(db, "tape", fetch_tape, collected_at=now, details={"mode": "live"}),
    ]
    if settings.capacity_json_dir:
        write_v4_files(db, settings.capacity_json_dir)
    return outcomes


def _log_master_failure(source: str, master: str, exc: BaseException) -> None:
    log_event(
        logger,
        "job",
        "nbu_fetch_failed",
        f"Ambil {source} dari {master} gagal: {exc}",
        severity="warning",
        error_id=getattr(exc, "error_id", None),
        master=master,
        source=source,
    )


# ---------------------------------------------------------------- impor JSON V4 (DEV / regresi)


def import_json(db: Database, json_dir: Path) -> list[JobOutcome]:
    """Impor ``capacity_cache.json`` & ``tape_cache.json`` V4. ``collected_at`` = waktu file (= V4)."""
    outcomes = []
    for source, name in (("capacity", DISK_FILE), ("tape", TAPE_FILE)):
        path = json_dir / name

        def fetch(path: Path = path) -> tuple[list[dict[str, Any]], dict[str, str]]:
            if not path.is_file():
                raise ValidationError(f"file tidak ditemukan: {path}")
            return json.loads(path.read_text(encoding="utf-8")), {}

        def mtime(path: Path = path) -> datetime:
            return datetime.fromtimestamp(path.stat().st_mtime, TZ)

        outcomes.append(
            _source_job(db, source, fetch, collected_at=mtime, details={"mode": "json_import", "file": name})
        )
    return outcomes


# ---------------------------------------------------------------- file V4 (transisi / rollback)


def write_v4_files(db: Database, json_dir: Path) -> None:
    """Tulis ulang JSON & Excel format V4 dari data terbaru di DB, agar web V4 tetap bisa dipakai."""
    with db.connection() as conn:
        latest = capacity_repo.latest_runs(conn)
        disk = [capacity_service.disk_row_from_db(r) for r in _rows(conn, latest, "capacity")]
        tape = [capacity_service.tape_row_from_db(r) for r in _rows(conn, latest, "tape")]
    json_dir.mkdir(parents=True, exist_ok=True)
    for name, data in ((DISK_FILE, disk), (TAPE_FILE, tape)):
        tmp = json_dir / f"{name}.tmp"
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(json_dir / name)
    report_dir = json_dir.parent / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "capacity_report.xlsx").write_bytes(capacity_workbook(disk, tape, now=datetime.now(TZ)))


def _rows(conn: psycopg.Connection, latest: dict, source: str) -> list[tuple]:
    if source not in latest:
        return []
    run_id = latest[source].run_id
    return (
        capacity_repo.disk_rows(conn, run_id)
        if source == "capacity"
        else capacity_repo.tape_rows(conn, run_id)
    )


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect kapasitas disk pool & tape ke database ATLAS.")
    parser.add_argument("--from-json", type=Path, help="Impor JSON V4 dari folder ini (tanpa akses NBU)")
    args = parser.parse_args(argv)

    settings = load_settings()
    log = setup_logging(settings, "capacity_job", announce=False)
    audit = start_audit(settings, "capacity_job", "app")
    announce_startup(settings, log)
    db = Database(settings, "app", "capacity_job", min_size=1, max_size=2)
    try:
        db.open()
        outcomes = import_json(db, args.from_json) if args.from_json else collect_live(db, settings)
    except AtlasError as exc:
        print(f"GAGAL [{exc.error_id}]: {exc.message}")
        return 1
    finally:
        db.close()
        audit.close()

    for source, outcome in zip(("Disk pool", "Tape"), outcomes, strict=True):
        if outcome.status in ("success", "partial"):
            errors = outcome.result.details.get("errors") or {}
            extra = f" — gagal: {', '.join(errors)}" if errors else ""
            print(
                f"{source}: {outcome.status.upper()} run {outcome.run_id}, "
                f"{outcome.result.total} baris{extra}"
            )
        elif outcome.status == "skipped":
            print(f"{source}: dilewati (run lain masih berjalan)")
        else:
            print(f"{source}: GAGAL [{outcome.error_id}] run {outcome.run_id}")
    return max(o.exit_code for o in outcomes)


if __name__ == "__main__":
    sys.exit(main())
