"""Event koneksi database (design 05 §2 kategori ``db``) tanpa PostgreSQL sungguhan.

Sebagian test memakai pool palsu; sebagian memakai psycopg asli ke port lokal yang tertutup,
sehingga jalur "DB mati" benar-benar diuji lewat driver.
"""

from __future__ import annotations

import socket
from contextlib import contextmanager

import pytest
from psycopg import errors as pg_errors
from psycopg_pool import PoolTimeout

from atlas.core.db import Database
from atlas.core.errors import DatabaseError

FAKE_PASSWORD = "Db-Pass-Palsu-123"


class FakePool:
    """Meniru antarmuka ConnectionPool yang dipakai Database."""

    def __init__(self, conninfo, **kwargs):
        self.conninfo = conninfo
        self.kwargs = kwargs
        self.fail_open = False
        self.acquire_error: BaseException | None = None
        self.stats = {"pool_size": 2, "pool_available": 1}
        self.closed = False

    def open(self, wait=False, timeout=30.0):
        if self.fail_open:
            raise PoolTimeout("pool initialization incomplete")

    def close(self):
        self.closed = True

    def get_stats(self):
        return dict(self.stats)

    @contextmanager
    def connection(self, timeout=None):
        if self.acquire_error is not None:
            raise self.acquire_error
        yield object()


def _db(make_settings, **env) -> tuple[Database, list[FakePool]]:
    created: list[FakePool] = []

    def factory(conninfo, **kwargs):
        pool = FakePool(conninfo, **kwargs)
        created.append(pool)
        return pool

    settings = make_settings(ATLAS_DB_PASSWORD_WEB=FAKE_PASSWORD, **env)
    return Database(settings, "web", "unit", pool_factory=factory), created


def _types(events) -> list[str]:
    return [e["event_type"] for e in events()]


# ---------------------------------------------------------------- pool palsu


def test_open_logs_pool_opened_without_password(make_settings, events, caplog):
    db, pools = _db(make_settings)
    assert db.open() is True
    assert _types(events) == ["db_pool_opened"]
    target = events()[0]["details"]["target"]
    assert target["user"] == "atlas_web"
    assert FAKE_PASSWORD not in str(events())
    assert FAKE_PASSWORD not in caplog.text
    # password hanya diteruskan ke driver, plus statement_timeout & application_name
    assert FAKE_PASSWORD in pools[0].conninfo
    assert "application_name=atlas-unit" in pools[0].conninfo
    assert pools[0].kwargs["kwargs"]["options"] == "-c statement_timeout=15000"


def test_pool_exhausted_vs_connect_failed_then_reconnected(make_settings, events):
    db, pools = _db(make_settings)
    db.open()
    pool = pools[0]

    pool.acquire_error = PoolTimeout("timeout")
    pool.stats = {"pool_size": 5, "pool_available": 0}  # penuh semua
    with pytest.raises(DatabaseError) as exhausted, db.connection():
        pass
    assert _types(events)[-1] == "db_pool_exhausted"
    assert events()[-1]["error_id"] == exhausted.value.error_id

    pool.stats = {"pool_size": 0, "pool_available": 0}  # tidak ada koneksi sama sekali
    with pytest.raises(DatabaseError), db.connection():
        pass
    assert _types(events)[-1] == "db_connect_failed"
    assert db.healthy is False

    pool.acquire_error = None
    with db.connection():
        pass
    assert _types(events)[-1] == "db_reconnected"
    assert db.healthy is True

    with db.connection():  # sudah sehat: tidak ada event baru
        pass
    assert _types(events)[-1] == "db_reconnected"
    assert _types(events).count("db_reconnected") == 1


def test_query_timeout_does_not_mark_database_down(make_settings, events):
    db, _ = _db(make_settings)
    db.open()
    with pytest.raises(DatabaseError), db.connection():
        raise pg_errors.QueryCanceled("canceling statement due to statement timeout")
    assert _types(events)[-1] == "db_query_timeout"
    assert db.healthy is True


def test_open_failure_can_keep_app_alive(make_settings, events):
    db, pools = _db(make_settings)

    def failing_factory(conninfo, **kwargs):
        pool = FakePool(conninfo, **kwargs)
        pool.fail_open = not pools  # hanya pool pertama yang gagal
        pools.append(pool)
        return pool

    db._pool_factory = failing_factory
    assert db.open(raise_on_failure=False) is False
    assert db.is_open and not db.healthy
    assert _types(events) == ["db_connect_failed"]
    assert len(pools) == 2  # pool yang timeout diganti pool baru yang menyambung di latar belakang


def test_slow_query_event(make_settings, events, monkeypatch):
    db, _ = _db(make_settings, ATLAS_DB_SLOW_QUERY_MS="1")
    clock = iter([100.0, 100.25])
    monkeypatch.setattr("atlas.core.db.time.monotonic", lambda: next(clock))
    with db.timed("inventory.search", rows=3):
        pass
    (event,) = events()
    assert event["event_type"] == "db_slow_query"
    assert event["duration_ms"] == 250
    assert event["details"]["query"] == "inventory.search"


def test_close_logs_event_and_is_idempotent(make_settings, events):
    db, pools = _db(make_settings)
    with db:
        pass
    db.close()
    assert pools[0].closed
    assert _types(events) == ["db_pool_opened", "db_pool_closed"]


def test_connection_before_open_raises(make_settings):
    db, _ = _db(make_settings)
    with pytest.raises(DatabaseError), db.connection():
        pass


# ---------------------------------------------------------------- driver asli, DB mati


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_driver_unreachable_database(make_settings, events, caplog):
    settings = make_settings(
        ATLAS_DB_HOST="127.0.0.1",
        ATLAS_DB_PORT=str(_closed_port()),
        ATLAS_DB_CONNECT_TIMEOUT_S="1",
        ATLAS_DB_PASSWORD_APP=FAKE_PASSWORD,
    )
    db = Database(settings, "app", "unit", min_size=1, max_size=1)
    with pytest.raises(DatabaseError) as info:
        db.open()
    assert _types(events)[-1] == "db_connect_failed"
    assert info.value.to_user()["error_id"] == events()[-1]["error_id"]

    # mode web: tidak crash, endpoint mendapat DatabaseError ber-ID
    assert db.open(raise_on_failure=False) is False
    try:
        with pytest.raises(DatabaseError), db.connection():
            pass
    finally:
        db.close()
    assert FAKE_PASSWORD not in caplog.text
