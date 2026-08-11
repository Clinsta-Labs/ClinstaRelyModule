"""Concurrency / FIFO claim tests against PostgreSQL."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hms_outbox.constants import EventStatus
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.producer.producer import OutboxProducer

pytestmark = [pytest.mark.integration, pytest.mark.concurrency]


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_same_event(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await producer.publish_async(
                session,
                event_type="CUSTOMER_INVOICE",
                event_group="SAME",
                group_sequence=1,
                payload={},
            )

    async def claim(worker_id: str):
        async with async_session_factory() as session:
            async with session.begin():
                return await repository.claim_next_async(
                    session,
                    worker_id=worker_id,
                    initial_retry_delay_ms=0,
                    retry_backoff_multiplier=2,
                    max_retry_delay_ms=1000,
                )

    results = await asyncio.gather(claim("w1"), claim("w2"))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1


@pytest.mark.asyncio
async def test_different_groups_claimed_concurrently(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            for group in ("A", "B", "C"):
                await producer.publish_async(
                    session,
                    event_type="CUSTOMER_INVOICE",
                    event_group=group,
                    group_sequence=1,
                    payload={},
                )

    async def claim(worker_id: str):
        async with async_session_factory() as session:
            async with session.begin():
                return await repository.claim_next_async(
                    session,
                    worker_id=worker_id,
                    initial_retry_delay_ms=0,
                    retry_backoff_multiplier=2,
                    max_retry_delay_ms=1000,
                )

    results = await asyncio.gather(claim("w1"), claim("w2"), claim("w3"))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 3
    assert {c.event_group for c in claimed} == {"A", "B", "C"}


@pytest.mark.asyncio
async def test_same_group_not_claimed_concurrently(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            for seq in (1, 2):
                await producer.publish_async(
                    session,
                    event_type="CUSTOMER_INVOICE",
                    event_group="ONE",
                    group_sequence=seq,
                    payload={},
                )

    async def claim(worker_id: str):
        async with async_session_factory() as session:
            async with session.begin():
                return await repository.claim_next_async(
                    session,
                    worker_id=worker_id,
                    initial_retry_delay_ms=0,
                    retry_backoff_multiplier=2,
                    max_retry_delay_ms=1000,
                )

    results = await asyncio.gather(claim("w1"), claim("w2"))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1
    assert claimed[0].group_sequence == 1


@pytest.mark.asyncio
async def test_group_blocking_on_failure(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            ids = []
            for seq in (1, 2, 3, 4):
                ids.append(
                    await producer.publish_async(
                        session,
                        event_type="CUSTOMER_INVOICE",
                        event_group="BLOCK",
                        group_sequence=seq,
                        payload={},
                    )
                )

    # Process seq 1 success
    async with async_session_factory() as session:
        async with session.begin():
            c1 = await repository.claim_next_async(
                session,
                worker_id="w1",
                initial_retry_delay_ms=0,
                retry_backoff_multiplier=2,
                max_retry_delay_ms=1000,
            )
            assert c1 and c1.group_sequence == 1
    async with async_session_factory() as session:
        async with session.begin():
            await repository.mark_synced_async(
                session,
                event_id=c1.event_id,
                worker_id="w1",
                reply_reference_type="JE",
                reply_reference="1",
            )

    # Fail seq 2
    async with async_session_factory() as session:
        async with session.begin():
            c2 = await repository.claim_next_async(
                session,
                worker_id="w1",
                initial_retry_delay_ms=0,
                retry_backoff_multiplier=2,
                max_retry_delay_ms=1000,
            )
            assert c2 and c2.group_sequence == 2
    async with async_session_factory() as session:
        async with session.begin():
            await repository.mark_failed_async(
                session,
                event_id=c2.event_id,
                worker_id="w1",
                retry_count=1,
                error_code="HTTP_500",
                last_error="fail",
                exhausted=False,
            )

    # With retry delay in the future (default last_retry just set), seq 3 must not claim.
    # Force last_retry far future by leaving FAILED with recent timestamp and large delay.
    async with async_session_factory() as session:
        async with session.begin():
            nxt = await repository.claim_next_async(
                session,
                worker_id="w1",
                initial_retry_delay_ms=60_000,
                retry_backoff_multiplier=2,
                max_retry_delay_ms=900_000,
            )
            assert nxt is None


@pytest.mark.asyncio
async def test_cross_group_failure_isolation(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            for group, seqs in (("A", (1, 2)), ("B", (1, 2))):
                for seq in seqs:
                    await producer.publish_async(
                        session,
                        event_type="CUSTOMER_INVOICE",
                        event_group=group,
                        group_sequence=seq,
                        payload={},
                    )

    async with async_session_factory() as session:
        rows, _ = await repository.list_events_async(session, limit=100)
        by_key = {(r.event_group, r.group_sequence): r for r in rows}

    async with async_session_factory() as session:
        async with session.begin():
            a1e = await repository.get_required_async(session, by_key[("A", 1)].event_id)
            a1e.status = EventStatus.SYNCED.value
            a1e.processed_at = datetime.now(timezone.utc)

            a2e = await repository.get_required_async(session, by_key[("A", 2)].event_id)
            a2e.status = EventStatus.FAILED.value
            a2e.retry_count = 1
            # Far future so automatic retry is not yet eligible.
            a2e.last_retry_timestamp = datetime.now(timezone.utc) + timedelta(hours=1)
            a2e.error_code = "HTTP_500"
            await session.flush()

    async with async_session_factory() as session:
        async with session.begin():
            claimed = await repository.claim_next_async(
                session,
                worker_id="w2",
                initial_retry_delay_ms=60_000,
                retry_backoff_multiplier=2,
                max_retry_delay_ms=900_000,
            )
            assert claimed is not None
            assert claimed.event_group == "B"
            assert claimed.group_sequence == 1
