r"""Aplikasi web ATLAS (FastAPI) — membaca database, tidak pernah menembak master NBU.

Jalankan (DEV):
    .venv\Scripts\python.exe -m uvicorn atlas.web.main:app --host 127.0.0.1 --port 8000

* Setiap request ``/api/*`` → satu event audit ``web/http_request`` (request_id, status, durasi, IP).
* Error → respons ``{"error": "...", "error_id": "ERR-XXXXXX"}`` tanpa stack trace; ID yang sama ada
  di file log dan tabel audit.
* DB mati saat start → aplikasi tetap hidup; endpoint data menjawab 503 dengan ID error.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from atlas import __version__
from atlas.core.audit import start_audit
from atlas.core.config import REPO_ROOT, Settings, load_settings
from atlas.core.db import Database
from atlas.core.errors import AtlasError, DatabaseError, NotFoundError, ValidationError, new_error_id
from atlas.core.logging import announce_startup, log_event, new_request_id, request_context, setup_logging
from atlas.web.cache import ChangeListener
from atlas.web.deps import AppState
from atlas.web.routes import audit, capacity, health, inventory

logger = logging.getLogger("atlas.web")
FRONTEND_DIR = REPO_ROOT / "frontend"
STATUS_BY_ERROR = {DatabaseError: 503, ValidationError: 400, NotFoundError: 404}
QUIET_PATHS = ("/api/audit/", "/api/health")


def asset_version() -> str:
    """Hash isi file CSS/JS frontend (8 karakter) — berubah hanya bila isi aset berubah."""
    digest = hashlib.sha256()
    for path in sorted(FRONTEND_DIR.glob("**/*")):
        if path.suffix in (".css", ".js") and path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:8]


def create_app(
    settings: Settings | None = None, *, enable_audit: bool = True, enable_listener: bool = True
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log = setup_logging(settings, "web", announce=False)
        audit = start_audit(settings, "web", "web") if enable_audit else None
        announce_startup(settings, log)
        db = Database(settings, "web", "web")
        db.open(wait=True, raise_on_failure=False)
        state = AppState(settings=settings, db=db, audit=audit)
        if enable_listener:
            state.listener = ChangeListener(settings, state.invalidate).start()
        app.state.atlas = state
        log_event(log, "system", "app_started", f"Web ATLAS {__version__} mulai", version=__version__)
        try:
            yield
        finally:
            log_event(log, "system", "app_stopped", "Web ATLAS berhenti")
            if state.listener:
                state.listener.stop()
            db.close()
            if audit:
                logging.getLogger().removeHandler(audit)
                audit.close()

    app = FastAPI(title="ATLAS", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def audit_requests(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        started = time.monotonic()
        with request_context(request_id):
            response = await call_next(request)
            if request.url.path.startswith("/api/"):
                elapsed = int((time.monotonic() - started) * 1000)
                if response.status_code >= 500:
                    severity = "warning"
                elif request.method == "GET" and request.url.path.startswith(QUIET_PATHS):
                    severity = (
                        "debug"  # polling rutin (auto-refresh Audit Log, health) tidak membanjiri audit
                    )
                else:
                    severity = "info"
                log_event(
                    logger,
                    "web",
                    "http_request",
                    f"{request.method} {request.url.path} → {response.status_code} ({elapsed} ms)",
                    severity=severity,
                    actor=request.client.host if request.client else None,
                    duration_ms=elapsed,
                    method=request.method,
                    path=request.url.path,
                    query=str(request.url.query)[:500] or None,
                    status=response.status_code,
                    user_agent=(request.headers.get("user-agent") or "")[:200],
                )
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(AtlasError)
    async def atlas_error(request: Request, exc: AtlasError) -> JSONResponse:
        status = next((code for cls, code in STATUS_BY_ERROR.items() if isinstance(exc, cls)), 500)
        if not isinstance(exc, DatabaseError):  # DatabaseError sudah dicatat oleh atlas.core.db
            log_event(
                logger,
                "security" if isinstance(exc, ValidationError) else "app",
                "validation_failed" if isinstance(exc, ValidationError) else "request_failed",
                exc.message,
                severity="warning" if status < 500 else "error",
                error_id=exc.error_id,
                path=request.url.path,
            )
        return JSONResponse(exc.to_user(), status_code=status)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        error_id = new_error_id()
        log_event(
            logger,
            "app",
            "request_failed",
            f"Error tak terduga di {request.url.path}: {type(exc).__name__}",
            severity="error",
            error_id=error_id,
            exc_info=True,
            path=request.url.path,
        )
        return JSONResponse(
            {"error": "Terjadi kesalahan pada sistem.", "error_id": error_id}, status_code=500
        )

    app.include_router(capacity.router)
    app.include_router(health.router)
    app.include_router(inventory.router)
    app.include_router(audit.router)

    index_html = (
        (FRONTEND_DIR / "index.html")
        .read_text(encoding="utf-8")
        .replace("{{ASSET_VERSION}}", asset_version())
    )

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        # versi aset di URL CSS/JS: rilis baru → URL baru → browser tidak memakai file lama dari cache
        return HTMLResponse(index_html, headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return FileResponse(FRONTEND_DIR / "favicon.svg", media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    return app


def __getattr__(name: str):  # ``uvicorn atlas.web.main:app`` — app dibuat saat pertama diminta
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
