"""Konfigurasi ATLAS: dibaca dari environment + file ``.env``, divalidasi sekali saat start.

Aturan (plan 04 §1): tidak ada path, URL, token, atau password di kode — semuanya lewat sini.
Nilai environment proses menimpa nilai di ``.env``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values

from atlas.core.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENTS = ("dev", "staging", "prod")
LOG_LEVELS = ("debug", "info", "warning", "error")
DbRole = Literal["web", "app", "migrator", "readonly"]


class Secret:
    """Pembungkus nilai rahasia: tidak pernah tampil lewat ``repr``/``str``/log."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret('***')" if self._value else "Secret('')"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)


@dataclass(frozen=True)
class DbCredentials:
    user: str
    password: Secret


@dataclass(frozen=True)
class NbuMaster:
    key: str  # tbs | bsd | brn
    name: str  # TBS | BSD | BRN (sama dengan kolom "Master" di JSON V4)
    base_url: str
    token: Secret


NBU_DEFAULT_URLS = {
    "tbs": "https://tbsnbuvpapp1/netbackup",
    "bsd": "https://bsdnbuvpapp1.telkomsel.co.id/netbackup",
    "brn": "https://brnnbuvpapp1.telkomsel.co.id/netbackup",
}


@dataclass(frozen=True)
class Settings:
    env: str
    log_level: str
    log_dir: Path
    db_host: str
    db_port: int
    db_name: str
    db_web: DbCredentials
    db_app: DbCredentials
    db_migrator: DbCredentials
    db_readonly: DbCredentials
    db_pool_min: int
    db_pool_max: int
    db_connect_timeout_s: int
    db_statement_timeout_ms: int
    db_slow_query_ms: int
    allow_live_nbu: bool
    nbu_masters: tuple[NbuMaster, ...] = ()
    nbu_timeout_s: int = 20
    nbu_min_interval_ms: int = 200
    nbu_max_retries: int = 3
    capacity_json_dir: Path | None = None
    cache_dir: Path = REPO_ROOT / "cache"
    policy_cache_path: Path | None = None

    def db_credentials(self, role: DbRole) -> DbCredentials:
        return {
            "web": self.db_web,
            "app": self.db_app,
            "migrator": self.db_migrator,
            "readonly": self.db_readonly,
        }[role]

    def db_conninfo(self, role: DbRole, application_name: str) -> str:
        """String koneksi libpq. Hanya untuk diteruskan ke driver — jangan pernah di-log."""
        from psycopg.conninfo import make_conninfo

        cred = self.db_credentials(role)
        return make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=cred.user,
            password=cred.password.get() or None,
            connect_timeout=self.db_connect_timeout_s,
            application_name=application_name,
        )

    def db_target(self, role: DbRole) -> dict[str, object]:
        """Identitas koneksi yang aman untuk log/audit (tanpa password)."""
        return {
            "host": self.db_host,
            "port": self.db_port,
            "database": self.db_name,
            "user": self.db_credentials(role).user,
        }

    def secret_values(self) -> list[str]:
        """Semua nilai rahasia yang aktif — diserahkan ke filter secret di logging."""
        creds = (self.db_web, self.db_app, self.db_migrator, self.db_readonly)
        values = [c.password.get() for c in creds if c.password]
        return values + [m.token.get() for m in self.nbu_masters if m.token]


# ---------------------------------------------------------------------------- loader


def load_settings(env_file: Path | None = None, environ: Mapping[str, str] | None = None) -> Settings:
    """Baca & validasi konfigurasi. Semua kesalahan dikumpulkan lalu dilaporkan sekaligus.

    ``environ`` diberikan oleh test agar tidak bergantung pada environment mesin; jika diberikan,
    file ``.env`` hanya dibaca bila ``env_file`` juga diberikan secara eksplisit.
    """
    values: dict[str, str] = {}
    if environ is None:
        path = env_file or REPO_ROOT / ".env"
        if path.is_file():
            values.update({k: v for k, v in dotenv_values(path).items() if v is not None})
        values.update(os.environ)
    else:
        if env_file is not None:
            values.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
        values.update(environ)

    reader = _Reader(values)
    settings = Settings(
        env=reader.choice("ATLAS_ENV", ENVIRONMENTS, default="dev"),
        log_level=reader.choice("ATLAS_LOG_LEVEL", LOG_LEVELS, default="info"),
        log_dir=reader.path("ATLAS_LOG_DIR", default="logs"),
        db_host=reader.text("ATLAS_DB_HOST", default="localhost"),
        db_port=reader.integer("ATLAS_DB_PORT", default=5432, minimum=1, maximum=65535),
        db_name=reader.text("ATLAS_DB_NAME", default="atlas"),
        db_web=DbCredentials(
            reader.text("ATLAS_DB_USER_WEB", default="atlas_web"),
            Secret(reader.text("ATLAS_DB_PASSWORD_WEB", default="")),
        ),
        db_app=DbCredentials(
            reader.text("ATLAS_DB_USER_APP", default="atlas_app"),
            Secret(reader.text("ATLAS_DB_PASSWORD_APP", default="")),
        ),
        db_migrator=DbCredentials(
            reader.text("ATLAS_DB_USER_MIGRATOR", default="atlas_migrator"),
            Secret(reader.text("ATLAS_DB_PASSWORD_MIGRATOR", default="")),
        ),
        db_readonly=DbCredentials(
            reader.text("ATLAS_DB_USER_READONLY", default="atlas_readonly"),
            Secret(reader.text("ATLAS_DB_PASSWORD_READONLY", default="")),
        ),
        db_pool_min=reader.integer("ATLAS_DB_POOL_MIN", default=2, minimum=1, maximum=20),
        db_pool_max=reader.integer("ATLAS_DB_POOL_MAX", default=5, minimum=1, maximum=50),
        db_connect_timeout_s=reader.integer("ATLAS_DB_CONNECT_TIMEOUT_S", default=5, minimum=1, maximum=60),
        db_statement_timeout_ms=reader.integer(
            "ATLAS_DB_STATEMENT_TIMEOUT_MS", default=15000, minimum=100, maximum=600_000
        ),
        db_slow_query_ms=reader.integer("ATLAS_DB_SLOW_QUERY_MS", default=500, minimum=1, maximum=600_000),
        allow_live_nbu=reader.boolean("ATLAS_ALLOW_LIVE_NBU", default=False),
        nbu_masters=tuple(
            NbuMaster(
                key,
                key.upper(),
                reader.text(f"NBU_{key.upper()}_URL", default=url).rstrip("/"),
                Secret(reader.text(f"NBU_{key.upper()}_TOKEN", default="")),
            )
            for key, url in NBU_DEFAULT_URLS.items()
        ),
        nbu_timeout_s=reader.integer("ATLAS_NBU_TIMEOUT_S", default=20, minimum=1, maximum=300),
        nbu_min_interval_ms=reader.integer(
            "ATLAS_NBU_MIN_INTERVAL_MS", default=200, minimum=0, maximum=10_000
        ),
        nbu_max_retries=reader.integer("ATLAS_NBU_MAX_RETRIES", default=3, minimum=1, maximum=10),
        capacity_json_dir=reader.optional_path("ATLAS_CAPACITY_JSON_DIR"),
        cache_dir=reader.path("ATLAS_CACHE_DIR", default="cache"),
        policy_cache_path=reader.optional_path("ATLAS_POLICY_CACHE"),
    )
    if settings.db_pool_min > settings.db_pool_max:
        reader.errors.append("ATLAS_DB_POOL_MIN tidak boleh lebih besar dari ATLAS_DB_POOL_MAX")
    if settings.env == "prod" and not (settings.db_web.password and settings.db_app.password):
        reader.errors.append("ATLAS_DB_PASSWORD_WEB dan ATLAS_DB_PASSWORD_APP wajib diisi di prod")

    if reader.errors:
        raise ConfigError(
            "Konfigurasi tidak valid: " + "; ".join(reader.errors),
            details={"invalid": reader.errors},
        )
    return settings


class _Reader:
    """Membaca nilai bertipe; error dikumpulkan, bukan langsung dilempar."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self.values = values
        self.errors: list[str] = []

    def _raw(self, key: str) -> str | None:
        raw = self.values.get(key)
        if raw is None or raw.strip() == "":
            return None
        return raw.strip()

    def text(self, key: str, *, default: str) -> str:
        raw = self._raw(key)
        return default if raw is None else raw

    def choice(self, key: str, options: tuple[str, ...], *, default: str) -> str:
        value = self.text(key, default=default).lower()
        if value not in options:
            self.errors.append(f"{key} harus salah satu dari {', '.join(options)} (sekarang: {value!r})")
            return default
        return value

    def integer(self, key: str, *, default: int, minimum: int, maximum: int) -> int:
        raw = self._raw(key)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError:
            self.errors.append(f"{key} harus bilangan bulat (sekarang: {raw!r})")
            return default
        if not minimum <= value <= maximum:
            self.errors.append(f"{key} harus di antara {minimum} dan {maximum} (sekarang: {value})")
            return default
        return value

    def boolean(self, key: str, *, default: bool) -> bool:
        raw = self._raw(key)
        if raw is None:
            return default
        lowered = raw.lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        self.errors.append(f"{key} harus 0 atau 1 (sekarang: {raw!r})")
        return default

    def optional_path(self, key: str) -> Path | None:
        raw = self._raw(key)
        if raw is None:
            return None
        path = Path(raw)
        return path if path.is_absolute() else REPO_ROOT / path

    def path(self, key: str, *, default: str) -> Path:
        path = Path(self.text(key, default=default))
        return path if path.is_absolute() else REPO_ROOT / path
