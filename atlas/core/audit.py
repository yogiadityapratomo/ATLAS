"""Penulis audit write-behind: event log → antrean memori → COPY batch ke ``audit.event`` (design 05 §3.2).

* Pemanggil (request web, job) **tidak pernah menunggu** database: ``emit`` hanya memasukkan ke antrean.
* Thread latar belakang menulis tiap ``flush_interval_s`` atau saat antrean mencapai ``batch_size``.
* DB mati → event tetap di antrean (dicoba lagi dengan backoff 1→60 dtk) dan tetap lengkap di file log
  (sumber kebenaran). Antrean dibatasi; bila penuh, event debug/info dibuang lebih dulu, warning ke atas
  dipertahankan. Jumlah yang terbuang dilaporkan lewat event ``audit_backlog_dropped`` setelah pulih.
* Record log biasa (tanpa ``log_event``) ikut dicatat bila level ≥ ERROR, sebagai ``system/log_error``.
* Semua teks melewati filter secret yang sama dengan file log.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import psycopg

from atlas import __version__
from atlas.core.errors import ERROR_ID_PATTERN, DatabaseError
from atlas.core.logging import CATEGORIES, EVENT_ATTR, REDACTOR, SEVERITIES

if TYPE_CHECKING:
    from atlas.core.config import DbRole, Settings
    from atlas.core.db import Database

logger = logging.getLogger("atlas.audit")

Sink = Callable[[psycopg.Connection, Sequence[Sequence[object]]], int]
PartitionHook = Callable[[psycopg.Connection], int]

_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
_HOST = socket.gethostname()
_MAX_MESSAGE = 4000
_MAX_TRACEBACK = 8000
_PARTITION_EVERY_S = 6 * 3600


class AuditHandler(logging.Handler):
    def __init__(
        self,
        db: Database,
        component: str,
        *,
        sink: Sink,
        ensure_partitions: PartitionHook | None = None,
        batch_size: int = 200,
        flush_interval_s: float = 1.0,
        max_queue: int = 10_000,
        max_backoff_s: float = 60.0,
    ) -> None:
        super().__init__(level=logging.DEBUG)
        self.db = db
        self.component = component
        self.sink = sink
        self.ensure_partitions = ensure_partitions
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self.max_queue = max_queue
        self.max_backoff_s = max_backoff_s

        self._queue: deque[tuple[int, int, tuple]] = deque()  # (seq, levelno, row)
        self._seq = 0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._backoff = 0.0
        self._last_partition_check = 0.0
        self.dropped = 0  # belum dilaporkan
        self.written = 0
        self.rejected = 0
        self._thread = threading.Thread(target=self._run, name=f"atlas-audit-{component}", daemon=True)

    # ------------------------------------------------------------------ siklus hidup

    def start(self) -> AuditHandler:
        self._thread.start()
        return self

    def flush(self, timeout: float = 5.0) -> bool:
        """Tunggu antrean kosong (dipakai saat shutdown & test). ``False`` bila timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                empty = not self._queue
            if empty and self._idle.is_set():
                return True
            self._wake.set()
            time.sleep(0.02)
        return False

    def close(self) -> None:
        if self._thread.is_alive():
            self.flush(timeout=5.0)
            self._stop.set()
            self._wake.set()
            self._thread.join(timeout=5.0)
        self.db.close()
        super().close()

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    # ------------------------------------------------------------------ logging.Handler

    def emit(self, record: logging.LogRecord) -> None:
        try:
            row = self._to_row(record)
            if row is not None:
                self._enqueue(record.levelno, row)
        except Exception:
            self.handleError(record)

    def _enqueue(self, levelno: int, row: tuple) -> None:
        with self._lock:
            if len(self._queue) >= self.max_queue:
                if levelno < logging.WARNING:
                    self.dropped += 1
                    return
                victim = next((item for item in self._queue if item[1] < logging.WARNING), None)
                if victim is not None:
                    self._queue.remove(victim)
                else:
                    self._queue.popleft()
                self.dropped += 1
            self._seq += 1
            self._queue.append((self._seq, levelno, row))
            full = len(self._queue) >= self.batch_size
        if full:
            self._wake.set()

    # ------------------------------------------------------------------ thread penulis

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=self._backoff or self.flush_interval_s)
            self._wake.clear()
            self._idle.clear()
            try:
                self._maybe_ensure_partitions()
                while self._write_batch():
                    pass
            finally:
                self._idle.set()
        self._write_batch()  # sisa terakhir saat berhenti (sekali coba)

    def _write_batch(self) -> bool:
        """Tulis satu batch. ``True`` bila masih ada sisa untuk ditulis segera."""
        with self._lock:
            batch = [item for _, item in zip(range(self.batch_size), self._queue, strict=False)]
            dropped = self.dropped
        if not batch and not dropped:
            return False
        rows = [item[2] for item in batch]
        if dropped:
            rows.append(self._backlog_row(dropped))
        try:
            with self.db.connection() as conn:
                self.sink(conn, rows)
        except DatabaseError:
            self._backoff = min(max(self._backoff * 2, 1.0), self.max_backoff_s)
            return False
        except psycopg.Error as exc:
            # data ditolak DB (seharusnya tidak terjadi; _to_row memvalidasi) — buang batch agar tidak macet
            self._remove_upto(batch[-1][0] if batch else 0, written=False)
            with self._lock:
                self.rejected += len(batch)
            logger.error(
                "Batch audit ditolak database (%s baris): %s", len(batch), exc, extra={"atlas_no_audit": True}
            )
            return False
        self._backoff = 0.0
        self._remove_upto(batch[-1][0] if batch else 0, written=True)
        with self._lock:
            self.dropped -= dropped
            return len(self._queue) >= self.batch_size

    def _remove_upto(self, seq: int, *, written: bool) -> None:
        with self._lock:
            count = 0
            while self._queue and self._queue[0][0] <= seq:
                self._queue.popleft()
                count += 1
            if written:
                self.written += count

    def _maybe_ensure_partitions(self) -> None:
        if self.ensure_partitions is None or self._backoff:
            return
        now = time.monotonic()
        if self._last_partition_check and now - self._last_partition_check < _PARTITION_EVERY_S:
            return
        try:
            with self.db.connection() as conn:
                created = self.ensure_partitions(conn)
            self._last_partition_check = now
            if created:
                logger.info("Partisi audit baru dibuat: %s", created)
        except DatabaseError:
            pass  # dicoba lagi pada siklus berikutnya; kegagalan sudah dicatat sebagai event db

    # ------------------------------------------------------------------ konversi record → baris

    def _to_row(self, record: logging.LogRecord) -> tuple | None:
        if getattr(record, "atlas_no_audit", False):
            return None
        event: dict[str, Any] | None = getattr(record, EVENT_ATTR, None)
        if event is None:
            if record.levelno < logging.ERROR:
                return None
            severity = "critical" if record.levelno >= logging.CRITICAL else "error"
            event = {
                "category": "system",
                "event_type": f"log_{severity}",
                "severity": severity,
                "details": {"logger": record.name},
            }

        details: dict[str, Any] = dict(REDACTOR.redact(event.get("details") or {}))
        category = event.get("category")
        if category not in CATEGORIES:
            details["category_raw"] = category
            category = "system"
        event_type = event.get("event_type") or ""
        if not _EVENT_TYPE.match(event_type):
            details["event_type_raw"] = event_type
            event_type = "unknown_event"
        severity = event.get("severity")
        if severity not in SEVERITIES:
            severity = logging.getLevelName(record.levelno).lower()
            severity = severity if severity in SEVERITIES else "info"
        error_id = event.get("error_id")
        if error_id is not None and not ERROR_ID_PATTERN.match(str(error_id)):
            details["error_id_raw"] = str(error_id)
            error_id = None
        request_id = event.get("request_id")
        if request_id is not None:
            try:
                request_id = str(uuid.UUID(str(request_id)))
            except ValueError:
                details["request_id_raw"] = str(request_id)
                request_id = None
        duration = event.get("duration_ms")
        duration = int(duration) if isinstance(duration, (int, float)) and duration >= 0 else None
        if record.exc_info and record.exc_info[0] is not None:
            details["exc_type"] = record.exc_info[0].__name__
            formatted = logging.Formatter().formatException(record.exc_info)
            details["traceback"] = REDACTOR.redact_text(formatted)[-_MAX_TRACEBACK:]

        return (
            datetime.fromtimestamp(record.created, UTC),
            category,
            event_type,
            severity,
            self.component,
            REDACTOR.redact_text(str(event["actor"])) if event.get("actor") else None,
            request_id,
            error_id,
            REDACTOR.redact_text(record.getMessage())[:_MAX_MESSAGE],
            duration,
            json.dumps(details, ensure_ascii=False, default=str),
            _HOST,
            record.process,
            __version__,
        )

    def _backlog_row(self, dropped: int) -> tuple:
        return (
            datetime.now(UTC),
            "system",
            "audit_backlog_dropped",
            "warning",
            self.component,
            None,
            None,
            None,
            f"{dropped} event audit tidak masuk database (antrean penuh); lengkap di file log",
            None,
            json.dumps({"dropped": dropped, "max_queue": self.max_queue}),
            _HOST,
            None,
            __version__,
        )


def start_audit(settings: Settings, component: str, role: DbRole = "app", **options: Any) -> AuditHandler:
    """Pasang penulis audit ke root logger. Pool khusus 1 koneksi agar tidak berebut dengan request.

    Tidak memblok start aplikasi: bila DB mati, pool menyambung di latar belakang.
    """
    from atlas.core.db import Database
    from atlas.repositories import audit as audit_repo

    db = Database(settings, role, f"{component}-audit", min_size=1, max_size=1)
    handler = AuditHandler(
        db, component, sink=audit_repo.copy_events, ensure_partitions=audit_repo.ensure_partitions, **options
    )
    logging.getLogger().addHandler(handler)  # dipasang dulu: event pembukaan pool ikut tercatat
    db.open(wait=False, raise_on_failure=False)
    return handler.start()
