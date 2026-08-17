"""Unit tests for event serialization helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hms_outbox.models.event import OutboxEvent


def test_dispatch_body_and_to_dict() -> None:
    event_id = uuid.uuid4()
    created = datetime(2026, 8, 11, 10, 0, 0, tzinfo=timezone.utc)
    event = OutboxEvent(
        event_id=event_id,
        organization_id=7,
        event_type="CUSTOMER_INVOICE",
        event_group="CUSTOMER-1001",
        group_sequence=42,
        reference_type="INVOICE",
        reference="INV-10001",
        payload={"invoiceId": "INV-10001"},
        status="CREATED",
        retry_count=0,
        created_at=created,
        updated_at=created,
    )
    body = event.dispatch_body()
    assert body == {"invoiceId": "INV-10001"}
    assert "eventId" not in body
    assert "organizationId" not in body
    assert "eventType" not in body
    assert "group" not in body
    assert "groupSequence" not in body
    assert "payload" not in body
    body["invoiceId"] = "mutated"
    assert event.payload["invoiceId"] == "INV-10001"

    as_dict = event.to_dict()
    assert as_dict["eventId"] == str(event_id)
    assert as_dict["organizationId"] == 7
    assert as_dict["status"] == "CREATED"
    assert as_dict["payload"]["invoiceId"] == "INV-10001"
