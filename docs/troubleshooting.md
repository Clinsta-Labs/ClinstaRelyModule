# Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Events stuck CREATED | Replay disabled / no workers | `OUTBOX_REPLAY_ENABLED=true` |
| Group not progressing | Earlier FAILED/RETRY_EXHAUSTED | Inspect failed; wait for retry or `retry-group` |
| PROCESSING forever | Worker crash before timeout | Wait for processing timeout recovery |
| RETRY_EXHAUSTED / ENDPOINT_NOT_CONFIGURED | Missing env endpoint | Add `OUTBOX_REPLAY_ENDPOINT_*` and restart replay; then retry |
| RETRY_EXHAUSTED / INVALID_RESPONSE | 2xx without reply identity | Add `X-Outbox-Reply-Reference-Type` and `X-Outbox-Reply-Reference` (or spec JSON body); then retry |
| Duplicate business effects | Target not idempotent | Fix target to key on EventId |
| Claim returns nothing | Retry delay not elapsed | Check `last_retry_timestamp` + backoff |
