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
- it is the lowest unprocessed sequence for its `(organization_id, event_group)`
- no earlier event in the same org+group is in `CREATED`, `PROCESSING`, `FAILED`, or `RETRY_EXHAUSTED`

## HTTP request

The POST body is the producer `payload` only. Sequencing metadata (`eventId`, `eventType`, `group`, `groupSequence`, `referenceType`, `reference`, `createdAt`) stays on the outbox row for replay/FIFO and is not sent to the target.

```json
{
  "invoiceId": "INV-10001"
}
```

Headers: `Content-Type`, `Idempotency-Key`, `X-Outbox-Event-Id`, `X-Outbox-Event-Type`, `X-Outbox-Organization-Id`, plus any `OUTBOX_REPLAY_HEADER_*`.
The library always sets `X-Outbox-Organization-Id` from the row (not from env). Tenancy for the target is that header, not a wrapped `organizationId` field.

## Success response

Reply identity is **mandatory**. HTTP 2xx is not enough to mark `SYNCED`.

**Primary (recommended):** response headers. The JSON body can be the target's native format.

```http
HTTP/1.1 201 Created
X-Outbox-Reply-Reference-Type: JOURNAL_ENTRY
X-Outbox-Reply-Reference: JE-10001
Content-Type: application/json

{"journalId": "JE-10001"}
```

**Fallback:** spec JSON body (no extra configuration):

```json
{
  "success": true,
  "replyReferenceType": "JOURNAL_ENTRY",
  "replyReference": "JE-10001"
}
```

Rules:

- Both type and reference are required (blank values do not count).
- Headers win when both are present.
- A partial header pair is a failure; it is not mixed with the body.
- Missing identity → `INVALID_RESPONSE` → `RETRY_EXHAUSTED` (not retried).
- HTTP 204 succeeds only when both reply headers are present.
