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


# ---------------------------------------------------------------- backup inventory

NOT_AVAILABLE_FILL = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
NO_BACKUP_FILL = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")


def inventory_workbook(
    rows: Sequence[dict[str, Any]], columns: Sequence[tuple[str, str]], *, cutoff: str
) -> bytes:
    """Format report "SearchByHostname" bot: baris 1 cut-off (kuning, teks merah), header baris 2,
    baris "Not Available" merah muda, freeze A3, lebar kolom otomatis (maks 50)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Backup Inventory"
    ws.append([f"This data uses the inventory backup cut-off as of {cutoff}"])
    ws["A1"].fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
    ws["A1"].font = Font(color="FF0000", bold=True)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.append([title for _, title in columns])
    for cell in ws[2]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([row.get(key) for key, _ in columns])
        fill = {"not_found": NOT_AVAILABLE_FILL, "no_backup": NO_BACKUP_FILL}.get(row.get("status"))
        if fill:
            for cell in ws[ws.max_row]:
                cell.fill = fill
    for col in ws.iter_cols(min_row=2):
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(width + 2, 50)
    ws.freeze_panes = "A3"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
