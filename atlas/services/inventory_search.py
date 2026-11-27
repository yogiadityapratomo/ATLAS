"""Validasi input pencarian Backup Inventory & bentuk baris hasil (design 03 §5–6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from atlas.core.errors import ValidationError
from atlas.services.policy_parser import search_terms

MAX_HOSTNAMES = 500
MAX_TERM_LENGTH = 255
MAX_APP_LENGTH = 200
DEFAULT_LIMIT = 1000
MAX_LIMIT = 2000
EXPORT_LIMIT = 20_000
NOT_AVAILABLE = "Not Available"
NO_BACKUP = "Tidak ada backup"

# kolom tabel/Excel: (kunci, judul). Urutan = report Search bot + kolom CMDB setelah hostname.
COLUMNS = (
    ("client_host", "Client Host"),
    ("app_names", "Aplikasi"),
    ("pics", "PIC"),
    ("environments", "Prod/Nonprod"),
    ("policy_name", "Policy Name"),
    ("policy_type", "Policy Type"),
    ("storage", "Storage"),
    ("volume_pool", "Volume Pool"),
    ("backup_selections", "Backup Selections"),
    ("client_os", "Client OS"),
    ("client_hw", "Client HW"),
    ("schedule_name", "Schedule Name"),
    ("schedule_days", "Schedule Days"),
    ("backup_type", "Backup Type"),
    ("start_times", "Start Times"),
    ("retention_period", "Retention Period"),
    ("master_server", "Master Server"),
    ("sites", "Site (CMDB)"),
)
BACKUP_KEYS = tuple(
    k for k, _ in COLUMNS if k not in ("client_host", "app_names", "pics", "environments", "sites")
)


@dataclass(frozen=True)
class SearchRequest:
    mode: str  # hostname | app
    terms: tuple[str, ...]
    app: str | None
    app_exact: bool
    master: str | None
    policy_type: str | None
    limit: int
    offset: int


def parse_request(
    *,
    hostnames: str | None,
    app: str | None,
    app_exact: bool = False,
    master: str | None = None,
    policy_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    max_limit: int = MAX_LIMIT,
) -> SearchRequest:
    hostnames = (hostnames or "").strip()
    app = (app or "").strip()
    if bool(hostnames) == bool(app):
        raise ValidationError(
            "isi salah satu: hostnames atau app",
            user_message="Isi salah satu: daftar hostname atau nama aplikasi.",
        )
    limit = DEFAULT_LIMIT if limit is None else limit
    offset = 0 if offset is None else offset
    if not 1 <= limit <= max_limit or offset < 0:
        raise ValidationError(
            f"limit 1..{max_limit}, offset >= 0", user_message="Parameter halaman tidak valid."
        )
    terms: tuple[str, ...] = ()
    if hostnames:
        all_terms = search_terms(hostnames, max_terms=MAX_HOSTNAMES + 1)
        if len(all_terms) > MAX_HOSTNAMES:
            raise ValidationError(
                f"lebih dari {MAX_HOSTNAMES} hostname",
                user_message=f"Maksimal {MAX_HOSTNAMES} hostname per pencarian.",
            )
        if any(len(t) > MAX_TERM_LENGTH for t in all_terms):
            raise ValidationError(
                "hostname terlalu panjang", user_message="Ada hostname yang terlalu panjang."
            )
        if any(len(t) < 2 for t in all_terms):
            raise ValidationError(
                "hostname < 2 karakter",
                user_message="Setiap hostname minimal 2 karakter (pencarian sebagian).",
            )
        terms = tuple(all_terms)
    if app and len(app) > MAX_APP_LENGTH:
        raise ValidationError("nama aplikasi terlalu panjang", user_message="Nama aplikasi terlalu panjang.")
    return SearchRequest(
        mode="hostname" if terms else "app",
        terms=terms,
        app=app or None,
        app_exact=app_exact,
        master=(master or "").strip() or None,
        policy_type=(policy_type or "").strip() or None,
        limit=limit,
        offset=offset,
    )


def with_status(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        row["status"] = "ok"
    return rows


def not_found_rows(terms: list[str]) -> list[dict[str, Any]]:
    """Sama dengan report bot: setiap kolom diisi "Not Available"."""
    return [
        {**{k: NOT_AVAILABLE for k, _ in COLUMNS}, "client_host": t, "app_names": None, "status": "not_found"}
        for t in terms
    ]


def no_backup_rows(hosts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**{k: None for k, _ in COLUMNS}, **h, "policy_name": NO_BACKUP, "status": "no_backup"} for h in hosts
    ]
