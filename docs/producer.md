# Producer API

```python
from hms_outbox import OutboxProducer

outbox = OutboxProducer()  # optional table_name=
```

## Sync

```python
with session.begin():
    create_business_row(...)
    event_id = outbox.publish(
        session,
        event_type="CUSTOMER_INVOICE",
        event_group="CUSTOMER-1001",
        group_sequence=42,          # required; caller-supplied in Phase 1
        reference_type="INVOICE",
        reference="INV-10001",
        payload={"invoiceId": "INV-10001"},
    )
```

## Async

```python
async with session.begin():
    event_id = await outbox.publish_async(session, ...)
```

## Rules

- The producer **never** commits your transaction.
- Insert business data and the Outbox event in the **same** transaction.
- `event_id` is generated once (UUID) and never changed on retry.
- Duplicate `reference` values are allowed across different events.
- `group_sequence` must be `>= 0` and is the FIFO key within `event_group`.
