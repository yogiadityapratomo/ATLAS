"""Backup Inventory end-to-end terhadap DB atlas_test (plan 04 PR-4)."""

from __future__ import annotations

import json
from io import BytesIO

import psycopg
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from atlas.collectors.cmdb_import import import_cmdb
from atlas.collectors.inventory_job import load_inventory
from atlas.core.db import Database
from atlas.web.main import create_app
from tests.integration.conftest import connect

pytestmark = pytest.mark.integration


def _policy(name, hosts, *, storage="stu_disk_tbsnbupapp9", ptype="Standard", source="tbsnbuvpapp1", day=2):
    return {
        "source": source,
        "data": {
            "attributes": {
                "policy": {
                    "policyName": name,
                    "policyType": ptype,
                    "policyAttributes": {"active": True, "storage": storage, "volumePool": "NetBackup"},
                    "backupSelections": {"selections": ["ALL_LOCAL_DRIVES"]},
                    "clients": [{"hostName": h, "OS": "Linux", "hardware": "x86"} for h in hosts],
                    "schedules": [
                        {
                            "scheduleName": "daily",
                            "backupType": "Full Backup",
                            "startWindow": [{"dayOfWeek": day, "startSeconds": 7200}],
                            "backupCopies": {"copies": [{"retentionPeriod": {"value": 2, "unit": "WEEKS"}}]},
                        }
                    ],
                }
            }
        },
    }


POLICIES = [
    _policy("pol_bill", ["billapp1", "billapp10", "billdb_01"]),
    _policy("pol_crm", ["crmapp1"], ptype="VMware", source="bsdnbuvpapp1"),
    _policy("pol_deploy", ["crmapp1"], storage=None, ptype="Deployment"),
]


def _write_cache(path, policies):
    path.write_text(json.dumps({"policies": policies, "slps": {}}), encoding="utf-8")
    return path


def _cmdb(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Master Inventory"
    ws.append(
        [
            "Name",
            "IP OAM",
            "IP Service",
            "Apps",
            "PIC",
            "Apps Priority",
            "Prod/Nonprod",
            "VM/Baremetal",
            "Site",
        ]
    )
    for host, app in [
        ("BILLAPP1", "Billing"),
        ("billapp10", "Billing"),
        ("billnew1", "Billing"),
        ("crmapp1", "CRM"),
    ]:
        ws.append([host, "10.0.0.1", None, app, "Budi", "P1", "Prod", "VM", "TBS"])
    wb.save(path)
    return path


@pytest.fixture
def loaded(clean_db, itest_settings, tmp_path):
    with Database(itest_settings, "app", "inv_itest", min_size=1, max_size=2) as db:
        assert import_cmdb(db, _cmdb(tmp_path / "cmdb.xlsx")).status == "success"
        first = load_inventory(db, _write_cache(tmp_path / "policy_cache.json", POLICIES))
        assert first.status == "success"
        yield db, tmp_path, first


@pytest.fixture
def client(itest_settings):
    with TestClient(create_app(itest_settings, enable_audit=False, enable_listener=False)) as c:
        yield c


def _search(client, **params):
    response = client.get("/api/backup-inventory/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_reload_without_change_writes_nothing_and_change_is_minimal(loaded):
    db, tmp, first = loaded
    assert (first.result.inserted, first.result.total) == (5, 5)
    again = load_inventory(db, tmp / "policy_cache.json")
    assert (again.result.inserted, again.result.updated, again.result.deleted) == (0, 0, 0)
    changed = [
        _policy("pol_bill", ["billapp1", "billapp10"], day=7),
        *POLICIES[1:],
    ]  # hari berubah, 1 host hilang
    third = load_inventory(db, _write_cache(tmp / "policy_cache.json", changed))
    assert (third.result.inserted, third.result.updated, third.result.deleted) == (0, 2, 1)


def test_partial_hostname_search_like_bot_with_not_found(loaded, client):
    body = _search(client, hostnames="billapp1\nghost99")
    assert [r["client_host"] for r in body["items"]] == ["billapp1", "billapp10"]  # cocok sebagian
    assert body["not_found"] == ["ghost99"]
    assert body["items"][0]["schedule_days"] == "Senin"  # dayOfWeek 2 = Senin
    assert body["items"][0]["app_names"] == "Billing"  # gabungan CMDB (beda huruf besar/kecil)
    assert body["cutoff"].endswith("+07:00")


def test_underscore_is_literal_not_wildcard(loaded, client):
    assert [r["client_host"] for r in _search(client, hostnames="db_0")["items"]] == ["billdb_01"]
    assert _search(client, hostnames="app_")["not_found"] == ["app_"]  # "_" bukan wildcard


def test_app_search_lists_hosts_without_backup(loaded, client):
    body = _search(client, app="Billing", app_exact="true")
    assert {r["client_host"] for r in body["items"]} == {"billapp1", "billapp10"}
    assert [r["client_host"] for r in body["no_backup_items"]] == ["billnew1"]
    assert body["app_host_count"] == 3
    partial = _search(client, app="bill")
    assert partial["app_host_count"] == 3


def test_filters_and_null_storage_policy(loaded, client):
    body = _search(client, hostnames="crmapp1", policy_type="Deployment")
    assert [(r["policy_name"], r["storage"]) for r in body["items"]] == [("pol_deploy", "-")]
    options = client.get("/api/backup-inventory/filters").json()
    assert options["masters"] == ["bsdnbuvpapp1", "tbsnbuvpapp1"]
    assert "Deployment" in options["policy_types"]


def test_app_suggestions(loaded, client):
    assert client.get("/api/backup-inventory/apps", params={"q": "bil"}).json() == [
        {"app_name": "Billing", "host_count": 3}
    ]
    assert client.get("/api/backup-inventory/apps", params={"q": "b"}).json() == []


def test_export_matches_bot_layout(loaded, client):
    response = client.get("/api/backup-inventory/export", params={"hostnames": "billapp1, ghost99"})
    assert response.status_code == 200
    assert "SearchByHostname" in response.headers["content-disposition"]
    ws = load_workbook(BytesIO(response.content)).active
    assert ws["A1"].value.startswith("This data uses the inventory backup cut-off as of")
    assert ws["A2"].value == "Client Host"
    assert ws.freeze_panes == "A3"
    last = [c.value for c in ws[ws.max_row]]
    assert last[0] == "ghost99" and "Not Available" in last
    assert ws.cell(row=ws.max_row, column=1).fill.start_color.rgb.endswith("F8D7DA")


def test_validation_errors_have_error_id(loaded, client):
    response = client.get("/api/backup-inventory/search")
    assert response.status_code == 400
    assert response.json()["error_id"].startswith("ERR-")
    assert client.get("/api/backup-inventory/search", params={"hostnames": "x"}).status_code == 400


def test_cmdb_change_refreshes_search_view(loaded, client, tmp_path):
    db, *_ = loaded
    wb = Workbook()
    ws = wb.active
    ws.title = "Master Inventory"
    ws.append(
        [
            "Name",
            "IP OAM",
            "IP Service",
            "Apps",
            "PIC",
            "Apps Priority",
            "Prod/Nonprod",
            "VM/Baremetal",
            "Site",
        ]
    )
    for host, app in [
        ("billapp1", "Billing Baru"),
        ("billapp10", "Billing"),
        ("billnew1", "Billing"),
        ("crmapp1", "CRM"),
    ]:
        ws.append([host, "10.0.0.1", None, app, "Budi", "P1", "Prod", "VM", "TBS"])
    wb.save(tmp_path / "cmdb2.xlsx")
    import_cmdb(db, tmp_path / "cmdb2.xlsx")
    body = _search(client, hostnames="billapp1")
    assert body["items"][0]["app_names"] == "Billing Baru"


def test_web_cannot_write_inventory(clean_db):
    with connect("web") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM nbu.backup_inventory")
