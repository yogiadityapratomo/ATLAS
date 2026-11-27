"""Export Excel. Kapasitas: 3 sheet dengan format sama persis dengan ``capacity_report.xlsx`` V4."""

from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from atlas.services.capacity import DISK_KEYS, TAPE_KEYS, summary_by_site

HEADER_FILL = PatternFill("solid", start_color="4F81BD")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def shift_title(now: datetime) -> str:
    """Judul sheet ringkasan V4: Shift 1 = 08:00–15:00, Shift 2 = 15:01–23:00, selain itu Shift 3."""
    hm = now.hour * 100 + now.minute
    shift = 1 if 800 <= hm <= 1500 else 2 if 1501 <= hm <= 2300 else 3
    return f"Shift {shift} {now.strftime('%d %B %Y')}"


def _header(ws, row: int, headers: Sequence[str]) -> None:
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=row, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL


def capacity_workbook(
    disk_rows: Sequence[dict[str, Any]], tape_rows: Sequence[dict[str, Any]], *, now: datetime
) -> bytes:
    wb = Workbook()

    ws = wb.active
    ws.title = "Disk Pool Detail"
    _header(ws, 1, DISK_KEYS)
    for r in disk_rows:
        ws.append([r[h] for h in DISK_KEYS])
    ws.freeze_panes = "A2"
    if disk_rows:
        ws.auto_filter.ref = ws.dimensions

    sw = wb.create_sheet("Disk Pool Summary")
    sw.merge_cells("A1:E1")
    title = sw["A1"]
    title.value = shift_title(now)
    title.font = Font(bold=True, size=14)
    title.alignment = Alignment(horizontal="center")
    _header(
        sw,
        2,
        ["Site", "Total Capacity (TB)", "Used Capacity (TB)", "Free Capacity (TB)", "Used Percentage (%)"],
    )
    for row in summary_by_site(disk_rows):
        sw.append(list(row))

    tw = wb.create_sheet("Tape Library")
    _header(tw, 1, ["No", *TAPE_KEYS])
    for idx, r in enumerate(tape_rows, 1):
        tw.append([idx] + [r[h] for h in TAPE_KEYS])
    tw.freeze_panes = "A2"
    if tape_rows:
        tw.auto_filter.ref = tw.dimensions

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
