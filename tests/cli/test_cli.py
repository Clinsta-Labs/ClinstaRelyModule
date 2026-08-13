"""CLI smoke tests."""

from __future__ import annotations


import pytest

from hms_outbox.cli.main import build_parser, main


def test_parser_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["stats"]).command == "stats"
    assert parser.parse_args(["failed"]).command == "failed"
    assert parser.parse_args(["event", "00000000-0000-0000-0000-000000000001"]).command == "event"
    assert parser.parse_args(["retry", "00000000-0000-0000-0000-000000000001"]).command == "retry"
    assert parser.parse_args(["retry-group", "G1", "--organization-id", "1"]).command == "retry-group"
    assert parser.parse_args(["health"]).command == "health"
    assert parser.parse_args(["replay"]).command == "replay"


def test_main_invalid_event_id(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["event", "not-a-uuid"])
    assert code == 2
