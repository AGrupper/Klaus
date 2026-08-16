"""Task capture and management, backed by Things 3 through its mirror.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.tools.registry import tool
from core.tools.state import _get_current_user_id

logger = logging.getLogger(__name__)


def _get_task_store():
    """Return the sole authoritative Things task store.

    Firestore retains only the Things mirror and Klaus-specific sidecar/outbox
    fields during the soak.  ``TASK_BACKEND`` is intentionally ignored so a
    configuration typo or outage cannot turn Firestore into a silent authority.
    """
    from memory.firestore_db import get_task_store
    return get_task_store()


def _task_today_iso() -> str:
    """Return today's date in Asia/Jerusalem as YYYY-MM-DD."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()


@tool({
        "name": "task_create",
        "description": (
            "Add a to-do to Amit's Things 3 list. Set due_date for when Amit plans "
            "to DO it, and hard_deadline_at for when it is actually DUE — these are "
            "different fields in Things and either alone is fine. "
            "Always try to file it: pass list_id with the project or area it "
            "belongs to rather than letting it fall into the Inbox, which is where "
            "Amit's to-dos go to die. Use task_list to see what projects and areas "
            "exist. Only set a date when the timing is genuinely implied — do not "
            "invent one to make the to-do look scheduled; an undated to-do is "
            "honest, a fabricated date is noise."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "To-do title."},
                "notes": {"type": "string", "description": "Optional notes or details."},
                "due_date": {
                    "type": "string",
                    "description": "Scheduled date — when Amit plans to work on it (YYYY-MM-DD). Things calls this 'When'.",
                },
                "due_time": {
                    "type": "string",
                    "description": "Reminder time (HH:MM, 24-hour, local). Only meaningful alongside due_date.",
                },
                "hard_deadline_at": {
                    "type": "string",
                    "description": "Deadline — when it must be finished (YYYY-MM-DD). Independent of due_date; Things stores day granularity.",
                },
                "list_id": {
                    "type": "string",
                    "description": "Things project or area id to file it under. Omit for the Inbox.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Things tag ids to attach. Use task_list to discover existing tags.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["none", "low", "medium", "high"],
                    "description": "Klaus-internal only — Things has no priority field, so this is stored on Klaus's side and is NOT visible in the Things app.",
                },
                "estimated_minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1440,
                    "description": "Klaus-internal: estimated focused work duration in minutes.",
                },
                "auto_schedule": {
                    "type": "boolean",
                    "description": "Klaus-internal: whether Klaus may place this into movable calendar blocks.",
                },
                "manual_lock": {
                    "type": "boolean",
                    "description": "Klaus-internal: Amit fixed the placement and Klaus must not move it.",
                },
                "calendar_event_id": {
                    "type": "string",
                    "description": "Klaus-internal: linked Klaus-owned calendar time-block event id.",
                },
            },
            "required": ["title"],
        },
    })
def _handle_task_create(
    title: str,
    notes: str | None = None,
    due_date: str | None = None,
    due_time: str | None = None,
    priority: str | None = None,
    list_id: str | None = None,
    tags: list | None = None,
    recurrence: dict | None = None,
    estimated_minutes: int | None = None,
    hard_deadline_at: str | None = None,
    auto_schedule: bool | None = None,
    manual_lock: bool | None = None,
    calendar_event_id: str | None = None,
) -> str:
    """Create a new task in TaskStore and return the created document."""
    store = _get_task_store()
    kwargs: dict = {"title": title}
    if notes is not None:
        kwargs["notes"] = notes
    if due_date is not None:
        kwargs["due_date"] = due_date
    if due_time is not None:
        kwargs["due_time"] = due_time
    if priority is not None:
        kwargs["priority"] = priority
    if list_id is not None:
        kwargs["list_id"] = list_id
    if tags is not None:
        kwargs["tag_ids"] = tags
    if recurrence is not None:
        # Things owns recurrence; the Things backend ignores this. Kept so the
        # Firestore fallback backend still behaves as it did in Phase 27.
        kwargs["recurrence"] = recurrence
    if estimated_minutes is not None:
        kwargs["estimated_minutes"] = estimated_minutes
    if hard_deadline_at is not None:
        kwargs["hard_deadline_at"] = hard_deadline_at
    if auto_schedule is not None:
        kwargs["auto_schedule"] = auto_schedule
    if manual_lock is not None:
        kwargs["manual_lock"] = manual_lock
    if calendar_event_id is not None:
        kwargs["calendar_event_id"] = calendar_event_id
    # TaskStore.create takes a single task dict (not kwargs) — passing **kwargs
    # raised TypeError and made Klaus's task_create reject every entry.
    result = store.create(kwargs)
    return json.dumps(result)


@tool({
        "name": "task_list",
        "description": (
            "Read Amit's open Things 3 to-dos. All filters are optional — omit them "
            "all to see the whole list, including project, area, and tag labels. "
            "Use upcoming_days to see the week ahead; note that Amit dates very few "
            "to-dos, so most of his list has no date at all and a date filter will "
            "usually come back empty. "
            "Every to-do also carries created_at (how long it has been sitting — "
            "the median age of his list is around four months, so this is how you "
            "spot what has gone stale), hard_deadline_at (a real deadline, distinct "
            "from the scheduled date), and bucket (inbox, anytime, upcoming or "
            "someday). An item in 'inbox' is unfiled and probably needs a home."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {
                    "type": "string",
                    "description": "Filter to a Things project or area id, or 'inbox' for unfiled to-dos.",
                },
                "date": {
                    "type": "string",
                    "description": "Only to-dos scheduled on this date (YYYY-MM-DD).",
                },
                "upcoming_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "description": "Only to-dos landing within this many days, by scheduled date OR deadline. Use 7 for the coming week.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["none", "low", "medium", "high"],
                    "description": "Filter by Klaus-internal priority (not a Things field).",
                },
                "overdue": {
                    "type": "boolean",
                    "description": "If true, only to-dos whose scheduled date is before today.",
                },
            },
            "required": [],
        },
    })
def _handle_task_list(
    list_id: str | None = None,
    date: str | None = None,
    upcoming_days: int | None = None,
    priority: str | None = None,
    overdue: bool | None = None,
) -> str:
    """Query tasks from the active store with optional filters."""
    store = _get_task_store()
    if overdue:
        tasks = store.get_overdue(_task_today_iso())
    elif upcoming_days:
        # get_upcoming checks scheduled date AND deadline; only the Things backend
        # has it, so fall back to a date-range scan on the Firestore store.
        get_upcoming = getattr(store, "get_upcoming", None)
        if get_upcoming:
            tasks = get_upcoming(_task_today_iso(), days=upcoming_days)
        else:
            from datetime import date as _date, timedelta
            today = _task_today_iso()
            horizon = (_date.fromisoformat(today) + timedelta(days=upcoming_days)).isoformat()
            tasks = [t for t in store.list(list_id=list_id)
                     if t.get("due_date") and today <= t["due_date"] <= horizon]
    elif date:
        # list all tasks then filter by due_date in Python (simple approach)
        all_tasks = store.list(list_id=list_id)
        tasks = [t for t in all_tasks if t.get("due_date") == date]
    else:
        tasks = store.list(list_id=list_id)
        if priority:
            tasks = [t for t in tasks if t.get("priority") == priority]
    return json.dumps(tasks)


@tool({
        "name": "task_complete",
        "description": (
            "Tick off a to-do in Things. Recurring to-dos are handled by Things "
            "itself, which spawns the next instance — 'next_id' is always null and "
            "you must never create the follow-up yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The to-do id to complete."},
            },
            "required": ["task_id"],
        },
    })
def _handle_task_complete(task_id: str) -> str:
    """Mark a task complete. Generates next recurring instance if applicable."""
    store = _get_task_store()
    result = store.complete(task_id, completed_on_iso=_task_today_iso())
    return json.dumps(result)


@tool({
        "name": "task_reschedule",
        "description": (
            "Move when Amit plans to WORK on a to-do. This changes the scheduled "
            "date only and deliberately leaves any deadline untouched — use "
            "task_edit's hard_deadline_at to move an actual deadline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The to-do id to reschedule."},
                "due_date": {
                    "type": "string",
                    "description": "New scheduled date (YYYY-MM-DD).",
                },
                "due_time": {
                    "type": "string",
                    "description": "New reminder time (HH:MM, 24-hour). Optional.",
                },
            },
            "required": ["task_id", "due_date"],
        },
    })
def _handle_task_reschedule(
    task_id: str,
    due_date: str,
    due_time: str | None = None,
) -> str:
    """Update due_date (and optionally due_time) on a task."""
    store = _get_task_store()
    updates: dict = {"due_date": due_date}
    if due_time is not None:
        updates["due_time"] = due_time
    result = store.update(task_id, updates)
    return json.dumps(result)


@tool({
        "name": "task_edit",
        "description": (
            "Edit a to-do in Things. Only the fields you provide are changed; "
            "everything else is left exactly as it is."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The to-do id to edit."},
                "title": {"type": "string", "description": "New title."},
                "notes": {"type": "string", "description": "New notes."},
                "hard_deadline_at": {
                    "type": "string",
                    "description": "New deadline — when it must be finished (YYYY-MM-DD). Separate from the scheduled date.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["none", "low", "medium", "high"],
                    "description": "Klaus-internal only — not visible in the Things app.",
                },
                "list_id": {"type": "string", "description": "Move to this Things project or area id."},
                "estimated_minutes": {
                    "type": "integer", "minimum": 1, "maximum": 1440,
                    "description": "Klaus-internal: updated estimated duration in minutes.",
                },
                "auto_schedule": {
                    "type": "boolean",
                    "description": "Klaus-internal: allow or disallow Klaus-owned time blocking.",
                },
                "manual_lock": {
                    "type": "boolean",
                    "description": "Klaus-internal: protect the current placement from automatic moves.",
                },
                "calendar_event_id": {
                    "type": "string",
                    "description": "Klaus-internal: linked Klaus-owned calendar time-block event id.",
                },
            },
            "required": ["task_id"],
        },
    })
def _handle_task_edit(
    task_id: str,
    title: str | None = None,
    notes: str | None = None,
    priority: str | None = None,
    list_id: str | None = None,
    estimated_minutes: int | None = None,
    hard_deadline_at: str | None = None,
    auto_schedule: bool | None = None,
    manual_lock: bool | None = None,
    calendar_event_id: str | None = None,
) -> str:
    """Edit title, notes, priority, and/or list of a task."""
    store = _get_task_store()
    updates: dict = {}
    if title is not None:
        updates["title"] = title
    if notes is not None:
        updates["notes"] = notes
    if priority is not None:
        updates["priority"] = priority
    if list_id is not None:
        updates["list_id"] = list_id
    if estimated_minutes is not None:
        updates["estimated_minutes"] = estimated_minutes
    if hard_deadline_at is not None:
        updates["hard_deadline_at"] = hard_deadline_at
    if auto_schedule is not None:
        updates["auto_schedule"] = auto_schedule
    if manual_lock is not None:
        updates["manual_lock"] = manual_lock
    if calendar_event_id is not None:
        updates["calendar_event_id"] = calendar_event_id
    result = store.update(task_id, updates)
    return json.dumps(result)


@tool({
        "name": "task_delete",
        "description": (
            "Move a to-do to the Things trash. Recoverable by hand from the app — "
            "Klaus never destroys a to-do outright."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The to-do id to trash."},
            },
            "required": ["task_id"],
        },
    })
def _handle_task_delete(task_id: str) -> str:
    """Permanently delete a task."""
    store = _get_task_store()
    store.delete(task_id)
    return json.dumps({"deleted": task_id})
