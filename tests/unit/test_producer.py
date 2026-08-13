"""Unit tests for producer validation."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hms_outbox.producer.producer import OutboxProducer


def test_publish_requires_fields() -> None:
    producer = OutboxProducer()
    session = MagicMock()
    with pytest.raises(ValueError):
        producer.publish(
            session,
            organization_id=1,
            event_type="",
            event_group="G",
            group_sequence=1,
            payload={},
        )
    with pytest.raises(ValueError):
        producer.publish(
            session,
            organization_id=1,
            event_type="T",
            event_group="G",
            group_sequence=-1,
            payload={},
        )
    with pytest.raises(ValueError, match="organization_id must be > 0"):
        producer.publish(
            session,
            organization_id=0,
            event_type="T",
            event_group="G",
            group_sequence=1,
            payload={},
        )
