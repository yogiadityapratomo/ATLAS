"""Migrasi schema (plan 04 task 2.1–2.2): DB kosong → semua versi; ulang = no-op; file berubah = ditolak."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from atlas.core.migrations import MIGRATIONS_DIR, MigrationError, discover, migrate
from tests.integration.conftest import connect, reset_database

pytestmark = pytest.mark.integration


def test_fresh_database_gets_all_versions_then_noop(migrated_db):
    reset_database()  # dari nol
    with connect("migrator") as conn:
        rows = conn.execute(
            "SELECT version, name, applied_by FROM core.schema_migrations ORDER BY 1"
        ).fetchall()
        assert rows[0] == (1, "init", "atlas_migrator")
        assert len(rows) == len(discover())
        result = migrate(conn, discover())
    assert result.applied == []
    assert result.already_applied == [m.version for m in discover()]


def test_changed_file_is_rejected(migrated_db, tmp_path):
    for path in MIGRATIONS_DIR.glob("*.sql"):
        shutil.copy(path, tmp_path / path.name)
    v001 = tmp_path / "V001__init.sql"
    v001.write_text(v001.read_text(encoding="utf-8") + "\n-- perubahan diam-diam\n", encoding="utf-8")
    with connect("migrator") as conn, pytest.raises(MigrationError, match="berubah setelah diterapkan"):
        migrate(conn, discover(tmp_path))


def test_line_ending_change_is_not_a_change(migrated_db, tmp_path):
    for path in MIGRATIONS_DIR.glob("*.sql"):
        data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        (tmp_path / path.name).write_bytes(data)
    with connect("migrator") as conn:
        assert migrate(conn, discover(tmp_path)).applied == []


def test_missing_file_for_applied_version_is_rejected(migrated_db, tmp_path):
    with connect("migrator") as conn, pytest.raises(MigrationError, match="file tidak ada"):
        migrate(conn, discover(tmp_path))  # folder kosong


def test_failed_migration_changes_nothing(migrated_db, tmp_path):
    for path in MIGRATIONS_DIR.glob("*.sql"):
        shutil.copy(path, tmp_path / path.name)
    (tmp_path / "V999__broken.sql").write_text(
        "CREATE TABLE core.should_not_exist (id int);\nSELECT 1/0;\n", encoding="utf-8"
    )
    with connect("migrator") as conn:
        with pytest.raises(Exception, match="division by zero"):
            migrate(conn, discover(tmp_path))
        assert conn.execute("SELECT to_regclass('core.should_not_exist')").fetchone()[0] is None
        assert (
            conn.execute("SELECT count(*) FROM core.schema_migrations WHERE version = 999").fetchone()[0] == 0
        )


def test_objects_are_owned_by_atlas_owner(migrated_db):
    with connect("migrator") as conn:
        owners = conn.execute(
            """
            SELECT DISTINCT pg_get_userbyid(c.relowner)
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname IN ('core', 'audit', 'cmdb', 'report') AND c.relkind IN ('r', 'p', 'v', 'i')
            """
        ).fetchall()
    assert owners == [("atlas_owner",)]


def test_audit_partitions_cover_now_and_ahead(migrated_db):
    with connect("migrator") as conn:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
                " WHERE i.inhparent = 'audit.event'::regclass"
            ).fetchall()
        }
    now = datetime.now(ZoneInfo("Asia/Jakarta"))
    assert f"event_{now:%Y_%m}" in names
    assert "event_default" in names
    assert len(names) == 1 + 5  # default + (1 bulan lalu .. 3 bulan ke depan)


def test_ensure_partitions_moves_rows_out_of_default(clean_db):
    far = datetime.now(ZoneInfo("Asia/Jakarta")).replace(day=15) + timedelta(days=31 * 8)
    with connect("app", autocommit=True) as conn:
        conn.execute(
            "INSERT INTO audit.event (occurred_at, category, event_type, severity, component, message)"
            " VALUES (%s, 'system', 'test_event', 'info', 'itest', 'masa depan')",
            (far,),
        )
    with connect("migrator") as conn:
        assert conn.execute("SELECT count(*) FROM audit.event_default").fetchone()[0] == 1
        created = conn.execute("SELECT core.ensure_monthly_partitions('audit.event', 0, 9)").fetchone()[0]
        assert created >= 1
        assert conn.execute("SELECT count(*) FROM audit.event_default").fetchone()[0] == 0
        part = conn.execute(
            "SELECT tableoid::regclass::text FROM audit.event WHERE message = 'masa depan'"
        ).fetchone()[0]
        assert part == f"audit.event_{far:%Y_%m}"
        assert conn.execute("SELECT core.ensure_monthly_partitions('audit.event', 0, 9)").fetchone()[0] == 0
    reset_database()
