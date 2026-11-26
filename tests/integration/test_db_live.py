"""Koneksi ke PostgreSQL sungguhan. Dilewati kecuali ATLAS_TEST_DB_USER & ATLAS_TEST_DB_PASSWORD diset.

Contoh (DEV, PowerShell):
    $env:ATLAS_TEST_DB_USER = "..."; $env:ATLAS_TEST_DB_PASSWORD = "..."; $env:ATLAS_TEST_DB_NAME = "postgres"
    .venv\\Scripts\\python.exe -m pytest -m integration
"""

from __future__ import annotations

import os

import pytest

from atlas.core.db import Database
from atlas.core.errors import DatabaseError

pytestmark = pytest.mark.integration

USER = os.environ.get("ATLAS_TEST_DB_USER")
PASSWORD = os.environ.get("ATLAS_TEST_DB_PASSWORD")
needs_db = pytest.mark.skipif(not (USER and PASSWORD), reason="ATLAS_TEST_DB_USER/PASSWORD tidak diset")


@pytest.fixture
def live_settings(make_settings):
    return make_settings(
        ATLAS_DB_HOST=os.environ.get("ATLAS_TEST_DB_HOST", "localhost"),
        ATLAS_DB_PORT=os.environ.get("ATLAS_TEST_DB_PORT", "5432"),
        ATLAS_DB_NAME=os.environ.get("ATLAS_TEST_DB_NAME", "atlas_test"),
        ATLAS_DB_USER_APP=USER or "",
        ATLAS_DB_PASSWORD_APP=PASSWORD or "",
        ATLAS_DB_STATEMENT_TIMEOUT_MS="300",
    )


@needs_db
def test_pool_roundtrip_and_session_settings(live_settings, events, caplog):
    with Database(live_settings, "app", "itest", min_size=1, max_size=2) as db:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT 1, current_setting('statement_timeout'), current_setting('application_name')"
            ).fetchone()
        assert row == (1, "300ms", "atlas-itest")
        assert db.healthy
    assert [e["event_type"] for e in events()] == ["db_pool_opened", "db_pool_closed"]
    assert PASSWORD not in caplog.text


@needs_db
def test_statement_timeout_becomes_query_timeout_event(live_settings, events):
    with Database(live_settings, "app", "itest", min_size=1, max_size=1) as db:
        with pytest.raises(DatabaseError), db.connection() as conn:
            conn.execute("SELECT pg_sleep(2)")
        assert db.healthy  # timeout query bukan tanda DB mati
        with db.connection() as conn:  # koneksi tetap bisa dipakai lagi
            assert conn.execute("SELECT 2").fetchone() == (2,)
    assert "db_query_timeout" in [e["event_type"] for e in events()]
