"""Transformasi kapasitas disk pool & tape library — logika **sama persis** dengan web V4.

Sumber: ``legacy/web-v4/capacity_cache_V2_patched.py`` (``fetch_master``) dan
``legacy/web-v4/netbackup_core.py`` (``build_tape_rows``). Fungsi di sini murni (tanpa HTTP/SQL)
sehingga bisa diuji regresi terhadap keluaran V4.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------- disk pool

DISK_POOL_STYPE = "PureDisk"
EXCLUDED_DISK_POOL_PARTS = ("brnnbupapp1", "brnnbupapp2", "brnnbupapp3", "nbubrnlpapp1")
DISK_KEYS = ("Site", "Master", "Disk Pool Name", "Usable (TB)", "Available (TB)", "Used (TB)", "Usage (%)")


def b2tb(value: float) -> float:
    return round(value / (1024**4), 2)


def disk_pool_rows(master_name: str, items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Item mentah ``/storage/disk-pools`` → baris V4 (hanya PureDisk, tanpa pool yang dikecualikan)."""
    out = []
    for item in items:
        a = item["attributes"]
        if a.get("sType") != DISK_POOL_STYPE:
            continue
        usable = a.get("usableSizeBytes", 0)
        avail = a.get("availableSpaceBytes", 0)
        used = a.get("usedCapacityBytes", 0)
        pct = round((used / usable) * 100, 2) if usable else 0
        site = master_name
        servers = item.get("relationships", {}).get("storageServers", {}).get("data", [])
        if servers:
            sid = servers[0].get("id", "")
            if ":" in sid:
                host = sid.split(":", 1)[1].split(".", 1)[0]
                site = host[:3].upper()
        name = a.get("name", "")
        if any(x in name for x in EXCLUDED_DISK_POOL_PARTS):
            continue
        out.append(
            {
                "Site": site,
                "Master": master_name,
                "Disk Pool Name": a.get("name"),
                "Usable (TB)": b2tb(usable),
                "Available (TB)": b2tb(avail),
                "Used (TB)": b2tb(used),
                "Usage (%)": pct,
            }
        )
    return out


def sort_disk_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda x: (x["Master"], x["Disk Pool Name"]))


# ---------------------------------------------------------------- tape library

ROBOT_SITE_MAP = {"tbs": {1: "BRN", 2: "TBS"}, "bsd": {0: "BSD"}, "brn": {0: "BRN", 1: "BRN"}}
TAPE_LIBRARY_INFO = {
    "BRN": {"ip": "10.2.119.203", "serial_number": "78BA713", "storage_name": "brn02_ts4500"},
    "TBS": {"ip": "10.2.245.104", "serial_number": "78BA712", "storage_name": "tbs03_ts4500"},
    "BSD": {"ip": "10.52.140.6", "serial_number": "78DD440", "storage_name": "bsd01_ts4500"},
}
TAPE_TYPE_SIZE_TB = {"L8": 12, "L9": 18}
TAPE_TYPE_LABEL = {"L8": "IBM (LTO8)", "L9": "IBM (LTO9)"}
TAPE_KEYS = (
    "Site",
    "IP",
    "Brand",
    "Type",
    "Model",
    "Serial Number",
    "Storage Name",
    "Domain",
    "Type Tape",
    "Total Tape (Qty)",
    "Tape Used (Qty)",
    "Tape Free (Qty)",
    "Raw Capacity (TB)",
    "Used Capacity (TB)",
    "Tape Used %",
    "Tape Free %",
)


def kb_to_tb(kb: float | None) -> float:
    return (kb or 0) / (1024**3)


def build_tape_rows(tape_items_by_master: Mapping[str, Iterable[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """``{master_key: [atribut tape mentah]}`` → baris tabel per site & tipe tape (robotNumber → site)."""
    site_groups: dict[str, list] = defaultdict(list)
    for key, items in tape_items_by_master.items():
        robot_map = ROBOT_SITE_MAP.get(key, {})
        for a in items:
            robot_no = (a.get("robot") or {}).get("robotNumber")
            site = robot_map.get(robot_no)
            if site is None:
                continue
            site_groups[site].append(a)

    rows = []
    for site in sorted(site_groups):
        by_type: dict[str, list] = defaultdict(list)
        for a in site_groups[site]:
            barcode = a.get("barcode") or ""
            by_type[barcode[-2:].upper()].append(a)
        info = TAPE_LIBRARY_INFO.get(site, {})
        for suffix in sorted(by_type):
            tapes = by_type[suffix]
            size_tb = TAPE_TYPE_SIZE_TB.get(suffix, 0)
            total_qty = len(tapes)
            used_qty = sum(1 for t in tapes if (t.get("kiloBytes") or 0) > 0)
            used_pct = round((used_qty / total_qty) * 100, 2) if total_qty else 0
            rows.append(
                {
                    "Site": site,
                    "IP": info.get("ip", ""),
                    "Brand": "IBM",
                    "Type": "Tape Library",
                    "Model": "TS4500",
                    "Serial Number": info.get("serial_number", ""),
                    "Storage Name": info.get("storage_name", ""),
                    "Domain": "Legacy",
                    "Type Tape": TAPE_TYPE_LABEL.get(suffix, f"Unknown ({suffix})"),
                    "Total Tape (Qty)": total_qty,
                    "Tape Used (Qty)": used_qty,
                    "Tape Free (Qty)": total_qty - used_qty,
                    "Raw Capacity (TB)": round(size_tb * total_qty, 2),
                    "Used Capacity (TB)": round(sum(kb_to_tb(t.get("kiloBytes")) for t in tapes), 2),
                    "Tape Used %": used_pct,
                    "Tape Free %": round(100 - used_pct, 2) if total_qty else 0,
                }
            )
    return rows


# ---------------------------------------------------------------- DB ⇄ JSON V4


def disk_row_to_db(row: Mapping[str, Any]) -> tuple:
    return tuple(row[k] for k in DISK_KEYS)


def tape_row_to_db(row: Mapping[str, Any]) -> tuple:
    return tuple(row[k] for k in TAPE_KEYS)


def _num(value: Any) -> float | int:
    """numeric DB → float JSON; nilai bulat yang di V4 berupa int (0 pada persen) tetap int."""
    if isinstance(value, Decimal):
        value = float(value)
    return value


def _json_number(value: Any, *, integral_as_int: bool) -> float | int:
    value = _num(value)
    if integral_as_int and isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def disk_row_from_db(values: tuple) -> dict[str, Any]:
    site, master, name, usable, avail, used, pct = values
    usable_f = _num(usable)
    return {
        "Site": site,
        "Master": master,
        "Disk Pool Name": name,
        "Usable (TB)": usable_f,
        "Available (TB)": _num(avail),
        "Used (TB)": _num(used),
        # V4: pct = 0 (int) bila usable = 0
        "Usage (%)": 0 if not usable_f else _num(pct),
    }


def tape_row_from_db(values: tuple) -> dict[str, Any]:
    row = dict(zip(TAPE_KEYS, values, strict=True))
    total = row["Total Tape (Qty)"]
    row["Raw Capacity (TB)"] = _json_number(row["Raw Capacity (TB)"], integral_as_int=True)  # V4: int
    row["Used Capacity (TB)"] = _num(row["Used Capacity (TB)"])
    row["Tape Used %"] = 0 if not total else _num(row["Tape Used %"])
    row["Tape Free %"] = 0 if not total else _num(row["Tape Free %"])
    return row


def summary_by_site(disk_rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, float, float, float, float]]:
    """(site, total, used, free, pct) — sama dengan sheet "Disk Pool Summary" V4."""
    grp: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0])
    for r in disk_rows:
        grp[r["Site"]][0] += r["Usable (TB)"]
        grp[r["Site"]][1] += r["Used (TB)"]
        grp[r["Site"]][2] += r["Available (TB)"]
    out = []
    for site in sorted(grp):
        total, used, free = grp[site]
        pct = round((used / total) * 100, 2) if total else 0
        out.append((site, round(total, 2), round(used, 2), round(free, 2), pct))
    return out
