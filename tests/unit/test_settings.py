"""Unit tests for configuration loading."""

from __future__ import annotations

import pytest

from hms_outbox.config.settings import load_settings
from hms_outbox.exceptions import ConfigurationError


def test_defaults_and_endpoint_discovery() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "OUTBOX_REPLAY_ENDPOINT_CUSTOMER_INVOICE": "http://accounting/invoice",
        "OUTBOX_REPLAY_ENDPOINT_CUSTOMER_PAYMENT": "http://accounting/payment?x=1",
        "OUTBOX_REPLAY_TIMEOUT_CUSTOMER_INVOICE_MS": "60000",
        "OUTBOX_REPLAY_HEADER_X_SERVICE_NAME": "pharmacy",
        "OUTBOX_REPLAY_HEADER_AUTHORIZATION": "Bearer secret",
    }
    settings = load_settings(env)
    assert settings.worker_count == 10
    assert settings.retry_jitter is True
    assert "CUSTOMER_INVOICE" in settings.endpoints
    assert settings.endpoints["CUSTOMER_INVOICE"].timeout_ms == 60000
    assert settings.static_headers["X-SERVICE-NAME"] == "pharmacy"
    assert settings.static_headers["AUTHORIZATION"] == "Bearer secret"


def test_outbox_database_url_override() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://a:a@localhost:5432/a",
        "OUTBOX_DATABASE_URL": "postgresql+asyncpg://b:b@localhost:5432/b",
    }
    settings = load_settings(env)
    assert "b:b@" in settings.database_url


def test_invalid_worker_count() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "OUTBOX_REPLAY_WORKER_COUNT": "0",
    }
    with pytest.raises(ConfigurationError):
        load_settings(env)


def test_invalid_boolean() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "OUTBOX_REPLAY_ENABLED": "maybe",
    }
    with pytest.raises(ConfigurationError):
        load_settings(env)


def test_invalid_endpoint_url() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "OUTBOX_REPLAY_ENDPOINT_CUSTOMER_INVOICE": "not-a-url",
    }
    with pytest.raises(ConfigurationError):
        load_settings(env)


def test_invalid_event_type_name() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "OUTBOX_REPLAY_ENDPOINT_customerInvoice": "http://x/y",
    }
    with pytest.raises(ConfigurationError):
        load_settings(env)


def test_invalid_table_name() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "OUTBOX_TABLE_NAME": "outbox;drop",
    }
    with pytest.raises(ConfigurationError):
        load_settings(env)


def test_missing_database_url() -> None:
    with pytest.raises(ConfigurationError):
        load_settings({})


def test_retry_multiplier_validation() -> None:
    env = {
        "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        "OUTBOX_REPLAY_RETRY_BACKOFF_MULTIPLIER": "0.5",
    }
    with pytest.raises(ConfigurationError):
        load_settings(env)


def test_sync_async_url_conversion() -> None:
    settings = load_settings(
        {"DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db"}
    )
    assert "+psycopg" in settings.sync_database_url
    assert "+asyncpg" in settings.async_database_url
