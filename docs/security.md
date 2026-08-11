# Security

## Admin APIs

- Require `OUTBOX_ADMIN_API_KEY` and `X-API-Key` header.
- Intended for **internal network / authenticated admin access only**.
- **Do not expose** `/internal/outbox/*` on the public internet.

## Secrets

- Do not log Authorization headers, API keys, passwords, tokens, or cookies.
- Error sanitization redacts likely secret-bearing messages.
- Prefer secret stores / orchestrator secrets for `OUTBOX_REPLAY_HEADER_AUTHORIZATION`.

## Endpoint URLs

Endpoint URLs come from trusted deployment configuration (env), not end-user input. Treat them as trusted config; still avoid pointing them at unintended internal hosts in shared environments (SSRF consideration).

## Payload logging

`OUTBOX_REPLAY_LOG_PAYLOAD=true` may leak PHI/PII/secrets — keep false in production.
