"""Endpoint registry built from environment variables."""

from __future__ import annotations

from hms_outbox.config.settings import EndpointConfig, OutboxSettings
from hms_outbox.exceptions import ConfigurationError


class EndpointRegistry:
    """Maps EventType → HTTP endpoint configuration."""

    def __init__(self, endpoints: dict[str, EndpointConfig] | None = None) -> None:
        self._endpoints = dict(endpoints or {})

    @classmethod
    def from_settings(cls, settings: OutboxSettings) -> EndpointRegistry:
        return cls(settings.endpoints)

    def get(self, event_type: str) -> EndpointConfig | None:
        return self._endpoints.get(event_type)

    def require(self, event_type: str) -> EndpointConfig:
        endpoint = self.get(event_type)
        if endpoint is None:
            raise ConfigurationError(
                f"No OUTBOX_REPLAY_ENDPOINT_{event_type} configured"
            )
        return endpoint

    def has(self, event_type: str) -> bool:
        return event_type in self._endpoints

    def items(self) -> list[tuple[str, EndpointConfig]]:
        return sorted(self._endpoints.items())

    def __len__(self) -> int:
        return len(self._endpoints)
