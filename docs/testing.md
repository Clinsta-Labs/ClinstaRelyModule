# Testing

```bash
pip install -e ".[dev]"
pytest tests/unit -q
pytest -m "integration or concurrency" -q   # needs Docker for testcontainers, or DATABASE_URL
pytest -m performance -q                    # opt-in
```

## Suites

- `tests/unit` — config, retry, HTTP classification, serialization
- `tests/integration` — PostgreSQL repository / FastAPI admin
- `tests/concurrency` — SKIP LOCKED / FIFO / group blocking
- `tests/e2e` — producer → worker → mock HTTP → SYNCED
- `tests/cli` — CLI parsing
- `tests/performance` — marked `@pytest.mark.performance`

Integration tests use `DATABASE_URL` / `OUTBOX_TEST_DATABASE_URL` when set; otherwise Testcontainers PostgreSQL 16.
