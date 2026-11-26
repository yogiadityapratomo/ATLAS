"""Hak akses role (design 03 §4.3, design 05 §5 & acceptance criteria 5)."""

from __future__ import annotations

import psycopg
import pytest

from tests.integration.conftest import connect

pytestmark = pytest.mark.integration

INSERT_EVENT = (
    "INSERT INTO audit.event (occurred_at, category, event_type, severity, component, message)"
    " VALUES (now(), 'system', 'priv_test', 'info', 'itest', 'cek hak akses')"
)


def _allowed(role: str, statement: str) -> bool:
    with connect(role) as conn:
        try:
            conn.execute(statement)
        except psycopg.errors.InsufficientPrivilege:
            return False
        except psycopg.errors.ReadOnlySqlTransaction:
            return False
        finally:
            conn.rollback()
    return True


@pytest.mark.parametrize(
    ("role", "statement", "expected"),
    [
        # audit.event: append-only untuk aplikasi
        ("atlas_web", INSERT_EVENT, True),
        ("atlas_app", INSERT_EVENT, True),
        ("atlas_readonly", INSERT_EVENT, False),
        ("atlas_web", "UPDATE audit.event SET message = 'x'", False),
        ("atlas_web", "DELETE FROM audit.event", False),
        ("atlas_app", "UPDATE audit.event SET message = 'x'", False),
        ("atlas_app", "DELETE FROM audit.event", False),
        ("atlas_app", "TRUNCATE audit.event", False),
        ("atlas_web", "SELECT count(*) FROM audit.event", True),
        ("atlas_readonly", "SELECT count(*) FROM audit.event", True),
        # data dashboard: web hanya baca
        ("atlas_web", "SELECT count(*) FROM report.cmdb_host", True),
        ("atlas_web", "DELETE FROM cmdb.server_inventory", False),
        ("atlas_web", "UPDATE core.collect_run SET status = 'failed'", False),
        ("atlas_readonly", "DELETE FROM cmdb.server_inventory", False),
        # job menulis data, tapi bukan DDL
        ("atlas_app", "DELETE FROM cmdb.server_inventory", True),
        ("atlas_app", "CREATE TABLE cmdb.coba (id int)", False),
        ("atlas_app", "DROP TABLE cmdb.server_inventory", False),
        ("atlas_web", "CREATE TABLE public.coba (id int)", False),
        ("atlas_web", "CREATE TEMP TABLE coba (id int)", False),
        ("atlas_app", "CREATE TEMP TABLE coba (id int)", True),
    ],
)
def test_role_privileges(clean_db, role, statement, expected):
    login = role.removeprefix("atlas_")
    assert _allowed(login, statement) is expected


def test_readonly_session_is_read_only(clean_db):
    with connect("readonly") as conn:
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"


def test_public_cannot_connect(clean_db):
    with connect("migrator") as conn:
        acl = conn.execute(
            "SELECT datacl::text FROM pg_database WHERE datname = current_database()"
        ).fetchone()[0]
    entries = acl.strip("{}").split(",")
    assert not [e for e in entries if e.startswith("=")]  # entri PUBLIC berbentuk "=c/owner"
    assert any(e.startswith("atlas_web=c/") for e in entries)
