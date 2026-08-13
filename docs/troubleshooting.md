# Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Events stuck CREATED | Replay disabled / no workers | `OUTBOX_REPLAY_ENABLED=true` |
| Group not progressing | Earlier FAILED/RETRY_EXHAUSTED in **same org+group** | Inspect failed with `organization_id`; wait for retry or `retry-group --organization-id` |
| `retry-group` does nothing | Wrong org, or no `RETRY_EXHAUSTED` in that org+group | Pass correct `--organization-id`; check status filter |
| Myth: org A failure blocks org B | FIFO is per `(organization_id, event_group)` | Cross-org same group name is independent |
| PROCESSING forever | Worker crash before timeout | Wait for processing timeout recovery |
| RETRY_EXHAUSTED / ENDPOINT_NOT_CONFIGURED | Missing env endpoint | Add `OUTBOX_REPLAY_ENDPOINT_*` and restart replay; then retry |
| RETRY_EXHAUSTED / INVALID_RESPONSE | 2xx without reply identity | Add `X-Outbox-Reply-Reference-Type` and `X-Outbox-Reply-Reference` (or spec JSON body); then retry |
| Duplicate business effects | Target not idempotent | Fix target to key on EventId |
| Claim returns nothing | Retry delay not elapsed | Check `last_retry_timestamp` + backoff |
| Migration fails adding `organization_id` | Existing rows without org | Truncate or backfill before upgrading to 0.2.0 |
