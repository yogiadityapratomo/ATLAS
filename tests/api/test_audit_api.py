"""Menu Audit Log & retensi partisi terhadap DB atlas_test (plan 04 PR-5, design 05 §6)."""

from __future__ import annotations

import csv
import io
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from fastapi.testclient import TestClient

from atlas.collectors.maintenance_job import run_maintenance
from atlas.core.db import Database
from atlas.web.main import create_app
from tests.integration.conftest import connect, reset_database

pytestmark = pytest.mark.integration
TZ = ZoneInfo("Asia/Jakarta")
RID = str(uuid.uuid4())


def _seed(n: int = 250) -> None:
    now = datetime.now(TZ)
    copy_sql = (
        "COPY audit.event (occurred_at, category, event_type, severity, component, request_id, error_id,"
        " message, duration_ms, details) FROM STDIN"
    )
    with connect("app", autocommit=True) as conn, conn.cursor() as cur, cur.copy(copy_sql) as copy:
        for i in range(n):
            failed = i % 50 == 0
            copy.write_row(
                (
                    now - timedelta(minutes=i),
                    "job" if failed else ("db" if i % 7 == 0 else "web"),
                    "job_failed" if failed else ("db_connect_failed" if i % 7 == 0 else "http_request"),
                    "error" if failed or i % 7 == 0 else "info",
                    "capacity_job" if failed else "web",
                    RID if i < 3 else None,
                    f"ERR-{i:06X}" if failed else None,
                    f"pesan nomor {i} {'gagal_total' if failed else 'ok'}",
                    i,
                    f'{{"i": {i}}}',
                )
            )


@pytest.fixture
def client(clean_db, itest_settings):
    _seed()
    with TestClient(create_app(itest_settings, enable_audit=False, enable_listener=False)) as c:
        yield c


def test_keyset_pagination_returns_every_event_once(client):
    seen, cursor = [], None
    while True:
        params = {"limit": 100, "range": "24h"} | ({"cursor": cursor} if cursor else {})
        body = client.get("/api/audit/events", params=params).json()
        seen += [e["id"] for e in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    within_24h = 24 * 60 + 1  # satu event per menit
    assert len(seen) == len(set(seen)) == min(250, within_24h)
    first = client.get("/api/audit/events", params={"limit": 1}).json()["items"][0]
    assert first["message"] == "pesan nomor 0 gagal_total"  # terbaru dulu


def test_filters(client):
    def ids(**params):
        return [
            e["event_type"]
            for e in client.get("/api/audit/events", params=params | {"limit": 200}).json()["items"]
        ]

    assert set(ids(category="job")) == {"job_failed"}
    assert len(ids(category="job")) == 5
    assert set(ids(severity="error")) == {"job_failed", "db_connect_failed"}
    assert ids(q="gagal_total") == ["job_failed"] * 5  # "_" literal, bukan wildcard
    assert len(ids(request_id=RID)) == 3
    one = client.get("/api/audit/events", params={"error_id": "err-000032"}).json()["items"]
    assert [e["error_id"] for e in one] == ["ERR-000032"]
    assert client.get("/api/audit/events", params={"category": "x"}).status_code == 400


def test_summary_and_csv_export(client):
    s = client.get("/api/audit/summary").json()
    assert s["events"] == 250
    assert s["job_failed"] == 5
    assert s["errors"] == 5 + len([i for i in range(250) if i % 7 == 0 and i % 50 != 0])
    assert "capacity_job" in s["components"]
    response = client.get("/api/audit/export", params={"category": "job"})
    assert response.headers["content-type"].startswith("text/csv")
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    assert rows[0][:3] == ["id", "occurred_at", "category"] and len(rows) == 6


def test_filter_100k_events_under_one_second(clean_db, itest_settings):
    """Acceptance criteria design 05 #7: menu Audit Log memfilter 100 ribu event < 1 detik."""
    with connect("migrator") as conn:
        conn.execute(
            """
            INSERT INTO audit.event (occurred_at, category, event_type, severity, component, message, details)
            SELECT now() - (g || ' seconds')::interval,
                   (ARRAY['web','db','job','app','system'])[1 + g % 5],
                   'evt_' || (g % 40), (ARRAY['info','info','info','warning','error'])[1 + g % 5],
                   'comp' || (g % 6), 'pesan acak ' || md5(g::text), '{}'
              FROM generate_series(1, 100000) g
            """
        )
        conn.execute("ANALYZE audit.event")
    with TestClient(create_app(itest_settings, enable_audit=False, enable_listener=False)) as c:
        c.get("/api/audit/events", params={"limit": 10})  # pemanasan pool
        timings = {}
        for name, params in {
            "terbaru": {"range": "7d"},
            "kategori+level": {"range": "7d", "category": "db", "severity": "error"},
            "teks bebas": {"range": "7d", "q": "abc"},
            "ringkasan": None,
        }.items():
            started = time.perf_counter()
            r = (
                c.get("/api/audit/summary")
                if params is None
                else c.get("/api/audit/events", params=params | {"limit": 200})
            )
            timings[name] = (time.perf_counter() - started) * 1000
            assert r.status_code == 200
    print("\nwaktu respons 100k event (ms):", {k: round(v) for k, v in timings.items()})
    assert max(timings.values()) < 1000


def test_drop_old_partitions_and_guards(clean_db, itest_settings):
    with connect("migrator") as conn:
        conn.execute("SELECT core.ensure_monthly_partitions('audit.event', 9, 3)")  # partisi 9 bulan lalu
    old_cutoff = datetime.now(TZ) - timedelta(days=180)
    with connect("app", autocommit=True) as conn:
        dropped = [
            r[0] for r in conn.execute("SELECT core.drop_old_partitions('audit.event', %s)", (old_cutoff,))
        ]
        assert dropped and all(name.startswith("audit.event_") for name in dropped)
        with pytest.raises(psycopg.errors.RaiseException, match="terlalu baru"):
            conn.execute("SELECT core.drop_old_partitions('audit.event', now())")
        with pytest.raises(psycopg.errors.RaiseException, match="tidak diizinkan"):
            conn.execute(
                "SELECT core.drop_old_partitions('cmdb.server_inventory', now() - interval '1 year')"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"DROP TABLE audit.event_{datetime.now(TZ):%Y_%m}")
    with connect("web") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT core.drop_old_partitions('audit.event', now() - interval '1 year')")
    reset_database()


def test_maintenance_job_records_run(clean_db, itest_settings):
    with Database(itest_settings, "app", "maint_itest", min_size=1, max_size=1) as db:
        outcome = run_maintenance(db, itest_settings)
    assert outcome.status == "success"
    assert set(outcome.result.details["partitions_created"]) == {
        "audit.event",
        "capacity.disk_pool_snapshot",
        "capacity.tape_library_snapshot",
    }
