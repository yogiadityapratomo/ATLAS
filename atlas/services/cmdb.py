"""CMDB dari Excel OSPLA (sheet "Master Inventory") → baris ``cmdb.server_inventory``.

Normalisasi sama dengan import lama (``scripts/dev/load_server_inventory_xlsx.py``): nilai di-``strip``,
string kosong menjadi NULL, baris tanpa hostname dilewati. Baris yang identik di semua kolom digabung
menjadi satu baris dengan ``occurrences`` = jumlah kemunculannya, sehingga jumlah baris asli tetap
dapat direkonstruksi dan impor ulang file yang sama tidak menulis apa pun.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from atlas.core.errors import ValidationError
from atlas.repositories.cmdb import FIELDS

DEFAULT_SHEET = "Master Inventory"
# kolom Excel -> kolom tabel (urutan = urutan kolom di COPY dan di row_hash)
EXCEL_COLUMNS: dict[str, str] = {
    "Name": "hostname",
    "IP OAM": "ip_oam",
    "IP Service": "ip_service",
    "Apps": "app_name",
    "PIC": "pic",
    "Apps Priority": "app_priority",
    "Prod/Nonprod": "environment",
    "VM/Baremetal": "vm_baremetal",
    "Site": "site",
}
assert tuple(EXCEL_COLUMNS.values()) == FIELDS, "pemetaan Excel harus mengikuti urutan kolom tabel"  # noqa: S101
_SEP = "\x1f"
_NULL = "\x00"


@dataclass(frozen=True)
class CmdbRow:
    values: tuple[str | None, ...]  # urutan FIELDS
    occurrences: int
    row_hash: str

    @property
    def hostname(self) -> str:
        return self.values[0] or ""

    def as_db_row(self) -> tuple[str, int, tuple[str | None, ...]]:
        return (self.row_hash, self.occurrences, self.values)


@dataclass
class ParsedCmdb:
    rows: list[CmdbRow] = field(default_factory=list)
    source_rows: int = 0  # baris data dengan hostname
    skipped_no_hostname: int = 0

    @property
    def duplicate_rows(self) -> int:
        return self.source_rows - len(self.rows)


def clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def row_hash(values: Sequence[str | None]) -> str:
    """md5 isi baris (deteksi perubahan, bukan keamanan). NULL dibedakan dari string kosong."""
    payload = _SEP.join(_NULL if v is None else v for v in values)
    return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def build_rows(records: Iterable[Sequence[object]]) -> ParsedCmdb:
    """``records`` = tuple mentah berurutan FIELDS. Gabungkan baris identik, pertahankan urutan pertama."""
    parsed = ParsedCmdb()
    counts: dict[tuple[str | None, ...], int] = {}
    for record in records:
        values = tuple(clean(v) for v in record)
        if len(values) != len(FIELDS):
            raise ValidationError(f"jumlah kolom baris tidak sesuai: {len(values)} (harus {len(FIELDS)})")
        if not values[0]:
            parsed.skipped_no_hostname += 1
            continue
        parsed.source_rows += 1
        counts[values] = counts.get(values, 0) + 1
    parsed.rows = [CmdbRow(values, n, row_hash(values)) for values, n in counts.items()]
    return parsed


def read_xlsx(path: Path, sheet: str = DEFAULT_SHEET) -> ParsedCmdb:
    from openpyxl import load_workbook

    if not path.is_file():
        raise ValidationError(f"file tidak ditemukan: {path}", user_message="File CMDB tidak ditemukan.")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet not in workbook.sheetnames:
            raise ValidationError(
                f"sheet {sheet!r} tidak ada (tersedia: {', '.join(workbook.sheetnames)})",
                user_message=f"Sheet '{sheet}' tidak ditemukan di file CMDB.",
            )
        rows = workbook[sheet].iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, ())]
        missing = [c for c in EXCEL_COLUMNS if c not in header]
        if missing:
            raise ValidationError(
                f"kolom tidak ditemukan di sheet {sheet!r}: {missing}",
                user_message="Format file CMDB tidak sesuai (kolom wajib tidak lengkap).",
            )
        index = [header.index(c) for c in EXCEL_COLUMNS]
        return build_rows(tuple(r[i] if i < len(r) else None for i in index) for r in rows)
    finally:
        workbook.close()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
