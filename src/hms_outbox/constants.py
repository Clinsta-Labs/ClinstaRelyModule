"""Public package markers and shared constants."""

from enum import StrEnum


class EventStatus(StrEnum):
    """Supported Outbox event statuses."""

    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"
    SYNCED = "SYNCED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


VALID_STATUSES: frozenset[str] = frozenset(s.value for s in EventStatus)

# Error codes stored on failure / recovery / config issues.
ERROR_PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"
ERROR_ENDPOINT_NOT_CONFIGURED = "ENDPOINT_NOT_CONFIGURED"
ERROR_INVALID_RESPONSE = "INVALID_RESPONSE"
ERROR_INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
ERROR_HTTP_TIMEOUT = "HTTP_TIMEOUT"
ERROR_CONNECTION_REFUSED = "CONNECTION_REFUSED"
ERROR_NETWORK = "NETWORK_ERROR"

DEFAULT_TABLE_NAME = "outbox_event"
TABLE_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
EVENT_TYPE_PATTERN = r"^[A-Z][A-Z0-9_]*$"

# Target response headers (primary source of reply identity).
HEADER_REPLY_REFERENCE_TYPE = "X-Outbox-Reply-Reference-Type"
HEADER_REPLY_REFERENCE = "X-Outbox-Reply-Reference"
