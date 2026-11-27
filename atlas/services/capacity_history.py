"""Historical Capacity — validasi parameter, rentang default, dan label periode (Bahasa Indonesia).

Nilai satu periode = posisi **akhir periode** tiap appliance (hari terakhir yang ada datanya di periode
itu), lalu dijumlahkan per grup; usage % grup = total used / total usable. Puncak (max usage %) dalam
periode ikut disajikan untuk melihat lonjakan yang tidak terlihat di akhir periode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from atlas.core.errors import ValidationError

PERIODS = ("day", "week", "month", "quarter", "semester", "year")
GROUPS = ("site", "master", "appliance")
# rentang default (hari ke belakang) & batas maksimum per periode
DEFAULT_LOOKBACK = {
    "day": 30,
    "week": 26 * 7,
    "month": 365,
    "quarter": 2 * 365,
    "semester": 3 * 365,
    "year": 5 * 365,
}
MAX_SPAN = {
    "day": 400,
    "week": 3 * 365,
    "month": 6 * 365,
    "quarter": 10 * 365,
    "semester": 10 * 365,
    "year": 20 * 365,
}
MAX_SERIES = 8  # aturan grafik: > 8 garis tidak terbaca → pilih appliance lebih sedikit
MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
PERIOD_LABEL = {
    "day": "Harian",
    "week": "Mingguan",
    "month": "Bulanan",
    "quarter": "Kuartal",
    "semester": "Semester",
    "year": "Tahunan",
}


@dataclass(frozen=True)
class HistoryRequest:
    period: str
    group: str
    start: date
    end: date
    sites: tuple[str, ...]
    masters: tuple[str, ...]
    appliances: tuple[tuple[str, str], ...]  # (master, disk_pool_name)


def _split(raw: str | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(p.strip() for p in (raw or "").split(",") if p.strip()))


def parse_request(
    *,
    today: date,
    period: str = "month",
    group: str = "site",
    start: date | None = None,
    end: date | None = None,
    sites: str | None = None,
    masters: str | None = None,
    appliances: str | None = None,
) -> HistoryRequest:
    if period not in PERIODS:
        raise ValidationError(f"periode tidak dikenal: {period}", user_message="Periode tidak valid.")
    if group not in GROUPS:
        raise ValidationError(f"grouping tidak dikenal: {group}", user_message="Pengelompokan tidak valid.")
    end = min(end or today, today)
    start = start or (end - timedelta(days=DEFAULT_LOOKBACK[period]))
    if start > end:
        raise ValidationError("start > end", user_message="Tanggal awal harus sebelum tanggal akhir.")
    if (end - start).days > MAX_SPAN[period]:
        raise ValidationError(
            "rentang terlalu panjang",
            user_message=f"Rentang terlalu panjang untuk periode {PERIOD_LABEL[period].lower()} "
            f"(maks {MAX_SPAN[period]} hari). Pilih periode yang lebih besar.",
        )
    pairs = []
    for key in _split(appliances):
        master, sep, pool = key.partition("/")
        if not sep or not master or not pool:
            raise ValidationError(
                f"appliance tidak valid: {key}", user_message="Format appliance: MASTER/nama_pool."
            )
        pairs.append((master, pool))
    if group == "appliance" and len(pairs) > MAX_SERIES:
        raise ValidationError(
            "terlalu banyak appliance",
            user_message=f"Pilih maksimal {MAX_SERIES} appliance agar grafik tetap terbaca.",
        )
    return HistoryRequest(period, group, start, end, _split(sites), _split(masters), tuple(pairs))


def bucket_label(period: str, start: date) -> str:
    if period == "day":
        return f"{start.day} {MONTHS[start.month - 1]} {start.year}"
    if period == "week":
        iso = start.isocalendar()
        return f"Mg {iso.week} {iso.year}"
    if period == "month":
        return f"{MONTHS[start.month - 1]} {start.year}"
    if period == "quarter":
        return f"Q{(start.month - 1) // 3 + 1} {start.year}"
    if period == "semester":
        return f"S{1 if start.month <= 6 else 2} {start.year}"
    return str(start.year)


def series_label(group: str, key: str) -> str:
    return key.split("/", 1)[1] if group == "appliance" else key
