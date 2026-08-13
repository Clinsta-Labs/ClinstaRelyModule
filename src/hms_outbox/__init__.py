"""hms-outbox: transactional Outbox producer and Group-FIFO replay engine.

Delivery semantics are **at-least-once**. Downstream endpoints MUST treat
``EventId`` / ``Idempotency-Key`` as an idempotency key. This package never
claims exactly-once delivery.
"""

from hms_outbox.models.event import EventStatus, OutboxEvent
from hms_outbox.producer.producer import OutboxProducer

__version__ = "0.2.0"
__all__ = [
    "EventStatus",
    "OutboxEvent",
    "OutboxProducer",
    "__version__",
]
