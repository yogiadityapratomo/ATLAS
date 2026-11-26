"""Import CMDB (plan 04 task 2.4): COPY + diff row_hash; impor ulang tanpa perubahan = 0 penulisan."""

from __future__ import annotations

import json

import pytest
from openpyxl import Workbook

from atlas.collectors.cmdb_import import import_cmdb
from atlas.core.db import Database
from tests.integration.conftest import connect

pytestmark = pytest.mark.integration

HEADER = (
    "Name",
    "IP OAM",
    "IP Service",
    "Apps",
    "PIC",
    "Apps Priority",
    "Prod/Nonprod",
    "VM/Baremetal",
    "Site",
)


def _row(host, app="BILLING", site="TBS", pic="Budi"):
    return (host, "10.1.1.1", "10.2.2.2", app, pic, "P1", "Prod", "VM", site)


def _xlsx(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Master Inventory"
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


BASE = [
    _row("srv-a"),
    _row("srv-b", app="CRM"),
    _row("f0s12", app="OCS", site="TBS"),
    _row("f0s12", app="OCS", site="BSD"),
    _row("srv-c", app="CRM"),
    _row("srv-c", app="CRM"),  # kembar persis
    _row(None),  # tanpa hostname
]


@pytest.fixture
def app_db(clean_db, itest_settings):
    with Database(itest_settings, "app", "cmdb_itest", min_size=1, max_size=2) as db:
        yield db


def _table():
    with connect("readonly") as conn:
        return conn.execute(
            "SELECT hostname, site, occurrences FROM cmdb.server_inventory ORDER BY hostname, site"
        ).fetchall()


def test_first_import_then_reimport_writes_nothing(app_db, tmp_path):
    path = _xlsx(tmp_path / "a.xlsx", BASE)
    first = import_cmdb(app_db, path)
    assert first.status == "success"
    r = first.result
    assert (r.total, r.inserted, r.updated, r.deleted) == (5, 5, 0, 0)
    assert r.details["source_rows"] == 6
    assert r.details["duplicate_rows"] == 1
    assert r.details["skipped_no_hostname"] == 1
    assert ("srv-c", "TBS", 2) in _table()

    with connect("readonly") as conn:
        before = conn.execute("SELECT xmin::text, id FROM cmdb.server_inventory ORDER BY id").fetchall()
    second = import_cmdb(app_db, path)
    r2 = second.result
    assert (r2.inserted, r2.updated, r2.deleted) == (0, 0, 0)
    with connect("readonly") as conn:
        after = conn.execute("SELECT xmin::text, id FROM cmdb.server_inventory ORDER BY id").fetchall()
    assert before == after  # tidak ada satu baris pun yang ditulis ulang


def test_changes_are_applied_as_minimal_diff(app_db, tmp_path):
    import_cmdb(app_db, _xlsx(tmp_path / "a.xlsx", BASE))
    changed = [
        _row("srv-a", pic="Ani"),  # isi berubah → 1 baru + 1 hapus
        _row("srv-b", app="CRM"),
        _row("f0s12", app="OCS", site="TBS"),
        _row("f0s12", app="OCS", site="BSD"),
        _row("srv-c", app="CRM"),  # dari 2 kembar menjadi 1 → update occurrences
        _row("srv-d", app="NEW"),  # baru
    ]
    outcome = import_cmdb(app_db, _xlsx(tmp_path / "b.xlsx", changed))
    r = outcome.result
    assert (r.inserted, r.updated, r.deleted) == (2, 1, 1)
    table = _table()
    assert ("srv-c", "TBS", 1) in table
    assert len(table) == 6
    with connect("readonly") as conn:
        pic = conn.execute("SELECT pic FROM cmdb.server_inventory WHERE hostname = 'srv-a'").fetchall()
    assert pic == [("Ani",)]


def test_report_views_aggregate_per_host_and_app(app_db, tmp_path):
    import_cmdb(app_db, _xlsx(tmp_path / "a.xlsx", BASE))
    with connect("web") as conn:
        host = conn.execute(
            "SELECT hostname, app_names, sites, source_rows FROM report.cmdb_host"
            " WHERE hostname_norm = 'f0s12'"
        ).fetchone()
        apps = dict(conn.execute("SELECT app_name, host_count FROM report.app_list").fetchall())
    assert host == ("f0s12", "OCS", "BSD, TBS", 2)
    assert apps == {"BILLING": 1, "CRM": 2, "OCS": 1}


def test_shrink_guard_rejects_suspicious_file(app_db, tmp_path):
    import_cmdb(app_db, _xlsx(tmp_path / "a.xlsx", BASE))
    small = _xlsx(tmp_path / "small.xlsx", [_row("srv-a")])
    outcome = import_cmdb(app_db, small)
    assert outcome.status == "failed"
    assert len(_table()) == 5  # data lama utuh
    assert import_cmdb(app_db, small, allow_shrink=True).status == "success"
    assert len(_table()) == 1


def test_notify_sent_only_when_data_changed(app_db, tmp_path):
    path = _xlsx(tmp_path / "a.xlsx", BASE)
    with connect("readonly", autocommit=True) as listener:
        listener.execute("LISTEN atlas_data_changed")
        first = import_cmdb(app_db, path)
        notes = list(listener.notifies(timeout=2, stop_after=1))
        assert [json.loads(n.payload) for n in notes] == [{"source": "cmdb", "run_id": first.run_id}]
        import_cmdb(app_db, path)  # tanpa perubahan
        assert list(listener.notifies(timeout=1, stop_after=1)) == []
