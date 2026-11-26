from __future__ import annotations

from atlas.core.errors import (
    ERROR_ID_PATTERN,
    AtlasError,
    DatabaseError,
    NotFoundError,
    new_error_id,
)


def test_error_id_format_and_uniqueness():
    ids = {new_error_id() for _ in range(2000)}
    assert all(ERROR_ID_PATTERN.match(i) for i in ids)
    assert len(ids) > 1990  # 16,7 juta kemungkinan; tabrakan sangat jarang


def test_error_carries_id_and_safe_user_payload():
    err = AtlasError("koneksi ke 10.0.0.1 ditolak", details={"host": "10.0.0.1"})
    payload = err.to_user()
    assert set(payload) == {"error", "error_id"}
    assert payload["error_id"] == err.error_id
    assert "10.0.0.1" not in payload["error"]  # detail teknis tidak bocor ke user
    assert err.error_id in str(err)


def test_explicit_error_id_and_user_message_are_kept():
    err = NotFoundError("host abc tidak ada", user_message="Hostname tidak ditemukan.", error_id="ERR-ABC123")
    assert err.to_user() == {"error": "Hostname tidak ditemukan.", "error_id": "ERR-ABC123"}


def test_subclass_default_message():
    assert "Database" in DatabaseError("x").user_message
    assert isinstance(DatabaseError("x"), AtlasError)
