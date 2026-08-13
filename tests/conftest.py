"""Shared pytest fixtures."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from hms_outbox.config.settings import OutboxSettings
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.db.session import create_async_db_engine, create_sync_engine
from hms_outbox.models.event import Base, OutboxEvent
from hms_outbox.producer.producer import OutboxProducer

_CONTAINER: Any = None


def _database_url() -> str | None:
    return os.environ.get("OUTBOX_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture
def settings() -> OutboxSettings:
    return OutboxSettings(
        database_url="postgresql+asyncpg://outbox:outbox@localhost:5432/outbox",
        replay_enabled=True,
        worker_count=2,
        poll_interval_ms=50,
        processing_timeout_ms=1000,
        max_retry_count=3,
        initial_retry_delay_ms=10,
        retry_backoff_multiplier=2.0,
        max_retry_delay_ms=1000,
        retry_jitter=False,
        http_connect_timeout_ms=1000,
        http_read_timeout_ms=2000,
        http_total_timeout_ms=3000,
        admin_api_key="test-admin-key",
        endpoints={},
        static_headers={},
    )


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    global _CONTAINER
    url = _database_url()
    if not url:
        try:
            from testcontainers.postgres import PostgresContainer

            _CONTAINER = PostgresContainer("postgres:16-alpine")
            _CONTAINER.start()
            raw = _CONTAINER.get_connection_url()
            if raw.startswith("postgresql+psycopg2://"):
                raw = raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
            elif raw.startswith("postgresql://"):
                raw = raw.replace("postgresql://", "postgresql+asyncpg://", 1)
            os.environ["OUTBOX_TEST_DATABASE_URL"] = raw
            url = raw
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"PostgreSQL not available for integration tests: {exc}")
    assert url is not None
    if "+asyncpg" not in url and url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    yield url
    if _CONTAINER is not None:
        _CONTAINER.stop()


@pytest_asyncio.fixture
async def async_engine(pg_url: str) -> AsyncIterator[AsyncEngine]:
    settings = OutboxSettings(database_url=pg_url)
    engine = create_async_db_engine(settings, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session_factory(
    async_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = async_sessionmaker(bind=async_engine, expire_on_commit=False)
    # Truncate between tests that share the session-scoped DB
    async with async_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {OutboxEvent.__tablename__} RESTART IDENTITY CASCADE"))
    yield factory


@pytest.fixture
def sync_engine(pg_url: str) -> Iterator[Any]:
    settings = OutboxSettings(database_url=pg_url)
    engine = create_sync_engine(settings, poolclass=NullPool)
    Base.metadata.create_all(engine)
    yield engine
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {OutboxEvent.__tablename__} RESTART IDENTITY CASCADE"))
    engine.dispose()


@pytest.fixture
def sync_session_factory(sync_engine: Any) -> sessionmaker[Session]:
    return sessionmaker(bind=sync_engine, expire_on_commit=False)


@pytest.fixture
def repository() -> OutboxRepository:
    return OutboxRepository(OutboxEvent)


@pytest.fixture
def producer() -> OutboxProducer:
    return OutboxProducer()


def make_event(
    *,
    organization_id: int = 1,
    event_type: str = "CUSTOMER_INVOICE",
    event_group: str = "CUSTOMER-1",
    group_sequence: int = 1,
    payload: dict[str, Any] | None = None,
    status: str = "CREATED",
    retry_count: int = 0,
    event_id: uuid.UUID | None = None,
) -> OutboxEvent:
    return OutboxEvent(
        event_id=event_id or uuid.uuid4(),
        organization_id=organization_id,
        event_type=event_type,
        event_group=event_group,
        group_sequence=group_sequence,
        reference_type="INVOICE",
        reference=f"INV-{group_sequence}",
        payload=payload or {"ok": True},
        status=status,
        retry_count=retry_count,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
