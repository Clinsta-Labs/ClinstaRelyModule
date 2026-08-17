# Idempotency

Delivery is **at-least-once**.

The library:

- sends `EventId` on every attempt
- never generates a new `EventId` on retry
- sets `Idempotency-Key` and `X-Outbox-Event-Id`
- also sends `X-Outbox-Organization-Id` as **tenancy context** (not the idempotency key)

The receiving service must treat `EventId` as the primary idempotency key and safely ignore duplicate deliveries.
`organization_id` tells the target which tenant the event belongs to; it does not replace `EventId`.
The POST body is the producer `payload` only — it does not wrap `eventId` / `organizationId`.
