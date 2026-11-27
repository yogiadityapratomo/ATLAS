"""``policy_cache.json`` → baris backup inventory (satu baris per policy × client × schedule).

Logika **sama dengan pencarian bot** (``check_v2.py``), yang disetujui sebagai acuan (design 03 §2):

* ``dayOfWeek`` NetBackup: **1 = Minggu … 7 = Sabtu** (terbukti dari audit log; loader ``dbbackup``
  lama salah memakai 1 = Senin).
* ``schedule_days`` diisi: satu hari, atau rentang "Senin - Jumat" dari hari minimum s/d maksimum.
* ``start_times`` hanya untuk hari dengan ``startSeconds > 0``; bila tidak ada, semua hari di window.
  Schedule tanpa start window dilewati (sama dengan bot).
* Hanya policy aktif; policy bernama "onetime"/"manual" dilewati.
* Retensi: SLP → operasi ke-2 di ``slps``; non-SLP → copy pertama schedule.
* Master: ``source`` di cache; bila tidak ada, ditebak dari nama storage (bsd/tbs).
* **Beda dari bot (perlu konfirmasi owner):** policy dengan ``storage = null`` (26 policy aktif di cache
  2026-11-20, mayoritas tipe Deployment) membuat bot error dan policy itu hilang diam-diam dari report.
  Di sini policy tersebut tetap ditampilkan dengan storage "-".

Kontrak ``policy_cache.json`` (path & struktur) **tidak diubah** — hanya dibaca.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

DAY_MAP = {1: "Minggu", 2: "Senin", 3: "Selasa", 4: "Rabu", 5: "Kamis", 6: "Jumat", 7: "Sabtu"}
DEFAULT_CLIENT = {"hostName": "-", "OS": "-", "hardware": "-"}
FIELDS = (
    "master_server",
    "policy_name",
    "policy_type",
    "client_host",
    "client_os",
    "client_hw",
    "storage",
    "volume_pool",
    "backup_selections",
    "schedule_name",
    "schedule_days",
    "backup_type",
    "start_times",
    "retention_period",
)
KEY_FIELDS = ("master_server", "policy_name", "client_host", "schedule_name")


@dataclass(frozen=True)
class InventoryRow:
    values: tuple[str, ...]  # urutan FIELDS

    def get(self, field: str) -> str:
        return self.values[FIELDS.index(field)]

    @property
    def key(self) -> tuple[str, str, str, str]:
        master, policy, host, schedule = (self.get(f) for f in KEY_FIELDS)
        return (master, policy, host.strip().lower(), schedule)

    @property
    def row_hash(self) -> str:
        payload = "\x1f".join(self.values)
        return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()

    def as_dict(self) -> dict[str, str]:
        return dict(zip(FIELDS, self.values, strict=True))


def seconds_to_hhmm(seconds: int) -> str:
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours:02d}:{minutes:02d}"


def day_name(day: Any) -> str:
    return DAY_MAP.get(day, f"Hari-{day}")


def detect_master_server(storage: str) -> str:
    lowered = storage.lower()
    if "bsd" in lowered:
        return "bsdnbuvpapp1"
    if "tbs" in lowered:
        return "tbsnbuvpapp1"
    return "Unknown"


def slp_retention(storage: str, slps: Mapping[str, Any]) -> str:
    data = slps.get(storage)
    if not data:
        return ""
    ops = data.get("data", {}).get("attributes", {}).get("operationList", [])
    if len(ops) < 2:
        return ""
    period = ops[1].get("retentionPeriod")
    if not period:
        return ""
    value = period.get("value")
    unit = period.get("unit", "").capitalize().rstrip("s")
    if value and unit:
        return f"{value} {unit}{'s' if value > 1 else ''}"
    return ""


def schedule_retention(schedule: Mapping[str, Any]) -> str:
    copies = schedule.get("backupCopies", {}).get("copies", [])
    if not copies:
        return ""
    period = copies[0].get("retentionPeriod", {})
    value = period.get("value")
    unit = period.get("unit", "").capitalize().rstrip("s")
    return f"{value} {unit}s" if value and unit else ""


def schedule_window(schedule: Mapping[str, Any]) -> tuple[str, str] | None:
    """(schedule_days, start_times) atau ``None`` bila schedule tidak punya start window."""
    window = schedule.get("startWindow", [])
    valid = [w.get("dayOfWeek") for w in window if w.get("startSeconds", 0) > 0]
    if not valid:
        valid = [w.get("dayOfWeek") for w in window]
    if not valid:
        return None
    lo, hi = min(valid), max(valid)
    days = day_name(lo) if lo == hi else f"{DAY_MAP.get(lo)} - {DAY_MAP.get(hi)}"
    starts = [
        f"{day_name(w.get('dayOfWeek'))}: {seconds_to_hhmm(w.get('startSeconds', 0))}"
        for w in window
        if w.get("dayOfWeek") in valid
    ]
    return days, "; ".join(starts)


def parse_policies(cache: Mapping[str, Any]) -> Iterator[InventoryRow]:
    slps = cache.get("slps", {}) or {}
    for item in cache.get("policies", []) or []:
        policy = item["data"]["attributes"]["policy"]
        attrs = policy.get("policyAttributes", {})
        if not attrs.get("active", False):
            continue
        name = policy.get("policyName", "-")
        if "onetime" in name.lower() or "manual" in name.lower():
            continue
        storage = attrs.get("storage") or "-"
        selections = ", ".join(policy.get("backupSelections", {}).get("selections", [])) or "-"
        master = item.get("source") or detect_master_server(storage)
        retention_slp = slp_retention(storage, slps) if attrs.get("storageIsSLP", False) else None
        for client in policy.get("clients", []) or [DEFAULT_CLIENT]:
            for schedule in policy.get("schedules", []):
                window = schedule_window(schedule)
                if window is None:
                    continue
                days, starts = window
                yield InventoryRow(
                    tuple(
                        str(v)
                        for v in (
                            master,
                            name,
                            policy.get("policyType") or "-",
                            (client.get("hostName") or "-").lower(),
                            client.get("OS") or "-",
                            client.get("hardware") or "-",
                            storage,
                            attrs.get("volumePool") or "-",
                            selections,
                            schedule.get("scheduleName") or "-",
                            days,
                            schedule.get("backupType") or "-",
                            starts,
                            retention_slp if retention_slp is not None else schedule_retention(schedule),
                        )
                    )
                )


@dataclass
class ParsedInventory:
    rows: list[InventoryRow]
    duplicates: int
    policies: int


def build_inventory(cache: Mapping[str, Any]) -> ParsedInventory:
    """Parse + buang baris berkunci sama (master, policy, host, schedule) — baris pertama dipakai."""
    seen: dict[tuple, InventoryRow] = {}
    duplicates = 0
    for row in parse_policies(cache):
        if row.key in seen:
            duplicates += 1
            continue
        seen[row.key] = row
    return ParsedInventory(list(seen.values()), duplicates, len(cache.get("policies", []) or []))


def search_terms(raw: str | Iterable[str], *, max_terms: int = 500) -> list[str]:
    """Input pencarian hostname: dipisah koma/baris/spasi, lowercase, unik, urutan dipertahankan."""
    text = raw if isinstance(raw, str) else "\n".join(raw)
    terms: list[str] = []
    for part in text.replace(",", "\n").replace(";", "\n").split():
        term = part.strip().lower()
        if term and term not in terms:
            terms.append(term)
    return terms[:max_terms]
