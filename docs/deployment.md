# Deployment

## Model B (recommended)

Run API and replay as separate processes from the same image:

| Process | Command | `OUTBOX_REPLAY_ENABLED` |
|---------|---------|-------------------------|
| API | `uvicorn app.main:app` | `false` |
| Replay | `python -m hms_outbox replay` | `true` |

Both share the same database and endpoint env vars.

See `docker-compose.yml` and `deploy/k8s/` for examples.

## Horizontal scale

Multiple replay processes may run against the same Outbox table. PostgreSQL locking coordinates claims — no external lock service.
