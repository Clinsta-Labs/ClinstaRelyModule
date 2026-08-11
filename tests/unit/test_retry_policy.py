"""Unit tests for retry policy."""

from __future__ import annotations

from hms_outbox.replay.retry_policy import RetryPolicy


def test_backoff_sequence_without_jitter() -> None:
    policy = RetryPolicy(
        max_retry_count=5,
        initial_retry_delay_ms=10000,
        retry_backoff_multiplier=2,
        max_retry_delay_ms=900000,
        retry_jitter=False,
    )
    assert policy.delay_for_retry_count(1) == 10000
    assert policy.delay_for_retry_count(2) == 20000
    assert policy.delay_for_retry_count(3) == 40000
    assert policy.delay_for_retry_count(4) == 80000
    assert policy.delay_for_retry_count(5) == 160000


def test_backoff_capped() -> None:
    policy = RetryPolicy(
        max_retry_count=10,
        initial_retry_delay_ms=10000,
        retry_backoff_multiplier=2,
        max_retry_delay_ms=900000,
        retry_jitter=False,
    )
    assert policy.delay_for_retry_count(20) == 900000


def test_exhaustion_at_max() -> None:
    policy = RetryPolicy(
        max_retry_count=3,
        initial_retry_delay_ms=10,
        retry_backoff_multiplier=2,
        max_retry_delay_ms=1000,
        retry_jitter=False,
    )
    d1 = policy.on_failure(0)
    assert d1.new_retry_count == 1 and not d1.exhausted
    d2 = policy.on_failure(1)
    assert d2.new_retry_count == 2 and not d2.exhausted
    d3 = policy.on_failure(2)
    assert d3.new_retry_count == 3 and d3.exhausted


def test_max_zero_exhausts_immediately() -> None:
    policy = RetryPolicy(
        max_retry_count=0,
        initial_retry_delay_ms=10,
        retry_backoff_multiplier=2,
        max_retry_delay_ms=1000,
        retry_jitter=False,
    )
    d = policy.on_failure(0)
    assert d.exhausted and d.new_retry_count == 1


def test_jitter_within_bounds() -> None:
    policy = RetryPolicy(
        max_retry_count=5,
        initial_retry_delay_ms=1000,
        retry_backoff_multiplier=2,
        max_retry_delay_ms=900000,
        retry_jitter=True,
    )
    delays = {policy.delay_for_retry_count(1) for _ in range(50)}
    assert min(delays) >= 500
    assert max(delays) <= 1500
