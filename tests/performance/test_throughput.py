"""Performance benchmarks (opt-in)."""

from __future__ import annotations

import time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hms_outbox.db.repository import OutboxRepository
from hms_outbox.producer.producer import OutboxProducer

pytestmark = [pytest.mark.performance, pytest.mark.integration]


@pytest.mark.asyncio
async def test_bulk_insert_and_claim_throughput(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
) -> None:
    n = 200
    started = time.perf_counter()
    async with async_session_factory() as session:
        async with session.begin():
            for i in range(n):
                await producer.publish_async(
                    session,
                    event_type="CUSTOMER_INVOICE",
                    event_group=f"G-{i % 20}",
                    group_sequence=i,
                    payload={"i": i},
                )
    insert_s = time.perf_counter() - started

    claimed = 0
    started = time.perf_counter()
    while claimed < n:
        async with async_session_factory() as session:
            async with session.begin():
                event = await repository.claim_next_async(
                    session,
                    worker_id=f"perf-{claimed}",
                    initial_retry_delay_ms=0,
                    retry_backoff_multiplier=2,
                    max_retry_delay_ms=1000,
                )
                if event is None:
                    break
                await repository.mark_synced_async(
                    session,
                    event_id=event.event_id,
                    worker_id=f"perf-{claimed}",
                    reply_reference_type="JE",
                    reply_reference=str(claimed),
                )
                claimed += 1
    claim_s = time.perf_counter() - started
    assert claimed == n
    # Soft assertion — mainly for benchmarking visibility
    print(f"insert={n / insert_s:.1f} evt/s claim={n / claim_s:.1f} evt/s")
