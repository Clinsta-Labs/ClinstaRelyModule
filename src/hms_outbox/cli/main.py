"""CLI entrypoint: ``python -m hms_outbox``."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from typing import Any

from hms_outbox.config.settings import load_settings
from hms_outbox.db.repository import OutboxRepository
from hms_outbox.db.session import (
    create_sync_engine,
    create_sync_session_factory,
)
from hms_outbox.exceptions import EventNotFoundError, InvalidEventStateError, OutboxError
from hms_outbox.health.service import HealthService
from hms_outbox.models.event import create_outbox_event_model
from hms_outbox.replay.engine import ReplayEngine
from hms_outbox.statistics.service import StatisticsService


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_replay(_: argparse.Namespace) -> int:
    settings = load_settings()
    if not settings.replay_enabled:
        print(
            "OUTBOX_REPLAY_ENABLED is false. Set OUTBOX_REPLAY_ENABLED=true to start replay.",
            file=sys.stderr,
        )
        return 2
    engine = ReplayEngine(settings)

    async def _run() -> None:
        await engine.run_forever()

    asyncio.run(_run())
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    settings = load_settings(validate=False)
    engine = create_sync_engine(settings)
    factory = create_sync_session_factory(engine)
    model = create_outbox_event_model(settings.table_name)
    repo = OutboxRepository(model)
    stats = StatisticsService(repo, configured_workers=settings.worker_count)
    with factory() as session:
        _print_json(stats.get_statistics(session))
    engine.dispose()
    return 0


def cmd_failed(args: argparse.Namespace) -> int:
    settings = load_settings(validate=False)
    engine = create_sync_engine(settings)
    factory = create_sync_session_factory(engine)
    model = create_outbox_event_model(settings.table_name)
    repo = OutboxRepository(model)
    with factory() as session:
        rows, total = repo.list_failed(
            session,
            limit=args.limit,
            offset=args.offset,
            event_type=args.event_type,
            event_group=args.event_group,
        )
        _print_json(
            {
                "total": total,
                "items": [r.to_dict() for r in rows],
            }
        )
    engine.dispose()
    return 0


def cmd_event(args: argparse.Namespace) -> int:
    try:
        event_id = uuid.UUID(args.event_id)
    except ValueError:
        print(f"Invalid event id: {args.event_id}", file=sys.stderr)
        return 2
    settings = load_settings(validate=False)
    engine = create_sync_engine(settings)
    factory = create_sync_session_factory(engine)
    model = create_outbox_event_model(settings.table_name)
    repo = OutboxRepository(model)
    with factory() as session:
        try:
            event = repo.get_required(session, event_id)
        except EventNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        _print_json(event.to_dict())
    engine.dispose()
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    try:
        event_id = uuid.UUID(args.event_id)
    except ValueError:
        print(f"Invalid event id: {args.event_id}", file=sys.stderr)
        return 2
    settings = load_settings(validate=False)
    engine = create_sync_engine(settings)
    factory = create_sync_session_factory(engine)
    model = create_outbox_event_model(settings.table_name)
    repo = OutboxRepository(model)
    with factory() as session:
        try:
            with session.begin():
                event = repo.retry_event(session, event_id)
            _print_json(event.to_dict())
        except (EventNotFoundError, InvalidEventStateError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    engine.dispose()
    return 0


def cmd_retry_group(args: argparse.Namespace) -> int:
    settings = load_settings(validate=False)
    engine = create_sync_engine(settings)
    factory = create_sync_session_factory(engine)
    model = create_outbox_event_model(settings.table_name)
    repo = OutboxRepository(model)
    with factory() as session:
        with session.begin():
            event = repo.retry_group(session, args.group)
        if event is None:
            _print_json({"retried": False, "event": None})
        else:
            _print_json({"retried": True, "event": event.to_dict()})
    engine.dispose()
    return 0


def cmd_health(_: argparse.Namespace) -> int:
    settings = load_settings(validate=False)
    sync_engine = create_sync_engine(settings)
    factory = create_sync_session_factory(sync_engine)
    model = create_outbox_event_model(settings.table_name)
    repo = OutboxRepository(model)
    health = HealthService(
        settings,
        repository=repo,
        sync_engine=sync_engine,
        sync_factory=factory,
    )
    payload = {"health": health.health(), "readiness": health.readiness()}
    _print_json(payload)
    sync_engine.dispose()
    return 0 if payload["readiness"].get("ready") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hms-outbox",
        description="HMS transactional Outbox producer/replay CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_replay = sub.add_parser("replay", help="Run the Outbox replay worker pool")
    p_replay.set_defaults(func=cmd_replay)

    p_stats = sub.add_parser("stats", help="Print Outbox statistics")
    p_stats.set_defaults(func=cmd_stats)

    p_failed = sub.add_parser("failed", help="List failed / retry-exhausted events")
    p_failed.add_argument("--limit", type=int, default=50)
    p_failed.add_argument("--offset", type=int, default=0)
    p_failed.add_argument("--event-type")
    p_failed.add_argument("--event-group")
    p_failed.set_defaults(func=cmd_failed)

    p_event = sub.add_parser("event", help="Show a single event")
    p_event.add_argument("event_id")
    p_event.set_defaults(func=cmd_event)

    p_retry = sub.add_parser("retry", help="Manually retry an event")
    p_retry.add_argument("event_id")
    p_retry.set_defaults(func=cmd_retry)

    p_rg = sub.add_parser(
        "retry-group",
        help="Retry lowest-sequence RETRY_EXHAUSTED event in a group",
    )
    p_rg.add_argument("group")
    p_rg.set_defaults(func=cmd_retry_group)

    p_health = sub.add_parser("health", help="Health and readiness checks")
    p_health.set_defaults(func=cmd_health)

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except OutboxError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
