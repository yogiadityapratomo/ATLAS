from __future__ import annotations

import pytest
from openpyxl import Workbook

from atlas.core.errors import ValidationError
from atlas.services.cmdb import EXCEL_COLUMNS, build_rows, clean, read_xlsx, row_hash

H = ("Name", "IP OAM", "IP Service", "Apps", "PIC", "Apps Priority", "Prod/Nonprod", "VM/Baremetal", "Site")


def _row(host, app="APP1", site="TBS", ip="10.0.0.1"):
    return (host, ip, None, app, "Budi", "P1", "Prod", "VM", site)


def test_clean_matches_legacy_behaviour():
    assert clean(None) is None
    assert clean("  ") is None
    assert clean("  abc ") == "abc"
    assert clean(10) == "10"


def test_identical_rows_merged_with_occurrences_and_order_kept():
    parsed = build_rows([_row("b"), _row("a"), _row("b"), _row(" b "), _row(None), _row("  ")])
    assert parsed.source_rows == 4
    assert parsed.skipped_no_hostname == 2
    assert parsed.duplicate_rows == 2
    assert [(r.hostname, r.occurrences) for r in parsed.rows] == [("b", 3), ("a", 1)]


def test_same_host_different_site_stays_separate():
    parsed = build_rows([_row("f0s12", site="TBS"), _row("f0s12", site="BSD")])
    assert len(parsed.rows) == 2
    assert parsed.rows[0].row_hash != parsed.rows[1].row_hash


def test_row_hash_is_stable_and_null_differs_from_text():
    assert row_hash(("a", None)) == row_hash(("a", None))
    assert row_hash(("a", None)) != row_hash(("a", ""))
    assert row_hash(("ab", "c")) != row_hash(("a", "bc"))  # pemisah mencegah tabrakan sambungan
    assert len(row_hash(("a",))) == 32


def _xlsx(tmp_path, header, rows, sheet="Master Inventory"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append(r)
    path = tmp_path / "cmdb.xlsx"
    wb.save(path)
    return path


def test_read_xlsx_with_extra_and_reordered_columns(tmp_path):
    header = ("No", *reversed(H))
    rows = [(1, *reversed(_row("host1"))), (2, *reversed(_row("host2")))]
    parsed = read_xlsx(_xlsx(tmp_path, header, rows))
    assert [r.hostname for r in parsed.rows] == ["host1", "host2"]
    assert parsed.rows[0].values == tuple(clean(v) for v in _row("host1"))


def test_read_xlsx_missing_column_and_sheet(tmp_path):
    with pytest.raises(ValidationError, match="kolom tidak ditemukan"):
        read_xlsx(_xlsx(tmp_path, H[:-1], []))
    with pytest.raises(ValidationError, match="sheet"):
        read_xlsx(_xlsx(tmp_path, H, [], sheet="Lain"))
    with pytest.raises(ValidationError, match="tidak ditemukan"):
        read_xlsx(tmp_path / "tidak-ada.xlsx")


def test_excel_mapping_covers_all_columns():
    assert tuple(EXCEL_COLUMNS) == H
