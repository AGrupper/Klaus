"""Calendar reads and writes.

Scheduling policy (travel buffers, Get Ready blocks, Training-calendar
routing) lives in mcp_tools.calendar_tool; these handlers add Klaus's
duplicate detection, action audit trail and training write-back.

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

# Lazy singletons. WHY lazy: importing this module must never trigger OAuth or
# network I/O — it is imported during tests and at cold start, long before any
# tool is actually called.
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
    """Return the shared GoogleCalendarManager instance, building it on first call."""
    global _calendar_tool
    if _calendar_tool is None:
        _calendar_tool = GoogleCalendarManager(auth_manager=_get_auth_manager())
    return _calendar_tool


# WR-05 — list_all_events caps results PER CALENDAR (default 20). The
# duplicate lookup runs over a caller-chosen window that can span days, so the
# default risked truncating past the very event it is looking for.
_DUPLICATE_LOOKUP_MAX_RESULTS = 50


def _existing_event_at(
    start_iso: str,
    end_iso: str,
    summary: str,
    calendar_id: str | None = None,
) -> dict | None:
    """Return the first existing event overlapping [start_iso, end_iso) whose
    summary matches `summary` case-insensitively after collapsing internal
    whitespace, else None.

    D-23 (Phase 33) removed the directive gate on proactive calendar writes —
    Layer 2 can now create events far more often, without asking first. That
    raises the stakes on a check-then-act failure mode the review flagged
    (amendment B2): compose succeeds, the disclosure send fails, D-10's
    write-after-send discipline logs nothing to the send-gated outreach log,
    and the next occasion re-composes from the same inputs — producing a
    duplicate event on Amit's calendar. This lookup is the mitigation: call it
    immediately before every proactive `create_event`, narrowing the
    lookup-to-create window as much as possible (33-RESEARCH.md Pitfall 6 —
    this remains a check-then-act race without an atomic guard; `_record_action`
    is the after-the-fact detector for the residual race).

    Args:
        start_iso: Window start (RFC 3339 / ISO 8601).
        end_iso:   Window end.
        summary:   Title to match, case- and whitespace-insensitively.
        calendar_id: WR-05 — when given, the match is SCOPED to that calendar.
            The parameter was previously accepted and silently ignored, so a
            same-titled event on ANY writable calendar suppressed a create on
            the Training calendar (and vice-versa). When None the caller has
            not pinned a calendar — `create_event` then routes to primary or
            Training depending on `is_workout`, which this function cannot
            know, so the lookup deliberately stays broad (checking everywhere
            is the conservative choice when the destination is ambiguous).

    Never raises — a Calendar API hiccup on the lookup must not block a
    legitimate create (fail-open): any exception here is logged and `None` is
    returned so the caller proceeds exactly as if no duplicate were found.
    """
    try:
        target = " ".join(summary.split()).casefold()
        # WR-05 — max_results is PER CALENDAR and defaulted to 20; a busy
        # multi-day window could truncate before reaching the match, silently
        # weakening the check exactly when the calendar is fullest.
        events = _get_calendar_tool().list_all_events(
            start_iso, end_iso, max_results=_DUPLICATE_LOOKUP_MAX_RESULTS,
        )
        for event in events:
            if calendar_id is not None and event.get("calendar_id") != calendar_id:
                continue
            existing_summary = event.get("summary", "") or ""
            if " ".join(existing_summary.split()).casefold() == target:
                return event
        return None
    except Exception:
        logger.warning(
            "_existing_event_at(%r, %r, %r) failed; proceeding as if unmatched (fail-open)",
            start_iso, end_iso, summary, exc_info=True,
        )
        return None


def _record_action(action: str, detail: str, *, occasion: str = "chat") -> str:
    """Append one ActionLogStore entry recording a Layer-2 calendar/task write.

    D-25 (Phase 33): every calendar mutation Klaus makes must land in the
    action audit trail the moment it happens, independent of whether the
    occasion's disclosure message ever ships — the deliberate inverse of
    the send-gated outreach log's D-10 write-after-send discipline (that
    store is untouched by this function). The entry starts life undisclosed
    (`disclosed=False`) so the next occasion's compose step can surface it
    if this one's send fails.

    Args:
        action: One of "calendar_create" | "calendar_update" | "calendar_delete".
        detail: Human-readable description of what changed.
        occasion: Which occasion made the write. Defaults to "chat" — plan
            33-04's `_run_cascade` does not currently thread an occasion
            identifier through to this call site, and attributing an action
            to its occasion is a nice-to-have the disclosure flow does not
            depend on (the entry's `at` timestamp plus `disclosed=False` is
            sufficient for D-25's "the next occasion sees I already did this
            but never told him"). Deliberately not read from an env var —
            that would add a cross-module global this plan doesn't need.

    Returns:
        The generated entry id (uuid4 hex), always — even if the Firestore
        write itself failed. Never raises: a write that already happened on
        the calendar must not be rolled back because its audit write failed,
        but the failure must be loud (logged at ERROR).
    """
    import uuid
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Jerusalem")
    entry_id = uuid.uuid4().hex
    entry = {
        "id": entry_id,
        "action": action,
        "detail": detail,
        "occasion": occasion,
        "at": datetime.now(tz).isoformat(),
        "disclosed": False,
    }
    try:
        from memory.firestore_db import ActionLogStore
        today_iso = datetime.now(tz).date().isoformat()
        ActionLogStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        ).append(today_iso, entry)
    except Exception:
        logger.error(
            "_record_action(%r, %r) failed to write ActionLogStore entry %s",
            action, detail, entry_id, exc_info=True,
        )
    return entry_id


def _training_calendar_writeback(
    event_id: str,
    *,
    operation: str,
    date_iso: str | None = None,
    summary: str | None = None,
) -> None:
    """Best-effort calendar-to-training reality write-back (WB-01/02)."""
    if os.environ.get("KLAUS_TRAINING_WRITEBACK_ENABLED", "false").strip().lower() not in {
        "1", "true", "yes", "on",
    }:
        return
    try:
        from memory.firestore_db import TrainingLogStore

        store = TrainingLogStore(
            os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
            os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
        )
        existing = store.get_by_slot(event_id) if operation != "create" else None
        if operation == "create":
            if not date_iso:
                return
            store.log_session(
                date=date_iso,
                slot=event_id,
                session_type=summary,
                planned=True,
                completed=False,
                source="calendar",
                calendar_event_id=event_id,
                plan_status="planned",
            )
            return
        if not existing:
            return
        old_date = str(existing.get("date") or "")
        session_type = summary or existing.get("type")
        if operation == "delete":
            store.log_session(
                date=old_date,
                slot=event_id,
                session_type=session_type,
                planned=False,
                completed=bool(existing.get("completed")),
                source="calendar",
                calendar_event_id=event_id,
                plan_status="deleted",
            )
            return
        if operation == "update":
            target_date = date_iso or old_date
            if target_date != old_date:
                store.log_session(
                    date=old_date,
                    slot=event_id,
                    session_type=existing.get("type"),
                    planned=False,
                    completed=bool(existing.get("completed")),
                    source="calendar",
                    calendar_event_id=event_id,
                    plan_status="moved",
                )
            store.log_session(
                date=target_date,
                slot=event_id,
                session_type=session_type,
                planned=True,
                completed=False,
                source="calendar",
                calendar_event_id=event_id,
                plan_status="planned",
            )
    except Exception:
        logger.error(
            "Training calendar write-back failed for %s (%s)",
            event_id,
            operation,
            exc_info=True,
        )


@tool({
        "name": "list_calendar_events",
        "description": (
            "List all calendar events within a given date/time window. "
            "Use ISO 8601 format for both parameters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "time_min_iso": {
                    "type": "string",
                    "description": "Start of the window, ISO 8601 (e.g. 2025-05-04T00:00:00+03:00).",
                },
                "time_max_iso": {
                    "type": "string",
                    "description": "End of the window, ISO 8601.",
                },
            },
            "required": ["time_min_iso", "time_max_iso"],
        },
    })
def _handle_list_calendar_events(time_min_iso: str, time_max_iso: str) -> str:
    """List events across ALL of the user's writable calendars, merged.

    Events live in many calendars (primary, Training, Personal, ...), so reading
    only one would hide the rest from the brain. list_all_events enumerates every
    writable calendar and tags each event with its display name ("calendar") and
    real "calendar_id" — the latter must be passed back to edit/delete an event in
    its own calendar.
    """
    cal = _get_calendar_tool()
    events = cal.list_all_events(time_min_iso, time_max_iso)
    return json.dumps({"events": events, "count": len(events)})


@tool({
        "name": "create_calendar_event",
        "description": (
            "Create a new event on the user's Google Calendar. "
            "You must decide whether the event is a workout and pass is_workout explicitly "
            "(there is no automatic keyword detection). When is_workout=true the event is routed "
            "to the dedicated Training calendar, a 15-minute travel buffer is embedded on each side, "
            "and a 45-minute 'Get Ready' prep block is created immediately before it — pass "
            "travel_minutes_each_way to override the default 15 min. For non-workout events, pass "
            "travel_minutes_each_way whenever the user explicitly states travel time to embed it "
            "inside the event window."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start_iso": {"type": "string", "description": "Start datetime, ISO 8601."},
                "end_iso": {"type": "string", "description": "End datetime, ISO 8601."},
                "description": {
                    "type": "string",
                    "description": "Optional event description or notes.",
                },
                "travel_minutes_each_way": {
                    "type": "integer",
                    "description": (
                        "Optional minutes of travel time to embed on each side of the event. "
                        "If omitted, workout events default to 15; all others default to 0. "
                        "Pass this whenever the user states travel time explicitly (e.g. user says "
                        "'it takes me 30 min to get there' → pass 30). Pass 0 to suppress the "
                        "buffer even for workouts."
                    ),
                },
                "is_workout": {
                    "type": "boolean",
                    "description": (
                        "Set to true if the event is a physical workout/training session — this routes it "
                        "to the Training calendar and adds travel buffers + a pre-workout 'Get Ready' prep "
                        "block. Set false for standard meetings/events. Always pass this explicitly based "
                        "on your judgment; if omitted it defaults to false (non-workout)."
                    ),
                },
                "calendar_id": {
                    "type": "string",
                    "description": (
                        "Optional. Explicit target calendar ID (from list_calendar_events) to create the "
                        "event in. Overrides the default primary/Training routing — use it to add an event "
                        "to a specific calendar (e.g. Personal). Omit to use the default routing."
                    ),
                },
                "allow_duplicate": {
                    "type": "boolean",
                    "description": (
                        "Optional, default false. Creates normally refuse when an event with the "
                        "same title already overlaps that window, to stop you double-booking the "
                        "user proactively. Set this to true ONLY when the user explicitly asked "
                        "for the event and you already got the duplicate refusal — never on your "
                        "own initiative."
                    ),
                },
            },
            "required": ["summary", "start_iso", "end_iso"],
        },
    })
def _handle_create_calendar_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    travel_minutes_each_way: int | None = None,
    is_workout: bool | None = None,
    calendar_id: str | None = None,
    allow_duplicate: bool = False,
) -> str:
    """Delegate to GoogleCalendarManager.create_event and serialise the result.

    D-23 idempotency pre-check: looks for an existing event with the same
    summary already overlapping [start_iso, end_iso) before creating. When
    found, refuses to create a duplicate and returns a `duplicate` response
    the brain can surface on its disclosure line instead of silently
    double-booking. See `_existing_event_at` for why this exists.

    WR-05 — the pre-check guards PROACTIVE creates (its docstring says so), but
    it is wired into every create, including interactive ones. Amit asking "add
    a second Standup at 14:00 tomorrow" when a "Standup" already overlaps got a
    flat `{"created": false, "duplicate": true}` with no way through, and the
    brain had to explain a refusal he did not ask for. `allow_duplicate` is that
    way through: the refusal response now names it, so the brain can retry
    within the same turn when the user's intent is explicit. The default stays
    False, so proactive Layer-2 creates behave exactly as before.

    D-25: a successful create is recorded in the action audit trail
    (`_record_action`) before returning. The duplicate branch above records
    nothing — nothing was written.
    """
    if not allow_duplicate:
        existing = _existing_event_at(
            start_iso, end_iso, summary, calendar_id=calendar_id,
        )
        if existing is not None:
            return json.dumps({
                "created": False,
                "duplicate": True,
                "existing_event_id": existing.get("id", ""),
                "existing_summary": existing.get("summary", ""),
                "reason": "An event with this summary already exists in that window",
                "override": (
                    "If the user explicitly asked for this event anyway, call "
                    "create_calendar_event again with allow_duplicate=true."
                ),
            })

    result = _get_calendar_tool().create_event(
        summary=summary,
        start_iso=start_iso,
        end_iso=end_iso,
        description=description,
        travel_minutes_each_way=travel_minutes_each_way,
        is_workout=is_workout,
        calendar_id=calendar_id,
    )
    if "error" not in result:
        result["action_id"] = _record_action(
            action="calendar_create", detail=f"{summary}, {start_iso}",
        )
        if is_workout and result.get("event_id"):
            _training_calendar_writeback(
                str(result["event_id"]),
                operation="create",
                date_iso=datetime.fromisoformat(start_iso).date().isoformat(),
                summary=summary,
            )
    return json.dumps(result)


@tool({
        "name": "check_calendar_free",
        "description": "Check whether a specific time window is free of calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_iso": {"type": "string", "description": "Start of the slot, ISO 8601."},
                "end_iso": {"type": "string", "description": "End of the slot, ISO 8601."},
            },
            "required": ["start_iso", "end_iso"],
        },
    })
def _handle_check_calendar_free(start_iso: str, end_iso: str) -> str:
    """Delegate to GoogleCalendarManager.is_free and serialise the result."""
    result = _get_calendar_tool().is_free(start_iso, end_iso)
    return json.dumps(result)


@tool({
        "name": "delete_calendar_event",
        "description": (
            "Delete an event from any of the user's Google Calendars by event ID. "
            "First call list_calendar_events to obtain the event_id AND its calendar_id, "
            "then pass both here. "
            "Note: workout events created via create_calendar_event also have a "
            "paired 'Get Ready: <name>' prep block — delete both IDs to fully "
            "remove a workout."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The Calendar event ID returned by list_calendar_events.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": (
                        "The calendar_id of the event, as returned by list_calendar_events. "
                        "Required to delete events outside the primary calendar (e.g. Training). "
                        "If omitted, defaults to primary and falls back to searching your calendars."
                    ),
                },
            },
            "required": ["event_id"],
        },
    })
def _handle_delete_calendar_event(event_id: str, calendar_id: str | None = None) -> str:
    """Delegate to GoogleCalendarManager.delete_event and serialise the result.

    D-25: a successful delete is recorded in the action audit trail
    (`_record_action`) before returning.
    """
    result = _get_calendar_tool().delete_event(event_id, calendar_id=calendar_id)
    if result.get("ok"):
        _training_calendar_writeback(event_id, operation="delete")
        summary = result.get("summary", "")
        detail = f"{event_id}, {summary}" if summary else event_id
        result["action_id"] = _record_action(action="calendar_delete", detail=detail)
    return json.dumps(result)


@tool({
        "name": "update_calendar_event",
        "description": (
            "Edit an existing calendar event IN PLACE — change its title, time, or description. "
            "ALWAYS prefer this over deleting + recreating when the user asks to change an event; "
            "do NOT create a duplicate. First call list_calendar_events to obtain the event_id and "
            "its calendar_id, then pass only the fields you want to change. "
            "Note: if you move a workout's time, also move its paired 'Get Ready: <name>' block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The Calendar event ID returned by list_calendar_events.",
                },
                "calendar_id": {
                    "type": "string",
                    "description": (
                        "The calendar_id of the event, as returned by list_calendar_events. "
                        "Required to edit events outside the primary calendar (e.g. Training). "
                        "If omitted, defaults to primary and falls back to searching your calendars."
                    ),
                },
                "summary": {"type": "string", "description": "New event title (omit to leave unchanged)."},
                "start_iso": {
                    "type": "string",
                    "description": "New start datetime, ISO 8601 (omit to leave unchanged).",
                },
                "end_iso": {
                    "type": "string",
                    "description": "New end datetime, ISO 8601 (omit to leave unchanged).",
                },
                "description": {
                    "type": "string",
                    "description": "New description (omit to leave unchanged).",
                },
            },
            "required": ["event_id"],
        },
    })
def _handle_update_calendar_event(
    event_id: str,
    calendar_id: str | None = None,
    summary: str | None = None,
    start_iso: str | None = None,
    end_iso: str | None = None,
    description: str | None = None,
) -> str:
    """Delegate to GoogleCalendarManager.update_event and serialise the result.

    D-25: a successful update is recorded in the action audit trail
    (`_record_action`) before returning, naming which fields changed.
    """
    result = _get_calendar_tool().update_event(
        event_id,
        calendar_id=calendar_id,
        summary=summary,
        start_iso=start_iso,
        end_iso=end_iso,
        description=description,
    )
    if result.get("ok"):
        if start_iso is not None or summary is not None:
            _training_calendar_writeback(
                event_id,
                operation="update",
                date_iso=(
                    datetime.fromisoformat(start_iso).date().isoformat()
                    if start_iso is not None
                    else None
                ),
                summary=summary,
            )
        changed = [
            field for field, value in (
                ("summary", summary), ("start", start_iso),
                ("end", end_iso), ("description", description),
            ) if value is not None
        ]
        detail = f"{event_id}: {', '.join(changed)}" if changed else event_id
        result["action_id"] = _record_action(action="calendar_update", detail=detail)
    return json.dumps(result)
