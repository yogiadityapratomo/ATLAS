from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from atlas.core.config import load_settings
from atlas.core.errors import ConfigError, ValidationError
from atlas.services import audit_query as svc

NOW = datetime(2026, 11, 27, 9, 0, tzinfo=ZoneInfo("Asia/Jakarta"))


def test_filter_defaults_and_ranges():
    f = svc.parse_filter(now=NOW)
    assert f.since == NOW - timedelta(hours=24)
    assert svc.parse_filter(now=NOW, range_="7d").since == NOW - timedelta(days=7)
    f = svc.parse_filter(now=NOW, category="db", severity="warning", component=" web ", q="  gagal ")
    assert (f.category, f.min_severity, f.component, f.q) == ("db", "warning", "web", "gagal")


def test_id_search_widens_window_and_normalizes():
    f = svc.parse_filter(now=NOW, range_="1h", error_id="err-7f3a2c")
    assert f.error_id == "ERR-7F3A2C"
    assert f.since == NOW - timedelta(days=30)  # ID dari laporan user bisa beberapa hari lalu
    f = svc.parse_filter(now=NOW, request_id="B31BA703-A44A-4FAD-ACAE-E2682A4B5DEC")
    assert f.request_id == "b31ba703-a44a-4fad-acae-e2682a4b5dec"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"range_": "2y"},
        {"category": "hacker"},
        {"severity": "fatal"},
        {"request_id": "bukan-uuid"},
        {"error_id": "ERR-12"},
    ],
)
def test_invalid_filters_rejected(kwargs):
    with pytest.raises(ValidationError):
        svc.parse_filter(now=NOW, **kwargs)


def test_cursor_round_trip_and_tamper():
    cursor = svc.encode_cursor(NOW, 12345)
    assert svc.decode_cursor(cursor) == (NOW, 12345)
    assert svc.decode_cursor(None) is None
    with pytest.raises(ValidationError):
        svc.decode_cursor("bukan-cursor!!")


def test_retention_minimum_enforced():
    assert load_settings(environ={"ATLAS_AUDIT_RETENTION_DAYS": "0"}).audit_retention_days == 0
    with pytest.raises(ConfigError, match="minimal 28"):
        load_settings(environ={"ATLAS_AUDIT_RETENTION_DAYS": "7"})
