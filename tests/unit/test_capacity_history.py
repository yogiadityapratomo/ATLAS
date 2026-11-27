from __future__ import annotations

from datetime import date, timedelta

import pytest

from atlas.core.errors import ValidationError
from atlas.services import capacity_history as svc

TODAY = date(2026, 11, 27)


def test_defaults_per_period():
    req = svc.parse_request(today=TODAY)
    assert (req.period, req.group, req.end) == ("month", "site", TODAY)
    assert req.start == TODAY - timedelta(days=365)
    assert svc.parse_request(today=TODAY, period="day").start == TODAY - timedelta(days=30)


def test_future_end_is_clamped_and_filters_parsed():
    req = svc.parse_request(
        today=TODAY,
        end=TODAY + timedelta(days=10),
        sites="BRN, TBS,BRN",
        appliances="BRN/dp_a, TBS/dp_b",
        group="appliance",
    )
    assert req.end == TODAY
    assert req.sites == ("BRN", "TBS")
    assert req.appliances == (("BRN", "dp_a"), ("TBS", "dp_b"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"period": "decade"},
        {"group": "rack"},
        {"start": date(2026, 12, 1), "end": date(2026, 11, 1)},
        {"period": "day", "start": date(2024, 1, 1)},  # > 400 hari untuk harian
        {"appliances": "tanpa-master"},
        {"group": "appliance", "appliances": ",".join(f"M/p{i}" for i in range(9))},
    ],
)
def test_invalid_requests(kwargs):
    with pytest.raises(ValidationError):
        svc.parse_request(today=TODAY, **kwargs)


@pytest.mark.parametrize(
    ("period", "start", "label"),
    [
        ("day", date(2026, 11, 27), "27 Nov 2026"),
        ("week", date(2026, 11, 23), "Mg 48 2026"),
        ("week", date(2025, 12, 29), "Mg 1 2026"),  # minggu ISO lintas tahun
        ("month", date(2026, 8, 1), "Agu 2026"),
        ("quarter", date(2026, 10, 1), "Q4 2026"),
        ("semester", date(2026, 7, 1), "S2 2026"),
        ("semester", date(2026, 1, 1), "S1 2026"),
        ("year", date(2025, 1, 1), "2025"),
    ],
)
def test_bucket_labels(period, start, label):
    assert svc.bucket_label(period, start) == label


def test_series_label():
    assert svc.series_label("appliance", "BRN/dp_disk_x") == "dp_disk_x"
    assert svc.series_label("site", "BRN") == "BRN"
