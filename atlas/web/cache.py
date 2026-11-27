"""Cache bertingkat dengan invalidasi otomatis (plan 04 §3.3).

* :class:`VersionedCache` — hasil mahal (JSON kapasitas, file Excel, daftar aplikasi) disimpan per
  *versi data*. Versi = id ``collect_run`` sukses terakhir, jadi cache **tidak pernah basi**: data
  baru → versi baru → kunci baru. Tidak ada TTL tebakan.
* :class:`VersionMemo` — versi data itu sendiri diingat beberapa detik agar request beruntun tidak
  menanyakan DB; dibuang seketika oleh :class:`ChangeListener` saat job mengirim ``NOTIFY``.
* :class:`ChangeListener` — thread ``LISTEN atlas_data_changed`` dengan reconnect otomatis. Bila
  putus, memo tetap kedaluwarsa sendiri (fallback polling), jadi data tetap segar.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

import psycopg

from atlas.core.config import Settings
from atlas.core.logging import log_event

logger = logging.getLogger("atlas.web.cache")
CHANNEL = "atlas_data_changed"


class VersionedCache:
    def __init__(self, max_entries: int = 64) -> None:
        self.max_entries = max_entries
        self._data: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_build(self, key: Hashable, build: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
        value = build()  # dibangun di luar lock; dua request bersamaan paling buruk membangun dua kali
        with self._lock:
            self.misses += 1
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class VersionMemo:
    def __init__(self, ttl_s: float = 10.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = ttl_s
        self.clock = clock
        self._value: Any = None
        self._at = 0.0
        self._lock = threading.Lock()

    def get(self, load: Callable[[], Any]) -> Any:
        with self._lock:
            if self._value is not None and self.clock() - self._at < self.ttl_s:
                return self._value
        value = load()
        with self._lock:
            self._value, self._at = value, self.clock()
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._value = None


class ChangeListener:
    def __init__(self, settings: Settings, on_change: Callable[[dict[str, Any]], None]) -> None:
        self.settings = settings
        self.on_change = on_change
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="atlas-listen", daemon=True)
        self.connected = False

    def start(self) -> ChangeListener:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=7)

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                conninfo = self.settings.db_conninfo("web", application_name="atlas-web-listen")
                with psycopg.connect(conninfo, autocommit=True) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    self.connected, backoff = True, 1.0
                    while not self._stop.is_set():
                        for note in conn.notifies(timeout=5, stop_after=1):
                            self._handle(note.payload)
            except psycopg.Error as exc:
                if self.connected:
                    log_event(
                        logger,
                        "db",
                        "db_connect_failed",
                        "LISTEN perubahan data terputus; cache memakai kedaluwarsa otomatis",
                        severity="warning",
                        reason=str(exc),
                    )
                self.connected = False
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 60.0)

    def _handle(self, payload: str) -> None:
        try:
            data = json.loads(payload) if payload else {}
        except ValueError:
            data = {"raw": payload}
        self.on_change(data)
        log_event(logger, "app", "cache_invalidated", "Cache dibuang: data baru dari job", **data)
