# Configuration reference

All configuration is environment-driven.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes* | — | Application DB URL |
| `OUTBOX_DATABASE_URL` | No | `DATABASE_URL` | Optional Outbox DB override |
| `OUTBOX_TABLE_NAME` | No | `outbox_event` | Table name (validated identifier) |
| `OUTBOX_REPLAY_ENABLED` | No | `false` | Start replay workers |
| `OUTBOX_REPLAY_WORKER_COUNT` | No | `10` | Worker pool size |
| `OUTBOX_REPLAY_POLL_INTERVAL_MS` | No | `1000` | Idle poll sleep |
| `OUTBOX_REPLAY_PROCESSING_TIMEOUT_MS` | No | `60000` | Stale PROCESSING recovery |
| `OUTBOX_REPLAY_MAX_RETRY_COUNT` | No | `5` | Exhaust when `retry_count >= max` |
| `OUTBOX_REPLAY_INITIAL_RETRY_DELAY_MS` | No | `10000` | Base backoff |
| `OUTBOX_REPLAY_RETRY_BACKOFF_MULTIPLIER` | No | `2` | Exponential multiplier |
| `OUTBOX_REPLAY_MAX_RETRY_DELAY_MS` | No | `900000` | Backoff cap |
| `OUTBOX_REPLAY_RETRY_JITTER` | No | `true` | Randomize delay |
| `OUTBOX_REPLAY_HTTP_CONNECT_TIMEOUT_MS` | No | `5000` | Connect timeout |
| `OUTBOX_REPLAY_HTTP_READ_TIMEOUT_MS` | No | `30000` | Read timeout |
| `OUTBOX_REPLAY_HTTP_TOTAL_TIMEOUT_MS` | No | `60000` | Total timeout |
| `OUTBOX_REPLAY_LOG_PAYLOAD` | No | `false` | Log payloads (unsafe in prod) |
| `OUTBOX_ADMIN_API_KEY` | Yes for admin router | — | `X-API-Key` for admin APIs |

\*Required for producer/replay; validated at load.

## Dynamic discovery

```
OUTBOX_REPLAY_ENDPOINT_<EVENT_TYPE>=https://host/path
OUTBOX_REPLAY_TIMEOUT_<EVENT_TYPE>_MS=60000
OUTBOX_REPLAY_HEADER_<HEADER_NAME>=value
```

Event types must match `^[A-Z][A-Z0-9_]*$`.

Example:

```env
OUTBOX_REPLAY_ENDPOINT_CUSTOMER_INVOICE=http://accounting/internal/customer/invoice
OUTBOX_REPLAY_HEADER_AUTHORIZATION=Bearer ...
OUTBOX_REPLAY_HEADER_X_SERVICE_NAME=pharmacy
```

Changing endpoints requires restarting the replay process (config is loaded at startup).
