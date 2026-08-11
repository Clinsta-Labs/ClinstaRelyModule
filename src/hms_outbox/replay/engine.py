"""Replay engine: worker pool + recovery loop."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hms_outbox.config.endpoint_registry import EndpointRegistry
from hms_outbox.config.settings import OutboxSettings, load_settings, validate_settings
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.db.session import create_async_db_engine, create_async_session_factory
from hms_outbox.exceptions import ConfigurationError
from hms_outbox.http.client import OutboxHttpClient
from hms_outbox.models.event import create_outbox_event_model
from hms_outbox.replay.claimer import EventClaimer
from hms_outbox.replay.dispatcher import EventDispatcher
from hms_outbox.replay.metrics import ReplayMetrics
from hms_outbox.replay.recovery import ProcessingRecovery, RecoveryLoop
from hms_outbox.replay.retry_policy import RetryPolicy
from hms_outbox.replay.worker import ReplayWorker

logger = logging.getLogger("hms_outbox.engine")


def build_worker_id(index: int, *, hostname: str | None = None, pid: int | None = None) -> str:
    if hostname:
        host = hostname
    elif hasattr(os, "uname"):
        host = os.uname().nodename
    else:
        host = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "host"
    process_id = pid if pid is not None else os.getpid()
    return f"{host}:{process_id}:worker-{index}"


class ReplayEngine:
    """Configurable worker-pool replay engine.

    Delivery is **at-least-once**. EventId is preserved across retries.
    """

    def __init__(
        self,
        settings: OutboxSettings,
        *,
        engine: AsyncEngine | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        http_client: OutboxHttpClient | None = None,
        metrics: ReplayMetrics | None = None,
    ) -> None:
        if not settings.replay_enabled:
            raise ConfigurationError(
                "OUTBOX_REPLAY_ENABLED is false; refusing to start ReplayEngine"
            )
        validate_settings(settings, require_replay=True)
        self.settings = settings
        self.metrics = metrics or ReplayMetrics()
        self._owns_engine = engine is None
        self.db_engine = engine or create_async_db_engine(settings)
        self.session_factory = session_factory or create_async_session_factory(self.db_engine)
        self.model = create_outbox_event_model(settings.table_name)
        self.repository = OutboxRepository(self.model)
        self.registry = EndpointRegistry.from_settings(settings)
        self.retry_policy = RetryPolicy.from_settings(settings)
        self.claimer = EventClaimer(self.repository, settings)
        self._http_client = http_client or OutboxHttpClient(settings)
        self.dispatcher = EventDispatcher(
            registry=self.registry,
            http_client=self._http_client,
            metrics=self.metrics,
            log_payload=settings.log_payload,
        )
        self.recovery = ProcessingRecovery(
            repository=self.repository,
            settings=settings,
            retry_policy=self.retry_policy,
            metrics=self.metrics,
        )
        self._workers: list[ReplayWorker] = []
        self._tasks: list[asyncio.Task[Any]] = []
        self._recovery_loop: RecoveryLoop | None = None
        self._started = False

    @classmethod
    def from_env(cls) -> ReplayEngine:
        return cls(load_settings())

    async def start(self) -> None:
        if self._started:
            return
        async with self.session_factory() as session:
            exists = await self.repository.table_exists_async(session)
            if not exists:
                raise ConfigurationError(
                    f"Outbox table {self.settings.table_name!r} does not exist; "
                    "run migrations first"
                )
        self._workers = [
            ReplayWorker(
                worker_id=build_worker_id(i),
                session_factory=self.session_factory,
                claimer=self.claimer,
                dispatcher=self.dispatcher,
                repository=self.repository,
                retry_policy=self.retry_policy,
                metrics=self.metrics,
                poll_interval_ms=self.settings.poll_interval_ms,
            )
            for i in range(self.settings.worker_count)
        ]
        self._recovery_loop = RecoveryLoop(
            recovery=self.recovery,
            session_factory=self.session_factory,
            interval_ms=min(5000, max(1000, self.settings.processing_timeout_ms // 2)),
        )
        self._tasks = [asyncio.create_task(w.run(), name=w.worker_id) for w in self._workers]
        self._tasks.append(
            asyncio.create_task(self._recovery_loop.run(), name="outbox-recovery")
        )
        self._started = True
        logger.info(
            "Replay engine started",
            extra={
                "worker_count": self.settings.worker_count,
                "endpoints": len(self.registry),
            },
        )

    async def stop(self) -> None:
        for worker in self._workers:
            worker.stop()
        if self._recovery_loop:
            self._recovery_loop.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self._http_client.aclose()
        if self._owns_engine:
            await self.db_engine.dispose()
        self._started = False
        logger.info("Replay engine stopped")

    async def run_forever(self) -> None:
        await self.start()
        stop_event = asyncio.Event()

        def _signal_handler(*_: object) -> None:
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                # Windows
                signal.signal(sig, lambda *_: stop_event.set())

        await stop_event.wait()
        await self.stop()
