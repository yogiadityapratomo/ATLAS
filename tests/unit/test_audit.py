"""Penulis audit write-behind tanpa DB sungguhan (design 05 §3.2)."""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager

import pytest

from atlas.core.audit import AuditHandler
from atlas.core.errors import DatabaseError
from atlas.core.logging import REDACTOR, log_event, request_context

COLS = {
    name: i
    for i, name in enumerate(
        (
            "occurred_at",
            "category",
            "event_type",
            "severity",
            "component",
            "actor",
            "request_id",
            "error_id",
            "message",
            "duration_ms",
            "details",
            "host",
            "pid",
            "app_version",
        )
    )
}


class FakeDb:
    def __init__(self):
        self.down = False
        self.closed = False

    @contextmanager
    def connection(self):
        if self.down:
            raise DatabaseError("db mati")
        yield object()

    def close(self):
        self.closed = True


class Sink:
    def __init__(self):
        self.rows: list[tuple] = []

    def __call__(self, conn, rows):
        self.rows.extend(rows)
        return len(rows)

    def col(self, name):
        return [r[COLS[name]] for r in self.rows]


@pytest.fixture
def audit():
    """AuditHandler terpasang pada logger 'atlas.t' (bukan root, agar tidak menangkap log pytest)."""
    created = []

    def _make(**options):
        db, sink = FakeDb(), Sink()
        handler = AuditHandler(db, "unit", sink=sink, flush_interval_s=0.01, max_backoff_s=0.05, **options)
        lg = logging.getLogger("atlas.t")
        lg.setLevel(logging.DEBUG)
        lg.addHandler(handler)
        created.append((lg, handler))
        return handler.start(), db, sink, lg

    yield _make
    for lg, handler in created:
        lg.removeHandler(handler)
        handler.close()


def test_events_are_written_in_batch_with_request_id(audit):
    handler, _, sink, lg = audit()
    with request_context() as rid:
        log_event(lg, "web", "http_request", "GET /api/data", duration_ms=12, status=200)
        log_event(lg, "app", "export_excel", "Export", actor="10.0.0.5")
    assert handler.flush()
    assert sink.col("event_type") == ["http_request", "export_excel"]
    assert sink.col("request_id") == [rid, rid]
    assert sink.col("component") == ["unit", "unit"]
    assert json.loads(sink.rows[0][COLS["details"]]) == {"status": 200}
    assert sink.rows[0][COLS["duration_ms"]] == 12
    assert handler.written == 2


def test_plain_error_logs_included_but_not_info(audit):
    handler, _, sink, lg = audit()
    lg.info("biasa saja")
    try:
        raise RuntimeError("meledak")
    except RuntimeError:
        lg.exception("Gagal memproses")
    assert handler.flush()
    assert sink.col("event_type") == ["log_error"]
    details = json.loads(sink.rows[0][COLS["details"]])
    assert details["exc_type"] == "RuntimeError"
    assert "meledak" in details["traceback"]


def test_secret_redacted_in_message_details_and_actor(audit):
    REDACTOR.add_secret("Rahasia-Audit-777")
    handler, _, sink, lg = audit()
    log_event(
        lg, "security", "request_rejected", "token=abcdef123456", actor="Rahasia-Audit-777", password="x"
    )
    assert handler.flush()
    text = repr(sink.rows)
    assert "Rahasia-Audit-777" not in text
    assert "abcdef123456" not in text
    assert json.loads(sink.rows[0][COLS["details"]]) == {"password": "***"}


def test_invalid_fields_are_sanitized_not_rejected(audit):
    handler, _, sink, lg = audit()
    log_event(lg, "app", "Bukan Valid!", "x", error_id="salah", request_id="bukan-uuid", duration_ms=-5)
    assert handler.flush()
    row = sink.rows[0]
    assert row[COLS["event_type"]] == "unknown_event"
    assert row[COLS["error_id"]] is None
    assert row[COLS["request_id"]] is None
    assert row[COLS["duration_ms"]] is None
    details = json.loads(row[COLS["details"]])
    assert details == {
        "event_type_raw": "Bukan Valid!",
        "error_id_raw": "salah",
        "request_id_raw": "bukan-uuid",
    }


def test_db_down_keeps_events_and_does_not_raise(audit):
    handler, db, sink, lg = audit()
    db.down = True
    for i in range(5):
        log_event(lg, "web", "http_request", f"req {i}")
    assert not handler.flush(timeout=0.3)  # tidak bisa kosong selama DB mati
    assert handler.pending == 5
    assert sink.rows == []
    db.down = False
    assert handler.flush(timeout=3)
    assert len(sink.rows) == 5
    assert "audit_backlog_dropped" not in sink.col("event_type")  # tidak ada yang terbuang


def test_full_queue_drops_info_first_and_reports_backlog(audit):
    handler, db, sink, lg = audit(max_queue=3, batch_size=10)
    db.down = True
    log_event(lg, "web", "http_request", "info-1")
    log_event(lg, "job", "job_failed", "error-1", severity="error")
    log_event(lg, "web", "http_request", "info-2")
    log_event(lg, "db", "db_connect_failed", "error-2", severity="error")  # penuh → info-1 dibuang
    log_event(lg, "web", "http_request", "info-3")  # penuh & info → langsung dibuang
    assert handler.pending == 3
    assert handler.dropped == 2
    db.down = False
    assert handler.flush(timeout=3)
    messages = sink.col("message")
    assert messages[:3] == ["error-1", "info-2", "error-2"]
    backlog = [r for r in sink.rows if r[COLS["event_type"]] == "audit_backlog_dropped"]
    assert len(backlog) == 1
    assert json.loads(backlog[0][COLS["details"]])["dropped"] == 2
    assert handler.dropped == 0


def test_no_audit_flag_skips_record(audit):
    handler, _, sink, lg = audit()
    lg.error("hanya ke file", extra={"atlas_no_audit": True})
    assert handler.flush()
    assert sink.rows == []


def test_close_flushes_and_closes_db(audit):
    handler, db, sink, lg = audit()
    log_event(lg, "system", "app_stopped", "berhenti", request_id=str(uuid.uuid4()))
    lg.removeHandler(handler)
    handler.close()
    assert len(sink.rows) == 1
    assert db.closed
