"""Retry policy: backoff, jitter, exhaustion."""

from __future__ import annotations

import random
from dataclasses import dataclass

from hms_outbox.config.settings import OutboxSettings


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """Outcome of evaluating a failed attempt."""

    new_retry_count: int
    exhausted: bool
    delay_ms: int


class RetryPolicy:
    """Retry semantics.

    ``retry_count`` is the number of retry attempts already consumed,
    excluding the initial attempt.

    Exhaustion: after a failure, ``new_retry_count = old + 1``. If
    ``new_retry_count >= max_retry_count`` the event becomes
    ``RETRY_EXHAUSTED`` (when ``max_retry_count == 0``, the first failure
    exhausts with ``retry_count == 1``).
    """

    def __init__(
        self,
        *,
        max_retry_count: int,
        initial_retry_delay_ms: int,
        retry_backoff_multiplier: float,
        max_retry_delay_ms: int,
        retry_jitter: bool = True,
    ) -> None:
        self.max_retry_count = max_retry_count
        self.initial_retry_delay_ms = initial_retry_delay_ms
        self.retry_backoff_multiplier = retry_backoff_multiplier
        self.max_retry_delay_ms = max_retry_delay_ms
        self.retry_jitter = retry_jitter

    @classmethod
    def from_settings(cls, settings: OutboxSettings) -> RetryPolicy:
        return cls(
            max_retry_count=settings.max_retry_count,
            initial_retry_delay_ms=settings.initial_retry_delay_ms,
            retry_backoff_multiplier=settings.retry_backoff_multiplier,
            max_retry_delay_ms=settings.max_retry_delay_ms,
            retry_jitter=settings.retry_jitter,
        )

    def delay_for_retry_count(self, retry_count: int) -> int:
        """Delay before the next attempt given the current ``retry_count``.

        For ``retry_count == 1`` (after first failure) delay is the initial delay.
        """
        exponent = max(retry_count - 1, 0)
        delay = self.initial_retry_delay_ms * (self.retry_backoff_multiplier**exponent)
        delay_ms = int(min(delay, self.max_retry_delay_ms))
        if self.retry_jitter and delay_ms > 0:
            # Full jitter: [0.5 * delay, 1.5 * delay], capped at max.
            jittered = delay_ms * (0.5 + random.random())
            delay_ms = int(min(jittered, self.max_retry_delay_ms))
        return max(delay_ms, 0)

    def on_failure(self, current_retry_count: int) -> RetryDecision:
        new_retry_count = current_retry_count + 1
        if self.max_retry_count == 0:
            exhausted = True
        else:
            exhausted = new_retry_count >= self.max_retry_count
        delay_ms = 0 if exhausted else self.delay_for_retry_count(new_retry_count)
        return RetryDecision(
            new_retry_count=new_retry_count,
            exhausted=exhausted,
            delay_ms=delay_ms,
        )
