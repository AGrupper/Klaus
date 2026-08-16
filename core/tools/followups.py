"""Time-based follow-ups.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from core.tools.registry import tool

logger = logging.getLogger(__name__)


@tool({
        "name": "schedule_followup",
        "description": (
            "Schedule a self-managed check-back. You will be reminded at the chosen "
            "time and may polish, send, or defer at that point. `when` accepts ISO 8601 "
            "('2026-05-21T15:00:00+00:00') or natural language ('tomorrow 3pm', 'next monday 10am'). "
            "Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "when": {"type": "string", "description": "ISO 8601 or natural-language datetime."},
                "note": {"type": "string", "description": "Reminder text — what is this check-back about."},
            },
            "required": ["when", "note"],
        },
    })
def _handle_schedule_followup(when: str, note: str) -> str:
    """Schedule a self-managed follow-up. ISO 8601 preferred; falls back to
    dateutil for natural-language strings (D-12).

    WARNING 7 fix — ImportError is caught explicitly. If Plan 01's
    requirements.txt update did not deploy (Cloud Run on a stale image, or
    a dev env without `python-dateutil` synced), the
    `from dateutil import parser` statement raises ModuleNotFoundError.
    Without catching it here, the chat surfaces a 500. With the catch, the
    user gets a structured `could_not_parse_when` error and Klaus's next
    turn can re-frame.

    Args:
        when: ISO 8601 (e.g. "2026-05-21T15:00:00+00:00") OR natural-language
            string (e.g. "tomorrow 3pm", "next monday 10am").
        note: Reminder text — what the check-back is about.

    Returns:
        JSON string. On success: ``{"id": <uuid hex>, "due_at": <ISO 8601 UTC>}``.
        On parse failure: ``{"error": "could_not_parse_when: ..."}``.
    """
    from datetime import timezone as _tz

    try:
        due_dt = datetime.fromisoformat(when)
    except (ValueError, TypeError):
        try:
            from dateutil import parser as _dt_parser
            due_dt = _dt_parser.parse(when)
        except (ImportError, ValueError, TypeError, OverflowError) as exc:
            return json.dumps({"error": f"could_not_parse_when: {exc}"})

    if due_dt.tzinfo is None:
        due_dt = due_dt.replace(tzinfo=_tz.utc)
    due_iso = due_dt.astimezone(_tz.utc).isoformat()

    from memory.firestore_db import FollowupStore
    store = FollowupStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    result = store.add(due_at=due_iso, note=note, origin="klaus_self")
    return json.dumps(result)


@tool({
        "name": "list_followups",
        "description": (
            "List your pending self-scheduled check-backs. Returns id, due_at, note, defer_count "
            "for each. Cancelled and done follow-ups are excluded. Available through Claude MCP."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    })
def _handle_list_followups() -> str:
    """Return pending follow-ups, stripped of internal fields.

    Only `id`, `due_at`, `note`, `defer_count` are exposed — `created_at`,
    `status`, and `origin` stay internal to FollowupStore.
    """
    from memory.firestore_db import FollowupStore
    store = FollowupStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    pending = store.list_pending()
    stripped = [
        {
            "id": p.get("id", ""),
            "due_at": p.get("due_at", ""),
            "note": p.get("note", ""),
            "defer_count": int(p.get("defer_count", 0)),
        }
        for p in pending
    ]
    return json.dumps(stripped)


@tool({
        "name": "cancel_followup",
        "description": (
            "Cancel a previously scheduled follow-up by id. Idempotent — calling on an already-"
            "cancelled or already-done follow-up is safe. Returns {ok: bool}. Call directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Follow-up id from list_followups."}},
            "required": ["id"],
        },
    })
def _handle_cancel_followup(id: str) -> str:
    """Cancel a follow-up by id. Idempotent (D-15).

    Returns ``{"ok": True}`` whenever the doc exists (even if already
    cancelled). Returns ``{"ok": False}`` only when the id does not exist.
    """
    from memory.firestore_db import FollowupStore
    store = FollowupStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    ok = store.cancel(id)
    return json.dumps({"ok": bool(ok)})
