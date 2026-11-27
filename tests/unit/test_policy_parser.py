"""Parser policy_cache.json — logika bot check_v2 (hari 1 = Minggu) + perbaikan storage null."""

from __future__ import annotations

import pytest

from atlas.core.errors import ValidationError
from atlas.services import inventory_search as svc
from atlas.services.policy_parser import (
    build_inventory,
    parse_policies,
    schedule_window,
    search_terms,
    seconds_to_hhmm,
)


def _policy(
    name="pol_a",
    *,
    active=True,
    clients=None,
    schedules=None,
    storage="stu_disk_bsdnbupapp4",
    slp=False,
    source="bsdnbuvpapp1",
    ptype="Standard",
):
    item = {
        "data": {
            "attributes": {
                "policy": {
                    "policyName": name,
                    "policyType": ptype,
                    "policyAttributes": {
                        "active": active,
                        "storage": storage,
                        "volumePool": "NetBackup",
                        "storageIsSLP": slp,
                    },
                    "backupSelections": {"selections": ["/home", "/apps"]},
                    "clients": clients
                    if clients is not None
                    else [{"hostName": "App01", "OS": "Linux", "hardware": "x86"}],
                    "schedules": schedules if schedules is not None else [_schedule()],
                }
            }
        }
    }
    if source is not None:
        item["source"] = source
    return item


def _schedule(name="daily", window=None, retention=(2, "WEEKS")):
    return {
        "scheduleName": name,
        "backupType": "Full Backup",
        "startWindow": window if window is not None else [{"dayOfWeek": 1, "startSeconds": 3600}],
        "backupCopies": {"copies": [{"retentionPeriod": {"value": retention[0], "unit": retention[1]}}]},
    }


def test_day_one_is_sunday_and_ranges():
    days, starts = schedule_window(
        {"startWindow": [{"dayOfWeek": d, "startSeconds": 79200 if d in (2, 6) else 0} for d in range(1, 8)]}
    )
    assert days == "Senin - Jumat"  # hanya hari dengan startSeconds > 0
    assert starts == "Senin: 22:00; Jumat: 22:00"
    assert schedule_window({"startWindow": [{"dayOfWeek": 1, "startSeconds": 0}]}) == (
        "Minggu",
        "Minggu: 00:00",
    )
    assert schedule_window({"startWindow": []}) is None
    assert seconds_to_hhmm(5400) == "01:30"


def test_row_fields_like_bot_report():
    (row,) = parse_policies({"policies": [_policy()]})
    d = row.as_dict()
    assert d["client_host"] == "app01"  # lowercase seperti bot
    assert d["schedule_days"] == "Minggu"
    assert d["start_times"] == "Minggu: 01:00"
    assert d["retention_period"] == "2 Weeks"
    assert d["backup_selections"] == "/home, /apps"
    assert d["master_server"] == "bsdnbuvpapp1"


def test_filters_inactive_onetime_manual_and_windowless():
    cache = {
        "policies": [
            _policy("aktif"),
            _policy("mati", active=False),
            _policy("x_onetime_y"),
            _policy("Manual_backup"),
            _policy("tanpa_window", schedules=[_schedule(window=[])]),
        ]
    }
    assert [r.get("policy_name") for r in parse_policies(cache)] == ["aktif"]


def test_slp_retention_and_master_fallback():
    slps = {
        "slp_tbs": {
            "data": {
                "attributes": {"operationList": [{}, {"retentionPeriod": {"value": 1, "unit": "MONTHS"}}]}
            }
        }
    }
    (row,) = parse_policies({"policies": [_policy(storage="slp_tbs", slp=True, source=None)], "slps": slps})
    assert row.get("retention_period") == "1 Month"
    assert row.get("master_server") == "tbsnbuvpapp1"  # ditebak dari nama storage


def test_null_storage_policy_is_kept_unlike_bot():
    (row,) = parse_policies({"policies": [_policy(storage=None, ptype="Deployment")]})
    assert row.get("storage") == "-"
    assert row.get("master_server") == "bsdnbuvpapp1"


def test_policy_without_clients_and_duplicate_keys():
    cache = {"policies": [_policy(clients=[]), _policy(), _policy()]}
    inv = build_inventory(cache)
    assert [r.get("client_host") for r in inv.rows] == ["-", "app01"]
    assert inv.duplicates == 1
    assert len({r.row_hash for r in inv.rows}) == 2


def test_search_terms_parsing():
    assert search_terms("App1, app2\n app1 ;APP3  host4") == ["app1", "app2", "app3", "host4"]


def test_parse_request_validation():
    with pytest.raises(ValidationError):
        svc.parse_request(hostnames="", app="")
    with pytest.raises(ValidationError):
        svc.parse_request(hostnames="a1", app="CRM")
    with pytest.raises(ValidationError, match="< 2 karakter"):
        svc.parse_request(hostnames="a", app=None).terms  # noqa: B018
    with pytest.raises(ValidationError):
        svc.parse_request(hostnames=",".join(f"h{i:04d}" for i in range(501)), app=None)
    with pytest.raises(ValidationError):
        svc.parse_request(hostnames="host1", app=None, limit=0)
    req = svc.parse_request(hostnames="Host1, host2", app=None, master=" ", limit=10)
    assert (req.mode, req.terms, req.master, req.limit) == ("hostname", ("host1", "host2"), None, 10)
    assert svc.parse_request(hostnames=None, app=" CRM ").app == "CRM"


def test_not_found_rows_match_bot_format():
    (row,) = svc.not_found_rows(["ghost1"])
    assert row["client_host"] == "ghost1"
    assert row["policy_name"] == row["master_server"] == "Not Available"
    assert row["status"] == "not_found"
