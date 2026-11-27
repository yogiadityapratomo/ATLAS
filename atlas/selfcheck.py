r"""Self-check rilis ATLAS — dijalankan **sebelum** switch rilis (deployment-workflow §4.2 langkah 6).

Semua pemeriksaan bersifat **READ-ONLY**: tidak menulis DB, tidak memanggil master NBU (kecuali
``--nbu-ping``, satu GET read-only per master). Exit 0 = siap, 1 = ada FAIL.

    .venv\Scripts\python.exe -m atlas.selfcheck
    .venv\Scripts\python.exe -m atlas.selfcheck --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg

from atlas import __version__
from atlas.core.config import REPO_ROOT, Settings, load_settings
from atlas.core.errors import ConfigError
from atlas.core.migrations import discover

TZ = ZoneInfo("Asia/Jakarta")
FRONTEND_FILES = (
    "index.html",
    "css/style.css",
    "js/common.js",
    "js/main.js",
    "js/capacity.js",
    "js/inventory.js",
    "js/audit.js",
)


@dataclass
class Check:
    name: str
    status: str  # OK | WARN | FAIL
    detail: str


def _connect(settings: Settings, role: str) -> psycopg.Connection:
    return psycopg.connect(settings.db_conninfo(role, application_name="atlas-selfcheck"), autocommit=True)


def check_db_roles(settings: Settings) -> list[Check]:
    out = []
    for role in ("web", "app"):
        try:
            with _connect(settings, role) as conn:
                user, tz = conn.execute("SELECT current_user, current_setting('TimeZone')").fetchone()
            status = "OK" if tz == "Asia/Jakarta" else "WARN"
            out.append(Check(f"db:{role}", status, f"login {user}, timezone {tz}"))
        except psycopg.Error as exc:
            out.append(Check(f"db:{role}", "FAIL", f"{type(exc).__name__}: {str(exc).splitlines()[0]}"))
    return out


def check_schema(settings: Settings) -> list[Check]:
    expected = {m.version: m.checksum for m in discover()}
    try:
        with _connect(settings, "app") as conn:
            applied = dict(conn.execute("SELECT version, checksum FROM core.schema_migrations").fetchall())
            trgm = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'").fetchone()
            months = [datetime.now(TZ).strftime("%Y_%m")]
            parts = {
                r[0]
                for r in conn.execute(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
                    " WHERE i.inhparent = 'audit.event'::regclass"
                )
            }
    except psycopg.Error as exc:
        return [Check("schema", "FAIL", f"{type(exc).__name__}: {str(exc).splitlines()[0]}")]
    out = []
    pending = sorted(set(expected) - set(applied))
    changed = sorted(v for v in applied if v in expected and applied[v] != expected[v])
    unknown = sorted(set(applied) - set(expected))
    if pending or changed or unknown:
        detail = f"belum diterapkan {pending}, checksum beda {changed}, tidak dikenal {unknown}"
        out.append(Check("schema:migrations", "FAIL", detail + " — jalankan scripts/db/migrate.py"))
    else:
        out.append(
            Check("schema:migrations", "OK", f"V{max(applied):03d} ({len(applied)} versi, checksum cocok)")
        )
    out.append(
        Check(
            "schema:pg_trgm", "OK" if trgm else "FAIL", f"versi {trgm[0]}" if trgm else "extension tidak ada"
        )
    )
    missing = [m for m in months if f"event_{m}" not in parts]
    out.append(
        Check(
            "schema:audit_partition",
            "WARN" if missing else "OK",
            f"partisi bulan ini tidak ada {missing} (job maintenance)"
            if missing
            else f"{len(parts)} partisi",
        )
    )
    return out


def check_files(settings: Settings) -> list[Check]:
    out = []
    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.log_dir, prefix=".selfcheck", delete=True):
            pass
        out.append(Check("files:log_dir", "OK", str(settings.log_dir)))
    except OSError as exc:
        out.append(Check("files:log_dir", "FAIL", f"tidak bisa menulis {settings.log_dir}: {exc}"))
    frontend = REPO_ROOT / "frontend"
    missing = [f for f in FRONTEND_FILES if not (frontend / f).is_file()]
    out.append(
        Check("files:frontend", "FAIL" if missing else "OK", f"hilang: {missing}" if missing else "lengkap")
    )
    path = settings.policy_cache_path
    if path is None:
        out.append(
            Check("files:policy_cache", "WARN", "ATLAS_POLICY_CACHE kosong (job inventory butuh --cache)")
        )
    elif not path.is_file():
        out.append(Check("files:policy_cache", "FAIL", f"tidak ditemukan: {path}"))
    else:
        age_h = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
        status = "OK" if age_h < 2 else "WARN"
        out.append(
            Check("files:policy_cache", status, f"{path.stat().st_size / 1e6:.1f} MB, umur {age_h:.1f} jam")
        )
    if settings.capacity_json_dir:
        ok = settings.capacity_json_dir.is_dir()
        out.append(Check("files:capacity_json_dir", "OK" if ok else "FAIL", str(settings.capacity_json_dir)))
    return out


def check_nbu(settings: Settings, ping: bool) -> list[Check]:
    if not settings.allow_live_nbu:
        return [Check("nbu", "OK", "live NBU dinonaktifkan (ATLAS_ALLOW_LIVE_NBU=0)")]
    out = []
    for master in settings.nbu_masters:
        if not master.token:
            out.append(Check(f"nbu:{master.key}", "FAIL", f"NBU_{master.name}_TOKEN kosong"))
            continue
        if not ping:
            out.append(Check(f"nbu:{master.key}", "OK", f"token ada; {master.base_url} (tanpa --nbu-ping)"))
            continue
        from atlas.collectors.nbu_client import NbuClient

        try:
            client = NbuClient(master, timeout_s=10, max_retries=1)
            client.get("/storage/disk-pools", {"page[limit]": 1, "page[offset]": 0})
            out.append(Check(f"nbu:{master.key}", "OK", f"GET disk-pools berhasil ({master.base_url})"))
        except Exception as exc:
            out.append(Check(f"nbu:{master.key}", "FAIL", str(exc)[:200]))
    return out


def run(ping_nbu: bool = False) -> tuple[list[Check], Settings | None]:
    try:
        settings = load_settings()
    except ConfigError as exc:
        return [Check("config", "FAIL", exc.message)], None
    checks = [
        Check(
            "config", "OK", f"env={settings.env}, db={settings.db_host}:{settings.db_port}/{settings.db_name}"
        )
    ]
    steps: list[Callable[[], list[Check]]] = [
        lambda: check_db_roles(settings),
        lambda: check_schema(settings),
        lambda: check_files(settings),
        lambda: check_nbu(settings, ping_nbu),
    ]
    for step in steps:
        checks += step()
    return checks, settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Self-check rilis ATLAS (read-only).")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--nbu-ping", action="store_true", help="Satu GET read-only per master NBU")
    args = parser.parse_args(argv)
    checks, _ = run(args.nbu_ping)
    failed = any(c.status == "FAIL" for c in checks)
    if args.json:
        print(
            json.dumps(
                {"version": __version__, "ok": not failed, "checks": [c.__dict__ for c in checks]}, indent=2
            )
        )
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        host = os.environ.get("COMPUTERNAME", "-")
        print(f"ATLAS {__version__} self-check — {datetime.now(TZ):%Y-%m-%d %H:%M:%S} — host {host}")
        for c in checks:
            print(f"  [{c.status:<4}] {c.name:<26} {c.detail}")
        print("HASIL:", "GAGAL — jangan switch rilis" if failed else "SIAP")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
