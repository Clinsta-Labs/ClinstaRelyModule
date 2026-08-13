"""Optional FastAPI admin router.

WARNING: These endpoints are for internal / authenticated administrative
access only. Do NOT expose them on the public internet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hms_outbox.admin.service import AdminService
from hms_outbox.config.settings import OutboxSettings, load_settings
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.db.session import create_async_db_engine, create_async_session_factory
from hms_outbox.exceptions import EventNotFoundError, InvalidEventStateError
from hms_outbox.health.service import HealthService
from hms_outbox.models.event import create_outbox_event_model
from hms_outbox.statistics.service import StatisticsService


def create_outbox_router(
    *,
    settings: OutboxSettings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    engine: AsyncEngine | None = None,
    admin_service: AdminService | None = None,
    statistics_service: StatisticsService | None = None,
    health_service: HealthService | None = None,
    api_key: str | None = None,
    prefix: str = "/internal/outbox",
) -> APIRouter:
    """Create a ready-to-mount FastAPI router for Outbox admin APIs.

    Authentication: require ``X-API-Key`` matching ``OUTBOX_ADMIN_API_KEY``.
    """
    cfg = settings or load_settings()
    expected_key = api_key if api_key is not None else cfg.admin_api_key
    if not expected_key:
        raise RuntimeError(
            "OUTBOX_ADMIN_API_KEY must be set to mount the Outbox admin router. "
            "Admin APIs must not be anonymous."
        )

    db_engine = engine
    factory = session_factory
    if factory is None:
        db_engine = db_engine or create_async_db_engine(cfg)
        factory = create_async_session_factory(db_engine)

    model = create_outbox_event_model(cfg.table_name)
    repository = OutboxRepository(model)
    stats = statistics_service or StatisticsService(
        repository, configured_workers=cfg.worker_count
    )
    admin = admin_service or AdminService(repository)
    health = health_service or HealthService(
        cfg,
        repository=repository,
        async_engine=db_engine,
        async_factory=factory,
    )

    router = APIRouter(prefix=prefix, tags=["outbox-admin"])

    async def require_api_key(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> None:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing X-API-Key",
            )

    async def get_session() -> Any:
        assert factory is not None
        async with factory() as session:
            yield session

    @router.get("/statistics", dependencies=[Depends(require_api_key)])
    async def statistics_endpoint(
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        return await stats.get_statistics_async(session)

    @router.get("/events", dependencies=[Depends(require_api_key)])
    async def list_events(
        session: AsyncSession = Depends(get_session),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        organization_id: int | None = None,
        event_type: str | None = None,
        event_group: str | None = None,
        status_filter: str | None = Query(None, alias="status"),
        reference_type: str | None = None,
        reference: str | None = None,
    ) -> dict[str, Any]:
        return await admin.get_events_async(
            session,
            limit=limit,
            offset=offset,
            organization_id=organization_id,
            event_type=event_type,
            event_group=event_group,
            status=status_filter,
            reference_type=reference_type,
            reference=reference,
        )

    @router.get("/events/failed", dependencies=[Depends(require_api_key)])
    async def list_failed(
        session: AsyncSession = Depends(get_session),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        organization_id: int | None = None,
        event_type: str | None = None,
        event_group: str | None = None,
        reference_type: str | None = None,
        reference: str | None = None,
        retry_count: int | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        status_filter: str | None = Query(None, alias="status"),
    ) -> dict[str, Any]:
        return await admin.get_failed_events_async(
            session,
            limit=limit,
            offset=offset,
            organization_id=organization_id,
            event_type=event_type,
            event_group=event_group,
            reference_type=reference_type,
            reference=reference,
            retry_count=retry_count,
            created_from=created_from,
            created_to=created_to,
            status=status_filter,
        )

    @router.get("/events/{event_id}", dependencies=[Depends(require_api_key)])
    async def get_event(
        event_id: uuid.UUID, session: AsyncSession = Depends(get_session)
    ) -> dict[str, Any]:
        try:
            return await admin.get_event_async(session, event_id)
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/events/{event_id}/retry", dependencies=[Depends(require_api_key)])
    async def retry_event(
        event_id: uuid.UUID, session: AsyncSession = Depends(get_session)
    ) -> dict[str, Any]:
        try:
            async with session.begin():
                return await admin.retry_event_async(session, event_id)
        except EventNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidEventStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/groups/{group}/retry", dependencies=[Depends(require_api_key)])
    async def retry_group(
        group: str,
        organization_id: int = Query(..., ge=1),
        session: AsyncSession = Depends(get_session),
    ) -> dict[str, Any]:
        async with session.begin():
            return await admin.retry_group_async(session, organization_id, group)

    @router.get("/health")
    async def health_endpoint() -> dict[str, Any]:
        return health.health()

    @router.get("/ready")
    async def ready_endpoint() -> dict[str, Any]:
        result = await health.readiness_async()
        if not result.get("ready"):
            raise HTTPException(status_code=503, detail=result)
        return result

    return router
