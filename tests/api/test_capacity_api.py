"""Web ATLAS + job kapasitas terhadap DB atlas_test (plan 04 PR-3).

Regresi utama: ``/api/data`` dari DB identik dengan JSON V4 untuk collect yang sama.
"""

from __future__ import annotations

import dataclasses
import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from atlas.collectors import capacity_job
from atlas.core.config import REPO_ROOT, NbuMaster, Secret
from atlas.core.db import Database
from atlas.core.errors import ValidationError
from atlas.web.main import create_app
from tests.integration.conftest import connect

pytestmark = pytest.mark.integration
# fixture sintetis berformat persis V4 (cache asli V4 tidak ada di repo — data production)
LEGACY_CACHE = REPO_ROOT / "tests" / "fixtures" / "v4_cache"


@pytest.fixture
def app_db(clean_db, itest_settings):
    with Database(itest_settings, "app", "capacity_itest", min_size=1, max_size=2) as db:
        yield db


@pytest.fixture
def client(clean_db, itest_settings):
    app = create_app(itest_settings, enable_audit=False, enable_listener=False)
    with TestClient(app) as c:
        yield c


def _legacy(name):
    return json.loads((LEGACY_CACHE / name).read_text(encoding="utf-8"))


def test_regression_api_data_identical_to_v4_json(app_db, client):
    outcomes = capacity_job.import_json(app_db, LEGACY_CACHE)
    assert [o.status for o in outcomes] == ["success", "success"]
    body = client.get("/api/data").json()
    assert json.dumps(body["disk_pools"]) == json.dumps(_legacy("capacity_cache.json"))
    assert json.dumps(body["tape_library"]) == json.dumps(_legacy("tape_cache.json"))
    assert body["last_updated"].endswith("+07:00")
    assert body["collect_status"]["capacity"]["data_status"] == "success"


def test_etag_304_and_new_version_after_collect(app_db, client):
    capacity_job.import_json(app_db, LEGACY_CACHE)
    first = client.get("/api/data")
    etag = first.headers["etag"]
    assert first.headers["cache-control"] == "no-cache"
    assert client.get("/api/data", headers={"If-None-Match": etag}).status_code == 304
    capacity_job.import_json(app_db, LEGACY_CACHE)  # collect baru → versi baru
    client.app.state.atlas.invalidate()  # yang biasanya dipicu NOTIFY
    again = client.get("/api/data", headers={"If-None-Match": etag})
    assert again.status_code == 200
    assert again.headers["etag"] != etag


def test_export_excel_from_db(app_db, client):
    assert client.get("/api/export").status_code == 404  # belum ada data
    capacity_job.import_json(app_db, LEGACY_CACHE)
    client.app.state.atlas.invalidate()  # yang biasanya dipicu NOTIFY
    response = client.get("/api/export")
    assert response.status_code == 200
    assert "capacity_report_" in response.headers["content-disposition"]
    wb = load_workbook(BytesIO(response.content))
    assert wb.sheetnames == ["Disk Pool Detail", "Disk Pool Summary", "Tape Library"]
    assert wb["Disk Pool Detail"].max_row == len(_legacy("capacity_cache.json")) + 1


def _fake_job(app_db, source, rows, errors):
    return capacity_job._source_job(
        app_db,
        source,
        lambda: (rows, errors),
        collected_at=lambda: capacity_job.datetime.now(capacity_job.TZ),
        details={"mode": "test"},
    )


def test_partial_and_failed_collect_are_reported_and_old_data_kept(app_db, client):
    disk = _legacy("capacity_cache.json")
    capacity_job.import_json(app_db, LEGACY_CACHE)
    partial = _fake_job(app_db, "capacity", [r for r in disk if r["Master"] != "TBS"], {"TBS": "HTTP 503"})
    assert partial.status == "partial"
    body = client.get("/api/data").json()
    assert {r["Master"] for r in body["disk_pools"]} == {"BRN", "BSD"}
    assert body["collect_status"]["capacity"]["errors"] == {"TBS": "HTTP 503"}

    failed = _fake_job(app_db, "capacity", [], {"TBS": "x", "BSD": "y", "BRN": "z"})
    assert failed.status == "failed"
    client.app.state.atlas.invalidate()
    body = client.get("/api/data").json()
    assert len(body["disk_pools"]) == len([r for r in disk if r["Master"] != "TBS"])  # data terakhir tetap
    status = body["collect_status"]["capacity"]
    assert status["last_attempt_status"] == "failed"
    assert status["last_error_id"] == failed.error_id


def test_live_collect_blocked_when_not_allowed(app_db, itest_settings, events):
    with pytest.raises(ValidationError, match="ATLAS_ALLOW_LIVE_NBU=0"):
        capacity_job.collect_live(app_db, itest_settings)
    assert "live_nbu_blocked" in [e["event_type"] for e in events()]


class FakeClient:
    def __init__(self, master, **kwargs):
        self.master = master

    def disk_pools(self, *, deadline_s):
        if self.master.name == "BRN":
            raise RuntimeError("timeout")
        tb = 1024**4
        return [
            {
                "attributes": {
                    "name": f"dp_disk_{self.master.key}nbupapp1x",
                    "sType": "PureDisk",
                    "usableSizeBytes": 10 * tb,
                    "availableSpaceBytes": 4 * tb,
                    "usedCapacityBytes": 6 * tb,
                },
                "relationships": {},
            }
        ]

    def tape_media(self, *, deadline_s, resume_dir):
        robot = {"tbs": 2, "bsd": 0, "brn": 0}[self.master.key]
        return [{"barcode": "X1L8", "robot": {"robotNumber": robot}, "kiloBytes": 1}]


def test_live_collect_with_fake_masters_end_to_end(app_db, itest_settings, client, tmp_path):
    masters = tuple(NbuMaster(k, k.upper(), "https://x", Secret("t")) for k in ("tbs", "bsd", "brn"))
    settings = dataclasses.replace(
        itest_settings, allow_live_nbu=True, nbu_masters=masters, capacity_json_dir=tmp_path / "cache"
    )
    disk, tape = capacity_job.collect_live(app_db, settings, client_factory=FakeClient)
    assert (disk.status, tape.status) == ("partial", "success")
    assert disk.result.details["errors"] == {"BRN": "timeout"}
    body = client.get("/api/data").json()
    assert [r["Disk Pool Name"] for r in body["disk_pools"]] == [
        "dp_disk_bsdnbupapp1x",
        "dp_disk_tbsnbupapp1x",
    ]
    assert {r["Site"] for r in body["tape_library"]} == {"BRN", "BSD", "TBS"}
    # transisi: file V4 ikut ditulis dari DB
    written = json.loads((tmp_path / "cache" / "capacity_cache.json").read_text(encoding="utf-8"))
    assert written == body["disk_pools"]
    assert (tmp_path / "report" / "capacity_report.xlsx").is_file()


def test_health_generate_and_request_audit(app_db, client, events, tmp_path):
    import os
    import shutil
    import time

    assert client.get("/api/health").json()["sources"]["capacity"]["last_success_at"] is None
    old = time.time() - 2 * 24 * 3600  # data diambil 2 hari lalu → basi (batas 30 menit)
    for name in ("capacity_cache.json", "tape_cache.json"):
        shutil.copy(LEGACY_CACHE / name, tmp_path / name)
        os.utime(tmp_path / name, (old, old))
    capacity_job.import_json(app_db, tmp_path)
    health = client.get("/api/health").json()
    assert health["db"] == "ok"
    assert health["sources"]["capacity"]["stale"] is True
    assert health["sources"]["capacity"]["age_minutes"] > 2 * 24 * 60 - 1
    assert health["status"] == "degraded"

    response = client.post("/api/generate")
    assert response.status_code == 403
    rid = client.get("/api/data", headers={"X-Request-ID": "11111111-2222-3333-4444-555555555555"}).headers[
        "x-request-id"
    ]
    assert rid == "11111111-2222-3333-4444-555555555555"
    reqs = [e for e in events() if e["event_type"] == "http_request" and e["request_id"] == rid]
    assert reqs and reqs[0]["details"]["status"] == 200


def test_web_role_cannot_write_capacity(clean_db):
    import psycopg

    with connect("web") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM capacity.disk_pool_snapshot")


def test_frontend_served(client):
    page = client.get("/")
    assert page.status_code == 200 and "/static/js/capacity.js" in page.text
    assert client.get("/static/js/common.js").status_code == 200
    assert client.get("/favicon.ico").status_code == 200


def test_notify_from_job_refreshes_web_immediately(app_db, itest_settings):
    """LISTEN/NOTIFY asli: data baru tampil tanpa menunggu memo versi kedaluwarsa (10 dtk)."""
    import time

    app = create_app(itest_settings, enable_audit=False, enable_listener=True)
    with TestClient(app) as c:
        listener = c.app.state.atlas.listener
        deadline = time.monotonic() + 5
        while not listener.connected and time.monotonic() < deadline:
            time.sleep(0.05)
        assert listener.connected
        assert c.get("/api/data").json()["disk_pools"] == []  # versi kosong kini diingat
        capacity_job.import_json(app_db, LEGACY_CACHE)  # job mengirim NOTIFY saat commit
        deadline = time.monotonic() + 5
        rows = []
        while not rows and time.monotonic() < deadline:
            time.sleep(0.1)
            rows = c.get("/api/data").json()["disk_pools"]
        assert len(rows) == len(_legacy("capacity_cache.json"))
