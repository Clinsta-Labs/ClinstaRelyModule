"""Health and readiness checks."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from hms_outbox.config.settings import OutboxSettings
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.db.session import check_database_async, check_database_sync
from hms_outbox.exceptions import ConfigurationError


class HealthService:
    """Process health and readiness probes."""

    def __init__(
        self,
        settings: OutboxSettings,
        *,
        repository: OutboxRepository,
        sync_engine: Any | None = None,
        async_engine: AsyncEngine | None = None,
        sync_factory: sessionmaker[Session] | None = None,
        async_factory: async_sessionmaker[AsyncSession] | None = None,
        workers_initialized: bool = False,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.sync_engine = sync_engine
        self.async_engine = async_engine
        self.sync_factory = sync_factory
        self.async_factory = async_factory
        self.workers_initialized = workers_initialized

    def health(self) -> dict[str, Any]:
        """Liveness: process is running and configuration loads."""
        return {
            "status": "ok",
            "replayEnabled": self.settings.replay_enabled,
            "workersInitialized": self.workers_initialized,
        }

    def readiness(self) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        ready = True
        try:
            if self.sync_engine is not None:
                check_database_sync(self.sync_engine)
                checks["database"] = "ok"
            else:
                checks["database"] = "skipped"
        except Exception as exc:  # noqa: BLE001
            ready = False
            checks["database"] = f"error: {exc}"

        try:
            if self.sync_factory is not None:
                with self.sync_factory() as session:
                    if not self.repository.table_exists(session):
                        ready = False
                        checks["table"] = "missing"
                    else:
                        checks["table"] = "ok"
            else:
                checks["table"] = "skipped"
        except Exception as exc:  # noqa: BLE001
            ready = False
            checks["table"] = f"error: {exc}"

        if self.settings.replay_enabled and self.settings.worker_count <= 0:
            ready = False
            checks["workers"] = "invalid"
        else:
            checks["workers"] = "ok"

        return {"ready": ready, "checks": checks}

    async def readiness_async(self) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        ready = True
        try:
            if self.async_engine is not None:
                await check_database_async(self.async_engine)
                checks["database"] = "ok"
            else:
                checks["database"] = "skipped"
        except Exception as exc:  # noqa: BLE001
            ready = False
            checks["database"] = f"error: {exc}"

        try:
            if self.async_factory is not None:
                async with self.async_factory() as session:
                    if not await self.repository.table_exists_async(session):
                        ready = False
                        checks["table"] = "missing"
                    else:
                        checks["table"] = "ok"
            else:
                checks["table"] = "skipped"
        except Exception as exc:  # noqa: BLE001
            ready = False
            checks["table"] = f"error: {exc}"

        if self.settings.replay_enabled and self.settings.worker_count <= 0:
            ready = False
            checks["workers"] = "invalid"
        else:
            checks["workers"] = "ok"

        try:
            from hms_outbox.config.settings import validate_settings

            validate_settings(self.settings)
            checks["configuration"] = "ok"
        except ConfigurationError as exc:
            ready = False
            checks["configuration"] = str(exc)

        return {"ready": ready, "checks": checks}
