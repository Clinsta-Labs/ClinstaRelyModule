# Architecture

`hms-outbox` implements the **transactional Outbox** pattern with a **Group-FIFO replay engine**.

## Components

1. **Producer** — inserts `outbox_event` rows inside the caller's SQLAlchemy transaction.
2. **Replay engine** — separate process/container that claims and dispatches events over HTTP.
3. **PostgreSQL** — durability and coordination (`FOR UPDATE SKIP LOCKED`). No Kafka/Redis.

## Process model (Model B)

```
pharmacy-api          (OUTBOX_REPLAY_ENABLED=false)
pharmacy-replay       (OUTBOX_REPLAY_ENABLED=true)
        \                   /
         \                 /
          v               v
        Pharmacy PostgreSQL (outbox_event)
```

Same image/package; different command and env.

## Guarantees

| Guarantee | Mechanism |
|-----------|-----------|
| At-least-once delivery | Retry after FAILED / timeout |
| FIFO within `(organization_id, event_group)` | DB eligibility: lowest unprocessed `group_sequence` in that org+group |
| Parallel across orgs / groups | Multiple workers + SKIP LOCKED |
| Group blocking | Earlier FAILED/PROCESSING/CREATED/RETRY_EXHAUSTED blocks later sequences **in the same org+group** |
| No duplicate concurrent claim | Atomic claim UPDATE … FOR UPDATE SKIP LOCKED |
| Crash recovery | PROCESSING older than timeout → FAILED |
| Reply identity required | Headers `X-Outbox-Reply-Reference-*`, else spec JSON body |

## Transaction boundaries

**Correct:**

```
BEGIN; CLAIM; COMMIT;
HTTP CALL;
BEGIN; UPDATE RESULT; COMMIT;
```

Never hold a DB lock open while waiting on HTTP.
