"""In-process metrics counters for the replay engine."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class ReplayMetrics:
    """Process-local counters (not persisted)."""

    events_processed_total: int = 0
    events_failed_total: int = 0
    events_synced_total: int = 0
    http_2xx_total: int = 0
    http_4xx_total: int = 0
    http_5xx_total: int = 0
    timeout_total: int = 0
    retry_total: int = 0
    processing_timeout_total: int = 0
    event_processing_duration_ms_total: float = 0.0
    http_request_duration_ms_total: float = 0.0
    active_workers: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            current = getattr(self, name)
            setattr(self, name, current + amount)

    def add_duration(self, name: str, ms: float) -> None:
        with self._lock:
            current = getattr(self, name)
            setattr(self, name, current + ms)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            return {
                "events_processed_total": self.events_processed_total,
                "events_failed_total": self.events_failed_total,
                "events_synced_total": self.events_synced_total,
                "http_2xx_total": self.http_2xx_total,
                "http_4xx_total": self.http_4xx_total,
                "http_5xx_total": self.http_5xx_total,
                "timeout_total": self.timeout_total,
                "retry_total": self.retry_total,
                "processing_timeout_total": self.processing_timeout_total,
                "event_processing_duration_ms_total": self.event_processing_duration_ms_total,
                "http_request_duration_ms_total": self.http_request_duration_ms_total,
                "active_workers": self.active_workers,
            }
