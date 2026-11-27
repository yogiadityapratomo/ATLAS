"""Historical Capacity — validasi parameter, rentang default, label periode, dan perbandingan.

* Nilai satu periode = posisi **akhir periode** tiap disk pool (hari terakhir yang ada datanya), dijumlah
  per grup; usage % grup = Σ used / Σ usable. Puncak usage dalam periode ikut disajikan.
* **Appliance** = host NetBackup appliance; disk pool-nya digabung (``capacity.appliance_name``, V008),
  mis. dp_disk_brnnbupapp07 + dp_disk_brnnbupapp7-worm → brnnbupapp7.
* **Perbandingan**: periode berjalan vs periode sebelumnya (hari/minggu/bulan/kuartal/semester/tahun),
  atau tanggal A vs tanggal B. Kenaikan/penurunan dalam TB, persen, dan poin persentase usage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from atlas.core.errors import ValidationError

PERIODS = ("day", "week", "month", "quarter", "semester", "year")
GROUPS = ("site", "master", "appliance")
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
MAX_SERIES = 8  # garis di grafik; tabel & ringkasan memuat semua pilihan
MAX_FILTER = 200
RANGE_TOLERANCE_DAYS = 31  # tanggal A/B tanpa data → pakai hari terakhir yang ada dalam 31 hari sebelumnya
MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
PERIOD_LABEL = {
    "day": "Harian",
    "week": "Mingguan",
    "month": "Bulanan",
    "quarter": "Kuartal",
    "semester": "Semester",
    "year": "Tahunan",
}
COMPARE_LABEL = {
    "day": ("Hari ini", "Kemarin"),
    "week": ("Minggu ini", "Minggu lalu"),
    "month": ("Bulan ini", "Bulan lalu"),
    "quarter": ("Kuartal ini", "Kuartal lalu"),
    "semester": ("Semester ini", "Semester lalu"),
    "year": ("Tahun ini", "Tahun lalu"),
}
_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


@dataclass(frozen=True)
class HistoryRequest:
    period: str
    group: str
    start: date
    end: date
    sites: tuple[str, ...]
    masters: tuple[str, ...]
    appliances: tuple[str, ...]


@dataclass(frozen=True)
class Window:
    label: str
    start: date
    end: date


def _split(raw: str | None, field: str) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(p.strip() for p in (raw or "").split(",") if p.strip()))
    if len(values) > MAX_FILTER or any(not _NAME.match(v) for v in values):
        raise ValidationError(f"filter {field} tidak valid", user_message=f"Filter {field} tidak valid.")
    return values


def _validate(period: str, group: str) -> None:
    if period not in PERIODS:
        raise ValidationError(f"periode tidak dikenal: {period}", user_message="Periode tidak valid.")
    if group not in GROUPS:
        raise ValidationError(f"grouping tidak dikenal: {group}", user_message="Pengelompokan tidak valid.")


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
    _validate(period, group)
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
    return HistoryRequest(
        period,
        group,
        start,
        end,
        _split(sites, "site"),
        _split(masters, "master"),
        tuple(a.lower() for a in _split(appliances, "appliance")),
    )


# ---------------------------------------------------------------- periode


def bucket_start(period: str, day: date) -> date:
    if period == "day":
        return day
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    if period == "quarter":
        return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
    if period == "semester":
        return date(day.year, 1 if day.month <= 6 else 7, 1)
    return date(day.year, 1, 1)


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
    return key


# ---------------------------------------------------------------- perbandingan


def compare_windows(
    *,
    today: date,
    mode: str,
    period: str = "week",
    ref: date | None = None,
    a: date | None = None,
    b: date | None = None,
) -> tuple[Window, Window]:
    """(pembanding/awal, sekarang/akhir)."""
    if mode == "period":
        if period not in PERIODS:
            raise ValidationError(f"periode tidak dikenal: {period}", user_message="Periode tidak valid.")
        ref = min(ref or today, today)
        cur_start = bucket_start(period, ref)
        prev_end = cur_start - timedelta(days=1)
        prev_start = bucket_start(period, prev_end)
        now_label, prev_label = COMPARE_LABEL[period]
        current = Window(f"{now_label} ({bucket_label(period, cur_start)})", cur_start, ref)
        previous = Window(f"{prev_label} ({bucket_label(period, prev_start)})", prev_start, prev_end)
        return previous, current
    if mode == "range":
        if not a or not b:
            raise ValidationError("tanggal A & B wajib", user_message="Isi tanggal awal dan tanggal akhir.")
        if a >= b:
            raise ValidationError("a >= b", user_message="Tanggal awal harus sebelum tanggal akhir.")
        b = min(b, today)
        tol = timedelta(days=RANGE_TOLERANCE_DAYS)
        return (
            Window(bucket_label("day", a), a - tol, a),
            Window(bucket_label("day", b), b - tol, b),
        )
    raise ValidationError(f"mode tidak dikenal: {mode}", user_message="Mode perbandingan tidak valid.")


def _pct_change(old: float, new: float) -> float | None:
    return round((new - old) / old * 100, 2) if old else None


def compare_rows(base: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Gabungkan posisi awal & akhir per grup; hitung kenaikan/penurunan."""
    out = []
    for key in sorted(set(base) | set(current)):
        a, b = base.get(key), current.get(key)
        row: dict[str, Any] = {"key": key, "label": key, "base": a, "current": b}
        if a and b:
            row.update(
                used_delta_tb=round(b["used_tb"] - a["used_tb"], 2),
                used_change_pct=_pct_change(a["used_tb"], b["used_tb"]),
                usable_delta_tb=round(b["usable_tb"] - a["usable_tb"], 2),
                free_delta_tb=round(b["free_tb"] - a["free_tb"], 2),
                usage_delta_pp=round(b["usage_pct"] - a["usage_pct"], 2),
                trend="naik"
                if b["used_tb"] > a["used_tb"]
                else "turun"
                if b["used_tb"] < a["used_tb"]
                else "tetap",
            )
        else:
            row["trend"] = "baru" if b else "hilang"
        out.append(row)
    return out


def totals(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not points:
        return None
    used = round(sum(p["used_tb"] for p in points), 2)
    usable = round(sum(p["usable_tb"] for p in points), 2)
    return {
        "used_tb": used,
        "usable_tb": usable,
        "free_tb": round(sum(p["free_tb"] for p in points), 2),
        "usage_pct": round(used / usable * 100, 2) if usable else 0.0,
        "as_of": max(p["as_of"] for p in points),
    }
