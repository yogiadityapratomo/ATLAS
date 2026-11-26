"""Logging ATLAS: satu baris JSON per event, rotasi harian, filter secret, request_id.

Semua komponen (web, job, bot) mencatat lewat modul ini. Event audit (design 05 §2) ditulis
dengan :func:`log_event`; di PR-2 penulis audit write-behind memakai record yang sama untuk
mengisi tabel ``audit.event``, sehingga file log dan tabel selalu konsisten.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import socket
import sys
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from atlas import __version__

if TYPE_CHECKING:
    from atlas.core.config import Settings

CATEGORIES = ("web", "app", "db", "job", "security", "system", "bot")
SEVERITIES = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}
EVENT_ATTR = "atlas_event"
REDACTED = "***"
LOG_RETENTION_DAYS = 30
_HANDLER_TAG = "_atlas_handler"

# ---------------------------------------------------------------------------- request_id

_request_id: ContextVar[str | None] = ContextVar("atlas_request_id", default=None)


def new_request_id() -> str:
    return str(uuid.uuid4())


def get_request_id() -> str | None:
    return _request_id.get()


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """Semua log di dalam blok ini membawa ``request_id`` yang sama (per request web / per run job)."""
    rid = request_id or new_request_id()
    token = _request_id.set(rid)
    try:
        yield rid
    finally:
        _request_id.reset(token)


# ---------------------------------------------------------------------------- filter secret

_SECRET_WORDS = r"password|passwd|pwd|secret|token|api[_-]?key"  # noqa: S105 — pola regex, bukan password
_SENSITIVE_KEY = re.compile(rf"({_SECRET_WORDS}|authorization|cookie|conninfo|dsn)", re.IGNORECASE)
_TEXT_PATTERNS = [
    # key=value / key: value / "key": "value"  (password=..., ATLAS_DB_PASSWORD_WEB=..., api_key="...")
    (
        re.compile(
            rf"""(?P<k>(?<![A-Za-z])(?:{_SECRET_WORDS})[A-Za-z0-9_]*["']?\s*[:=]\s*["']?)"""
            r"""(?P<v>[^\s"',;&}]+)""",
            re.IGNORECASE,
        ),
        r"\g<k>" + REDACTED,
    ),
    # Authorization: Bearer xxx / Basic xxx
    (
        re.compile(r"(?P<k>\b(?:Bearer|Basic)\s+)(?P<v>[A-Za-z0-9._~+/=-]+)", re.IGNORECASE),
        r"\g<k>" + REDACTED,
    ),
    # URL dengan kredensial: postgresql://user:pass@host
    (re.compile(r"(?P<k>://[^:/@\s]+:)(?P<v>[^@\s]+)(?=@)"), r"\g<k>" + REDACTED),
]
_MIN_SECRET_LEN = 4


class SecretRedactor:
    """Menyamarkan secret di teks dan struktur data sebelum ditulis ke log/audit.

    Dua lapis: (1) nilai secret yang dikenal (dari config) dicari apa adanya; (2) pola umum
    seperti ``password=...`` atau ``Bearer ...``. Key dict yang sensitif selalu disamarkan.
    """

    def __init__(self) -> None:
        self._known: set[str] = set()
        self._lock = threading.Lock()

    def add_secret(self, value: str | None) -> None:
        if value and len(value) >= _MIN_SECRET_LEN:
            with self._lock:
                self._known.add(value)

    def clear(self) -> None:
        with self._lock:
            self._known.clear()

    def redact_text(self, text: str) -> str:
        with self._lock:
            known = sorted(self._known, key=len, reverse=True)
        for value in known:
            if value in text:
                text = text.replace(value, REDACTED)
        for pattern, repl in _TEXT_PATTERNS:
            text = pattern.sub(repl, text)
        return text

    def redact(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.redact_text(obj)
        if isinstance(obj, dict):
            return {
                k: (REDACTED if isinstance(k, str) and _SENSITIVE_KEY.search(k) else self.redact(v))
                for k, v in obj.items()
            }
        if isinstance(obj, (list, tuple, set)):
            return [self.redact(v) for v in obj]
        return obj


REDACTOR = SecretRedactor()

# ---------------------------------------------------------------------------- formatter

_HOST = socket.gethostname()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class JsonFormatter(logging.Formatter):
    """Satu baris JSON per record; field event audit disertakan bila ada."""

    def __init__(self, component: str, redactor: SecretRedactor = REDACTOR) -> None:
        super().__init__()
        self.component = component
        self.redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = getattr(record, EVENT_ATTR, None) or {}
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "component": self.component,
            "logger": record.name,
            "message": self.redactor.redact_text(record.getMessage()),
            "request_id": event.get("request_id") or get_request_id(),
        }
        for key in ("category", "event_type", "error_id", "actor", "duration_ms"):
            if event.get(key) is not None:
                payload[key] = event[key]
        if event.get("details"):
            payload["details"] = self.redactor.redact(event["details"])
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["traceback"] = self.redactor.redact_text(self.formatException(record.exc_info))
        payload.update(host=_HOST, pid=record.process, app_version=__version__)
        return json.dumps(payload, ensure_ascii=False, default=_json_default)


class ConsoleFormatter(logging.Formatter):
    """Format ringkas untuk terminal DEV; tetap melewati filter secret."""

    def __init__(self, redactor: SecretRedactor = REDACTOR) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
        self.redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        event = getattr(record, EVENT_ATTR, None) or {}
        if event.get("event_type"):
            line += f" [{event['category']}/{event['event_type']}]"
        if event.get("error_id"):
            line += f" {event['error_id']}"
        return self.redactor.redact_text(line)


# ---------------------------------------------------------------------------- API


def log_event(
    logger: logging.Logger,
    category: str,
    event_type: str,
    message: str,
    *,
    severity: str = "info",
    error_id: str | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
    request_id: str | None = None,
    exc_info: bool = False,
    **details: Any,
) -> None:
    """Catat satu event audit (design 05 §2). ``details`` = data terstruktur tambahan."""
    if category not in CATEGORIES:
        raise ValueError(f"kategori event tidak dikenal: {category!r}")
    if severity not in SEVERITIES:
        raise ValueError(f"severity tidak dikenal: {severity!r}")
    event = {
        "category": category,
        "event_type": event_type,
        "severity": severity,
        "error_id": error_id,
        "actor": actor,
        "duration_ms": duration_ms,
        "request_id": request_id or get_request_id(),
        "details": details,
    }
    logger.log(SEVERITIES[severity], message, exc_info=exc_info, extra={EVENT_ATTR: event})


def setup_logging(
    settings: Settings, component: str, *, console: bool = True, announce: bool = True
) -> logging.Logger:
    """Pasang handler file JSON (rotasi tengah malam, simpan 30 hari) + konsol.

    Satu file per komponen (``logs/web.log``, ``logs/capacity_job.log``, …) agar dua proses
    tidak berebut rotasi file yang sama di Windows. Aman dipanggil ulang (handler lama diganti).
    ``announce=False``: event ``config_loaded`` ditunda — panggil :func:`announce_startup` setelah
    penulis audit terpasang agar event itu juga masuk ``audit.event``.
    """
    for secret in settings.secret_values():
        REDACTOR.add_secret(secret)

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            root.removeHandler(handler)
            handler.close()
    root.setLevel(SEVERITIES[settings.log_level])

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        settings.log_dir / f"{component}.log",
        when="midnight",
        backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setFormatter(JsonFormatter(component))
    handlers: list[logging.Handler] = [file_handler]
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(ConsoleFormatter())
        handlers.append(stream)
    for handler in handlers:
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)

    logger = logging.getLogger(f"atlas.{component}")
    if announce:
        announce_startup(settings, logger)
    return logger


def announce_startup(settings: Settings, logger: logging.Logger) -> None:
    log_event(
        logger,
        "system",
        "config_loaded",
        "Konfigurasi dimuat",
        env=settings.env,
        log_level=settings.log_level,
        db=settings.db_target("app"),
        allow_live_nbu=settings.allow_live_nbu,
        pid=os.getpid(),
    )
