from __future__ import annotations

from atlas.web.cache import VersionedCache, VersionMemo


def test_versioned_cache_builds_once_per_key_and_evicts_oldest():
    cache = VersionedCache(max_entries=2)
    calls = []

    def build(v):
        calls.append(v)
        return f"payload-{v}"

    assert cache.get_or_build(("data", 1), lambda: build(1)) == "payload-1"
    assert cache.get_or_build(("data", 1), lambda: build(1)) == "payload-1"
    assert calls == [1]
    cache.get_or_build(("data", 2), lambda: build(2))
    cache.get_or_build(("data", 3), lambda: build(3))
    assert len(cache) == 2
    cache.get_or_build(("data", 1), lambda: build(1))  # sudah dibuang → dibangun ulang
    assert calls == [1, 2, 3, 1]
    assert (cache.hits, cache.misses) == (1, 4)


def test_version_memo_ttl_and_invalidate():
    now = [0.0]
    memo = VersionMemo(ttl_s=10, clock=lambda: now[0])
    loads = []

    def load():
        loads.append(now[0])
        return (len(loads), 0)

    assert memo.get(load) == (1, 0)
    now[0] = 5
    assert memo.get(load) == (1, 0)  # masih dalam TTL: DB tidak ditanya
    memo.invalidate()  # NOTIFY dari job
    assert memo.get(load) == (2, 0)
    now[0] = 20
    assert memo.get(load) == (3, 0)  # kedaluwarsa sendiri (fallback bila LISTEN putus)
