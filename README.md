# HMS Outbox (`hms-outbox`)

Reusable, production-grade **transactional Outbox producer** and **Group-FIFO replay/dispatch engine** for HMS Python services (IPD, Pharmacy, Laboratory, OPD, Accounting, Insurance/TPA, and future services).

This package is **not** a microservice. Each application owns its own Outbox table, database, event types, endpoint configuration, and replay worker process. The library provides the generic machinery.

## Delivery semantics (important)

Delivery is **at-least-once**. The package does **not** claim exactly-once delivery.

If a target service commits work but the HTTP response is lost, replay may retry with the **same** `EventId`. Downstream endpoints **must** be idempotent using:

- `Idempotency-Key: <event_id>`
- `X-Outbox-Event-Id: <event_id>`

Successful dispatch requires a reply identity. Prefer response headers (JSON body can be native):

- `X-Outbox-Reply-Reference-Type`
- `X-Outbox-Reply-Reference`

If those headers are absent, the spec JSON body (`success`, `replyReferenceType`, `replyReference`) is accepted. HTTP 2xx without a reply identity is `RETRY_EXHAUSTED`, not `SYNCED`.

## Features

- Transactional Outbox producer (sync `Session` and async `AsyncSession`)
- Group-FIFO ordering within `(organization_id, event_group)` with cross-org / cross-group parallelism
- Atomic claiming via PostgreSQL `FOR UPDATE SKIP LOCKED`
- Configurable worker pool, retries, exponential backoff, jitter
- Processing-timeout recovery for crashed workers
- Environment-driven EventType → endpoint mapping (no Python handlers)
- Statistics, failed-event APIs, manual retry / retry-group
- Dispatch always sends `X-Outbox-Organization-Id` (header); the POST body is the producer `payload` only
- CLI (`python -m hms_outbox ...`)
- Optional FastAPI admin router (`X-API-Key`)

## Install

```bash
pip install hms-outbox
# with FastAPI admin router + Alembic:
pip install "hms-outbox[fastapi,alembic]"
```

From this repository:

```bash
cd hms-outbox
pip install -e ".[dev]"
```

## Database migration

```bash
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/app
alembic -c alembic.ini upgrade head
```

## Quick start

### `.env`

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/pharmacy
OUTBOX_REPLAY_ENABLED=false
OUTBOX_REPLAY_WORKER_COUNT=10
OUTBOX_REPLAY_ENDPOINT_CUSTOMER_INVOICE=http://accounting/internal/customer/invoice
OUTBOX_REPLAY_ENDPOINT_CUSTOMER_PAYMENT=http://accounting/internal/customer/payment
OUTBOX_ADMIN_API_KEY=change-me
```

### Producer (same DB transaction as business data)

```python
from hms_outbox import OutboxProducer

outbox = OutboxProducer()

with session.begin():
    invoice = create_invoice(...)
    event_id = outbox.publish(
        session,
        organization_id=invoice.organization_id,
        event_type="CUSTOMER_INVOICE",
        event_group=f"CUSTOMER-{invoice.customer_id}",
        group_sequence=invoice.sequence,
        reference_type="INVOICE",
        reference=invoice.id,
        payload=invoice_payload,
    )
```

Async:

```python
event_id = await outbox.publish_async(async_session, ...)
```

The producer **does not** commit. Your application transaction must commit both business rows and the Outbox insert.

### Replay process

```bash
OUTBOX_REPLAY_ENABLED=true python -m hms_outbox replay
```

API processes should keep `OUTBOX_REPLAY_ENABLED=false`.

### FastAPI admin (internal only)

```python
from hms_outbox.fastapi import create_outbox_router

app.include_router(create_outbox_router())
```

**Do not expose admin routes on the public internet.** They require `X-API-Key: $OUTBOX_ADMIN_API_KEY`.

## CLI

```bash
python -m hms_outbox replay
python -m hms_outbox stats
python -m hms_outbox failed
python -m hms_outbox event <event-id>
python -m hms_outbox retry <event-id>
python -m hms_outbox retry-group <group> --organization-id <org-id>
python -m hms_outbox health
```

## Documentation

See [`docs/`](docs/) for architecture, configuration, FIFO, retry, idempotency, operations, security, deployment, and testing guides.

## Non-goals

No Kafka, Redis, Celery, RabbitMQ, external distributed locks, event-handler classes, or mandatory YAML configuration.

## License

MIT
