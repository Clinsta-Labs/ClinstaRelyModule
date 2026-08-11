"""FastAPI integration package.

WARNING: Admin APIs are for internal authenticated use only.
Do not expose them publicly.
"""

from hms_outbox.fastapi.router import create_outbox_router

__all__ = ["create_outbox_router"]
