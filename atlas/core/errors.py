"""Error aplikasi ATLAS.

Setiap error yang sampai ke user membawa ID error (mis. ``ERR-7F3A2C``). ID yang sama ditulis
ke file log dan tabel audit, sehingga keluhan user bisa langsung dicari di menu Audit Log
(design 05 §2).
"""

from __future__ import annotations

import re
import secrets

ERROR_ID_PATTERN = re.compile(r"^ERR-[0-9A-F]{6}$")


def new_error_id() -> str:
    """ID error pendek, mudah dibacakan user lewat telepon/chat."""
    return f"ERR-{secrets.token_hex(3).upper()}"


class AtlasError(Exception):
    """Error dasar. ``message`` untuk log (teknis), ``user_message`` untuk ditampilkan ke user."""

    default_user_message = "Terjadi kesalahan pada sistem."

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        error_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.user_message = user_message or self.default_user_message
        self.error_id = error_id or new_error_id()
        self.details = details or {}

    def to_user(self) -> dict[str, str]:
        """Bentuk aman untuk respons API / pesan bot: tanpa detail teknis atau stack trace."""
        return {"error": self.user_message, "error_id": self.error_id}

    def __str__(self) -> str:
        return f"[{self.error_id}] {self.message}"


class ConfigError(AtlasError):
    default_user_message = "Konfigurasi aplikasi tidak valid."


class DatabaseError(AtlasError):
    default_user_message = "Database sedang tidak dapat diakses. Silakan coba lagi beberapa saat."


class ValidationError(AtlasError):
    default_user_message = "Input tidak valid."


class NotFoundError(AtlasError):
    default_user_message = "Data tidak ditemukan."
