"""Migrasi schema: file SQL bernomor di ``db/migrations/`` (design 03 §4.4).

Aturan:

* Nama file ``V001__deskripsi.sql`` — versi unik, urutan = nomor versi.
* Setiap versi dijalankan dalam **satu transaksi** bersama pencatatannya di ``core.schema_migrations``;
  gagal = tidak ada yang berubah.
* Checksum (SHA-256 isi file, line ending dinormalkan) disimpan. File yang **berubah setelah
  diterapkan ditolak** — perubahan schema harus lewat versi baru.
* Versi yang tercatat di DB tetapi filenya tidak ada juga ditolak (repo dan DB tidak sinkron).
* Advisory lock mencegah dua proses migrasi berjalan bersamaan.
* Objek dibuat sebagai ``atlas_owner`` (``SET ROLE``), bukan sebagai user login migrator.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import sql

from atlas.core.config import REPO_ROOT
from atlas.core.errors import AtlasError
from atlas.core.logging import log_event

logger = logging.getLogger("atlas.migrate")

MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
OWNER_ROLE = "atlas_owner"
REQUIRED_ROLES = ("atlas_owner", "atlas_app", "atlas_web", "atlas_readonly")
_FILE_PATTERN = re.compile(r"^V(?P<version>\d{3})__(?P<name>[a-z0-9_]+)\.sql$")
_LOCK_KEY = "atlas.migrate"

_BOOTSTRAP_SQL = """
CREATE SCHEMA IF NOT EXISTS core;
CREATE TABLE IF NOT EXISTS core.schema_migrations (
    version     integer     PRIMARY KEY,
    name        text        NOT NULL,
    checksum    text        NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    applied_at  timestamptz NOT NULL DEFAULT now(),
    applied_by  text        NOT NULL DEFAULT session_user,
    duration_ms integer     NOT NULL CHECK (duration_ms >= 0)
);
COMMENT ON TABLE core.schema_migrations IS 'Riwayat migrasi schema ATLAS (scripts/db/migrate.py)';
"""


class MigrationError(AtlasError):
    default_user_message = "Migrasi database gagal."


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str


@dataclass
class MigrationResult:
    applied: list[Migration] = field(default_factory=list)
    already_applied: list[int] = field(default_factory=list)
    pending: list[Migration] = field(default_factory=list)  # diisi saat dry-run


def checksum_of(text: str) -> str:
    normalized = text.lstrip("﻿").replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"nama file migrasi tidak valid: {path.name} (format: V001__nama.sql)")
        version = int(match["version"])
        if version in migrations:
            raise MigrationError(f"versi migrasi ganda: V{version:03d}")
        text = path.read_text(encoding="utf-8-sig")
        migrations[version] = Migration(version, match["name"], path, text, checksum_of(text))
    return [migrations[v] for v in sorted(migrations)]


def migrate(
    conn: psycopg.Connection, migrations: list[Migration], *, dry_run: bool = False
) -> MigrationResult:
    """Terapkan migrasi yang belum ada. ``conn`` = koneksi user migrator (autocommit akan diatur)."""
    conn.autocommit = True
    _check_roles(conn)
    previous_role = conn.execute("SELECT current_user").fetchone()[0]
    conn.execute(f"SET ROLE {OWNER_ROLE}")
    locked = conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (_LOCK_KEY,)).fetchone()[0]
    if not locked:
        raise MigrationError("migrasi lain sedang berjalan (advisory lock dipegang proses lain)")
    try:
        with conn.transaction():
            conn.execute(_BOOTSTRAP_SQL)
        applied = dict(conn.execute("SELECT version, checksum FROM core.schema_migrations").fetchall())
        _verify(applied, migrations)

        result = MigrationResult(already_applied=sorted(applied))
        for migration in migrations:
            if migration.version in applied:
                continue
            if dry_run:
                result.pending.append(migration)
                continue
            started = time.monotonic()
            with conn.transaction():
                conn.execute(migration.sql)
                duration_ms = int((time.monotonic() - started) * 1000)
                conn.execute(
                    "INSERT INTO core.schema_migrations (version, name, checksum, duration_ms)"
                    " VALUES (%s, %s, %s, %s)",
                    (migration.version, migration.name, migration.checksum, duration_ms),
                )
            result.applied.append(migration)
            log_event(
                logger,
                "system",
                "migration_applied",
                f"Migrasi V{migration.version:03d} {migration.name} diterapkan",
                duration_ms=duration_ms,
                version=migration.version,
                checksum=migration.checksum,
            )
        return result
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (_LOCK_KEY,))
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(previous_role)))


def _check_roles(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(REQUIRED_ROLES),)
    ).fetchall()
    missing = sorted(set(REQUIRED_ROLES) - {r[0] for r in rows})
    if missing:
        raise MigrationError(
            f"role belum ada: {', '.join(missing)} — jalankan scripts/db/bootstrap.py lebih dulu"
        )


def _verify(applied: dict[int, str], migrations: list[Migration]) -> None:
    on_disk = {m.version: m for m in migrations}
    unknown = sorted(set(applied) - set(on_disk))
    if unknown:
        raise MigrationError(
            "versi tercatat di DB tetapi file tidak ada: " + ", ".join(f"V{v:03d}" for v in unknown)
        )
    changed = [v for v, checksum in applied.items() if on_disk[v].checksum != checksum]
    if changed:
        raise MigrationError(
            "file migrasi berubah setelah diterapkan (buat versi baru, jangan ubah file lama): "
            + ", ".join(on_disk[v].path.name for v in sorted(changed)),
            details={"versions": sorted(changed)},
        )
