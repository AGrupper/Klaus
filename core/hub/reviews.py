"""Browser-safe shaping of published routine reviews.

A stored review carries internal fields the Hub has no business receiving, so
the client view is an explicit allowlist rather than a blocklist: a field added
to the store is invisible to the browser until someone deliberately lists it.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_REVIEW_CLIENT_FIELDS = frozenset({
    "review_id",
    "correlation_id",
    "routine",
    "target_date",
    "routine_status",
    "provider",
    "review_text",
    "structured",
    "action_ids",
    "partial_actions",
    "published_at",
})


def _review_for_client(review: dict, runs) -> dict:
    """Return a browser-safe canonical review with optional Claude navigation."""
    from core.review_delivery import normalise_claude_session_url

    result = {
        key: value for key, value in review.items() if key in _REVIEW_CLIENT_FIELDS
    }
    session_url = normalise_claude_session_url(review.get("claude_session_url"))
    if not session_url and review.get("correlation_id"):
        run = runs.get(str(review["correlation_id"])) or {}
        session_url = normalise_claude_session_url(run.get("claude_session_url"))
        if not session_url:
            remote = run.get("remote_trigger_result")
            session_url = normalise_claude_session_url(
                remote.get("claude_code_session_url")
                if isinstance(remote, dict)
                else None
            )
    if session_url:
        result["claude_session_url"] = session_url
    return result
