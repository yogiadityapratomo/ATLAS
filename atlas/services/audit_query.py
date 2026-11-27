"""Validasi filter menu Audit Log & cursor keyset (design 05 §4)."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta
from typing import Any

from atlas.core.errors import ERROR_ID_PATTERN, ValidationError
from atlas.core.logging import CATEGORIES, SEVERITIES
from atlas.repositories.audit import EventFilter

RANGES = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
MAX_PAGE = 200
EXPORT_LIMIT = 50_000


def parse_filter(
    *,
    now: datetime,
    range_: str = "24h",
    category: str | None = None,
    severity: str | None = None,
    component: str | None = None,
    event_type: str | None = None,
    q: str | None = None,
    request_id: str | None = None,
    error_id: str | None = None,
) -> EventFilter:
    if range_ not in RANGES:
        raise ValidationError(f"range tidak dikenal: {range_}", user_message="Rentang waktu tidak valid.")
    if category and category not in CATEGORIES:
        raise ValidationError(f"kategori tidak dikenal: {category}", user_message="Kategori tidak valid.")
    if severity and severity not in SEVERITIES:
        raise ValidationError(f"level tidak dikenal: {severity}", user_message="Level tidak valid.")
    rid = (request_id or "").strip() or None
    if rid:
        try:
            rid = str(uuid.UUID(rid))
        except ValueError as exc:
            raise ValidationError("request_id bukan UUID", user_message="Request ID tidak valid.") from exc
    eid = (error_id or "").strip().upper() or None
    if eid and not ERROR_ID_PATTERN.match(eid):
        raise ValidationError("error_id tidak valid", user_message="Format Error ID: ERR-XXXXXX.")
    # mencari berdasarkan ID: abaikan rentang waktu pendek (ID bisa dari laporan user beberapa hari lalu)
    span = RANGES["30d"] if (rid or eid) else RANGES[range_]
    return EventFilter(
        since=now - span,
        until=now + timedelta(minutes=5),
        category=category or None,
        min_severity=severity or None,
        component=(component or "").strip() or None,
        event_type=(event_type or "").strip() or None,
        request_id=rid,
        error_id=eid,
        q=(q or "").strip()[:200] or None,
    )


def encode_cursor(occurred_at: datetime, event_id: int) -> str:
    raw = f"{occurred_at.isoformat()}|{event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[datetime, int] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, event_id = base64.urlsafe_b64decode(padded.encode()).decode().split("|")
        return datetime.fromisoformat(at), int(event_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("cursor tidak valid", user_message="Halaman tidak valid; muat ulang.") from exc


def to_json(row: dict[str, Any], tz) -> dict[str, Any]:
    out = dict(row)
    out["occurred_at"] = row["occurred_at"].astimezone(tz).isoformat(timespec="milliseconds")
    out["request_id"] = str(row["request_id"]) if row.get("request_id") else None
    return out
