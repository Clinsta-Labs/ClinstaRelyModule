FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY examples ./examples

RUN pip install --no-cache-dir -e ".[fastapi,alembic]"

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "hms_outbox", "replay"]
