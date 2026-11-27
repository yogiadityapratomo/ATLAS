"""Kerangka eksekusi job (collector, loader, import).

Satu pola untuk semua job:

1. ``request_id`` baru → semua log/event job membawa ID yang sama.
2. **Advisory lock** per source (``pg_try_advisory_lock``): bila job yang sama sedang berjalan,
   run ini berhenti dengan event ``job_skipped_locked`` — tidak ada run ganda (assessment R1/D3).
3. Baris ``core.collect_run`` status ``running`` di-commit lebih dulu, sehingga run yang gagal tetap
   tercatat.
4. Pekerjaan data dalam **satu transaksi**: sukses = commit semua; gagal = rollback, data lama utuh.
5. ``collect_run`` ditutup (``success``/``partial``/``failed``) + event ``job_finished``/``job_failed``.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg

from atlas.core.db import Database
from atlas.core.errors import AtlasError, new_error_id
from atlas.core.logging import log_event, request_context
from atlas.repositories import runs

logger = logging.getLogger("atlas.job")


@dataclass
class JobResult:
    """Hasil pekerjaan data. ``status`` = success | partial."""

    total: int | None = None
    inserted: int | None = None
    updated: int | None = None
    deleted: int | None = None
    status: str = "success"
    details: dict[str, Any] = field(default_factory=dict)

    def counts(self) -> dict[str, int | None]:
        return {
            "total": self.total,
            "inserted": self.inserted,
            "updated": self.updated,
            "deleted": self.deleted,
        }


@dataclass
class JobOutcome:
    status: str  # success | partial | failed | skipped
    run_id: int | None
    request_id: str
    result: JobResult | None = None
    error_id: str | None = None
    duration_ms: int = 0

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "failed" else 0


@dataclass
class JobContext:
    run_id: int
    request_id: str
    source: str
    data: Any = None  # hasil langkah prepare (mis. data dari master NBU)


Work = Callable[[psycopg.Connection, JobContext], JobResult]
Prepare = Callable[[JobContext], Any]


def run_job(
    db: Database,
    source: str,
    work: Work,
    *,
    prepare: Prepare | None = None,
    details: dict[str, Any] | None = None,
) -> JobOutcome:
    """Jalankan ``work(conn, ctx)`` di dalam satu transaksi dengan lock & pencatatan run.

    ``prepare(ctx)`` (opsional) dijalankan **sesudah** lock & baris run dibuat tetapi **di luar**
    transaksi — untuk pekerjaan lama tanpa DB (mis. mengambil data dari master NBU) agar tidak
    menahan transaksi terbuka. Hasilnya tersedia sebagai ``ctx.data`` di ``work``.
    """
    lock_key = f"atlas.job.{source}"
    with request_context() as request_id:
        started = time.monotonic()
        with db.connection() as conn:
            conn.autocommit = True
            try:
                if not runs.try_advisory_lock(conn, lock_key):
                    log_event(
                        logger,
                        "job",
                        "job_skipped_locked",
                        f"Job {source} dilewati: run sebelumnya masih berjalan",
                        severity="warning",
                        actor=source,
                    )
                    return JobOutcome("skipped", None, request_id)
                try:
                    return _execute(conn, source, work, prepare, request_id, started, details or {})
                finally:
                    if not conn.broken:
                        runs.advisory_unlock(conn, lock_key)
            finally:
                if not conn.broken:
                    conn.autocommit = False


def _execute(
    conn: psycopg.Connection,
    source: str,
    work: Work,
    prepare: Prepare | None,
    request_id: str,
    started: float,
    details: dict[str, Any],
) -> JobOutcome:
    orphaned = runs.fail_orphaned_runs(conn, source, error_id=new_error_id())
    if orphaned:
        log_event(
            logger,
            "job",
            "job_orphaned",
            f"{orphaned} run {source} sebelumnya terputus; ditandai gagal",
            severity="warning",
            actor=source,
            count=orphaned,
        )
    run_id = runs.start_run(conn, source, request_id=request_id, host=socket.gethostname(), details=details)
    log_event(logger, "job", "job_started", f"Job {source} mulai (run {run_id})", actor=source, run_id=run_id)
    ctx = JobContext(run_id=run_id, request_id=request_id, source=source)
    try:
        if prepare is not None:
            ctx.data = prepare(ctx)
        with conn.transaction():
            result = work(conn, ctx)
    except Exception as exc:
        error_id = exc.error_id if isinstance(exc, AtlasError) else new_error_id()
        elapsed = _ms(started)
        if not conn.broken:
            runs.finish_run(
                conn,
                run_id,
                status="failed",
                error_id=error_id,
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
                details={"duration_ms": elapsed},
            )
        log_event(
            logger,
            "job",
            "job_failed",
            f"Job {source} gagal (run {run_id})",
            severity="error",
            error_id=error_id,
            actor=source,
            duration_ms=elapsed,
            exc_info=True,
            run_id=run_id,
        )
        return JobOutcome("failed", run_id, request_id, error_id=error_id, duration_ms=elapsed)

    elapsed = _ms(started)
    runs.finish_run(
        conn,
        run_id,
        status=result.status,
        counts=result.counts(),
        details={**result.details, "duration_ms": elapsed},
    )
    log_event(
        logger,
        "job",
        "job_finished",
        f"Job {source} selesai (run {run_id}): {result.status}",
        severity="info" if result.status == "success" else "warning",
        actor=source,
        duration_ms=elapsed,
        run_id=run_id,
        **result.counts(),
    )
    return JobOutcome(result.status, run_id, request_id, result=result, duration_ms=elapsed)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
