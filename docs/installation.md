# Installation

```bash
pip install hms-outbox
pip install "hms-outbox[fastapi,alembic]"   # optional extras
```

Editable install for development:

```bash
cd hms-outbox
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Migrate the Outbox table

```bash
export DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db
# or postgresql+asyncpg — Alembic env converts to psycopg automatically
alembic -c alembic.ini upgrade head
```

## Verify

```bash
python -m hms_outbox health
```
