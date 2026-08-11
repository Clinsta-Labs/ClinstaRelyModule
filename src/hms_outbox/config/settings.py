"""Configuration loading and validation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse

from hms_outbox.constants import DEFAULT_TABLE_NAME, EVENT_TYPE_PATTERN, TABLE_NAME_PATTERN
from hms_outbox.exceptions import ConfigurationError


def _env(name: str, default: str | None = None, *, environ: Mapping[str, str] | None = None) -> str | None:
    source = environ if environ is not None else os.environ
    value = source.get(name)
    if value is None or value == "":
        return default
    return value


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"Invalid boolean value: {value!r}")


def _parse_int(name: str, value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {value!r}") from exc


def _parse_float(name: str, value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {value!r}") from exc


def _validate_url(name: str, url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"{name} must be a valid http(s) URL, got {url!r}")


def _validate_database_url(url: str) -> None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ConfigurationError(f"DATABASE_URL is invalid: {url!r}")
    scheme = parsed.scheme.lower()
    if "postgresql" not in scheme and "postgres" not in scheme:
        raise ConfigurationError(
            f"DATABASE_URL must use PostgreSQL (got scheme {parsed.scheme!r})"
        )


def _validate_table_name(name: str) -> str:
    if not re.fullmatch(TABLE_NAME_PATTERN, name):
        raise ConfigurationError(
            f"OUTBOX_TABLE_NAME must match {TABLE_NAME_PATTERN}, got {name!r}"
        )
    return name


def _validate_event_type(event_type: str) -> str:
    if not re.fullmatch(EVENT_TYPE_PATTERN, event_type):
        raise ConfigurationError(
            f"Event type must match {EVENT_TYPE_PATTERN}, got {event_type!r}"
        )
    return event_type


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    """Resolved endpoint configuration for a single EventType."""

    event_type: str
    url: str
    timeout_ms: int | None = None


@dataclass(slots=True)
class OutboxSettings:
    """All environment-driven Outbox settings."""

    database_url: str
    table_name: str = DEFAULT_TABLE_NAME
    replay_enabled: bool = False
    worker_count: int = 10
    poll_interval_ms: int = 1000
    processing_timeout_ms: int = 60000
    max_retry_count: int = 5
    initial_retry_delay_ms: int = 10000
    retry_backoff_multiplier: float = 2.0
    max_retry_delay_ms: int = 900000
    retry_jitter: bool = True
    http_connect_timeout_ms: int = 5000
    http_read_timeout_ms: int = 30000
    http_total_timeout_ms: int = 60000
    log_payload: bool = False
    admin_api_key: str | None = None
    endpoints: dict[str, EndpointConfig] = field(default_factory=dict)
    static_headers: dict[str, str] = field(default_factory=dict)

    @property
    def sync_database_url(self) -> str:
        """Return a sync-compatible SQLAlchemy URL (psycopg3)."""
        url = self.database_url
        if "+asyncpg" in url:
            return url.replace("+asyncpg", "+psycopg")
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        return url

    @property
    def async_database_url(self) -> str:
        """Return an async-compatible SQLAlchemy URL (asyncpg)."""
        url = self.database_url
        if "+psycopg" in url:
            return url.replace("+psycopg", "+asyncpg")
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url


def load_settings(environ: Mapping[str, str] | None = None, *, validate: bool = True) -> OutboxSettings:
    """Load and optionally validate settings from environment variables."""
    env = environ if environ is not None else os.environ

    database_url = _env("OUTBOX_DATABASE_URL", None, environ=env) or _env(
        "DATABASE_URL", None, environ=env
    )
    if not database_url:
        raise ConfigurationError(
            "DATABASE_URL (or OUTBOX_DATABASE_URL) is required"
        )
    _validate_database_url(database_url)

    table_name = _validate_table_name(
        _env("OUTBOX_TABLE_NAME", DEFAULT_TABLE_NAME, environ=env) or DEFAULT_TABLE_NAME
    )

    settings = OutboxSettings(
        database_url=database_url,
        table_name=table_name,
        replay_enabled=_parse_bool(_env("OUTBOX_REPLAY_ENABLED", "false", environ=env), False),
        worker_count=_parse_int(
            "OUTBOX_REPLAY_WORKER_COUNT",
            _env("OUTBOX_REPLAY_WORKER_COUNT", "10", environ=env),
            10,
        ),
        poll_interval_ms=_parse_int(
            "OUTBOX_REPLAY_POLL_INTERVAL_MS",
            _env("OUTBOX_REPLAY_POLL_INTERVAL_MS", "1000", environ=env),
            1000,
        ),
        processing_timeout_ms=_parse_int(
            "OUTBOX_REPLAY_PROCESSING_TIMEOUT_MS",
            _env("OUTBOX_REPLAY_PROCESSING_TIMEOUT_MS", "60000", environ=env),
            60000,
        ),
        max_retry_count=_parse_int(
            "OUTBOX_REPLAY_MAX_RETRY_COUNT",
            _env("OUTBOX_REPLAY_MAX_RETRY_COUNT", "5", environ=env),
            5,
        ),
        initial_retry_delay_ms=_parse_int(
            "OUTBOX_REPLAY_INITIAL_RETRY_DELAY_MS",
            _env("OUTBOX_REPLAY_INITIAL_RETRY_DELAY_MS", "10000", environ=env),
            10000,
        ),
        retry_backoff_multiplier=_parse_float(
            "OUTBOX_REPLAY_RETRY_BACKOFF_MULTIPLIER",
            _env("OUTBOX_REPLAY_RETRY_BACKOFF_MULTIPLIER", "2", environ=env),
            2.0,
        ),
        max_retry_delay_ms=_parse_int(
            "OUTBOX_REPLAY_MAX_RETRY_DELAY_MS",
            _env("OUTBOX_REPLAY_MAX_RETRY_DELAY_MS", "900000", environ=env),
            900000,
        ),
        retry_jitter=_parse_bool(
            _env("OUTBOX_REPLAY_RETRY_JITTER", "true", environ=env), True
        ),
        http_connect_timeout_ms=_parse_int(
            "OUTBOX_REPLAY_HTTP_CONNECT_TIMEOUT_MS",
            _env("OUTBOX_REPLAY_HTTP_CONNECT_TIMEOUT_MS", "5000", environ=env),
            5000,
        ),
        http_read_timeout_ms=_parse_int(
            "OUTBOX_REPLAY_HTTP_READ_TIMEOUT_MS",
            _env("OUTBOX_REPLAY_HTTP_READ_TIMEOUT_MS", "30000", environ=env),
            30000,
        ),
        http_total_timeout_ms=_parse_int(
            "OUTBOX_REPLAY_HTTP_TOTAL_TIMEOUT_MS",
            _env("OUTBOX_REPLAY_HTTP_TOTAL_TIMEOUT_MS", "60000", environ=env),
            60000,
        ),
        log_payload=_parse_bool(
            _env("OUTBOX_REPLAY_LOG_PAYLOAD", "false", environ=env), False
        ),
        admin_api_key=_env("OUTBOX_ADMIN_API_KEY", None, environ=env),
        endpoints=_discover_endpoints(env),
        static_headers=_discover_headers(env),
    )

    if validate:
        validate_settings(settings)
    return settings


def _discover_endpoints(env: Mapping[str, str]) -> dict[str, EndpointConfig]:
    prefix = "OUTBOX_REPLAY_ENDPOINT_"
    timeout_prefix = "OUTBOX_REPLAY_TIMEOUT_"
    endpoints: dict[str, EndpointConfig] = {}
    for key, value in env.items():
        if not key.startswith(prefix) or not value:
            continue
        event_type = _validate_event_type(key[len(prefix) :])
        _validate_url(key, value)
        timeout_key = f"{timeout_prefix}{event_type}_MS"
        timeout_raw = env.get(timeout_key)
        timeout_ms = None
        if timeout_raw:
            timeout_ms = _parse_int(timeout_key, timeout_raw, 0)
            if timeout_ms <= 0:
                raise ConfigurationError(f"{timeout_key} must be > 0")
        endpoints[event_type] = EndpointConfig(
            event_type=event_type, url=value, timeout_ms=timeout_ms
        )
    return endpoints


def _discover_headers(env: Mapping[str, str]) -> dict[str, str]:
    prefix = "OUTBOX_REPLAY_HEADER_"
    headers: dict[str, str] = {}
    for key, value in env.items():
        if not key.startswith(prefix) or value is None:
            continue
        header_name = key[len(prefix) :].replace("_", "-")
        if not header_name:
            raise ConfigurationError(f"Invalid header variable: {key}")
        headers[header_name] = value
    return headers


def validate_settings(settings: OutboxSettings, *, require_replay: bool = False) -> None:
    """Fail-fast validation of settings."""
    if settings.worker_count <= 0:
        raise ConfigurationError("OUTBOX_REPLAY_WORKER_COUNT must be > 0")
    if settings.max_retry_count < 0:
        raise ConfigurationError("OUTBOX_REPLAY_MAX_RETRY_COUNT must be >= 0")
    if settings.poll_interval_ms < 0:
        raise ConfigurationError("OUTBOX_REPLAY_POLL_INTERVAL_MS must be >= 0")
    if settings.processing_timeout_ms <= 0:
        raise ConfigurationError("OUTBOX_REPLAY_PROCESSING_TIMEOUT_MS must be > 0")
    if settings.retry_backoff_multiplier < 1:
        raise ConfigurationError("OUTBOX_REPLAY_RETRY_BACKOFF_MULTIPLIER must be >= 1")
    if settings.initial_retry_delay_ms < 0:
        raise ConfigurationError("OUTBOX_REPLAY_INITIAL_RETRY_DELAY_MS must be >= 0")
    if settings.max_retry_delay_ms < 0:
        raise ConfigurationError("OUTBOX_REPLAY_MAX_RETRY_DELAY_MS must be >= 0")
    if settings.http_connect_timeout_ms <= 0:
        raise ConfigurationError("OUTBOX_REPLAY_HTTP_CONNECT_TIMEOUT_MS must be > 0")
    if settings.http_read_timeout_ms <= 0:
        raise ConfigurationError("OUTBOX_REPLAY_HTTP_READ_TIMEOUT_MS must be > 0")
    if settings.http_total_timeout_ms <= 0:
        raise ConfigurationError("OUTBOX_REPLAY_HTTP_TOTAL_TIMEOUT_MS must be > 0")
    _validate_database_url(settings.database_url)
    _validate_table_name(settings.table_name)
    for endpoint in settings.endpoints.values():
        _validate_event_type(endpoint.event_type)
        _validate_url(f"OUTBOX_REPLAY_ENDPOINT_{endpoint.event_type}", endpoint.url)
    if require_replay and not settings.replay_enabled:
        raise ConfigurationError("OUTBOX_REPLAY_ENABLED must be true to start replay")
