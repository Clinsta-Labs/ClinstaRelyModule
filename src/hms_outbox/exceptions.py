"""Package exceptions."""


class OutboxError(Exception):
    """Base error for hms-outbox."""


class ConfigurationError(OutboxError):
    """Invalid or missing configuration."""


class EventNotFoundError(OutboxError):
    """Requested event does not exist."""


class InvalidEventStateError(OutboxError):
    """Operation is not allowed for the event's current state."""


class ClaimConflictError(OutboxError):
    """Event ownership conflict during status update."""
