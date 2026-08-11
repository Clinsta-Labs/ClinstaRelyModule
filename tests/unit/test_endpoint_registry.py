"""Unit tests for endpoint registry."""

from __future__ import annotations

import pytest

from hms_outbox.config.endpoint_registry import EndpointRegistry
from hms_outbox.config.settings import EndpointConfig
from hms_outbox.exceptions import ConfigurationError


def test_registry_require() -> None:
    registry = EndpointRegistry(
        {
            "CUSTOMER_INVOICE": EndpointConfig(
                event_type="CUSTOMER_INVOICE", url="http://x/y"
            )
        }
    )
    assert registry.has("CUSTOMER_INVOICE")
    assert registry.require("CUSTOMER_INVOICE").url == "http://x/y"
    with pytest.raises(ConfigurationError):
        registry.require("MISSING")
