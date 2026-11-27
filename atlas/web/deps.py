"""State aplikasi web yang dipakai bersama route (pool DB, cache, versi data)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg
from fastapi import Request

from atlas.core.audit import AuditHandler
from atlas.core.config import Settings
from atlas.core.db import Database
from atlas.web.cache import ChangeListener, VersionedCache, VersionMemo


@dataclass
class AppState:
    settings: Settings
    db: Database
    cache: VersionedCache = field(default_factory=VersionedCache)
    versions: VersionMemo = field(default_factory=VersionMemo)
    audit: AuditHandler | None = None
    listener: ChangeListener | None = None

    def invalidate(self, _payload: dict | None = None) -> None:
        self.versions.invalidate()
        self.cache.clear()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """Koneksi baca dari pool web; dibuka dalam transaksi read-only."""
        with self.db.connection() as conn:
            conn.read_only = True
            try:
                yield conn
            finally:
                if not conn.broken:
                    conn.rollback()
                    conn.read_only = False


def get_state(request: Request) -> AppState:
    return request.app.state.atlas
