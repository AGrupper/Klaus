"""Human-readable rendering of action-log entries for the Hub's bell feed.

``ActionLogStore`` records what Klaus *did*, and its ``detail`` field is
whatever the calling tool passed — usually the raw MCP argument payload as
JSON, occasionally a hand-built string. Dumping that straight into the bell
produced rows like ``Klaus did: {"action_ids": [], "correlation_id": …``.

This module turns an entry into one plain sentence, decides which entries are
worth showing at all, and collapses rows that record the same physical write.
It is pure: no Firestore, no I/O.
"""
from __future__ import annotations

import json
from datetime import datetime

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


# Retired action name → the surviving name for the same act. Until commit
# 4d7742c Klaus owned its own calendar tools, and each one wrote an audit entry
# of its own beside the MCP gateway's — so one event create left two rows about
# 0.2s apart under different names. Nothing writes the left-hand names any more,
# but the rows they wrote sit in the bell's window until they age out.
_ACTION_TWINS = {
    "calendar_create": "create_calendar_event",
    "calendar_update": "update_calendar_event",
    "calendar_delete": "delete_calendar_event",
}

# Two rows about the same act land within a second of each other. The window is
# wide enough to absorb a slow write, far too narrow to swallow a genuine
# re-creation of the same event later on.
_TWIN_WINDOW_SECONDS = 300


def _parse_at(entry: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(entry.get("at") or ""))
    except ValueError:
        return None


def _same_moment(first: dict, second: dict) -> bool:
    """True when two entries were logged close enough to be one act.

    Unreadable timestamps answer False: keeping a duplicate is the cheaper
    failure here, and the whole point of this log is that nothing goes missing.
    """
    left, right = _parse_at(first), _parse_at(second)
    if left is None or right is None:
        return False
    return abs((left - right).total_seconds()) <= _TWIN_WINDOW_SECONDS


def _twin_key(entry: dict) -> tuple[str, str, str] | None:
    """Identify the calendar event an entry is about, or None if it can't.

    Both writers name the same event, in different shapes: the MCP payload
    carries ``summary``/``start_iso`` keys, the retired one a ``"<summary>,
    <start>"`` sentence. Returning None means "don't touch this row".
    """
    action = str(entry.get("action") or "").strip()
    canonical = _ACTION_TWINS.get(action, action)
    if canonical not in set(_ACTION_TWINS.values()):
        return None

    detail = entry.get("detail")
    if isinstance(detail, str) and detail.strip().startswith("{"):
        try:
            detail = json.loads(detail)
        except ValueError:
            return None

    summary = start = ""
    if isinstance(detail, dict):
        summary = str(detail.get("summary") or detail.get("title") or "")
        start = str(detail.get("start_iso") or detail.get("start") or "")
    elif isinstance(detail, str) and ", " in detail:
        summary, _, start = detail.rpartition(", ")

    summary = " ".join(summary.split()).casefold()
    if not summary:
        return None
    return (canonical, summary, start.strip())


def dedupe_actions(entries: list[dict]) -> list[dict]:
    """Collapse entries that record one physical write, preserving order.

    Two doublings exist, and neither is a write-path bug to be tidied away:

    * The idempotency gateway re-audits on its ``executed`` replay path
      (``interfaces/mcp/server.py``) so that a crash between a write and its
      audit can never lose the record. A replay re-appends under the same ``id``.
    * The retired Klaus-owned calendar tools audited alongside the MCP gateway
      (see ``_ACTION_TWINS``).

    Both are D-25 working as designed — nothing Klaus does to the calendar may
    stay invisible because one writer failed. So the collapse belongs here, on
    the read side, and only fires when two rows are positively the same act;
    ``GET /api/activity`` still serves the source records unmerged.
    """
    kept: list[dict] = []
    seen_ids: set[str] = set()
    twin_positions: dict[tuple[str, str, str], int] = {}

    for entry in entries:
        entry_id = str(entry.get("id") or "").strip()
        if entry_id and entry_id in seen_ids:
            continue

        key = _twin_key(entry)
        if key is not None:
            position = twin_positions.get(key)
            if position is not None and _same_moment(kept[position], entry):
                # The surviving tool's row quotes the event's name on its own;
                # the retired one trails a raw ISO timestamp. Prefer the former.
                if str(entry.get("action") or "") not in _ACTION_TWINS:
                    kept[position] = entry
                if entry_id:
                    seen_ids.add(entry_id)
                continue
            twin_positions[key] = len(kept)

        if entry_id:
            seen_ids.add(entry_id)
        kept.append(entry)

    return kept
