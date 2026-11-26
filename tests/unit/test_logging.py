from __future__ import annotations

import json
import logging

import pytest

from atlas.core.logging import (
    EVENT_ATTR,
    REDACTOR,
    JsonFormatter,
    get_request_id,
    log_event,
    request_context,
    setup_logging,
)

FAKE_SECRET = "Pa55-Sangat-Rahasia-XYZ"


def _record(msg: str, *args, event: dict | None = None, exc_info=None) -> logging.LogRecord:
    record = logging.LogRecord("atlas.test", logging.INFO, __file__, 1, msg, args, exc_info)
    if event is not None:
        setattr(record, EVENT_ATTR, event)
    return record


def _format(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter("unit").format(record))


# ---------------------------------------------------------------- format


def test_json_line_has_required_fields():
    out = _format(_record("halo %s", "dunia"))
    assert out["message"] == "halo dunia"
    assert out["level"] == "info"
    assert out["component"] == "unit"
    assert out["logger"] == "atlas.test"
    for key in ("ts", "host", "pid", "app_version", "request_id"):
        assert key in out
    assert out["ts"].endswith("+00:00")


def test_event_fields_are_included(events):
    logger = logging.getLogger("atlas.test")
    log_event(
        logger,
        "job",
        "job_failed",
        "Job gagal",
        severity="error",
        error_id="ERR-000001",
        duration_ms=1234,
        actor="capacity_job",
        rows=7,
    )
    (event,) = events()
    assert event["category"] == "job"
    assert event["event_type"] == "job_failed"
    assert event["severity"] == "error"
    assert event["details"] == {"rows": 7}

    out = _format(_record("Job gagal", event=event))
    assert out["event_type"] == "job_failed"
    assert out["error_id"] == "ERR-000001"
    assert out["duration_ms"] == 1234
    assert out["details"] == {"rows": 7}


def test_invalid_category_or_severity_rejected():
    logger = logging.getLogger("atlas.test")
    with pytest.raises(ValueError):
        log_event(logger, "lainnya", "x", "x")
    with pytest.raises(ValueError):
        log_event(logger, "app", "x", "x", severity="fatal")


# ---------------------------------------------------------------- request_id


def test_request_context_sets_and_restores_id():
    assert get_request_id() is None
    with request_context() as outer:
        assert get_request_id() == outer
        with request_context("abc-123"):
            assert get_request_id() == "abc-123"
            assert _format(_record("x"))["request_id"] == "abc-123"
        assert get_request_id() == outer
    assert get_request_id() is None


# ---------------------------------------------------------------- filter secret


def test_known_secret_redacted_in_message_details_and_traceback():
    REDACTOR.add_secret(FAKE_SECRET)
    try:
        raise RuntimeError(f"gagal login dengan {FAKE_SECRET}")
    except RuntimeError:
        import sys

        exc_info = sys.exc_info()
    event = {"category": "db", "event_type": "db_connect_failed", "details": {"note": [f"x{FAKE_SECRET}x"]}}
    line = JsonFormatter("unit").format(_record("pesan %s", FAKE_SECRET, event=event, exc_info=exc_info))
    assert FAKE_SECRET not in line
    assert line.count("***") >= 3


@pytest.mark.parametrize(
    ("text", "leak"),
    [
        ("host=db user=atlas password=s3cr3tValue dbname=atlas", "s3cr3tValue"),
        ("ATLAS_DB_PASSWORD_WEB=envSecret99", "envSecret99"),
        ('{"api_key": "AbCdEf012345"}', "AbCdEf012345"),
        ("token: tok_live_998877", "tok_live_998877"),
        ("Authorization: Bearer eyJhbGciOi.JIUzI1NiIs", "eyJhbGciOi.JIUzI1NiIs"),
        ("postgresql://atlas:UrlPass77@localhost/atlas", "UrlPass77"),
    ],
)
def test_common_secret_patterns_redacted(text, leak):
    redacted = REDACTOR.redact_text(text)
    assert leak not in redacted
    assert "***" in redacted


def test_sensitive_dict_keys_redacted_recursively():
    data = {
        "user": "atlas",
        "password": "x",
        "nested": {"Authorization": "y", "rows": 3},
        "list": [{"token": 1}],
    }
    assert REDACTOR.redact(data) == {
        "user": "atlas",
        "password": "***",
        "nested": {"Authorization": "***", "rows": 3},
        "list": [{"token": "***"}],
    }


def test_ordinary_text_not_redacted():
    for text in ("5 passed, 0 failed", "hostname tbsnbuvpapp1 policy PASSPORT_DB", "secretariat server"):
        assert REDACTOR.redact_text(text) == text


# ---------------------------------------------------------------- setup_logging


def test_setup_logging_writes_json_file_without_secret(make_settings):
    settings = make_settings(ATLAS_DB_PASSWORD_APP=FAKE_SECRET)
    logger = setup_logging(settings, "unit_job", console=False)
    logger.warning("koneksi memakai %s", FAKE_SECRET)
    setup_logging(settings, "unit_job", console=False)  # dipanggil ulang: handler tidak dobel
    root = logging.getLogger()
    atlas_handlers = [h for h in root.handlers if getattr(h, "_atlas_handler", False)]
    assert len(atlas_handlers) == 1
    for h in atlas_handlers:
        h.flush()

    lines = (settings.log_dir / "unit_job.log").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert FAKE_SECRET not in "\n".join(lines)
    assert any(r.get("event_type") == "config_loaded" for r in records)
    assert any(r["message"] == "koneksi memakai ***" for r in records)

    for h in atlas_handlers:
        root.removeHandler(h)
        h.close()
