# Replay engine

```bash
OUTBOX_REPLAY_ENABLED=true python -m hms_outbox replay
```

If `OUTBOX_REPLAY_ENABLED=false`, the CLI refuses to start workers (API processes stay producers-only).

## Worker pool

Each worker:

1. Atomically claims one eligible event
2. POSTs to the configured endpoint
3. Updates status (`SYNCED` / `FAILED` / `RETRY_EXHAUSTED`)
4. Polls again (sleeps when idle)

Workers never process multiple events concurrently.

## Claiming eligibility (DB-enforced)

An event is eligible when:

- status is `CREATED`, or `FAILED` and retry delay has elapsed
- it is the lowest unprocessed sequence for its group
- no earlier event in the group is in `CREATED`, `PROCESSING`, `FAILED`, or `RETRY_EXHAUSTED`

## HTTP request

```json
{
  "eventId": "...",
  "eventType": "CUSTOMER_INVOICE",
  "group": "CUSTOMER-1001",
  "groupSequence": 42,
  "referenceType": "INVOICE",
  "reference": "INV-10001",
  "payload": {},
  "createdAt": "2026-08-11T10:00:00Z"
}
```

Headers: `Content-Type`, `Idempotency-Key`, `X-Outbox-Event-Id`, `X-Outbox-Event-Type`, plus any `OUTBOX_REPLAY_HEADER_*`.

## Success response

```json
{
  "success": true,
  "replyReferenceType": "JOURNAL_ENTRY",
  "replyReference": "JE-10001"
}
```

HTTP 2xx without a valid body (including 204) is treated as failure.
