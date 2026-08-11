# API reference

## Producer

- `OutboxProducer.publish(session, ...)` → `UUID`
- `OutboxProducer.publish_async(session, ...)` → `UUID`

## Admin / ops (framework-neutral)

- `StatisticsService.get_statistics(session)`
- `AdminService.get_failed_events(session, ...)`
- `AdminService.retry_event(session, event_id)`
- `AdminService.retry_group(session, group)` — lowest `RETRY_EXHAUSTED` only
- `HealthService.health()` / `readiness()`

## FastAPI

```python
from hms_outbox.fastapi import create_outbox_router
app.include_router(create_outbox_router())
```

| Method | Path | Auth |
|--------|------|------|
| GET | `/internal/outbox/statistics` | X-API-Key |
| GET | `/internal/outbox/events` | X-API-Key |
| GET | `/internal/outbox/events/failed` | X-API-Key |
| GET | `/internal/outbox/events/{event_id}` | X-API-Key |
| POST | `/internal/outbox/events/{event_id}/retry` | X-API-Key |
| POST | `/internal/outbox/groups/{group}/retry` | X-API-Key |
| GET | `/internal/outbox/health` | none (liveness) |
| GET | `/internal/outbox/ready` | none (readiness) |
