"""Shared Google Calendar client for the Hub's day view.

Klaus publishes no calendar tools. Claude reaches the calendar through its own
Google Calendar connector, which is richer than anything reimplemented here and
is attached directly to the Project and to each routine.

What survives is the read Klaus cannot get from Claude: `core.hub.today` calls
`list_all_events` to build `GET /api/today`, and that same snapshot feeds
`get_life_snapshot` and `core.notifications.deterministic_alerts`. The alert
evaluator has no model in it, so nothing else can produce a conflict push.

Scheduling policy — travel buffers, Get Ready blocks, Training-calendar routing
— moved to the skills along with the write tools.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Lazy singletons. WHY lazy: importing this module must never trigger OAuth or
# network I/O — it is imported during tests and at cold start, long before any
# read is actually performed.
from core.auth.google import GoogleAuthManager, build_auth_manager_from_env  # noqa: E402
from mcp_tools.calendar_tool import GoogleCalendarManager  # noqa: E402

_auth_manager: GoogleAuthManager | None = None
_calendar_tool: GoogleCalendarManager | None = None


def _get_auth_manager() -> GoogleAuthManager:
    """Return the shared GoogleAuthManager, constructing it on first call.

    Delegates construction entirely to `build_auth_manager_from_env()`, which
    selects the correct token storage backend (file vs. Secret Manager) based
    on the `GOOGLE_TOKEN_STORAGE` env var. This makes the singleton work in
    both local dev and Cloud Run without any code changes here.
    """
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = build_auth_manager_from_env()
    return _auth_manager


def _get_calendar_tool() -> GoogleCalendarManager:
    """Return the shared GoogleCalendarManager instance, building it on first call.

    WHY shared: the instance retains Google's short-lived access token in
    process memory. The Hub rebuilds its day view every few minutes, and a new
    manager per call would re-exchange the same static refresh grant each time.
    """
    global _calendar_tool
    if _calendar_tool is None:
        _calendar_tool = GoogleCalendarManager(auth_manager=_get_auth_manager())
    return _calendar_tool
