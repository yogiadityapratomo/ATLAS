"""Akses PostgreSQL: connection pool dengan event koneksi (design 05 §2, kategori ``db``).

Event yang dicatat:

* ``db_pool_opened`` / ``db_pool_closed`` — siklus hidup pool.
* ``db_connect_failed`` — DB tidak bisa dihubungi (saat open, ambil koneksi, atau koneksi putus).
* ``db_reconnected`` — koneksi berhasil lagi setelah sebelumnya gagal.
* ``db_pool_exhausted`` — semua koneksi sedang dipakai sampai batas waktu tunggu.
* ``db_query_timeout`` — query dibatalkan ``statement_timeout``.
* ``db_slow_query`` — query melewati ``ATLAS_DB_SLOW_QUERY_MS`` (lewat :meth:`Database.timed`).

Kegagalan DB tidak membuat proses crash: pemanggil menerima :class:`DatabaseError` yang membawa
ID error untuk ditampilkan ke user. Advisory lock & helper transaksi job menyusul di PR-2.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import errors as pg_errors
from psycopg_pool import ConnectionPool, PoolTimeout

from atlas.core.config import DbRole, Settings
from atlas.core.errors import DatabaseError
from atlas.core.logging import log_event

logger = logging.getLogger("atlas.db")

PoolFactory = Callable[..., Any]


class Database:
    def __init__(
        self,
        settings: Settings,
        role: DbRole,
        component: str,
        *,
        min_size: int | None = None,
        max_size: int | None = None,
        pool_factory: PoolFactory = ConnectionPool,
    ) -> None:
        self.settings = settings
        self.role = role
        self.component = component
        self.min_size = min_size or settings.db_pool_min
        self.max_size = max_size or settings.db_pool_max
        self.timeout_s = float(settings.db_connect_timeout_s)
        self._pool_factory = pool_factory
        self._pool: Any = None
        self._down = False
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------------ status

    @property
    def target(self) -> dict[str, object]:
        """Identitas koneksi tanpa password — aman untuk log/audit."""
        return {**self.settings.db_target(self.role), "pool": f"{self.min_size}-{self.max_size}"}

    @property
    def is_open(self) -> bool:
        return self._pool is not None

    @property
    def healthy(self) -> bool:
        """``False`` sejak kegagalan terakhir sampai koneksi berikutnya berhasil."""
        return self.is_open and not self._down

    # ------------------------------------------------------------------ siklus hidup

    def _make_pool(self) -> Any:
        conninfo = self.settings.db_conninfo(self.role, application_name=f"atlas-{self.component}")
        return self._pool_factory(
            conninfo,
            min_size=self.min_size,
            max_size=self.max_size,
            open=False,
            name=f"atlas-{self.component}-{self.role}",
            timeout=self.timeout_s,
            check=ConnectionPool.check_connection,  # koneksi basi (mis. setelah DB restart) dibuang
            kwargs={"options": f"-c statement_timeout={self.settings.db_statement_timeout_ms}"},
            reconnect_failed=self._on_reconnect_failed,
        )

    def open(self, *, wait: bool = True, raise_on_failure: bool = True) -> bool:
        """Buka pool.

        ``wait=True``: tunggu sampai ``min_size`` koneksi siap. Jika gagal dan
        ``raise_on_failure=False`` (dipakai web), pool tetap dibuka di latar belakang dan terus
        mencoba menyambung — aplikasi tetap hidup, endpoint yang butuh DB mengembalikan error ber-ID.
        """
        if self._pool is not None:
            return True
        pool = self._make_pool()
        started = time.monotonic()
        try:
            pool.open(wait=wait, timeout=self.timeout_s)
        except PoolTimeout as exc:
            error = self._fail("db_connect_failed", exc, phase="open")
            if raise_on_failure:
                raise error from exc
            pool = self._make_pool()  # pool yang timeout sudah ditutup; buka ulang tanpa menunggu
            pool.open(wait=False)
            self._pool = pool
            return False
        self._pool = pool
        log_event(
            logger,
            "db",
            "db_pool_opened",
            "Pool koneksi database dibuka",
            duration_ms=_ms_since(started),
            target=self.target,
        )
        return True

    def close(self) -> None:
        if self._pool is None:
            return
        pool, self._pool = self._pool, None
        pool.close()
        log_event(logger, "db", "db_pool_closed", "Pool koneksi database ditutup", target=self.target)

    def __enter__(self) -> Database:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ pemakaian

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """Pinjam satu koneksi dari pool; dikembalikan otomatis (commit jika sukses, rollback jika error)."""
        if self._pool is None:
            raise DatabaseError("pool database belum dibuka", details=self.target)
        try:
            with self._pool.connection(timeout=self.timeout_s) as conn:
                self._mark_up()
                yield conn
        except PoolTimeout as exc:
            stats = self._pool.get_stats() if self._pool is not None else {}
            exhausted = stats.get("pool_size", 0) >= self.max_size and stats.get("pool_available", 0) == 0
            event = "db_pool_exhausted" if exhausted else "db_connect_failed"
            raise self._fail(event, exc, phase="acquire", stats=stats) from exc
        except pg_errors.QueryCanceled as exc:
            raise self._fail("db_query_timeout", exc, phase="query", mark_down=False) from exc
        except psycopg.OperationalError as exc:
            raise self._fail("db_connect_failed", exc, phase="query") from exc

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """Satu transaksi eksplisit: semua berhasil atau semua dibatalkan."""
        with self.connection() as conn, conn.transaction():
            yield conn

    @contextmanager
    def timed(self, query_name: str, **details: Any) -> Iterator[None]:
        """Ukur durasi blok query; catat ``db_slow_query`` bila melewati ambang."""
        started = time.monotonic()
        try:
            yield
        finally:
            elapsed = _ms_since(started)
            if elapsed >= self.settings.db_slow_query_ms:
                log_event(
                    logger,
                    "db",
                    "db_slow_query",
                    f"Query lambat: {query_name} ({elapsed} ms)",
                    severity="warning",
                    duration_ms=elapsed,
                    query=query_name,
                    threshold_ms=self.settings.db_slow_query_ms,
                    **details,
                )

    # ------------------------------------------------------------------ internal

    def _mark_up(self) -> None:
        with self._state_lock:
            was_down, self._down = self._down, False
        if was_down:
            log_event(logger, "db", "db_reconnected", "Koneksi database pulih", target=self.target)

    def _fail(
        self, event_type: str, exc: BaseException, *, mark_down: bool = True, **details: Any
    ) -> DatabaseError:
        if mark_down:
            with self._state_lock:
                self._down = True
        error = DatabaseError(f"{event_type}: {exc}", details={"target": self.target, **details})
        messages = {
            "db_connect_failed": "Gagal terhubung ke database",
            "db_pool_exhausted": "Semua koneksi database sedang terpakai",
            "db_query_timeout": "Query database melewati batas waktu",
        }
        log_event(
            logger,
            "db",
            event_type,
            messages.get(event_type, event_type),
            severity="error",
            error_id=error.error_id,
            target=self.target,
            reason=f"{type(exc).__name__}: {exc}",
            **details,
        )
        return error

    def _on_reconnect_failed(self, pool: Any) -> None:
        """Dipanggil psycopg_pool setelah lama gagal menyambung ulang (default 5 menit)."""
        with self._state_lock:
            self._down = True
        log_event(
            logger,
            "db",
            "db_connect_failed",
            "Database tetap tidak dapat dihubungi setelah percobaan ulang",
            severity="critical",
            target=self.target,
            phase="reconnect",
        )


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
