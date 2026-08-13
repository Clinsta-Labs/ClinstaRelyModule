# Retry policy

`retry_count` = number of **retry attempts already consumed**, excluding the initial attempt.

## Exhaustion

After a failure: `new_retry_count = old + 1`.  
If `new_retry_count >= OUTBOX_REPLAY_MAX_RETRY_COUNT` → `RETRY_EXHAUSTED`.

With `max_retry_count=3`, continuous failure ends at `retry_count=3` / `RETRY_EXHAUSTED`.

## Backoff

```
delay = min(initial * multiplier^(retry_count-1), max_delay)
```

Optional full jitter when `OUTBOX_REPLAY_RETRY_JITTER=true`.

Next attempt is eligible when `last_retry_timestamp + delay <= now`.

## Retryable vs non-retryable

**Retryable:** 408, 425, 429, 5xx, timeouts, connection refused, network errors.

**Non-retryable:** 400, 401, 403, 404, 405, 409, 422 (and similar 4xx) → immediate `RETRY_EXHAUSTED`.

**Configuration:** missing endpoint → `RETRY_EXHAUSTED` / `ENDPOINT_NOT_CONFIGURED` (no endless retry).

## Manual retry

```bash
python -m hms_outbox retry <event-id>
python -m hms_outbox retry-group <group> --organization-id <org-id>
```

`retry_group` resets only the **lowest-sequence `RETRY_EXHAUSTED`** event in that `(organization_id, event_group)`. It does **not** reset `FAILED` events still under automatic retry. Events in `PROCESSING` cannot be manually retried.
