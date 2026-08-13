"""PostgreSQL integration tests for repository / producer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hms_outbox.constants import EventStatus
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.producer.producer import OutboxProducer
from tests.conftest import make_event

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_insert_claim_sync_flow(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                organization_id=1,
                event_type="CUSTOMER_INVOICE",
                event_group="CUSTOMER-1",
                group_sequence=1,
                payload={"x": 1},
                reference_type="INVOICE",
                reference="INV-1",
            )

    async with async_session_factory() as session:
        async with session.begin():
            claimed = await repository.claim_next_async(
                session,
                worker_id="w1",
                initial_retry_delay_ms=10,
                retry_backoff_multiplier=2,
                max_retry_delay_ms=1000,
            )
            assert claimed is not None
            assert claimed.event_id == event_id
            assert claimed.status == EventStatus.PROCESSING.value
            assert claimed.worker_id == "w1"

    async with async_session_factory() as session:
        async with session.begin():
            ok = await repository.mark_synced_async(
                session,
                event_id=event_id,
                worker_id="w1",
                reply_reference_type="JOURNAL_ENTRY",
                reply_reference="JE-1",
            )
            assert ok

    async with async_session_factory() as session:
        event = await repository.get_required_async(session, event_id)
        assert event.status == EventStatus.SYNCED.value
        assert event.reply_reference == "JE-1"


@pytest.mark.asyncio
async def test_failed_and_exhaustion(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                organization_id=1,
                event_type="CUSTOMER_INVOICE",
                event_group="G-EX",
                group_sequence=1,
                payload={},
            )

    for expected_retry in (1, 2, 3):
        async with async_session_factory() as session:
            async with session.begin():
                claimed = await repository.claim_next_async(
                    session,
                    worker_id="w1",
                    initial_retry_delay_ms=0,
                    retry_backoff_multiplier=2,
                    max_retry_delay_ms=1000,
                )
                assert claimed is not None
                assert claimed.event_id == event_id

        exhausted = expected_retry >= 3
        async with async_session_factory() as session:
            async with session.begin():
                await repository.mark_failed_async(
                    session,
                    event_id=event_id,
                    worker_id="w1",
                    retry_count=expected_retry,
                    error_code="HTTP_500",
                    last_error="boom",
                    exhausted=exhausted,
                )

    async with async_session_factory() as session:
        event = await repository.get_required_async(session, event_id)
        assert event.status == EventStatus.RETRY_EXHAUSTED.value
        assert event.retry_count == 3


@pytest.mark.asyncio
async def test_processing_recovery(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
) -> None:
    event = make_event(status=EventStatus.PROCESSING.value)
    event.worker_id = "dead-worker"
    event.processing_started_at = datetime.now(timezone.utc) - timedelta(hours=1)

    async with async_session_factory() as session:
        async with session.begin():
            await repository.add_async(session, event)

    async with async_session_factory() as session:
        async with session.begin():
            recovered = await repository.recover_stale_processing_async(
                session, timeout_ms=1000
            )
            assert event.event_id in recovered

    async with async_session_factory() as session:
        row = await repository.get_required_async(session, event.event_id)
        assert row.status == EventStatus.FAILED.value
        assert row.error_code == "PROCESSING_TIMEOUT"
        assert row.retry_count == 1


@pytest.mark.asyncio
async def test_manual_retry(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
) -> None:
    event = make_event(status=EventStatus.RETRY_EXHAUSTED.value, retry_count=3)
    event.error_code = "HTTP_500"
    event.last_error = "fail"

    async with async_session_factory() as session:
        async with session.begin():
            await repository.add_async(session, event)
            reset = await repository.retry_event_async(session, event.event_id)
            assert reset.status == EventStatus.CREATED.value
            assert reset.retry_count == 0
            assert reset.error_code is None


@pytest.mark.asyncio
async def test_retry_group_only_retry_exhausted(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
) -> None:
    failed = make_event(
        event_group="GRP", group_sequence=1, status=EventStatus.FAILED.value, retry_count=1
    )
    exhausted = make_event(
        event_group="GRP",
        group_sequence=2,
        status=EventStatus.RETRY_EXHAUSTED.value,
        retry_count=3,
    )
    async with async_session_factory() as session:
        async with session.begin():
            await repository.add_async(session, failed)
            await repository.add_async(session, exhausted)
            result = await repository.retry_group_async(session, 1, "GRP")
            assert result is not None
            assert result.event_id == exhausted.event_id
            assert result.status == EventStatus.CREATED.value

    async with async_session_factory() as session:
        still_failed = await repository.get_required_async(session, failed.event_id)
        assert still_failed.status == EventStatus.FAILED.value


@pytest.mark.asyncio
async def test_ownership_prevents_stale_update(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                organization_id=1,
                event_type="CUSTOMER_INVOICE",
                event_group="OWN",
                group_sequence=1,
                payload={},
            )
    async with async_session_factory() as session:
        async with session.begin():
            claimed = await repository.claim_next_async(
                session,
                worker_id="w1",
                initial_retry_delay_ms=0,
                retry_backoff_multiplier=2,
                max_retry_delay_ms=1000,
            )
            assert claimed is not None

    async with async_session_factory() as session:
        async with session.begin():
            ok = await repository.mark_synced_async(
                session,
                event_id=event_id,
                worker_id="other-worker",
                reply_reference_type="JE",
                reply_reference="1",
            )
            assert ok is False
