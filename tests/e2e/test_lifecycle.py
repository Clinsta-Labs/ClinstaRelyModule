"""End-to-end replay against mock HTTP target."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hms_outbox.config.endpoint_registry import EndpointRegistry
from hms_outbox.config.settings import EndpointConfig, OutboxSettings
from hms_outbox.constants import EventStatus
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.http.client import OutboxHttpClient
from hms_outbox.producer.producer import OutboxProducer
from hms_outbox.replay.claimer import EventClaimer
from hms_outbox.replay.dispatcher import EventDispatcher
from hms_outbox.replay.metrics import ReplayMetrics
from hms_outbox.replay.retry_policy import RetryPolicy
from hms_outbox.replay.worker import ReplayWorker

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@respx.mock
async def test_e2e_lifecycle(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
    settings: OutboxSettings,
) -> None:
    route = respx.post("http://target/invoice").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "replyReferenceType": "JOURNAL_ENTRY",
                "replyReference": "JE-10001",
            },
        )
    )

    settings.endpoints = {
        "CUSTOMER_INVOICE": EndpointConfig(
            event_type="CUSTOMER_INVOICE", url="http://target/invoice"
        )
    }
    settings.poll_interval_ms = 20
    settings.initial_retry_delay_ms = 1
    settings.retry_jitter = False

    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                event_type="CUSTOMER_INVOICE",
                event_group="CUSTOMER-1001",
                group_sequence=1,
                payload={"invoiceId": "INV-10001"},
                reference_type="INVOICE",
                reference="INV-10001",
            )

    http_client = OutboxHttpClient(settings)
    worker = ReplayWorker(
        worker_id="test:1:worker-0",
        session_factory=async_session_factory,
        claimer=EventClaimer(repository, settings),
        dispatcher=EventDispatcher(
            registry=EndpointRegistry.from_settings(settings),
            http_client=http_client,
            metrics=ReplayMetrics(),
        ),
        repository=repository,
        retry_policy=RetryPolicy.from_settings(settings),
        metrics=ReplayMetrics(),
        poll_interval_ms=20,
    )

    assert await worker.run_once() is True
    await http_client.aclose()

    assert route.called
    request = route.calls[0].request
    assert request.headers["Idempotency-Key"] == str(event_id)
    assert request.headers["X-Outbox-Event-Id"] == str(event_id)

    async with async_session_factory() as session:
        event = await repository.get_required_async(session, event_id)
        assert event.status == EventStatus.SYNCED.value
        assert event.reply_reference == "JE-10001"
        assert event.reply_reference_type == "JOURNAL_ENTRY"


@pytest.mark.asyncio
@respx.mock
async def test_idempotency_key_preserved_on_retry(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
    settings: OutboxSettings,
) -> None:
    call_count = {"n": 0}

    def _responder(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(500, json={"error": "temp"})
        return httpx.Response(
            200,
            json={
                "success": True,
                "replyReferenceType": "JE",
                "replyReference": "1",
            },
        )

    respx.post("http://target/invoice").mock(side_effect=_responder)
    settings.endpoints = {
        "CUSTOMER_INVOICE": EndpointConfig(
            event_type="CUSTOMER_INVOICE", url="http://target/invoice"
        )
    }
    settings.initial_retry_delay_ms = 0
    settings.retry_jitter = False
    settings.max_retry_count = 5
    settings.poll_interval_ms = 10

    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                event_type="CUSTOMER_INVOICE",
                event_group="IDEM",
                group_sequence=1,
                payload={},
            )

    http_client = OutboxHttpClient(settings)
    metrics = ReplayMetrics()
    worker = ReplayWorker(
        worker_id="test:1:worker-0",
        session_factory=async_session_factory,
        claimer=EventClaimer(repository, settings),
        dispatcher=EventDispatcher(
            registry=EndpointRegistry.from_settings(settings),
            http_client=http_client,
            metrics=metrics,
        ),
        repository=repository,
        retry_policy=RetryPolicy.from_settings(settings),
        metrics=metrics,
        poll_interval_ms=10,
    )

    assert await worker.run_once() is True
    # Wait for retry eligibility (delay 0)
    await asyncio.sleep(0.05)
    assert await worker.run_once() is True
    await http_client.aclose()

    assert call_count["n"] == 2
    # Both calls used same EventId
    async with async_session_factory() as session:
        event = await repository.get_required_async(session, event_id)
        assert event.status == EventStatus.SYNCED.value
        assert event.event_id == event_id


@pytest.mark.asyncio
@respx.mock
async def test_missing_endpoint_exhausts(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
    settings: OutboxSettings,
) -> None:
    settings.endpoints = {}
    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                event_type="CUSTOMER_INVOICE",
                event_group="NOEP",
                group_sequence=1,
                payload={},
            )

    http_client = OutboxHttpClient(settings)
    worker = ReplayWorker(
        worker_id="test:1:worker-0",
        session_factory=async_session_factory,
        claimer=EventClaimer(repository, settings),
        dispatcher=EventDispatcher(
            registry=EndpointRegistry.from_settings(settings),
            http_client=http_client,
            metrics=ReplayMetrics(),
        ),
        repository=repository,
        retry_policy=RetryPolicy.from_settings(settings),
        metrics=ReplayMetrics(),
        poll_interval_ms=10,
    )
    await worker.run_once()
    await http_client.aclose()

    async with async_session_factory() as session:
        event = await repository.get_required_async(session, event_id)
        assert event.status == EventStatus.RETRY_EXHAUSTED.value
        assert event.error_code == "ENDPOINT_NOT_CONFIGURED"


@pytest.mark.asyncio
@respx.mock
async def test_non_retryable_http_exhausts(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
    settings: OutboxSettings,
) -> None:
    respx.post("http://target/invoice").mock(
        return_value=httpx.Response(422, json={"detail": "invalid"})
    )
    settings.endpoints = {
        "CUSTOMER_INVOICE": EndpointConfig(
            event_type="CUSTOMER_INVOICE", url="http://target/invoice"
        )
    }
    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                event_type="CUSTOMER_INVOICE",
                event_group="NR",
                group_sequence=1,
                payload={},
            )

    http_client = OutboxHttpClient(settings)
    worker = ReplayWorker(
        worker_id="w",
        session_factory=async_session_factory,
        claimer=EventClaimer(repository, settings),
        dispatcher=EventDispatcher(
            registry=EndpointRegistry.from_settings(settings),
            http_client=http_client,
        ),
        repository=repository,
        retry_policy=RetryPolicy.from_settings(settings),
        metrics=ReplayMetrics(),
        poll_interval_ms=10,
    )
    await worker.run_once()
    await http_client.aclose()

    async with async_session_factory() as session:
        event = await repository.get_required_async(session, event_id)
        assert event.status == EventStatus.RETRY_EXHAUSTED.value
        assert event.error_code == "HTTP_422"


@pytest.mark.asyncio
@respx.mock
async def test_e2e_reply_headers_with_native_json(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
    settings: OutboxSettings,
) -> None:
    respx.post("http://target/invoice").mock(
        return_value=httpx.Response(
            201,
            json={"journalId": "JE-HEADER", "status": "posted"},
            headers={
                "X-Outbox-Reply-Reference-Type": "JOURNAL_ENTRY",
                "X-Outbox-Reply-Reference": "JE-HEADER",
            },
        )
    )
    settings.endpoints = {
        "CUSTOMER_INVOICE": EndpointConfig(
            event_type="CUSTOMER_INVOICE", url="http://target/invoice"
        )
    }
    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                event_type="CUSTOMER_INVOICE",
                event_group="HDR",
                group_sequence=1,
                payload={},
            )

    http_client = OutboxHttpClient(settings)
    worker = ReplayWorker(
        worker_id="w",
        session_factory=async_session_factory,
        claimer=EventClaimer(repository, settings),
        dispatcher=EventDispatcher(
            registry=EndpointRegistry.from_settings(settings),
            http_client=http_client,
        ),
        repository=repository,
        retry_policy=RetryPolicy.from_settings(settings),
        metrics=ReplayMetrics(),
        poll_interval_ms=10,
    )
    await worker.run_once()
    await http_client.aclose()

    async with async_session_factory() as session:
        event = await repository.get_required_async(session, event_id)
        assert event.status == EventStatus.SYNCED.value
        assert event.reply_reference_type == "JOURNAL_ENTRY"
        assert event.reply_reference == "JE-HEADER"


@pytest.mark.asyncio
@respx.mock
async def test_2xx_without_reply_identity_exhausts(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    producer: OutboxProducer,
    settings: OutboxSettings,
) -> None:
    respx.post("http://target/invoice").mock(
        return_value=httpx.Response(200, json={"ok": True, "id": "ignored"})
    )
    settings.endpoints = {
        "CUSTOMER_INVOICE": EndpointConfig(
            event_type="CUSTOMER_INVOICE", url="http://target/invoice"
        )
    }
    async with async_session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                event_type="CUSTOMER_INVOICE",
                event_group="NOID",
                group_sequence=1,
                payload={},
            )

    http_client = OutboxHttpClient(settings)
    worker = ReplayWorker(
        worker_id="w",
        session_factory=async_session_factory,
        claimer=EventClaimer(repository, settings),
        dispatcher=EventDispatcher(
            registry=EndpointRegistry.from_settings(settings),
            http_client=http_client,
        ),
        repository=repository,
        retry_policy=RetryPolicy.from_settings(settings),
        metrics=ReplayMetrics(),
        poll_interval_ms=10,
    )
    await worker.run_once()
    await http_client.aclose()

    async with async_session_factory() as session:
        event = await repository.get_required_async(session, event_id)
        assert event.status == EventStatus.RETRY_EXHAUSTED.value
        assert event.error_code == "INVALID_RESPONSE"
