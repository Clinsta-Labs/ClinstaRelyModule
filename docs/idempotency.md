# Idempotency

Delivery is **at-least-once**.

The library:

- sends `EventId` on every attempt
- never generates a new `EventId` on retry
- sets `Idempotency-Key` and `X-Outbox-Event-Id`

The receiving service must treat `EventId` as an idempotency key and safely ignore duplicate deliveries.
