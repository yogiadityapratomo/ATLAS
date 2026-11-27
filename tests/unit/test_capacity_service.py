"""Transformasi kapasitas = V4, dan konversi DB ⇄ JSON tanpa perubahan nilai/tipe."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook

from atlas.core.config import REPO_ROOT
from atlas.services import capacity as cs
from atlas.services.excel_export import capacity_workbook, shift_title

LEGACY_CACHE = REPO_ROOT / "legacy" / "web-v4" / "cache"
TB = 1024**4


def _pool(name, usable, avail, used, stype="PureDisk", server="PureDisk:bsdnbupapp5.telkomsel.co.id"):
    return {
        "attributes": {
            "name": name,
            "sType": stype,
            "usableSizeBytes": usable,
            "availableSpaceBytes": avail,
            "usedCapacityBytes": used,
        },
        "relationships": {"storageServers": {"data": [{"id": server}] if server else []}},
    }


def test_disk_pool_rows_filter_site_and_rounding():
    rows = cs.disk_pool_rows(
        "TBS",
        [
            _pool("dp_disk_bsdnbupapp5", 100 * TB, 40 * TB, 60 * TB),
            _pool("dp_tape_like", 1, 1, 1, stype="MediaServer"),  # bukan PureDisk
            _pool("dp_disk_brnnbupapp1", 1, 1, 1),  # dikecualikan
            _pool("dp_disk_kosong", 0, 0, 0, server=None),
        ],
    )
    assert rows == [
        {
            "Site": "BSD",  # dari hostname storage server, bukan master
            "Master": "TBS",
            "Disk Pool Name": "dp_disk_bsdnbupapp5",
            "Usable (TB)": 100.0,
            "Available (TB)": 40.0,
            "Used (TB)": 60.0,
            "Usage (%)": 60.0,
        },
        {
            "Site": "TBS",
            "Master": "TBS",
            "Disk Pool Name": "dp_disk_kosong",
            "Usable (TB)": 0.0,
            "Available (TB)": 0.0,
            "Used (TB)": 0.0,
            "Usage (%)": 0,
        },
    ]


def test_build_tape_rows_maps_robot_to_site_and_counts():
    tb = 1024**3
    items = {
        "tbs": [
            {"barcode": "A001L8", "robot": {"robotNumber": 1}, "kiloBytes": 2 * tb},  # BRN
            {"barcode": "A002L8", "robot": {"robotNumber": 2}, "kiloBytes": 0},  # TBS
            {"barcode": "A003L9", "robot": {"robotNumber": 2}, "kiloBytes": tb},  # TBS LTO9
            {"barcode": "A004L8", "robot": {"robotNumber": 7}, "kiloBytes": tb},  # robot tak dikenal
        ],
        "bsd": [{"barcode": "B001l9", "robot": {"robotNumber": 0}, "kiloBytes": None}],
    }
    rows = cs.build_tape_rows(items)
    assert [(r["Site"], r["Type Tape"], r["Total Tape (Qty)"], r["Tape Used (Qty)"]) for r in rows] == [
        ("BRN", "IBM (LTO8)", 1, 1),
        ("BSD", "IBM (LTO9)", 1, 0),
        ("TBS", "IBM (LTO8)", 1, 0),
        ("TBS", "IBM (LTO9)", 1, 1),
    ]
    brn = rows[0]
    assert brn["Raw Capacity (TB)"] == 12 and isinstance(brn["Raw Capacity (TB)"], int)
    assert brn["Used Capacity (TB)"] == 2.0
    assert (brn["Tape Used %"], brn["Tape Free %"]) == (100.0, 0.0)
    assert brn["Serial Number"] == "78BA713"


def _through_db(values: tuple) -> tuple:
    """Simulasi round-trip kolom numeric PostgreSQL (Decimal 2 desimal)."""
    return tuple(Decimal(f"{v:.2f}") if isinstance(v, float) else v for v in values)


def test_legacy_cache_round_trips_identically():
    disk = json.loads((LEGACY_CACHE / "capacity_cache.json").read_text(encoding="utf-8"))
    tape = json.loads((LEGACY_CACHE / "tape_cache.json").read_text(encoding="utf-8"))
    disk_back = [cs.disk_row_from_db(_through_db(cs.disk_row_to_db(r))) for r in disk]
    tape_back = [cs.tape_row_from_db(_through_db(cs.tape_row_to_db(r))) for r in tape]
    assert json.dumps(disk_back) == json.dumps(disk)  # nilai, tipe (int vs float), dan urutan kunci
    assert json.dumps(tape_back) == json.dumps(tape)


def test_summary_by_site_matches_v4_excel_logic():
    disk = json.loads((LEGACY_CACHE / "capacity_cache.json").read_text(encoding="utf-8"))
    summary = {row[0]: row for row in cs.summary_by_site(disk)}
    assert set(summary) == {"BRN", "BSD", "TBS"}
    _site, total, used, _free, pct = summary["BRN"]
    assert pct == round(used / total * 100, 2)


def test_shift_title():
    assert shift_title(datetime(2026, 11, 27, 8, 0)) == "Shift 1 27 November 2026"
    assert shift_title(datetime(2026, 11, 27, 15, 1)) == "Shift 2 27 November 2026"
    assert shift_title(datetime(2026, 11, 27, 23, 1)) == "Shift 3 27 November 2026"
    assert shift_title(datetime(2026, 11, 27, 7, 59)) == "Shift 3 27 November 2026"


def test_capacity_workbook_has_v4_sheets_and_headers():
    disk = json.loads((LEGACY_CACHE / "capacity_cache.json").read_text(encoding="utf-8"))
    tape = json.loads((LEGACY_CACHE / "tape_cache.json").read_text(encoding="utf-8"))
    wb = load_workbook(BytesIO(capacity_workbook(disk, tape, now=datetime(2026, 11, 27, 9, 0))))
    assert wb.sheetnames == ["Disk Pool Detail", "Disk Pool Summary", "Tape Library"]
    assert [c.value for c in wb["Disk Pool Detail"][1]] == list(cs.DISK_KEYS)
    assert wb["Disk Pool Detail"].max_row == len(disk) + 1
    assert wb["Disk Pool Summary"]["A1"].value == "Shift 1 27 November 2026"
    assert [c.value for c in wb["Tape Library"][1]] == ["No", *cs.TAPE_KEYS]
    assert wb["Tape Library"].max_row == len(tape) + 1


def test_legacy_cache_files_present():
    assert Path(LEGACY_CACHE / "capacity_cache.json").is_file()
