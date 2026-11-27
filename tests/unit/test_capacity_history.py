from __future__ import annotations

from datetime import date, timedelta

import pytest

from atlas.core.errors import ValidationError
from atlas.services import capacity_history as svc

TODAY = date(2026, 11, 27)  # Jumat


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
        appliances="BrnNbupApp7, tbsnbupapp11",
        group="appliance",
    )
    assert req.end == TODAY
    assert req.sites == ("BRN", "TBS")
    assert req.appliances == ("brnnbupapp7", "tbsnbupapp11")


def test_select_all_has_no_eight_series_cap():
    req = svc.parse_request(today=TODAY, group="appliance", appliances=",".join(f"app{i}" for i in range(30)))
    assert len(req.appliances) == 30  # grafik membatasi 8 garis; tabel & ringkasan memuat semua


@pytest.mark.parametrize(
    "kwargs",
    [
        {"period": "decade"},
        {"group": "rack"},
        {"start": date(2026, 12, 1), "end": date(2026, 11, 1)},
        {"period": "day", "start": date(2024, 1, 1)},  # > 400 hari untuk harian
        {"appliances": "nama dengan spasi"},
        {"appliances": "x;DROP TABLE"},
        {"appliances": ",".join(f"a{i}" for i in range(201))},
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


@pytest.mark.parametrize(
    ("period", "prev", "cur"),
    [
        ("day", (date(2026, 11, 26), date(2026, 11, 26)), (date(2026, 11, 27), date(2026, 11, 27))),
        ("week", (date(2026, 11, 16), date(2026, 11, 22)), (date(2026, 11, 23), date(2026, 11, 27))),
        ("month", (date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 11, 1), date(2026, 11, 27))),
        ("quarter", (date(2026, 7, 1), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 11, 27))),
        ("semester", (date(2026, 1, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 11, 27))),
        ("year", (date(2025, 1, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 11, 27))),
    ],
)
def test_compare_windows_period_vs_previous(period, prev, cur):
    base, current = svc.compare_windows(today=TODAY, mode="period", period=period)
    assert (base.start, base.end) == prev
    assert (current.start, current.end) == cur
    assert base.label.split(" (")[0] == svc.COMPARE_LABEL[period][1]


def test_compare_windows_range_and_validation():
    base, current = svc.compare_windows(today=TODAY, mode="range", a=date(2026, 1, 15), b=date(2026, 12, 31))
    assert base.end == date(2026, 1, 15) and base.start == date(2025, 12, 15)  # toleransi 31 hari
    assert current.end == TODAY  # masa depan dipotong ke hari ini
    for kwargs in ({"a": date(2026, 5, 1), "b": date(2026, 4, 1)}, {"a": None, "b": TODAY}):
        with pytest.raises(ValidationError):
            svc.compare_windows(today=TODAY, mode="range", **kwargs)
    with pytest.raises(ValidationError):
        svc.compare_windows(today=TODAY, mode="ytd")


def _p(used, usable, free=None):
    return {
        "used_tb": used,
        "usable_tb": usable,
        "free_tb": free if free is not None else usable - used,
        "usage_pct": round(used / usable * 100, 2),
        "as_of": "2026-11-27",
    }


def test_compare_rows_increase_decrease_expansion_and_missing():
    rows = {
        r["key"]: r
        for r in svc.compare_rows(
            {"A": _p(100, 200), "B": _p(80, 100), "C": _p(50, 100), "GONE": _p(1, 10)},
            {"A": _p(150, 300), "B": _p(60, 100), "C": _p(50, 100), "NEW": _p(5, 10)},
        )
    }
    a = rows["A"]
    assert (a["used_delta_tb"], a["used_change_pct"], a["usable_delta_tb"], a["usage_delta_pp"]) == (
        50,
        50.0,
        100,
        0.0,
    )
    assert a["trend"] == "naik"
    assert (rows["B"]["used_change_pct"], rows["B"]["usage_delta_pp"], rows["B"]["trend"]) == (
        -25.0,
        -20.0,
        "turun",
    )
    assert rows["C"]["trend"] == "tetap"
    assert (rows["NEW"]["trend"], rows["GONE"]["trend"]) == ("baru", "hilang")


def test_totals():
    t = svc.totals([_p(100, 200), _p(50, 100)])
    assert (t["used_tb"], t["usable_tb"], t["usage_pct"]) == (150, 300, 50.0)
    assert svc.totals([]) is None
