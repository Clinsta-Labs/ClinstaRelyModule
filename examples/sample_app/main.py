"""Minimal FastAPI sample demonstrating Outbox producer + admin router."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hms_outbox import OutboxProducer
from hms_outbox.config.settings import load_settings
from hms_outbox.db.session import create_async_db_engine, create_async_session_factory
from hms_outbox.fastapi import create_outbox_router

settings = load_settings()
engine = create_async_db_engine(settings)
session_factory: async_sessionmaker[AsyncSession] = create_async_session_factory(engine)
producer = OutboxProducer(table_name=settings.table_name)

app = FastAPI(title="Pharmacy sample (hms-outbox)")
app.include_router(create_outbox_router(settings=settings, session_factory=session_factory))


@app.post("/demo/invoice")
async def create_invoice(body: dict[str, Any]) -> dict[str, Any]:
    customer_id = str(body.get("customerId", "1001"))
    sequence = int(body.get("sequence", 1))
    invoice_id = str(body.get("invoiceId", f"INV-{sequence}"))
    async with session_factory() as session:
        async with session.begin():
            event_id = await producer.publish_async(
                session,
                event_type="CUSTOMER_INVOICE",
                event_group=f"CUSTOMER-{customer_id}",
                group_sequence=sequence,
                reference_type="INVOICE",
                reference=invoice_id,
                payload={"invoiceId": invoice_id, "customerId": customer_id},
            )
    return {"eventId": str(event_id), "invoiceId": invoice_id}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "replayEnabled": str(os.environ.get("OUTBOX_REPLAY_ENABLED"))}
