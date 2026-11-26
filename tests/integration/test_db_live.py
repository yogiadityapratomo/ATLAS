"""Pool koneksi ke PostgreSQL sungguhan (role atlas_app, DB atlas_test)."""

from __future__ import annotations

import dataclasses

import pytest

from atlas.core.db import Database
from atlas.core.errors import DatabaseError

pytestmark = pytest.mark.integration


def test_pool_roundtrip_and_session_settings(itest_settings, events, caplog):
    settings = dataclasses.replace(itest_settings, db_statement_timeout_ms=300)
    with Database(settings, "app", "itest", min_size=1, max_size=2) as db:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT 1, current_setting('statement_timeout'), current_setting('application_name'),"
                " current_user, current_setting('TimeZone')"
            ).fetchone()
        assert row == (1, "300ms", "atlas-itest", "atlas_app", "Asia/Jakarta")
        assert db.healthy
    assert [e["event_type"] for e in events()] == ["db_pool_opened", "db_pool_closed"]
    assert settings.db_app.password.get() not in caplog.text


def test_statement_timeout_becomes_query_timeout_event(itest_settings, events):
    settings = dataclasses.replace(itest_settings, db_statement_timeout_ms=300)
    with Database(settings, "app", "itest", min_size=1, max_size=1) as db:
        with pytest.raises(DatabaseError), db.connection() as conn:
            conn.execute("SELECT pg_sleep(2)")
        assert db.healthy  # timeout query bukan tanda DB mati
        with db.connection() as conn:  # koneksi tetap bisa dipakai lagi
            assert conn.execute("SELECT 2").fetchone() == (2,)
    assert "db_query_timeout" in [e["event_type"] for e in events()]


def test_wrong_password_is_connect_failed_without_leak(itest_settings, events, caplog):
    from atlas.core.config import DbCredentials, Secret

    bad = dataclasses.replace(
        itest_settings, db_app=DbCredentials("atlas_app", Secret("Salah-Sekali-999")), db_connect_timeout_s=2
    )
    db = Database(bad, "app", "itest", min_size=1, max_size=1)
    with pytest.raises(DatabaseError):
        db.open()
    assert events()[-1]["event_type"] == "db_connect_failed"
    assert "Salah-Sekali-999" not in caplog.text
