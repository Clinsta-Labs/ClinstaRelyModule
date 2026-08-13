"""FastAPI admin router tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hms_outbox.admin.service import AdminService
from hms_outbox.config.settings import OutboxSettings
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.fastapi.router import create_outbox_router
from hms_outbox.producer.producer import OutboxProducer
from hms_outbox.statistics.service import StatisticsService

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_admin_router_requires_api_key(
    async_session_factory: async_sessionmaker[AsyncSession],
    repository: OutboxRepository,
    settings: OutboxSettings,
    producer: OutboxProducer,
) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await producer.publish_async(
                session,
                organization_id=1,
                event_type="CUSTOMER_INVOICE",
                event_group="ADMIN",
                group_sequence=1,
                payload={},
            )

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(
        create_outbox_router(
            settings=settings,
            session_factory=async_session_factory,
            api_key="test-admin-key",
            admin_service=AdminService(repository),
            statistics_service=StatisticsService(repository, configured_workers=2),
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.get("/internal/outbox/statistics")
        assert unauthorized.status_code == 401
        resp = await client.get(
            "/internal/outbox/statistics",
            headers={"X-API-Key": "test-admin-key"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

        # retry-group requires organization_id
        missing_org = await client.post(
            "/internal/outbox/groups/ADMIN/retry",
            headers={"X-API-Key": "test-admin-key"},
        )
        assert missing_org.status_code == 422

        retry = await client.post(
            "/internal/outbox/groups/ADMIN/retry",
            params={"organization_id": 1},
            headers={"X-API-Key": "test-admin-key"},
        )
        assert retry.status_code == 200
        assert retry.json()["retried"] is False

        listed = await client.get(
            "/internal/outbox/events",
            params={"organization_id": 1},
            headers={"X-API-Key": "test-admin-key"},
        )
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1
