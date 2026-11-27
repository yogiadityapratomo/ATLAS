"""Klien NBU dengan sesi HTTP palsu: rate limit, retry per halaman, deadline, lanjutan tape."""

from __future__ import annotations

import json

import pytest
import requests

from atlas.collectors.nbu_client import NbuClient, NbuError
from atlas.core.config import NbuMaster, Secret

TOKEN = "Token-Nbu-Palsu-0001"


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body


class FakeSession:
    """Mengembalikan respons dari skrip berurutan; mencatat parameter tiap request."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, *, headers, params, verify, timeout, proxies):
        self.calls.append(
            {"url": url, "params": dict(params), "auth": headers["Authorization"], "proxies": proxies}
        )
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(round(seconds, 3))
        self.now += seconds


def _client(script, **kw):
    clock = Clock()
    session = FakeSession(script)
    master = NbuMaster("bsd", "BSD", "https://nbu.example/netbackup", Secret(TOKEN))
    client = NbuClient(master, session=session, sleep=clock.sleep, clock=clock, **kw)
    return client, session, clock


def _page(n, start=0):
    return Resp(body={"data": [{"attributes": {"i": start + i}} for i in range(n)]})


def test_disk_pools_retry_resumes_failed_page_not_offset_zero(events):
    client, session, clock = _client(
        [_page(50), Resp(503, headers={"Retry-After": "3"}), _page(50, 50), _page(10, 100)],
        min_interval_s=0.2,
    )
    items = client.disk_pools(deadline_s=60)
    assert len(items) == 110
    assert [c["params"]["page[offset]"] for c in session.calls] == [0, 50, 50, 100]
    assert 3.0 in clock.sleeps  # Retry-After dihormati
    assert all(c["proxies"] == {"http": None, "https": None} for c in session.calls)
    retry = [e for e in events() if e["event_type"] == "nbu_retry"]
    assert retry and retry[0]["details"]["master"] == "BSD"


def test_rate_limit_spaces_requests(events):
    client, _, clock = _client([_page(50), _page(50, 50), _page(1, 100)], min_interval_s=0.5)
    client.disk_pools(deadline_s=60)
    assert clock.sleeps.count(0.5) == 2  # jeda sebelum request ke-2 dan ke-3


def test_non_retryable_status_fails_fast():
    client, session, _ = _client([Resp(401)])
    with pytest.raises(NbuError, match="HTTP 401"):
        client.disk_pools(deadline_s=60)
    assert len(session.calls) == 1


def test_gives_up_after_max_retries_with_backoff():
    client, session, clock = _client([requests.Timeout("t")] * 3, max_retries=3, min_interval_s=0)
    with pytest.raises(NbuError, match="3 percobaan"):
        client.disk_pools(deadline_s=60)
    assert len(session.calls) == 3
    assert clock.sleeps == [2.0, 4.0]


def test_deadline_stops_before_next_page():
    client, session, clock = _client([_page(50), _page(50, 50)], min_interval_s=0)
    original = session.get

    def slow_get(*args, **kwargs):
        clock.now += 30
        return original(*args, **kwargs)

    session.get = slow_get
    with pytest.raises(NbuError, match="tidak selesai dalam 45"):
        client.disk_pools(deadline_s=45)
    assert len(session.calls) == 2  # tidak ada request ke-3 setelah deadline lewat


def _tape_page(ids, cursor):
    body = {"data": [{"attributes": {"barcode": f"T{i}L8"}} for i in ids]}
    if cursor:
        body["meta"] = {"pagination": {"next": cursor}}
    return Resp(body=body)


def test_tape_media_saves_progress_and_resumes_next_run(tmp_path):
    first, _session, _ = _client(
        [_tape_page([1, 2], "c2"), Resp(500), Resp(500), Resp(500)], min_interval_s=0
    )
    with pytest.raises(NbuError):
        first.tape_media(deadline_s=360, resume_dir=tmp_path)
    state = json.loads((tmp_path / "tape_resume_bsd.json").read_text(encoding="utf-8"))
    assert state["cursor"] == "c2" and len(state["records"]) == 2

    second, session2, _ = _client([_tape_page([3], None)], min_interval_s=0)
    records = second.tape_media(deadline_s=360, resume_dir=tmp_path)
    assert [r["barcode"] for r in records] == ["T1L8", "T2L8", "T3L8"]
    assert session2.calls[0]["params"]["page[after]"] == "c2"  # lanjut dari halaman yang gagal
    assert not (tmp_path / "tape_resume_bsd.json").exists()


def test_missing_token_is_rejected_and_token_never_logged(events, caplog):
    with pytest.raises(NbuError, match="token NBU"):
        NbuClient(NbuMaster("tbs", "TBS", "https://x", Secret("")))
    client, session, _ = _client([Resp(503), _page(1)], min_interval_s=0)
    client.disk_pools(deadline_s=60)
    assert session.calls[0]["auth"] == f"Bearer {TOKEN}"
    assert TOKEN not in caplog.text
