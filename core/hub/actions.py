"""Human-readable rendering of action-log entries for the Hub's bell feed.

``ActionLogStore`` records what Klaus *did*, and its ``detail`` field is
whatever the calling tool passed — usually the raw MCP argument payload as
JSON, occasionally a hand-built string. Dumping that straight into the bell
produced rows like ``Klaus did: {"action_ids": [], "correlation_id": …``.

This module turns an entry into one plain sentence, and decides which entries
are worth showing at all. It is pure: no Firestore, no I/O.
"""
from __future__ import annotations

import json

# Actions the bell never shows. `publish_review` is the routine machinery
# recording that a review was published — the review itself is already a
# first-class bell item, so listing both is pure duplication (it was 26 of the
# last 60 entries).
_SUPPRESSED_ACTIONS = frozenset({"publish_review"})

# action → (verb phrase, ordered payload keys to quote after an em dash)
_ACTION_PHRASES: dict[str, tuple[str, tuple[str, ...]]] = {
    "calendar_create": ("Added a calendar event", ()),
    "create_calendar_event": ("Added a calendar event", ("summary", "title", "label")),
    "calendar_update": ("Updated a calendar event", ("summary", "title")),
    "update_calendar_event": ("Updated a calendar event", ("summary", "title")),
    "calendar_delete": ("Removed a calendar event", ()),
    "delete_calendar_event": ("Removed a calendar event", ("summary", "title")),
    "task_create": ("Filed a to-do", ("title",)),
    "task_edit": ("Edited a to-do", ("title",)),
    "task_complete": ("Completed a to-do", ("title",)),
    "task_delete": ("Deleted a to-do", ("title",)),
    "task_reschedule": ("Rescheduled a to-do", ("due_date",)),
    "remember": ("Remembered something", ("content",)),
    "forget_memory": ("Forgot a memory", ()),
    "schedule_followup": ("Scheduled a follow-up", ("note",)),
    "cancel_followup": ("Cancelled a follow-up", ()),
    "set_standing_directive": ("Set a standing directive", ("text",)),
    "cancel_standing_directive": ("Cancelled a standing directive", ()),
    "update_training_profile": ("Updated your training profile", ()),
    "log_training": ("Logged a training session", ("label", "title")),
    "log_benchmark": ("Logged a benchmark", ("facet", "label")),
    "publish_portfolio_snapshot": ("Recorded the weekly portfolio snapshot", ()),
    "upsert_portfolio_holding": ("Updated a portfolio holding", ("symbol", "name")),
    "start_block": ("Started a training block", ("name", "label")),
    "end_block": ("Ended a training block", ()),
    "update_plan": ("Updated your plan", ()),
}

# Any opaque-looking detail longer than this is dropped rather than quoted.
_MAX_QUOTE = 80


def _looks_like_identifier(value: str) -> bool:
    """True for bare ids (calendar event ids, uuids) — never worth showing."""
    stripped = value.strip()
    return (
        len(stripped) >= 16
        and " " not in stripped
        and not any(character in stripped for character in ".,:;!?")
    )


def _quote(value: object) -> str | None:
    """Return a short display string for a payload value, or None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(value)
    elif isinstance(value, str):
        text = " ".join(value.split())
    else:
        return None
    if not text or _looks_like_identifier(text):
        return None
    return text if len(text) <= _MAX_QUOTE else text[:_MAX_QUOTE].rstrip() + "…"


def humanize_action(entry: dict) -> str | None:
    """Return one plain sentence for an action-log entry, or None to hide it.

    Falls back to the action name with underscores spaced out, so a tool added
    later still reads sensibly here before anyone updates the table above.
    """
    action = str(entry.get("action") or "").strip()
    if action in _SUPPRESSED_ACTIONS:
        return None

    detail = entry.get("detail")
    payload: dict = {}
    plain: str | None = None
    if isinstance(detail, dict):
        payload = detail
    elif isinstance(detail, str) and detail.strip():
        text = detail.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
                payload = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                payload = {}
        else:
            plain = _quote(text)

    phrase, keys = _ACTION_PHRASES.get(
        action, (action.replace("_", " ").strip().capitalize() or "Did something", ())
    )

    # A hand-built human detail (legacy calendar_create) wins over payload keys.
    if plain:
        return f"{phrase} — {plain}"
    for key in keys:
        quoted = _quote(payload.get(key))
        if quoted:
            return f"{phrase} — {quoted}"
    return phrase
