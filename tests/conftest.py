from __future__ import annotations

import logging
from collections.abc import Callable

import pytest

from atlas.core.config import Settings, load_settings
from atlas.core.logging import EVENT_ATTR, REDACTOR


@pytest.fixture
def make_settings(tmp_path) -> Callable[..., Settings]:
    """Settings dari environ buatan (tidak membaca .env / environment mesin)."""

    def _make(**env: str) -> Settings:
        base = {"ATLAS_LOG_DIR": str(tmp_path / "logs")}
        base.update(env)
        return load_settings(environ=base)

    return _make


@pytest.fixture(autouse=True)
def _reset_redactor():
    REDACTOR.clear()
    yield
    REDACTOR.clear()


@pytest.fixture
def events(caplog) -> Callable[[], list[dict]]:
    """Daftar event audit (``log_event``) yang tercatat selama test."""
    caplog.set_level(logging.DEBUG)

    def _events() -> list[dict]:
        return [getattr(r, EVENT_ATTR) for r in caplog.records if hasattr(r, EVENT_ATTR)]

    return _events
