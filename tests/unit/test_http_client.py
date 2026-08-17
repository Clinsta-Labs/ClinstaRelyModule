"""Unit tests for Outbox HTTP client reply extraction."""

from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from hms_outbox.config.settings import OutboxSettings
from hms_outbox.constants import (
    HEADER_ORGANIZATION_ID,
    HEADER_REPLY_REFERENCE,
    HEADER_REPLY_REFERENCE_TYPE,
)
from hms_outbox.http.client import OutboxHttpClient
from hms_outbox.http.errors import DispatchFailure, DispatchSuccess


@pytest.fixture
def settings() -> OutboxSettings:
    return OutboxSettings(
        database_url="postgresql+asyncpg://outbox:outbox@localhost:5432/outbox",
        http_connect_timeout_ms=1000,
        http_read_timeout_ms=2000,
        http_total_timeout_ms=3000,
    )


@pytest.mark.asyncio
@respx.mock
async def test_client_uses_reply_headers(settings: OutboxSettings) -> None:
    route = respx.post("http://target/invoice").mock(
        return_value=httpx.Response(
            201,
            json={"journalId": "JE-9"},
            headers={
                HEADER_REPLY_REFERENCE_TYPE: "JOURNAL_ENTRY",
                HEADER_REPLY_REFERENCE: "JE-9",
            },
        )
    )
    client = OutboxHttpClient(settings)
    result = await client.post_event(
        url="http://target/invoice",
        event_id=uuid.uuid4(),
        event_type="CUSTOMER_INVOICE",
        organization_id=42,
        body={"invoiceId": "INV-9"},
    )
    await client.aclose()
    assert isinstance(result, DispatchSuccess)
    assert result.reply_reference_type == "JOURNAL_ENTRY"
    assert result.reply_reference == "JE-9"
    assert route.calls[0].request.headers[HEADER_ORGANIZATION_ID] == "42"


@pytest.mark.asyncio
@respx.mock
async def test_client_invalid_json_succeeds_when_headers_present(
    settings: OutboxSettings,
) -> None:
    respx.post("http://target/invoice").mock(
        return_value=httpx.Response(
            200,
            content=b"not-json",
            headers={
                HEADER_REPLY_REFERENCE_TYPE: "JOURNAL_ENTRY",
                HEADER_REPLY_REFERENCE: "JE-1",
            },
        )
    )
    client = OutboxHttpClient(settings)
    result = await client.post_event(
        url="http://target/invoice",
        event_id=uuid.uuid4(),
        event_type="CUSTOMER_INVOICE",
        organization_id=1,
        body={},
    )
    await client.aclose()
    assert isinstance(result, DispatchSuccess)
    assert result.reply_reference == "JE-1"


@pytest.mark.asyncio
@respx.mock
async def test_client_2xx_without_reply_identity_is_non_retryable(
    settings: OutboxSettings,
) -> None:
    respx.post("http://target/invoice").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = OutboxHttpClient(settings)
    result = await client.post_event(
        url="http://target/invoice",
        event_id=uuid.uuid4(),
        event_type="CUSTOMER_INVOICE",
        organization_id=1,
        body={},
    )
    await client.aclose()
    assert isinstance(result, DispatchFailure)
    assert result.retryable is False
    assert result.error_code == "INVALID_RESPONSE"
