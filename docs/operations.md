# Operations

## Statistics

```bash
python -m hms_outbox stats
# GET /internal/outbox/statistics
```

## Failed events

```bash
python -m hms_outbox failed
python -m hms_outbox failed --organization-id 1
# GET /internal/outbox/events/failed?organization_id=1
```

## Manual intervention

```bash
python -m hms_outbox retry <event-id>
python -m hms_outbox retry-group <group> --organization-id <org-id>
# POST /internal/outbox/groups/{group}/retry?organization_id=<org-id>
```

`retry-group` scopes to `(organization_id, event_group)` and resets only the lowest-sequence `RETRY_EXHAUSTED` event in that scope.

## Health

```bash
python -m hms_outbox health
```

## Logging

Structured fields include `event_id`, `organization_id`, `event_type`, `event_group`, `group_sequence`, `worker_id`, `retry_count`, `duration_ms`, `endpoint`.

Payloads are not logged unless `OUTBOX_REPLAY_LOG_PAYLOAD=true` (unsafe for production).
