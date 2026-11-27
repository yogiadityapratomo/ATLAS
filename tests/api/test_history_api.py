"""Historical Capacity terhadap DB atlas_test: rollup harian, agregasi periode, data contoh."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import psycopg
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from atlas.collectors import capacity_job
from atlas.collectors.maintenance_job import run_maintenance
from atlas.core.config import REPO_ROOT
from atlas.core.db import Database
from atlas.web.main import create_app
from tests.integration.conftest import connect

pytestmark = pytest.mark.integration
TZ = ZoneInfo("Asia/Jakarta")
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "v4_cache"
TODAY = datetime.now(TZ).date()


def _daily(rows):
    """Isi capacity.disk_pool_daily langsung (day, site, master, pool, used, usable, peak_pct, source)."""
    with connect("app", autocommit=True) as conn:
        for day, site, master, pool, used, usable, peak, source in rows:
            conn.execute(
                "INSERT INTO capacity.disk_pool_daily (day, site, master, disk_pool_name, usable_tb,"
                " available_tb, used_tb, usage_pct, max_used_tb, max_usage_pct, samples, source)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
                (
                    day,
                    site,
                    master,
                    pool,
                    usable,
                    usable - used,
                    used,
                    round(used / usable * 100, 2),
                    used,
                    peak,
                    source,
                ),
            )


@pytest.fixture
def client(clean_db, itest_settings):
    with TestClient(create_app(itest_settings, enable_audit=False, enable_listener=False)) as c:
        yield c


def test_capacity_job_rolls_up_daily_and_rerun_is_idempotent(clean_db, itest_settings):
    with Database(itest_settings, "app", "hist_itest", min_size=1, max_size=1) as db:
        capacity_job.import_json(db, FIXTURES)
        with connect("readonly") as conn:
            rows = conn.execute(
                "SELECT count(*), sum(samples), bool_and(source = 'collect') FROM capacity.disk_pool_daily"
            ).fetchone()
        assert rows == (8, 8, True)  # 8 disk pool fixture, 1 snapshot
        outcome = run_maintenance(db, itest_settings)
    assert outcome.result.details["daily_rollup_rows"] == 0  # sudah diringkas oleh job kapasitas


def test_period_value_is_end_of_period_and_group_sum(client):
    m1 = TODAY.replace(day=1)
    prev_end = m1 - timedelta(days=1)
    _daily(
        [
            # bulan lalu: 2 hari; nilai bulan = hari TERAKHIR (bukan rata-rata)
            (prev_end - timedelta(days=5), "BRN", "BRN", "p1", 10, 100, 12, "collect"),
            (prev_end, "BRN", "BRN", "p1", 40, 100, 95, "collect"),
            (prev_end, "BRN", "BRN", "p2", 20, 100, 30, "collect"),
            (prev_end, "TBS", "TBS", "p3", 50, 200, 26, "collect"),
            (TODAY, "BRN", "BRN", "p1", 60, 100, 61, "collect"),
        ]
    )
    body = client.get("/api/capacity/history", params={"period": "month", "group": "site"}).json()
    brn = next(s for s in body["series"] if s["key"] == "BRN")
    last_month = brn["points"][prev_end.replace(day=1).isoformat()]
    assert (last_month["used_tb"], last_month["usable_tb"]) == (60.0, 200.0)  # 40 + 20 (akhir bulan)
    assert last_month["usage_pct"] == 30.0
    assert last_month["peak_pct"] == 95.0  # puncak dalam periode tetap terlihat
    assert last_month["appliances"] == 2
    assert brn["points"][m1.isoformat()]["used_tb"] == 60.0  # bulan ini: hanya p1 yang ada datanya
    assert body["has_demo"] is False


def test_appliance_grouping_filters_and_demo_flag(client):
    _daily(
        [
            (TODAY - timedelta(days=40), "BRN", "BRN", "p1", 10, 100, 10, "demo"),
            (TODAY, "BRN", "BRN", "p1", 20, 100, 20, "collect"),
            (TODAY, "BSD", "BSD", "p9", 70, 100, 70, "collect"),
        ]
    )
    options = client.get("/api/capacity/history/options").json()
    assert [a["key"] for a in options["appliances"]] == ["BRN/p1", "BSD/p9"]
    assert options["has_demo"] is True
    body = client.get(
        "/api/capacity/history", params={"period": "week", "group": "appliance", "appliances": "BRN/p1"}
    ).json()
    assert [s["label"] for s in body["series"]] == ["p1"]
    assert body["has_demo"] is True
    assert all(b["label"].startswith("Mg ") for b in body["buckets"])
    bad = client.get("/api/capacity/history", params={"period": "decade"})
    assert bad.status_code == 400 and bad.json()["error_id"].startswith("ERR-")


def test_semester_and_year_buckets(client):
    _daily(
        [
            (date(TODAY.year - 1, 3, 31), "BRN", "BRN", "p1", 10, 100, 10, "demo"),
            (date(TODAY.year - 1, 9, 30), "BRN", "BRN", "p1", 30, 100, 30, "demo"),
        ]
    )
    sem = client.get("/api/capacity/history", params={"period": "semester"}).json()
    assert [b["label"] for b in sem["buckets"]] == [f"S1 {TODAY.year - 1}", f"S2 {TODAY.year - 1}"]
    year = client.get("/api/capacity/history", params={"period": "year"}).json()
    assert year["series"][0]["points"][f"{TODAY.year - 1}-01-01"]["used_tb"] == 30.0


def test_export_has_metric_sheets_and_demo_note(client):
    _daily([(TODAY - timedelta(days=3), "BRN", "BRN", "p1", 10, 100, 10, "demo")])
    response = client.get("/api/capacity/history/export", params={"period": "day"})
    wb = load_workbook(BytesIO(response.content))
    assert wb.sheetnames == ["Usage", "Used", "Free", "Detail"]
    assert "DATA CONTOH" in wb["Usage"]["A1"].value


def test_web_cannot_write_daily(clean_db):
    with connect("web") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM capacity.disk_pool_daily")
