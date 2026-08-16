"""Per-dispatch caller identity.

Klaus is single-user, but the memory handlers still namespace every read and
write by user id so a vector can never be recalled across identities. The id is
thread-local because MCP dispatch runs handlers in a worker thread
(`asyncio.to_thread`), and a module-level global would be shared between
concurrent calls.
"""
from __future__ import annotations

import threading

_thread_local = threading.local()


def set_current_user_id(user_id: int) -> None:
    """Bind the canonical MCP user id for the current dispatch thread."""
    _thread_local.user_id = user_id


def _get_current_user_id() -> int:
    """Return the bound user id, or 0 when nothing has been bound."""
    return getattr(_thread_local, "user_id", 0)
