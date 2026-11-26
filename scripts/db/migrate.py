r"""migrate.py — terapkan migrasi schema ATLAS (db/migrations/V*.sql).

Di production: **CHANGE — butuh CR** (lihat docs/process/deployment-workflow.md). Pakai --dry-run dulu.

Contoh:
    .venv\Scripts\python.exe scripts\db\migrate.py --dry-run
    .venv\Scripts\python.exe scripts\db\migrate.py
    .venv\Scripts\python.exe scripts\db\migrate.py --database atlas_test
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

import psycopg

from atlas.core.config import load_settings
from atlas.core.errors import AtlasError
from atlas.core.logging import setup_logging
from atlas.core.migrations import discover, migrate


def main() -> int:
    parser = argparse.ArgumentParser(description="Terapkan migrasi schema ATLAS.")
    parser.add_argument("--database", help="Override nama database (mis. atlas_test)")
    parser.add_argument("--dry-run", action="store_true", help="Tampilkan versi yang akan diterapkan saja")
    args = parser.parse_args()

    settings = load_settings()
    if args.database:
        settings = dataclasses.replace(settings, db_name=args.database)
    setup_logging(settings, "migrate")
    try:
        migrations = discover()
        with psycopg.connect(settings.db_conninfo("migrator", application_name="atlas-migrate")) as conn:
            result = migrate(conn, migrations, dry_run=args.dry_run)
    except (AtlasError, psycopg.Error) as exc:
        error_id = getattr(exc, "error_id", "-")
        print(f"GAGAL [{error_id}]: {exc}")
        return 1

    print(f"Database {settings.db_name}: {len(result.already_applied)} versi sudah diterapkan sebelumnya")
    for m in result.pending:
        print(f"  akan diterapkan: V{m.version:03d} {m.name}")
    for m in result.applied:
        print(f"  diterapkan: V{m.version:03d} {m.name}")
    if not (result.pending or result.applied):
        print("  tidak ada migrasi baru")
    return 0


if __name__ == "__main__":
    sys.exit(main())
