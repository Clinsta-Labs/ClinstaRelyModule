# API reference

## Producer

- `OutboxProducer.publish(session, organization_id, ...)` → `UUID`
- `OutboxProducer.publish_async(session, organization_id, ...)` → `UUID`

`organization_id` is required (`int > 0`).

## Admin / ops (framework-neutral)

- `StatisticsService.get_statistics(session)`
- `AdminService.get_failed_events(session, ..., organization_id=None)`
- `AdminService.get_events(session, ..., organization_id=None)`
- `AdminService.retry_event(session, event_id)`
- `AdminService.retry_group(session, organization_id, group)` — lowest `RETRY_EXHAUSTED` in that org+group only
- `HealthService.health()` / `readiness()`

## FastAPI

```python
from hms_outbox.fastapi import create_outbox_router
app.include_router(create_outbox_router())
```

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/internal/outbox/statistics` | X-API-Key | |
| GET | `/internal/outbox/events` | X-API-Key | optional `organization_id` |
| GET | `/internal/outbox/events/failed` | X-API-Key | optional `organization_id` |
| GET | `/internal/outbox/events/{event_id}` | X-API-Key | |
| POST | `/internal/outbox/events/{event_id}/retry` | X-API-Key | |
| POST | `/internal/outbox/groups/{group}/retry` | X-API-Key | **required** query `organization_id` |
| GET | `/internal/outbox/health` | none (liveness) | |
| GET | `/internal/outbox/ready` | none (readiness) | |

## Target HTTP contract

Replay POSTs the event and requires a reply identity to mark `SYNCED`.

Request body includes `organizationId` (integer).

Request headers: `Idempotency-Key`, `X-Outbox-Event-Id`, `X-Outbox-Event-Type`, `X-Outbox-Organization-Id`.

Response (primary):

- `X-Outbox-Reply-Reference-Type`
- `X-Outbox-Reply-Reference`

Response (fallback JSON): `{ "success": true, "replyReferenceType": "...", "replyReference": "..." }`.
