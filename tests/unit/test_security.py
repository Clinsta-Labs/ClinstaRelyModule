"""Security-focused unit tests."""

from __future__ import annotations

from hms_outbox.config.settings import load_settings
from hms_outbox.http.errors import sanitize_error_message


def test_authorization_not_preserved_in_sanitizer() -> None:
    msg = sanitize_error_message("failed Authorization: Bearer super-secret-token")
    assert "super-secret-token" not in msg


def test_payload_logging_flag_default_false() -> None:
    settings = load_settings(
        {"DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db"}
    )
    assert settings.log_payload is False
