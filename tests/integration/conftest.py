"""Fixture test integrasi: DB ``atlas_test`` dengan role aplikasi dari ``.env`` root.

Dilewati otomatis bila password role belum ada (mis. di mesin tanpa bootstrap). Persiapan DEV:
``scripts/db/bootstrap.py --database atlas_test --generate-missing-passwords``
(lihat docs/process/dev-setup.md).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import psycopg
import pytest

from atlas.core.config import Settings, load_settings
from atlas.core.migrations import discover, migrate

TEST_DB = "atlas_test"
SCHEMAS = ("report", "cmdb", "audit", "core")


def _base_settings() -> Settings | None:
    try:
        settings = load_settings()
    except Exception:
        return None
    needed = (settings.db_migrator, settings.db_app, settings.db_web, settings.db_readonly)
    if not all(c.password for c in needed):
        return None
    return dataclasses.replace(settings, db_name=TEST_DB)


_SETTINGS = _base_settings()


def pytest_collection_modifyitems(config, items):
    if _SETTINGS is not None:
        return
    skip = pytest.mark.skip(reason="password role ATLAS belum ada di .env (jalankan scripts/db/bootstrap.py)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def connect(role: str, settings: Settings | None = None, **kwargs) -> psycopg.Connection:
    """Koneksi sebagai role login. ``migrator`` langsung ``SET ROLE atlas_owner`` (autocommit)."""
    settings = settings or _SETTINGS
    assert settings is not None
    if role == "migrator":
        kwargs.setdefault("autocommit", True)
    conn = psycopg.connect(settings.db_conninfo(role, application_name=f"atlas-itest-{role}"), **kwargs)
    if role == "migrator":
        conn.execute("SET ROLE atlas_owner")
    return conn


@pytest.fixture(scope="session")
def itest_base() -> Settings:
    assert _SETTINGS is not None
    return _SETTINGS


@pytest.fixture
def itest_settings(itest_base, tmp_path) -> Settings:
    return dataclasses.replace(itest_base, log_dir=tmp_path / "logs")


def reset_database() -> None:
    """Hapus semua objek ATLAS di atlas_test lalu migrasi dari nol."""
    with connect("migrator") as conn:
        for schema in SCHEMAS:
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.execute("DROP EXTENSION IF EXISTS pg_trgm")
        migrate(conn, discover())


@pytest.fixture(scope="session")
def migrated_db(itest_base) -> Settings:
    reset_database()
    return itest_base


@pytest.fixture
def clean_db(migrated_db) -> Iterator[Settings]:
    """DB termigrasi dengan tabel data kosong (dijalankan sebelum tiap test)."""
    with connect("migrator") as conn:
        conn.execute("TRUNCATE cmdb.server_inventory, audit.event, core.collect_run RESTART IDENTITY CASCADE")
    yield migrated_db
