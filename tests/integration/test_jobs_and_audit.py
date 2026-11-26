"""Kerangka job (lock, collect_run, transaksi) dan penulis audit ke tabel asli."""

from __future__ import annotations

import threading

import pytest

from atlas.collectors.runner import JobResult, run_job
from atlas.core.audit import start_audit
from atlas.core.db import Database
from atlas.core.logging import log_event, request_context
from tests.integration.conftest import connect

pytestmark = pytest.mark.integration


@pytest.fixture
def app_db(clean_db, itest_settings):
    with Database(itest_settings, "app", "itest", min_size=1, max_size=3) as db:
        yield db


def _runs():
    with connect("migrator") as conn:
        return conn.execute(
            "SELECT source, status, rows_total, error_id IS NOT NULL, request_id::text"
            " FROM core.collect_run ORDER BY id"
        ).fetchall()


def test_successful_job_records_run_and_events(app_db, events):
    def work(conn, ctx):
        assert ctx.run_id > 0
        return JobResult(total=3, inserted=3, updated=0, deleted=0)

    outcome = run_job(app_db, "cmdb", work)
    assert outcome.status == "success"
    assert outcome.exit_code == 0
    ((source, status, total, has_error, request_id),) = _runs()
    assert (source, status, total, has_error) == ("cmdb", "success", 3, False)
    assert request_id == outcome.request_id
    types = [e["event_type"] for e in events() if e["category"] == "job"]
    assert types == ["job_started", "job_finished"]


def test_failed_job_rolls_back_data_and_records_error(app_db, events):
    def work(conn, ctx):
        conn.execute(
            "INSERT INTO cmdb.server_inventory (row_hash, hostname, run_id) VALUES (md5('x'), 'host-x', %s)",
            (ctx.run_id,),
        )
        raise RuntimeError("gagal di tengah")

    outcome = run_job(app_db, "cmdb", work)
    assert outcome.status == "failed"
    assert outcome.exit_code == 1
    assert _runs()[0][:2] == ("cmdb", "failed")
    with connect("migrator") as conn:
        assert conn.execute("SELECT count(*) FROM cmdb.server_inventory").fetchone()[0] == 0  # rollback
        assert conn.execute("SELECT error_id FROM core.collect_run").fetchone()[0] == outcome.error_id
    failed = [e for e in events() if e["event_type"] == "job_failed"]
    assert failed[0]["error_id"] == outcome.error_id


def test_second_concurrent_run_is_skipped(app_db, events):
    inside, release = threading.Event(), threading.Event()
    outcomes = {}

    def slow(conn, ctx):
        inside.set()
        release.wait(5)
        return JobResult(total=0)

    first = threading.Thread(target=lambda: outcomes.setdefault("first", run_job(app_db, "cmdb", slow)))
    first.start()
    assert inside.wait(5)
    outcomes["second"] = run_job(app_db, "cmdb", lambda c, x: JobResult())
    release.set()
    first.join(5)
    assert outcomes["second"].status == "skipped"
    assert outcomes["first"].status == "success"
    assert len(_runs()) == 1  # run yang dilewati tidak membuat baris
    assert "job_skipped_locked" in [e["event_type"] for e in events()]


def test_orphaned_running_run_is_closed_by_next_run(app_db, events):
    with connect("app", autocommit=True) as conn:
        conn.execute("INSERT INTO core.collect_run (source) VALUES ('cmdb')")  # proses mati, status running
    run_job(app_db, "cmdb", lambda c, x: JobResult(total=0))
    statuses = [r[1] for r in _runs()]
    assert statuses == ["failed", "success"]
    assert "job_orphaned" in [e["event_type"] for e in events()]


def test_audit_writer_copies_events_into_table(clean_db, itest_settings, events):  # events: level DEBUG
    secret = itest_settings.db_app.password.get()
    handler = start_audit(itest_settings, "itest", "web", flush_interval_s=0.05)
    try:
        import logging

        lg = logging.getLogger("atlas.itest")
        with request_context() as rid:
            for i in range(250):  # lebih dari satu batch (200)
                log_event(lg, "web", "http_request", f"GET /api/{i}", duration_ms=i, status=200)
            log_event(
                lg, "security", "request_rejected", f"login gagal password={secret}", severity="warning"
            )
        assert handler.flush(timeout=10)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    with connect("readonly") as conn:
        rows = conn.execute(
            "SELECT count(*), count(DISTINCT request_id), max(duration_ms) FROM audit.event"
            " WHERE event_type = 'http_request' AND request_id = %s",
            (rid,),
        ).fetchone()
        assert rows == (250, 1, 249)
        message = conn.execute(
            "SELECT message FROM audit.event WHERE event_type = 'request_rejected'"
        ).fetchone()[0]
        assert secret not in message
        assert "***" in message
        assert (
            conn.execute(
                "SELECT count(*) FROM audit.event WHERE category = 'db' AND event_type = 'db_pool_opened'"
            ).fetchone()[0]
            >= 1
        )  # event koneksi DB pool audit sendiri ikut tercatat
