"""Safe metadata helpers for Claude routine review delivery."""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit


ROUTINE_NAMES = frozenset({"morning", "nightly", "weekly"})
_SESSION_PATH = re.compile(r"^/(?:code|epitaxy)/session_[A-Za-z0-9_-]+$")


def normalise_claude_session_url(value: object) -> str | None:
    """Return a canonical, safe Claude session URL or ``None`` for unsafe input."""
    if not isinstance(value, str) or any(
        ord(char) < 32 or ord(char) == 127 for char in value
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname not in {"claude.ai", "www.claude.ai"}:
        return None
    if parsed.username or parsed.password or port not in {None, 443}:
        return None
    path = parsed.path.rstrip("/")
    if not _SESSION_PATH.fullmatch(path):
        return None
    return urlunsplit(("https", "claude.ai", path, "", ""))


def routine_review_path(routine: str, target_date: str) -> str:
    """Return the deterministic Hub route for a supported routine review."""
    if routine not in ROUTINE_NAMES:
        raise ValueError(f"unsupported routine: {routine}")
    try:
        parsed_date = date.fromisoformat(target_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("target_date must be an ISO date") from exc
    canonical = parsed_date.isoformat()
    if canonical != target_date:
        raise ValueError("target_date must be an ISO date")
    return f"/klaus/reviews/{routine}/{canonical}"


def routine_review_title(routine: str) -> str:
    """Return the user-visible title for a supported routine review."""
    if routine not in ROUTINE_NAMES:
        raise ValueError(f"unsupported routine: {routine}")
    return f"Klaus {routine.title()} Review"
