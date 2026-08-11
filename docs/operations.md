# Operations

## Statistics

```bash
python -m hms_outbox stats
# GET /internal/outbox/statistics
```

## Failed events

```bash
python -m hms_outbox failed
# GET /internal/outbox/events/failed
```

## Manual intervention

```bash
python -m hms_outbox retry <event-id>
python -m hms_outbox retry-group <group>
```

## Health

```bash
python -m hms_outbox health
```

## Logging

Structured fields include `event_id`, `event_type`, `event_group`, `group_sequence`, `worker_id`, `retry_count`, `duration_ms`, `endpoint`.

Payloads are not logged unless `OUTBOX_REPLAY_LOG_PAYLOAD=true` (unsafe for production).
