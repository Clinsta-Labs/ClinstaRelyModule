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

### Upgrading to 0.2.0

`0.2.0` adds mandatory `organization_id INTEGER NOT NULL`.

- **Greenfield:** initial migration already includes the column.
- **Existing empty table:** revision `20260813_0002` adds the column.
- **Existing rows without org:** migration refuses to invent ids — truncate or backfill before upgrade.

## Verify

```bash
python -m hms_outbox health
```
