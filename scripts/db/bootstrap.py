r"""bootstrap.py — siapkan role & database ATLAS di cluster PostgreSQL (sekali per environment).

Dijalankan oleh DBA/superuser. Di production: **CHANGE — butuh CR**. Idempoten: aman diulang.

Yang dilakukan (design 03 §4.3 + design 05 §5):
  1. Role: atlas_owner (NOLOGIN, pemilik objek), atlas_migrator (LOGIN, boleh SET ROLE atlas_owner),
     atlas_app (job), atlas_web (web), atlas_readonly (pembaca lain), lengkap dengan timeout per role.
  2. Database (default: atlas) milik atlas_owner, UTF8, collation builtin C.UTF-8, zona Asia/Jakarta,
     CONNECT hanya untuk role ATLAS (dicabut dari PUBLIC), TEMPORARY untuk atlas_app (tabel staging).
  Objek (schema, tabel, GRANT) dibuat oleh migrasi: scripts/db/migrate.py.

Password role dibaca dari .env (ATLAS_DB_PASSWORD_*). Di DEV, --generate-missing-passwords membuat
password acak dan menuliskannya ke .env (tidak pernah dicetak). Password admin dari PGPASSWORD.

Contoh DEV (PowerShell):
    $env:PGPASSWORD = (Get-Content "$env:USERPROFILE\.atlas\pg_postgres_password.txt" -Raw).Trim()
    .venv\Scripts\python.exe scripts\db\bootstrap.py --database atlas --database atlas_test `
        --generate-missing-passwords
    Remove-Item Env:PGPASSWORD
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from atlas.core.config import REPO_ROOT, load_settings

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DB_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class RoleSpec:
    name: str
    login: bool
    env_key: str | None
    settings: dict[str, str]
    connection_limit: int = -1


ROLES = [
    RoleSpec("atlas_owner", login=False, env_key=None, settings={}),
    RoleSpec(
        "atlas_migrator",
        login=True,
        env_key="ATLAS_DB_PASSWORD_MIGRATOR",
        settings={"lock_timeout": "10s", "statement_timeout": "10min"},
        connection_limit=3,
    ),
    RoleSpec(
        "atlas_app",
        login=True,
        env_key="ATLAS_DB_PASSWORD_APP",
        settings={
            "statement_timeout": "10min",
            "lock_timeout": "30s",
            "idle_in_transaction_session_timeout": "5min",
        },
        connection_limit=10,
    ),
    RoleSpec(
        "atlas_web",
        login=True,
        env_key="ATLAS_DB_PASSWORD_WEB",
        settings={
            "statement_timeout": "15s",
            "lock_timeout": "5s",
            "idle_in_transaction_session_timeout": "60s",
        },
        connection_limit=15,
    ),
    RoleSpec(
        "atlas_readonly",
        login=True,
        env_key="ATLAS_DB_PASSWORD_READONLY",
        settings={
            "statement_timeout": "30s",
            "idle_in_transaction_session_timeout": "60s",
            "default_transaction_read_only": "on",
        },
        connection_limit=10,
    ),
]
LOGIN_ROLES = [r.name for r in ROLES if r.login]


def main() -> int:
    parser = argparse.ArgumentParser(description="Siapkan role & database ATLAS (idempoten).")
    parser.add_argument(
        "--database", action="append", help="Nama database (boleh diulang). Default: dari .env"
    )
    parser.add_argument("--admin-user", default="postgres")
    parser.add_argument("--admin-db", default="postgres")
    parser.add_argument(
        "--generate-missing-passwords", action="store_true", help="DEV: isi password kosong di .env"
    )
    parser.add_argument(
        "--allow-remote", action="store_true", help="Izinkan host non-localhost (production, CR)"
    )
    args = parser.parse_args()

    # sama dengan load_settings(): server memakai ATLAS_ENV_FILE (shared\.env di luar folder rilis)
    env_file = Path(os.environ.get("ATLAS_ENV_FILE") or REPO_ROOT / ".env")
    settings = load_settings()
    if settings.db_host not in LOCAL_HOSTS and not args.allow_remote:
        print(f"DITOLAK: host {settings.db_host!r} bukan localhost. Pakai --allow-remote (butuh CR).")
        return 2
    admin_password = os.environ.get("PGPASSWORD")
    if not admin_password:
        print("PGPASSWORD (password admin) belum di-set.")
        return 2

    if args.generate_missing_passwords:
        if settings.env == "prod":
            print("DITOLAK: --generate-missing-passwords tidak boleh di prod; isi password lewat .env.")
            return 2
        generated = ensure_passwords(env_file)
        if generated:
            print(f"Password baru dibuat di .env untuk: {', '.join(generated)} (tidak ditampilkan)")
        settings = load_settings()

    passwords = {r.name: settings.db_credentials(_role_key(r.name)).password.get() for r in ROLES if r.login}
    missing = [name for name, pw in passwords.items() if not pw]
    if missing:
        print(f"Password belum diisi di .env untuk: {', '.join(missing)}")
        return 2
    users = {r.name: settings.db_credentials(_role_key(r.name)).user for r in ROLES if r.login}
    renamed = {k: v for k, v in users.items() if k != v}
    if renamed:
        print(
            f"DITOLAK: nama user di .env berbeda dari role standar: {renamed}. "
            "GRANT di migrasi memakai nama standar."
        )
        return 2

    databases = args.database or [settings.db_name]
    for name in databases:
        if not DB_NAME_PATTERN.match(name):
            print(f"Nama database tidak valid: {name!r}")
            return 2

    with psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=args.admin_db,
        user=args.admin_user,
        password=admin_password,
        connect_timeout=settings.db_connect_timeout_s,
        application_name="atlas-bootstrap",
        autocommit=True,
    ) as conn:
        log_statement = conn.execute("SHOW log_statement").fetchone()[0]
        if log_statement in ("all", "ddl"):
            print(f"DITOLAK: log_statement={log_statement} akan menulis password role ke log server.")
            return 2
        for role in ROLES:
            print(ensure_role(conn, role, passwords.get(role.name)))
        conn.execute("GRANT atlas_owner TO atlas_migrator WITH INHERIT FALSE, SET TRUE")
        for name in databases:
            for line in ensure_database(conn, name):
                print(line)
    print("Selesai. Langkah berikutnya: .venv\\Scripts\\python.exe scripts\\db\\migrate.py")
    return 0


def _role_key(role: str):
    return role.removeprefix("atlas_")  # atlas_web -> "web"


def ensure_role(conn: psycopg.Connection, role: RoleSpec, password: str | None) -> str:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role.name,)).fetchone()
    ident = sql.Identifier(role.name)
    options = sql.SQL("LOGIN" if role.login else "NOLOGIN") + sql.SQL(
        " NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT {}"
    ).format(sql.Literal(role.connection_limit))
    verb = "ALTER" if exists else "CREATE"
    conn.execute(sql.SQL(verb + " ROLE {} ").format(ident) + options)
    if password:
        conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(ident, sql.Literal(password)))
    for key, value in role.settings.items():
        conn.execute(
            sql.SQL("ALTER ROLE {} SET {} = {}").format(ident, sql.Identifier(key), sql.Literal(value))
        )
    return f"role {role.name}: {'diperbarui' if exists else 'dibuat'}"


def ensure_database(conn: psycopg.Connection, name: str) -> list[str]:
    ident = sql.Identifier(name)
    row = conn.execute(
        "SELECT datlocprovider, datlocale, pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s",
        (name,),
    ).fetchone()
    lines = []
    if row is None:
        conn.execute(
            sql.SQL(
                "CREATE DATABASE {} OWNER atlas_owner TEMPLATE template0 ENCODING 'UTF8' "
                "LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8' LOCALE 'C'"
            ).format(ident)
        )
        lines.append(f"database {name}: dibuat (builtin C.UTF-8)")
    else:
        provider, locale, owner = row
        if (provider, locale) != ("b", "C.UTF-8"):
            lines.append(
                f"PERINGATAN database {name}: collation {provider}/{locale} (disarankan builtin C.UTF-8); "
                "tidak diubah otomatis"
            )
        if owner != "atlas_owner":
            conn.execute(sql.SQL("ALTER DATABASE {} OWNER TO atlas_owner").format(ident))
        lines.append(f"database {name}: sudah ada (owner atlas_owner)")
    conn.execute(sql.SQL("ALTER DATABASE {} SET timezone = 'Asia/Jakarta'").format(ident))
    conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(ident))
    conn.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            ident, sql.SQL(", ").join(sql.Identifier(r) for r in LOGIN_ROLES)
        )
    )
    conn.execute(sql.SQL("GRANT TEMPORARY ON DATABASE {} TO atlas_app").format(ident))
    return lines


def ensure_passwords(env_file: Path) -> list[str]:
    """Isi ATLAS_DB_PASSWORD_* yang kosong di .env dengan nilai acak. Nilai yang sudah ada tidak diubah."""
    if not env_file.exists():
        example = REPO_ROOT / ".env.example"
        env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    lines = env_file.read_text(encoding="utf-8").splitlines()
    keys = [r.env_key for r in ROLES if r.env_key]
    generated = []
    for key in keys:
        idx = next((i for i, line in enumerate(lines) if line.split("=", 1)[0].strip() == key), None)
        current = lines[idx].split("=", 1)[1].strip() if idx is not None and "=" in lines[idx] else ""
        if current:
            continue
        value = f"{key}={secrets.token_urlsafe(24)}"
        if idx is None:
            lines.append(value)
        else:
            lines[idx] = value
        generated.append(key)
    if generated:
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return generated


if __name__ == "__main__":
    sys.exit(main())
