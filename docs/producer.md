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
        organization_id=1,            # required; int > 0
        event_type="CUSTOMER_INVOICE",
        event_group="CUSTOMER-1001",
        group_sequence=42,            # required; caller-supplied in Phase 1
        reference_type="INVOICE",
        reference="INV-10001",
        payload={"invoiceId": "INV-10001"},
    )
```

## Async

```python
async with session.begin():
    event_id = await outbox.publish_async(
        session,
        organization_id=1,
        event_type="CUSTOMER_INVOICE",
        ...
    )
```

## Rules

- The producer **never** commits your transaction.
- Insert business data and the Outbox event in the **same** transaction.
- `organization_id` is required (`int > 0`). It scopes FIFO and is sent on every dispatch as `X-Outbox-Organization-Id`.
- Store the **target's native request JSON** in `payload`; replay POSTs that object as the HTTP body.
- `event_id` is generated once (UUID) and never changed on retry.
- Duplicate `reference` values are allowed across different events.
- `group_sequence` must be `>= 0` and is the FIFO key within `(organization_id, event_group)`.
