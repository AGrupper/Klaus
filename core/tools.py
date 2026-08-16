"""Canonical deterministic tool registry used by Claude MCP endpoints."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread-local canonical user id so every memory handler is namespace-scoped.
_thread_local = threading.local()


def set_current_user_id(user_id: int) -> None:
    """Bind the canonical MCP user id for the current dispatch thread."""
    _thread_local.user_id = user_id


def _get_current_user_id() -> int:
    return getattr(_thread_local, "user_id", 0)


# ------------------------------------------------------------------ #
# Tool schemas consumed by the MCP server.                           #
# ------------------------------------------------------------------ #

TOOL_SCHEMAS: list[dict] = [
    {
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
    },
    {
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
    },
    {
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
    },
    {
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
    },
    {
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
    },
    # --- Task tools — backed by Amit's real Things 3 list (TASK_BACKEND=things) ---
    #
    # Things separates "when I'll do it" (due_date) from "when it's due"
    # (hard_deadline_at).  Keep them distinct: collapsing them loses real meaning,
    # and rescheduling must never silently move a deadline.
    {
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
    },
    {
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
    },
    {
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
    },
    {
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
    },
    {
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
    },
    {
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
    },
    # --- Native HabitStore tools (Phase 28 Plan 03 — HABIT-05) ---
    {
        "name": "get_habit_adherence",
        "description": (
            "Read today's pending habits and supplements with streak info. "
            "Returns list of items not yet checked off today with their current streak. "
            "Use to assess adherence or to prepare a coaching note."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slot": {
                    "type": "string",
                    "enum": ["Morning", "Noon", "Evening", "Bedtime"],
                    "description": "Filter by time slot. Omit for all slots.",
                },
                "type": {
                    "type": "string",
                    "enum": ["habit", "supplement"],
                    "description": "Filter by item type. Omit for both.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "remember",
        "description": (
            "Save a durable piece of information about the user to long-term memory. "
            "Available through Claude MCP. "
            "Use kind='fact' for short atomic statements (preferred). "
            "Use kind='chunk' for longer contextual passages where the narrative "
            "or emotional thread matters more than a single statement. "
            "Content cap: 2000 characters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to store. Max 2000 characters.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["fact", "chunk"],
                    "description": (
                        "'fact': short atomic statement e.g. 'Amit's gym is Mon/Wed/Fri'. "
                        "'chunk': longer contextual passage (a story, evolving situation). "
                        "Prefer 'fact' when in doubt."
                    ),
                },
            },
            "required": ["content", "kind"],
        },
    },
    {
        "name": "recall",
        "description": (
            "Search long-term memory for information relevant to a query. "
            "Available through Claude MCP. "
            "Returns top-k matches across facts and chunks, ranked by semantic "
            "similarity. Call proactively before asking the user clarifying questions "
            "about their preferences or history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query.",
                },
                "k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10).",
                },
                "kind": {
                    "type": "string",
                    "enum": ["fact", "chunk", "self"],
                    "description": (
                        "Optional. Restrict recall to one memory kind. "
                        "'self' searches Klaus's own journal entries. "
                        "Omit for the default fact+chunk search."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "forget_memory",
        "description": (
            "Deliberately and permanently delete one stored memory by its vector id — "
            "Amit's explicit 'forget that' trigger (MEM-03). "
            "This is a hard delete with no undo. Only call when "
            "Amit has clearly asked to forget or correct a specific stored fact — e.g. "
            "after a `recall` surfaced it and Amit disputes it, or the nightly review "
            "flagged a `memory_contradiction` and Amit confirmed the drop. Never call "
            "speculatively or without an explicit trigger."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vector_id": {
                    "type": "string",
                    "description": (
                        "The Pinecone vector id of the memory to delete — returned by a "
                        "prior `remember`/`recall` call, or surfaced as `vector_id` in a "
                        "nightly memory_contradiction flag."
                    ),
                },
            },
            "required": ["vector_id"],
        },
    },
    {
        "name": "fetch_weather",
        "description": (
            "Fetch current weather conditions and today/tomorrow forecast for a location. "
            "Defaults to Tel Aviv. Use when the user asks about weather, temperature, "
            "rain, or when composing a daily briefing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or coordinates (default: 'Tel Aviv').",
                },
            },
            "required": [],
        },
    },
    {
        "name": "fetch_garmin_today",
        "description": (
            "Fetch today's health summary from Garmin Connect: sleep score, sleep hours, "
            "HRV status, body battery, and resting heart rate. "
            "Use when the user asks about sleep, recovery, readiness, or health data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },

    {
        "name": "get_self_status",
        "description": (
            "Return Klaus's retained operational state: container uptime, current "
            "status timestamp, and the latest reflection journal summary. "
            "Available through Claude MCP. "
            "Use when asked about current status, uptime, or health. "
            "It deliberately excludes model usage, costs, and fallback telemetry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_push_health",
        "description": (
            "Return Web Push self-awareness data: how many devices are subscribed, "
            "each device's user agent / last successful delivery timestamp / failure "
            "count, and when push was first enabled. "
            "Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
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
    },
    {
        "name": "list_followups",
        "description": (
            "List your pending self-scheduled check-backs. Returns id, due_at, note, defer_count "
            "for each. Cancelled and done follow-ups are excluded. Available through Claude MCP."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
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
    },
    {
        "name": "set_standing_directive",
        "description": (
            "Capture one of Amit's lasting behavioral wishes verbatim as a durable standing "
            "directive — a persistent instruction that outlives this conversation (e.g. 'no "
            "training nudges until I'm back from France', 'always suggest 2 restaurant options'). "
            "Capture liberally whenever a remark plausibly reads as a lasting wish — do not ask a "
            "gating question first; your one-line ack is the correction surface. `expires_at` "
            "(ISO 8601 or natural language) and `condition_text` (event-based, e.g. 'while I'm in "
            "France') are both optional — a directive with neither persists indefinitely until "
            "cancelled. Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The wish, captured verbatim."},
                "expires_at": {
                    "type": "string",
                    "description": "Optional ISO 8601 or natural-language hard-date expiry.",
                },
                "condition_text": {
                    "type": "string",
                    "description": "Optional event-based expiry description (e.g. 'while I'm in France').",
                },
                "supersedes": {
                    "type": "string",
                    "description": (
                        "Optional id of an existing directive this refined directive replaces when "
                        "resolving a persona conflict (D-16) — the old directive is marked "
                        "superseded_by this new one. Get the id from a prior list_standing_directives "
                        "call."
                    ),
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_standing_directives",
        "description": (
            "List Amit's standing directives — active by default; pass include_history=true when "
            "he asks about cancelled/expired/superseded ones too. Returns id, text, origin, "
            "expires_at, condition_text, status for each; self-proposed directives (origin="
            "'klaus_self') are marked accordingly. Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "include_history": {
                    "type": "boolean",
                    "description": "True to include cancelled/expired/superseded directives. Defaults to active-only.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "cancel_standing_directive",
        "description": (
            "Cancel a standing directive by id. Idempotent — calling on an already-cancelled "
            "directive is safe. Resolve the id from a prior list_standing_directives call — Amit "
            "may refer to it by number or by natural-language description ('drop the France one'); "
            "no confirmation gate needed. Rejecting a directive Klaus proposed himself (origin "
            "'klaus_self') durably vetoes it (status='vetoed', never deleted) so reflection will "
            "not propose the same or near-same directive again — the veto is itself training "
            "signal (D-13). Amit cancelling his own directive still writes 'cancelled'. Returns "
            "{ok: bool}. Available through Claude MCP."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Directive id from list_standing_directives."},
            },
            "required": ["id"],
        },
    },
    # ============ PHASE 19 Plan 02 — TRAINING PROFILE + GARMIN LIVE ============
    {
        "name": "get_training_profile",
        "description": (
            "Read Amit's stored training profile (athletic_goals, training_constraints, "
            "recovery_preferences). call this when you need to know "
            "Amit's coaching context before answering or planning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # ============ PHASE 22 — COACHING GUIDE ON-DEMAND LOOKUP (COACH-01) ============
    {
        "name": "read_coaching_guide",
        "description": (
            "Read a deep section of the coaching knowledge guide. "
            "Call when Amit asks 'why?' about a training concept, or when the slim "
            "core digest (already in your system prompt) is not detailed enough. "
            "Returns the full section text for the requested topic. "
            "Do NOT call for routine coaching messages — the slim core covers those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "Section to retrieve. Use one of: 'interference-effect', "
                        "'block-periodization', 'threshold-runs', 'top-set-strength', "
                        "'calisthenics-progressions', 'intervals-vo2max', "
                        "'peri-workout-fueling', 'protein-timing', "
                        "'carb-periodization', 'supplements'. "
                        "Free-text also accepted — nearest section slug is matched."
                    ),
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "read_user_profile",
        "description": (
            "Read one section of Amit's durable profile verbatim from docs/USER.md. "
            "The whole profile is already included in every get_life_snapshot, so call "
            "this only when you need a section word-for-word — for example to quote a "
            "scheduling rule back while explaining a decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Section to retrieve. One of: 'identity', 'rhythms', "
                        "'footprints', 'working-style', 'scheduling-rules'. "
                        "Free-text also accepted — nearest section slug is matched."
                    ),
                },
            },
            "required": ["section"],
        },
    },
    {
        "name": "update_training_profile",
        "description": (
            "Merge new fields into Amit's stored training profile. "
            "Record the change and tell him you did; only ask first if the new value is "
            "genuinely ambiguous. Recognized top-level keys: "
            "athletic_goals (list), training_constraints (list), recovery_preferences (object), "
            "dated_goals (list), weekly_split (object), nutrition_targets (object), "
            "supplement_schedule (list), fueling_timeline (list), plan_start_date (string)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": (
                        "Dict of fields to merge into users/amit. Top-level keys: "
                        "athletic_goals, training_constraints, recovery_preferences, "
                        "dated_goals, weekly_split, nutrition_targets, "
                        "supplement_schedule, fueling_timeline, plan_start_date."
                    ),
                },
            },
            "required": ["patch"],
        },
    },
    {
        "name": "update_plan",
        "description": (
            "Update Amit's living training plan (goals, weekly split, nutrition targets, "
            "dates). Record the change and tell him; only ask first if the "
            "value is genuinely ambiguous. "
            "Same structured keys as update_training_profile: "
            "dated_goals (list), weekly_split (object), nutrition_targets (object), "
            "supplement_schedule (list), fueling_timeline (list), plan_start_date (string), "
            "athletic_goals (list), training_constraints (list), recovery_preferences (object)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": (
                        "Dict of fields to merge into users/amit. Top-level keys: "
                        "dated_goals, weekly_split, nutrition_targets, "
                        "supplement_schedule, fueling_timeline, plan_start_date, "
                        "athletic_goals, training_constraints, recovery_preferences."
                    ),
                },
            },
            "required": ["patch"],
        },
    },
    {
        "name": "fetch_training_status",
        "description": (
            "Fetch today's Garmin training status (PRODUCTIVE / MAINTAINING / RECOVERY / "
            "DETRAINING / OVERREACHING), VO2 max, and load focus. "
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "fetch_recent_activities",
        "description": (
            "Fetch Amit's last N days of Garmin activities as a normalized list "
            "(activity_id, date, type, duration_sec, distance_m, perceived_exertion, "
            "feel, training_load). Default days=7. "
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days of history to fetch, inclusive of today. Default 7.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_acwr",
        "description": (
            "Compute Amit's acute:chronic workload ratio (ACWR) from the Postgres "
            "`activities` table. Returns JSON {acute, chronic, ratio}: acute = mean "
            "7-day training_load, chronic = mean 28-day training_load, ratio = "
            "acute/chronic. ratio is null when fewer than 14 of the last 28 days "
            "have training_load data (\"chronic baseline insufficient\"). "
            "Single-call wrapper — do NOT fetch raw activities and compute manually. "
            ""
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    # ============ PHASE 19 Plan 03 — GOOGLE FIT NUTRITION ============
    {
        "name": "fetch_recent_meals",
        "description": (
            "Get the user's logged nutrition from the last N hours "
            "(Lifesum → Apple HealthKit → Klaus on iOS, or Google Fit on Android; "
            "both land in the same meal store). Returns an object with: `meals` "
            "(per-meal entries — calories, protein_g, carbs_g, fat_g, fiber_g, "
            "meal_type, optional food_item), `totals_by_day` (exact macro totals "
            "per calendar date, SERVER-COMPUTED in Python), and `window_totals` "
            "(exact macro totals across the whole window). For any nutrition "
            "total/status question, report the server-computed totals VERBATIM — "
            "never sum the meals yourself. CAUTION: HealthKit/Lifesum meal "
            "timestamps are canonical slot times (breakfast=08:00, lunch=12:00, "
            "dinner=20:00), NOT the actual eating time — never infer when the "
            "user actually ate from them. Meals also only sync when the user "
            "closes Lifesum, so a just-eaten meal may not be here yet. "
            "Default hours=24. "
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "Hours back to fetch. Default 24.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "fetch_nutrition_trend",
        "description": (
            "Get the user's nutrition TREND over the last N days: a per-day "
            "series of daily totals (calories, protein_g, carbs_g, fat_g, "
            "fiber_g, meal_count) plus SERVER-COMPUTED `averages` over the days "
            "that have logged meals (`days_with_data`). Use this for any "
            "weekly/multi-day question — average protein, calorie balance, "
            "consistency of a build phase; use fetch_recent_meals for what was "
            "eaten today/yesterday. Report the server-computed averages "
            "VERBATIM — never average the series yourself. `missing_dates` are "
            "days with NO logged meals — treat them as unlogged, never as "
            "zero-calorie days. When the profile has targets, `targets` and "
            "`avg_protein_g_per_kg` are included for comparison. "
            "Default days=14 (max 60). "
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days back to aggregate. Default 14, max 60.",
                },
            },
            "required": [],
        },
    },
    # ============ PHASE 20 Plan 01 — TRAINING LOG (LOG-03/LOG-04) ============
    {
        "name": "log_training",
        "description": (
            "Log a completed or skipped training session. "
            "Call when Amit reports a workout done, skipped, or RPE. "
            "Parameters: date (YYYY-MM-DD, required), session_type (gym/run/etc), "
            "completed (bool), rpe (1–10 optional), notes (optional), "
            "skipped_reason (rest_recovery | sick_injured | too_busy | other, optional)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Training date in YYYY-MM-DD format.",
                },
                "session_type": {
                    "type": "string",
                    "description": "Type of session (gym, run, bike, swim, etc.).",
                },
                "completed": {
                    "type": "boolean",
                    "description": "True if the session was completed; False if skipped.",
                },
                "skipped_reason": {
                    "type": "string",
                    "description": (
                        "Reason for skipping. One of: rest_recovery, sick_injured, "
                        "too_busy, other."
                    ),
                },
                "rpe": {
                    "type": "integer",
                    "description": "Perceived exertion on 1–10 scale (Rate of Perceived Exertion).",
                },
                "feel": {
                    "type": "integer",
                    "description": "Garmin feel value (verbatim, 0–4 scale).",
                },
                "notes": {
                    "type": "string",
                    "description": "Free-form session notes from Amit.",
                },
                "source": {
                    "type": "string",
                    "description": "Origin of the log entry: telegram | garmin | manual_chat.",
                },
                "garmin_activity_id": {
                    "type": "string",
                    "description": "Garmin activity ID if this log entry was auto-created from Garmin.",
                },
            },
            "required": ["date"],
        },
    },
    {
        "name": "get_training_history",
        "description": (
            "Return recent training log entries from Firestore. "
            "Use days param (default 7) for recent history."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days of history to return. Default 7.",
                },
            },
            "required": [],
        },
    },
    # ============ HEVY STRENGTH — full per-set progression + cross-domain context ============
    {
        "name": "get_strength_progress",
        "description": (
            "Read Amit's strength-training history synced from Hevy (full per-set "
            "detail: every exercise, set, rep, weight_kg, RPE — plus derived "
            "top_set, est_1rm, and volume_kg). "
            "Pass `exercise` (e.g. 'Bench Press') to get that lift's progression "
            "over time for trend/stall analysis, or omit it for all recent "
            "sessions. `days` defaults to 30. `detail` defaults to 'full'; pass "
            "'summary' to drop per-set arrays and keep only derived metrics. "
            "Reason over the data yourself — do not expect pre-computed verdicts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise": {
                    "type": "string",
                    "description": "Exercise name to get the progression for (case-insensitive). Omit for all sessions.",
                },
                "days": {
                    "type": "integer",
                    "description": "Days of history to return when no exercise is given. Default 30.",
                },
                "detail": {
                    "type": "string",
                    "description": "'full' (every set) or 'summary' (derived metrics only). Default 'full'.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_training_context",
        "description": (
            "Get Amit's FULL cross-domain training picture in one call — strength "
            "(Hevy per-set), session log, running/cardio + training load, ACWR, "
            "Garmin training status/VO2, nutrition totals per day, and recovery "
            "(HRV/RHR/sleep). Use this when Amit asks open-ended "
            "questions about how training is going or what to change, so you can "
            "correlate ACROSS domains and surface non-obvious, individualized "
            "insight rather than siloed per-metric readouts. `days` defaults to 14. "
            "Nothing is filtered — you decide what matters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Look-back window in days across all domains. Default 14.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_training_reality",
        "description": (
            "THE tool for any question about what training has or has not "
            "happened — 'what did I do this week', 'did I miss anything', "
            "'how has training gone', or before you assert that a session was "
            "missed. Returns a week back through tomorrow with every session "
            "already reconciled across the calendar, the training log, Hevy and "
            "Garmin, so you never have to infer it from raw sources. Each "
            "session carries one status: completed, planned, missed, "
            "unverified, moved, cancelled, skipped, or unplanned — plus the "
            "evidence refs behind it. One session may span several activity "
            "records — a warmup, the effort and a cooldown are grouped into "
            "one session, so report it as one. `unverified` means a source was "
            "unreadable, NOT that the session was skipped; check "
            "`evidence_complete` and say so rather than calling it missed. A "
            "slot with evidence against it is closed — never ask Amit to "
            "confirm it. Use get_training_context instead only for wider "
            "analysis (load, pace trends, nutrition correlation)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Days before today to reconcile. Default 7.",
                },
                "days_forward": {
                    "type": "integer",
                    "description": "Days after today to include. Default 1.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_run_detail",
        "description": (
            "Read Amit's per-run Garmin detail synced from Garmin Connect — the "
            "recorded laps/intervals exactly as the watch captured them (per-km "
            "for easy/tempo runs, per-rep for interval sessions), each with pace, "
            "HR, cadence, stride length and power; plus a whole-run min/avg/max "
            "summary of cadence, stride, vertical oscillation, ground contact, "
            "power and HR; plus derived split_shape (negative/positive/even), "
            "hr_drift, cadence_drift and pace_cv (interval consistency). "
            "Pass `activity_id` for one run, or omit for recent runs "
            "within `days` (default 14). `detail`='full' (every lap + summary) or "
            "'summary' (derived signals + per-run pace only). Reason over the data "
            "yourself — no pre-computed verdicts. Some runs (treadmill, no HRM "
            "strap) lack dynamics; respect `has_dynamics` and never invent cadence "
            "or stride for them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "string",
                    "description": "Garmin activity id for a single run. Omit for recent runs.",
                },
                "days": {
                    "type": "integer",
                    "description": "Look-back window in days when no activity_id is given. Default 14.",
                },
                "detail": {
                    "type": "string",
                    "description": "'full' (every lap + summary) or 'summary' (derived + per-run pace only). Default 'full'.",
                },
            },
            "required": [],
        },
    },
    # ============ PHASE 23 — BLOCK + BENCHMARK TRACKING (BLOCK-01/BLOCK-03) ============
    # All 6 are available through Claude MCP (registered below). update_plan is NOT re-added.
    {
        "name": "get_plan",
        "description": (
            "Read Amit's living training plan merged with the currently-active "
            "mesocycle block. Returns the stored profile/plan fields "
            "plus the active block (resolved automatically by today's date — no "
            "start_block needed) and the current 1-based week number. Call when Amit "
            "asks 'what's my plan?' or 'what block/week am I in?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_block_status",
        "description": (
            "Read the currently-active mesocycle block (resolved by today's date), "
            "its recorded benchmarks, and the raw per-facet delta versus the prior "
            "block. Call when Amit asks how the current block is going "
            "or how his benchmarks compare to last block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "log_benchmark",
        "description": (
            "Record one benchmark result for the current block. "
            "Record it and tell him; only confirm first if the value is genuinely ambiguous. Valid facets "
            "(closed set): bench_press_1rm, squat_1rm, push_ups, pull_ups, "
            "threshold_pace. For a bench/squat top-set (weight x reps), compute the "
            "1RM estimate first (Epley: weight x (1 + reps/30)) and pass it as value."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD date of the benchmark."},
                "facet": {
                    "type": "string",
                    "description": (
                        "One of: bench_press_1rm, squat_1rm, push_ups, pull_ups, "
                        "threshold_pace."
                    ),
                },
                "value": {"type": "number", "description": "Numeric result."},
                "unit": {"type": "string", "description": "'kg' | 'reps' | 'sec_per_km'."},
                "block_id": {
                    "type": "string",
                    "description": "FK to the training_blocks doc id (use get_block_status).",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional context (e.g. 'Epley estimate from 85kg x 5').",
                },
            },
            "required": ["date", "facet", "value", "unit", "block_id"],
        },
    },
    {
        "name": "get_benchmark_history",
        "description": (
            "Read the cross-block history for one benchmark facet, newest first. "
            "Call when Amit asks how a lift/run has trended over time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facet": {
                    "type": "string",
                    "description": (
                        "One of: bench_press_1rm, squat_1rm, push_ups, pull_ups, "
                        "threshold_pace."
                    ),
                },
                "n": {
                    "type": "integer",
                    "description": "Max number of entries to return (default 10).",
                },
            },
            "required": ["facet"],
        },
    },
    {
        "name": "get_goal_projection",
        "description": (
            "Compute a deterministic linear-trend projection for one benchmark facet "
            "toward its dated goal. Call when Amit asks 'am I on track "
            "for my October bench target?' or similar. Returns a ProjectionResult dict "
            "with projected_value, behind_by (positive = behind target for EVERY facet, "
            "including pace), on_track, confidence, and confidence_label computed "
            "server-side — numbers are never LLM-invented. Prefer behind_by over the raw "
            "gap, whose sign flips between higher-is-better and lower-is-better facets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facet": {
                    "type": "string",
                    "description": (
                        "One of: bench_press_1rm, squat_1rm, push_ups, pull_ups, "
                        "threshold_pace."
                    ),
                },
            },
            "required": ["facet"],
        },
    },
    {
        "name": "start_block",
        "description": (
            "Bookkeeping: mark a block active and set the current_block_id FK. "
            "NOTE: get_plan/get_block_status already resolve the active "
            "block by date automatically — only call this for explicit bookkeeping."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string", "description": "training_blocks doc id."},
            },
            "required": ["block_id"],
        },
    },
    {
        "name": "end_block",
        "description": (
            "Bookkeeping: mark a block complete and clear the current_block_id FK. "
            "The next block is surfaced automatically by date."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string", "description": "training_blocks doc id."},
            },
            "required": ["block_id"],
        },
    },
]

# ------------------------------------------------------------------ #
# Lazy singletons for real tool instances.                           #
# ------------------------------------------------------------------ #
# WHY lazy: importing core.tools must never trigger OAuth or network
# I/O (e.g. during tests or early import cycles). The singletons are
# built on the first actual tool call, not at module load time.

from core.auth_google import GoogleAuthManager, build_auth_manager_from_env  # noqa: E402 (post-constant import)
from mcp_tools.calendar_tool import GoogleCalendarManager  # noqa: E402
from mcp_tools.weather_tool import fetch_weather        # noqa: E402
from mcp_tools.garmin_tool import fetch_garmin_today    # noqa: E402
from memory.pinecone_db import MemoryStore              # noqa: E402
from mcp_tools.memory import MemoryTool                 # noqa: E402
import os                                               # noqa: E402

_auth_manager: GoogleAuthManager | None = None
_calendar_tool: GoogleCalendarManager | None = None
_memory_store: MemoryStore | None = None
_memory_tool: MemoryTool | None = None


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



def _get_memory_store() -> MemoryStore:
    """Return the shared MemoryStore instance, building it on first call."""
    global _memory_store
    if _memory_store is None:
        api_key = os.environ["PINECONE_API_KEY"]
        index_name = os.getenv("PINECONE_INDEX_NAME", "klaus-memory")
        _memory_store = MemoryStore(api_key=api_key, index_name=index_name)
    return _memory_store


def _get_memory_tool() -> MemoryTool:
    """Return the shared MemoryTool instance, building it on first call."""
    global _memory_tool
    if _memory_tool is None:
        _memory_tool = MemoryTool(memory_store=_get_memory_store())
    return _memory_tool





# ------------------------------------------------------------------ #
# Real handler functions — thin bridges to the tool classes.        #
# ------------------------------------------------------------------ #

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


def _handle_check_calendar_free(start_iso: str, end_iso: str) -> str:
    """Delegate to GoogleCalendarManager.is_free and serialise the result."""
    result = _get_calendar_tool().is_free(start_iso, end_iso)
    return json.dumps(result)


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


# --- Native TaskStore handlers (Phase 27 Plan 03 — replaces _handle_add_task) ---

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


def _handle_task_complete(task_id: str) -> str:
    """Mark a task complete. Generates next recurring instance if applicable."""
    store = _get_task_store()
    result = store.complete(task_id, completed_on_iso=_task_today_iso())
    return json.dumps(result)


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


def _handle_task_delete(task_id: str) -> str:
    """Permanently delete a task."""
    store = _get_task_store()
    store.delete(task_id)
    return json.dumps({"deleted": task_id})


def _handle_fetch_weather(location: str = "Tel Aviv") -> str:
    result = fetch_weather(location=location)
    return json.dumps(result)




def _handle_fetch_garmin_today() -> str:
    result = fetch_garmin_today()
    return json.dumps(result)


def _handle_remember(content: str, kind: str) -> str:
    """Delegate to MemoryTool.remember and serialise the result."""
    result = _get_memory_tool().remember(_get_current_user_id(), content, kind)
    return json.dumps(result)


def _handle_recall(query: str, k: int = 5, kind: str | None = None) -> str:
    """Delegate to MemoryTool.recall and serialise the result."""
    kinds = [kind] if kind else None   # None → recall() default ["fact","chunk"]
    result = _get_memory_tool().recall(_get_current_user_id(), query, k, kinds=kinds)
    return json.dumps(result)




def _handle_forget_memory(vector_id: str) -> str:
    """Delegate to MemoryTool.forget_memory and serialise the result."""
    result = _get_memory_tool().forget_memory(vector_id)
    return json.dumps(result)








def _handle_get_self_status() -> str:
    """Return retained operational state without model, cost, or fallback telemetry."""
    import os as _os
    from datetime import datetime, timezone

    result: dict = {}

    # --- Uptime via /proc/uptime (Linux / Cloud Run) ---
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.read().split()[0])
        hours, remainder = divmod(int(uptime_seconds), 3600)
        minutes = remainder // 60
        result["uptime"] = f"{hours}h {minutes}m"
        result["uptime_seconds"] = uptime_seconds
    except (OSError, ValueError):
        # macOS / local dev — /proc/uptime not available
        result["uptime"] = "unavailable (local dev or non-Linux)"

    # --- Timestamp ---
    result["status_at"] = datetime.now(timezone.utc).isoformat()

    # --- Journal (Phase 17) ---
    try:
        project_id = _os.environ.get("GCP_PROJECT_ID")
        if project_id:
            database = _os.environ.get("FIRESTORE_DATABASE", "(default)")
            from memory.firestore_db import JournalStore
            recent = JournalStore(project_id=project_id, database=database).get_recent(1)
            if recent:
                j = recent[0]
                result["journal"] = {
                    "date": j.get("date"),
                    "summary": j.get("summary"),
                    "mood": j.get("mood"),
                }
            else:
                result["journal"] = None
        else:
            result["journal"] = None
    except Exception as exc:
        result["journal"] = None
        result["journal_error"] = str(exc)

    return json.dumps(result)


# ------------------------------------------------------------------ #
# Phase 29 Plan 05 — push self-awareness tools (PUSH-03/D-13).       #
# ------------------------------------------------------------------ #

def _get_hub_settings_store():
    """Return a HubSettingsStore instance using env-driven project/database config."""
    from memory.firestore_db import HubSettingsStore
    return HubSettingsStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _get_push_subscription_store():
    """Return a PushSubscriptionStore instance using env-driven project/database config."""
    from memory.firestore_db import PushSubscriptionStore
    return PushSubscriptionStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _handle_get_push_health() -> str:
    """Report Web Push subscription health (D-13 self-awareness).

    T-29-09 mitigation: only user_agent/last_success_at/failure_count are
    surfaced per subscription — the p256dh/auth encryption keys and the VAPID
    private key are never included in the response.
    """
    from memory.firestore_db import _jsonsafe_doc

    sub_store = _get_push_subscription_store()
    settings_store = _get_hub_settings_store()

    subscriptions = sub_store.list_all()
    devices = [
        {
            "user_agent": sub.get("user_agent"),
            "last_success_at": sub.get("last_success_at"),
            "failure_count": sub.get("failure_count", 0),
        }
        for sub in subscriptions
    ]
    settings = _jsonsafe_doc(settings_store.get())

    return json.dumps({
        "subscription_count": len(devices),
        "devices": devices,
        "push_enabled_at": settings.get("push_enabled_at"),
    })


# ------------------------------------------------------------------ #
# Phase 18 — self-scheduled follow-ups (AUTO-05, D-12/D-15).         #
# ------------------------------------------------------------------ #

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
    from datetime import datetime, timezone as _tz

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


# ------------------------------------------------------------------ #
# Phase 31 — standing directives (DIR-01/DIR-04/DIR-05).             #
# ------------------------------------------------------------------ #

def _handle_set_standing_directive(
    text: str,
    expires_at: str | None = None,
    condition_text: str | None = None,
    supersedes: str | None = None,
) -> str:
    """Capture a standing directive verbatim (DIR-01). Origin defaults to
    'user_chat' — capture is user-initiated, unlike self-scheduled follow-ups
    which default to 'klaus_self'.

    `expires_at` is expected as ISO 8601 where possible (the brain should
    pass ISO), but a natural-language string is parsed defensively via the
    same dateutil try/except shape as `_handle_schedule_followup` — the
    field is stored as-received if it isn't parseable as either, since
    `condition_text` is the intended path for non-dated expiries anyway.

    `supersedes` (D-16 persona-conflict resolution): when set to an existing
    directive's id, the new directive is added first, then the old directive
    is flipped to `status="superseded"` + `superseded_by=<new id>` via
    `StandingDirectiveStore.supersede()` — a durable audit link, distinct
    from a plain cancel. Backward compatible: omitting `supersedes` never
    calls `supersede()` (unchanged capture behavior).

    Args:
        text: The wish, captured verbatim.
        expires_at: Optional ISO 8601 or natural-language hard-date expiry.
        condition_text: Optional event-based expiry description.
        supersedes: Optional id of an existing directive this one replaces.

    Returns:
        JSON string of the persisted directive doc, plus a `"superseded"`
        bool key when `supersedes` was provided.
    """
    from datetime import datetime, timezone as _tz

    normalized_expiry = expires_at
    if expires_at:
        try:
            due_dt = datetime.fromisoformat(expires_at)
        except (ValueError, TypeError):
            try:
                from dateutil import parser as _dt_parser
                due_dt = _dt_parser.parse(expires_at)
            except (ImportError, ValueError, TypeError, OverflowError):
                due_dt = None
        if due_dt is not None:
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=_tz.utc)
            normalized_expiry = due_dt.astimezone(_tz.utc).isoformat()

    from memory.firestore_db import StandingDirectiveStore
    store = StandingDirectiveStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    result = store.add(
        text=text,
        origin="user_chat",
        context_quote=text,
        expires_at=normalized_expiry,
        condition_text=condition_text,
    )
    if supersedes:
        result = dict(result)
        result["superseded"] = bool(store.supersede(old_id=supersedes, new_directive_id=result["id"]))
    return json.dumps(result)


def _handle_list_standing_directives(include_history: bool = False) -> str:
    """Return standing directives, stripped of internal fields (D-17/D-18:
    active by default, full history on ask).

    Args:
        include_history: True to include cancelled/expired/superseded
            directives via `list_all()`; False (default) returns only
            `list_active()`.

    Returns:
        JSON string list of {id, text, origin, expires_at, condition_text,
        status}. Self-proposed entries (origin='klaus_self') are preserved
        as-is so the brain can mark them accordingly when presenting.
    """
    from memory.firestore_db import StandingDirectiveStore
    store = StandingDirectiveStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    items = store.list_all() if include_history else store.list_active()
    stripped = [
        {
            "id": d.get("id", ""),
            "text": d.get("text", ""),
            "origin": d.get("origin", ""),
            "expires_at": d.get("expires_at"),
            "condition_text": d.get("condition_text"),
            "status": d.get("status", "active"),
        }
        for d in items
    ]
    return json.dumps(stripped)


def _handle_cancel_standing_directive(id: str) -> str:
    """Cancel a standing directive by id. Idempotent (D-17 — the brain
    resolves a number or natural-language description to an id from a
    prior list_standing_directives call; no command syntax required here).

    Origin-aware routing (DIR-07/D-13, verification gap 2): a directive
    Klaus proposed himself (``origin == "klaus_self"``) is durably VETOED
    (status='vetoed', never hard-deleted) rather than merely cancelled —
    rejecting a self-proposal is training signal that feeds
    `core/reflection.py`'s vetoed_texts guard so the same or near-same
    directive is never re-proposed. A directive Amit stated himself
    (``origin == "user_chat"``) still cancels normally — cancelling one's
    own wish is not an anti-lesson.

    Returns ``{"ok": True}`` whenever the doc exists (even if already
    cancelled/vetoed). Returns ``{"ok": False}`` when the id does not exist.
    """
    from memory.firestore_db import StandingDirectiveStore
    store = StandingDirectiveStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    directive = store.get(id)
    if directive is None:
        return json.dumps({"ok": False})
    if directive.get("origin") == "klaus_self":
        ok = store.veto(id)
    else:
        ok = store.cancel(id)
    return json.dumps({"ok": bool(ok)})


def render_standing_directives_block(directives: list[dict], *, style: str = "prose") -> str:
    """One shared formatter for the standing-directives context block.

    ``style="prose"`` — chat/compose system-prompt injection: a bulleted,
    human-readable block headed "**Active standing directives:**".
    ``style="json"``  — the triage snapshot: compact, machine-parseable JSON.

    Callers own their own (cached) store read; this function only formats.
    This is the ONE formatter consumed by all 5 injection sites (chat,
    tick triage, Layer-2 compose, follow-up compose, interim legacy-cron
    gathers) — mirrors ``_format_now_block`` in core/autonomous.py ("one
    helper, N call sites, no drift").

    Args:
        directives: List of directive dicts (as returned by
            ``StandingDirectiveStore.list_active()``/``list_all()``).
        style: "prose" (default) or "json".

    Returns:
        "" for an empty list in prose style (empty-state-omits-block
        discipline, matching self_state/journal_digest/training_profile);
        "[]" for an empty list in json style.
    """
    if not directives:
        return "" if style == "prose" else "[]"

    if style == "json":
        return json.dumps([
            {
                "text": d.get("text", ""),
                "origin": d.get("origin", ""),
                "expires_at": d.get("expires_at"),
                "condition_text": d.get("condition_text"),
            }
            for d in directives
        ], ensure_ascii=False)

    lines = ["**Active standing directives:**"]
    for d in directives:
        line = f"- {d.get('text', '')}"
        if d.get("expires_at"):
            line += f" (until {d['expires_at']})"
        elif d.get("condition_text"):
            line += f" (until: {d['condition_text']})"
        if d.get("origin") == "klaus_self":
            line += " [self-proposed]"
        lines.append(line)
    return "\n".join(lines)


# ------------------------------------------------------------------ #
# Phase 19 Plan 02 — training profile + Garmin live handlers         #
# ------------------------------------------------------------------ #

def _handle_get_training_profile() -> str:
    """PROFILE-04 return the user training profile dict as JSON.

    Uses _jsonsafe_doc to ISO-convert any DatetimeWithNanoseconds values
    (e.g. updated_at, bootstrapped_at) before json.dumps so this handler
    never raises a TypeError on a real Firestore doc.  T-21-04 mitigation.
    """
    from memory.firestore_db import UserProfileStore, _jsonsafe_doc
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    return json.dumps(_jsonsafe_doc(store.load()))


def _handle_read_coaching_guide(topic: str) -> str:
    """COACH-01 return the coaching guide section for the requested topic.

    Reads docs/COACHING_GUIDE.md, finds the <!-- SECTION: {slug} --> anchor,
    and returns the section text as JSON. Fuzzy fallback on partial word match.

    T-22-04 mitigation: topic is normalized to a slug and used ONLY inside a regex
    against authored <!-- SECTION: slug --> anchors in a hardcoded file path. It is
    NEVER concatenated into a filesystem path. '..' / '/' / absolute paths fail to
    match a slug and return error JSON — they cannot escape to the filesystem.
    """
    from core import doc_sections

    content = doc_sections.read_document("COACHING_GUIDE.md")
    if content is None:
        return json.dumps({"error": "COACHING_GUIDE.md not found"})

    section = doc_sections.find_section(content, topic)
    if section is None:
        return json.dumps({"error": f"Section '{topic}' not found in COACHING_GUIDE.md"})

    return json.dumps({"topic": doc_sections.slugify(topic), "content": section})


def _handle_read_user_profile(section: str) -> str:
    """Return one section of Amit's profile from docs/USER.md.

    The whole profile already ships in every get_life_snapshot, so this is for
    the narrower case where Claude wants one section verbatim — for example to
    quote a scheduling rule back while explaining a decision.

    Args:
        section: Section slug, e.g. "footprints". Matched against authored
            anchors only, never used as a path (see doc_sections).

    Returns:
        str: JSON with "section" and "content", or "error" when not found.
    """
    from core import user_profile

    body = user_profile.section(section)
    if body is None:
        available = ", ".join(user_profile.load_sections()) or "none"
        return json.dumps(
            {"error": f"Section '{section}' not found in USER.md. Available: {available}"}
        )

    from core import doc_sections

    return json.dumps({"section": doc_sections.slugify(section), "content": body})


def _handle_update_training_profile(patch: dict) -> str:
    """PROFILE-04 merge a patch into users/amit profile."""
    from memory.firestore_db import UserProfileStore
    store = UserProfileStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    try:
        store.update(patch)
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _handle_fetch_training_status() -> str:
    """GARMIN-04 live Garmin training status / VO2 / load focus."""
    from mcp_tools.garmin_tool import (
        fetch_garmin_training_status,
        GarminUnavailableError,
        GarminAuthError,
    )
    try:
        return json.dumps(fetch_garmin_training_status())
    except (GarminUnavailableError, GarminAuthError) as exc:
        return json.dumps({"error": str(exc)})


def _handle_fetch_recent_activities(days: int = 7) -> str:
    """GARMIN-04 live Garmin activities for the last N days."""
    from mcp_tools.garmin_tool import (
        fetch_garmin_activities,
        GarminUnavailableError,
        GarminAuthError,
    )
    try:
        return json.dumps(fetch_garmin_activities(days=days))
    except (GarminUnavailableError, GarminAuthError) as exc:
        return json.dumps({"error": str(exc)})


def _handle_get_acwr() -> str:
    """Phase 19 SC-1 closeout: single-call ACWR wrapper around compute_acwr_from_db.

    Reads last 28 days from Postgres `activities`, returns
    {"acute", "chronic", "ratio"}. ratio is null when chronic baseline is
    insufficient (<14 of 28 days with training_load). compute_acwr_from_db
    swallows all exceptions and returns the sentinel — this handler never raises.
    """
    from mcp_tools.garmin_tool import compute_acwr_from_db
    return json.dumps(compute_acwr_from_db())


def _handle_fetch_recent_meals(hours: int = 24) -> str:
    """Brain-direct: recent meals + SERVER-COMPUTED macro totals from MealStore.

    Reads ``MealStore.get_day()`` for the Asia/Jerusalem calendar date(s) the
    requested window touches, then filters per-meal entries to the last ``hours``.
    Lifesum on iPhone writes to Apple HealthKit, surfaced into MealStore by
    ``/cron/healthkit-sync``; MealStore is the shared, source-agnostic store the
    morning briefing already reads, so meals from either source are visible here.

    Returns a JSON object (NOT a bare list) with three keys:

    - ``meals``: per-meal entries within the last ``hours`` (each includes
      ``fiber_g`` alongside the core macros — Phase 19.2), ascending by time.
    - ``totals_by_day``: exact macro totals per calendar date the window
      touches, computed in **Python** by ``MealStore.get_day_aggregate`` (the
      same source of truth the morning briefing and ``get_training_context``
      use, so chat and briefing can never disagree). These are FULL-calendar-day
      totals — the authoritative "how much did I eat on date X" number.
    - ``window_totals``: those per-day totals summed across the window, in Python.

    The brain MUST report these totals verbatim and never sum the ``meals`` list
    itself — LLM column-summing was the source of the wrong/drifting numbers this
    tool was rebuilt to fix. On error returns ``{"error": ...}`` so the brain
    gets a structured tool-result rather than a raised exception.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Jerusalem")
    now = datetime.now(tz)
    cutoff = now - timedelta(hours=hours)
    try:
        from memory.firestore_db import MealStore
        ms = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
            database=os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
        )
        # Enumerate EVERY calendar date the window touches (a >48h window has
        # dates strictly between cutoff-day and today — the old two-endpoint
        # union silently skipped them). MealStore.get_day never raises.
        span = (now.date() - cutoff.date()).days
        dates = [
            (cutoff.date() + timedelta(days=i)).isoformat() for i in range(span + 1)
        ]
        meals: list[dict] = []
        for d in dates:
            meals.extend(ms.get_day(d))
        out: list[dict] = []
        for m in meals:
            try:
                ts = datetime.fromisoformat(m["timestamp"])
                if ts >= cutoff:
                    out.append(m)
            except (KeyError, ValueError, TypeError):
                # Malformed timestamp on one entry → skip it, keep the rest.
                continue

        # Server-computed totals — reuse get_day_aggregate (Python arithmetic),
        # never leave macro-summing to the LLM. totals_by_day is keyed only by
        # dates that actually have logged meals (get_day_aggregate returns {}
        # for an empty day — Pitfall 4 contract).
        totals_by_day: dict[str, dict] = {}
        for d in dates:
            agg = ms.get_day_aggregate(d)
            if agg:
                totals_by_day[d] = agg["totals"]
        macro_keys = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
        window_totals = {
            k: sum(day.get(k, 0) or 0 for day in totals_by_day.values())
            for k in macro_keys
        }

        return json.dumps({
            "meals": out,
            "totals_by_day": totals_by_day,
            "window_totals": window_totals,
            # WHY: Lifesum stamps HealthKit samples with canonical meal-slot
            # times, not the moment the user ate (verified 2026-06-12: every
            # synced meal sits exactly on 08:00/10:00/12:00/20:00). Without
            # this note the brain reasons about digestion windows from times
            # the user never ate at.
            "timestamp_note": (
                "HealthKit (Lifesum) meal timestamps are canonical SLOT times "
                "(breakfast=08:00, lunch=12:00, dinner=20:00) — NOT the actual "
                "eating time. Do not infer when the user actually ate from "
                "them; if timing matters, ask."
            ),
        })
    except Exception as exc:  # noqa: BLE001 — structured tool-result, never raise
        return json.dumps({"error": str(exc)})


_NUTRITION_MACRO_KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")


def _compute_nutrition_averages(day_records: list[dict], macro_keys=_NUTRITION_MACRO_KEYS) -> dict:
    """Average each macro key across day_records that HAVE data.

    Shared by _handle_fetch_nutrition_trend (chat tool) and
    interfaces.web_server's GET /api/health/nutrition route (Phase 30 HLTH-02) so
    the two paths compute identical numbers — extracted specifically so the
    "server computes, client renders" invariant cannot drift into two slightly
    different reimplementations (RESEARCH.md Anti-Patterns / the 2026-06-09
    drifting-numbers lesson).

    Days with no logged meals are simply absent from `day_records` (the
    caller's missing_dates contract) — never averaged in as zero.
    """
    averages: dict = {"days_with_data": len(day_records)}
    if day_records:
        for k in macro_keys:
            vals = [d.get(k) or 0 for d in day_records]
            averages[k] = round(sum(vals) / len(vals), 1)
    return averages


def _nutrition_targets_and_protein_ratio(profile: dict, averages: dict) -> dict:
    """Silent-omit `targets` + `avg_protein_g_per_kg` (mirrors D-15).

    Shared by _handle_fetch_nutrition_trend and the /api/health/nutrition route
    — see _compute_nutrition_averages docstring for why this is extracted.
    Returns {} when the profile carries no nutrition_targets / bodyweight_kg.
    """
    out: dict = {}
    targets = profile.get("nutrition_targets")
    if targets:
        out["targets"] = targets
    bodyweight = profile.get("bodyweight_kg")
    if bodyweight and averages.get("protein_g"):
        out["avg_protein_g_per_kg"] = round(averages["protein_g"] / float(bodyweight), 2)
    return out


def _handle_fetch_nutrition_trend(days: int = 14) -> str:
    """Brain-direct: per-day nutrition series + server-computed averages.

    The trend companion to _handle_fetch_recent_meals: answers "how has he
    been eating this week/fortnight" (average protein, calorie balance,
    logging consistency) with all arithmetic done here in Python. Averages
    divide by days WITH data; unlogged days are reported as missing_dates,
    never counted as zero-calorie days.
    """
    from zoneinfo import ZoneInfo
    try:
        days = max(1, min(int(days), 60))  # clamp — each day is a Firestore read
    except (TypeError, ValueError):
        days = 14
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    try:
        from memory.firestore_db import MealStore
        ms = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
            database=os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
        )
        macro_keys = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
        series: list[dict] = []
        missing_dates: list[str] = []
        for i in range(days - 1, -1, -1):  # oldest → newest
            d = (today - timedelta(days=i)).isoformat()
            agg = ms.get_day_aggregate(d)
            if agg:
                totals = agg.get("totals", {})
                series.append({
                    "date": d,
                    "meal_count": agg.get("meal_count"),
                    **{k: totals.get(k) for k in macro_keys},
                })
            else:
                missing_dates.append(d)

        averages = _compute_nutrition_averages(series, macro_keys)

        out: dict = {
            "window_days": days,
            "series": series,
            "missing_dates": missing_dates,
            "averages": averages,
        }

        # Targets comparison — silent-omit when the profile carries none.
        try:
            from memory.firestore_db import UserProfileStore
            profile = UserProfileStore(
                project_id=os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
                database=os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
            ).load()
            out.update(_nutrition_targets_and_protein_ratio(profile, averages))
        except Exception:
            logger.warning("fetch_nutrition_trend: profile read failed", exc_info=True)

        return json.dumps(out)
    except Exception as exc:  # noqa: BLE001 — structured tool-result, never raise
        return json.dumps({"error": str(exc)})


# ------------------------------------------------------------------ #
# Phase 20 Plan 01 — training log handlers (LOG-03/LOG-04)          #
# ------------------------------------------------------------------ #

def _handle_log_training(**kwargs) -> str:
    """LOG-03 write one training session to TrainingLogStore."""
    from memory.firestore_db import TrainingLogStore
    store = TrainingLogStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    # Derive slot from explicit slot kwarg, else a unique timestamped manual slot.
    # A literal "manual" slot collides on {date}_manual, so a second same-day
    # free-form chat log would overwrite the first via merge=True (data loss).
    if "slot" not in kwargs or not kwargs.get("slot"):
        kwargs["slot"] = datetime.now(timezone.utc).strftime("manual_%H%M%S")
    try:
        store.log_session(**kwargs)
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _handle_get_training_history(days: int = 7) -> str:
    """LOG-04 return recent training log entries as JSON."""
    from memory.firestore_db import TrainingLogStore
    store = TrainingLogStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    # default=str guards against any non-JSON-serialisable Firestore value
    # (e.g. a server timestamp) slipping through the store's normalisation.
    return json.dumps(store.get_recent(days), default=str)


# ------------------------------------------------------------------ #
# Hevy strength — full per-set progression + cross-domain context    #
# ------------------------------------------------------------------ #

def _handle_get_strength_progress(
    exercise: str | None = None, days: int = 30, detail: str = "full",
) -> str:
    """Brain-direct: read Hevy strength history from StrengthSessionStore.

    With `exercise` → that lift's per-session progression (top_set/est_1rm/volume).
    Without it → recent full sessions (every set unless detail='summary').
    Returns a structured tool-result; never raises (errors become {"error": ...}).
    """
    from memory.firestore_db import StrengthSessionStore
    try:
        store = StrengthSessionStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        if exercise:
            return json.dumps(
                {"exercise": exercise, "history": store.get_exercise_history(exercise)},
                default=str,
            )
        sessions = store.get_recent(days)
        if detail != "full":
            sessions = [
                {
                    "date": s.get("date"),
                    "title": s.get("title"),
                    "duration_min": s.get("duration_min"),
                    "total_volume_kg": s.get("total_volume_kg"),
                    "exercises": [
                        {
                            "name": e.get("name"),
                            "top_set": e.get("top_set"),
                            "est_1rm": e.get("est_1rm"),
                            "volume_kg": e.get("volume_kg"),
                            "set_count": e.get("set_count"),
                        }
                        for e in s.get("exercises") or []
                    ],
                }
                for s in sessions
            ]
        return json.dumps({"window_days": days, "sessions": sessions}, default=str)
    except Exception as exc:  # noqa: BLE001 — structured tool-result, never raise
        return json.dumps({"error": str(exc)})


def _handle_get_training_reality(
    days_back: int = 3, days_forward: int = 1,
) -> str:
    """WB-04 return the reconciled planned-vs-actual training window.

    The reconciliation itself lives in ``core.training_reality`` so it stays
    testable without any live store. This handler only adapts it to the tool
    boundary.
    """
    from core.training_reality import build_training_reality

    return json.dumps(build_training_reality(days_back, days_forward))


def _handle_get_training_context(days: int = 14) -> str:
    """Brain-direct: assemble the FULL cross-domain training picture in one call.

    Reuses existing reads (strength, training log, Garmin activities/status, ACWR,
    nutrition, biometrics). Every block is best-effort fail-open: one outage sets
    that key to None rather than aborting the whole snapshot, so the brain always
    gets as much of the picture as is available. Nothing is down-sampled.
    """
    from zoneinfo import ZoneInfo

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    tz = ZoneInfo("Asia/Jerusalem")
    today = datetime.now(tz).date()
    ctx: dict = {"window_days": days}

    try:
        from memory.firestore_db import StrengthSessionStore
        ctx["strength_sessions"] = StrengthSessionStore(project_id, database).get_recent(days)
    except Exception:
        logger.warning("get_training_context: strength fetch failed", exc_info=True)
        ctx["strength_sessions"] = None

    try:
        from memory.firestore_db import TrainingLogStore
        ctx["training_log"] = TrainingLogStore(project_id, database).get_recent(days)
    except Exception:
        logger.warning("get_training_context: training_log fetch failed", exc_info=True)
        ctx["training_log"] = None

    try:
        from mcp_tools.garmin_tool import fetch_garmin_activities
        ctx["garmin_activities"] = fetch_garmin_activities(days)
    except Exception:
        logger.warning("get_training_context: garmin activities failed", exc_info=True)
        ctx["garmin_activities"] = None

    try:
        from memory.firestore_db import RunDetailStore
        ctx["run_details"] = RunDetailStore(project_id, database).get_recent(days)
    except Exception:
        logger.warning("get_training_context: run detail fetch failed", exc_info=True)
        ctx["run_details"] = None

    try:
        from mcp_tools.garmin_tool import fetch_garmin_training_status
        ctx["training_status"] = fetch_garmin_training_status()
    except Exception:
        logger.warning("get_training_context: training status failed", exc_info=True)
        ctx["training_status"] = None

    try:
        from mcp_tools.garmin_tool import compute_acwr_from_db
        ctx["acwr"] = compute_acwr_from_db()
    except Exception:
        logger.warning("get_training_context: acwr failed", exc_info=True)
        ctx["acwr"] = None

    try:
        from memory.firestore_db import MealStore
        ms = MealStore(project_id, database)
        nutrition: dict = {}
        for i in range(days):
            d = (today - timedelta(days=i)).isoformat()
            agg = ms.get_day_aggregate(d)
            if agg:
                nutrition[d] = agg.get("totals", {})
        ctx["nutrition_by_day"] = nutrition
    except Exception:
        logger.warning("get_training_context: nutrition failed", exc_info=True)
        ctx["nutrition_by_day"] = None

    try:
        from mcp_tools.database_tool import query_health_database
        start = (today - timedelta(days=days)).isoformat()
        sql = (
            "SELECT date, resting_hr, hrv_baseline, hrv_overnight, "
            "sleep_duration, sleep_score FROM daily_biometrics "
            f"WHERE date >= '{start}' ORDER BY date DESC"
        )
        rows = query_health_database(sql)
        ctx["biometrics"] = rows if isinstance(rows, list) else None
    except Exception:
        logger.warning("get_training_context: biometrics failed", exc_info=True)
        ctx["biometrics"] = None

    return json.dumps(ctx, default=str)


def _handle_get_run_detail(
    activity_id: str | None = None, days: int = 14, detail: str = "full",
) -> str:
    """Brain-direct: read per-run Garmin detail from RunDetailStore.

    With `activity_id` → that single run's full detail. Without it → recent runs
    within `days` (every lap unless detail='summary', which keeps only the
    derived signals + per-run pace). Never raises (errors become {"error": ...}).
    """
    from memory.firestore_db import RunDetailStore
    try:
        store = RunDetailStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        if activity_id:
            return json.dumps({"run": store.get_run(str(activity_id))}, default=str)
        runs = store.get_recent(days)
        if detail != "full":
            runs = [
                {
                    "date": r.get("date"),
                    "type": r.get("type"),
                    "distance_m": r.get("distance_m"),
                    "avg_pace_sec_per_km": r.get("avg_pace_sec_per_km"),
                    "derived": r.get("derived"),
                    "has_dynamics": r.get("has_dynamics"),
                }
                for r in runs
            ]
        return json.dumps({"window_days": days, "runs": runs}, default=str)
    except Exception as exc:  # noqa: BLE001 — structured tool-result, never raise
        return json.dumps({"error": str(exc)})


# ------------------------------------------------------------------ #
# Phase 23 — block + benchmark tracking handlers (BLOCK-01/BLOCK-03) #
# ------------------------------------------------------------------ #

# Default cycle start used for week-number framing when the profile has no
# plan_start_date set yet (anchor: first mesocycle block, 2026-06-21).
_PLAN_START_DEFAULT = "2026-06-21"


def epley_1rm(weight: float, reps: int) -> float:
    """Epley 1RM estimate: weight * (1 + reps/30), rounded to 1 decimal.

    Exposed for handler/brain use when deriving a 1RM from a bench/squat top-set.
    The brain normally passes the computed value to log_benchmark directly.
    """
    return round(weight * (1 + reps / 30), 1)


def _block_stores():
    """Construct (BlockStore, BenchmarkStore, UserProfileStore) from env."""
    from memory.firestore_db import BlockStore, BenchmarkStore, UserProfileStore
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    return (
        BlockStore(project_id=project_id, database=database),
        BenchmarkStore(project_id=project_id, database=database),
        UserProfileStore(project_id=project_id, database=database),
    )


def _handle_get_plan() -> str:
    """BLOCK-01 profile/plan merged with the date-resolved active block.

    The block is resolved by date range (get_current) — never depends on a manual
    start_block call (D-01). week_num is computed against the profile plan_start_date
    (default 2026-06-21).
    """
    from memory.firestore_db import get_week_num, _jsonsafe_doc
    from datetime import date as _date
    blocks, _benchmarks, profiles = _block_stores()
    profile = _jsonsafe_doc(profiles.load())
    block = blocks.get_current()
    today = _date.today().isoformat()
    plan_start = profile.get("plan_start_date") or _PLAN_START_DEFAULT
    week_num = get_week_num(plan_start, today)
    return json.dumps({
        "profile": profile,
        "current_block": block,
        "week_num": week_num,
        "plan_start_date": plan_start,
    })


def _handle_get_block_status() -> str:
    """BLOCK-01/BLOCK-03 active block + its benchmarks + raw cross-block deltas.

    facet_deltas is raw (current_value - prior_block_value) per facet — NO trend
    projection (Phase 25 scope). The prior value is the most recent benchmark for
    that facet belonging to a DIFFERENT block than the current one.
    """
    blocks, benchmarks, _profiles = _block_stores()
    block = blocks.get_current()
    if not block:
        return json.dumps({"current_block": None, "benchmarks": [], "facet_deltas": {}})
    block_id = block.get("doc_id") or block.get("block_id")
    current = benchmarks.get_block_benchmarks(block_id)
    facet_deltas: dict[str, float] = {}
    for entry in current:
        facet = entry.get("facet")
        if not facet or facet in facet_deltas:
            continue
        history = benchmarks.get_facet_history(facet, n=20)
        prior = next((h for h in history if h.get("block_id") != block_id), None)
        if (
            prior is not None
            and isinstance(entry.get("value"), (int, float))
            and isinstance(prior.get("value"), (int, float))
        ):
            facet_deltas[facet] = round(entry["value"] - prior["value"], 2)
    return json.dumps({
        "current_block": block,
        "benchmarks": current,
        "facet_deltas": facet_deltas,
    })


def _handle_log_benchmark(
    date: str, facet: str, value: float, unit: str, block_id: str, notes: str = ""
) -> str:
    """BLOCK-03 record a benchmark. Store raises ValueError on bad facet."""
    _blocks, benchmarks, _profiles = _block_stores()
    try:
        benchmarks.log_benchmark(
            date=date, facet=facet, value=value, unit=unit, block_id=block_id, notes=notes
        )
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _handle_get_benchmark_history(facet: str, n: int = 10) -> str:
    """BLOCK-03 cross-block history for one facet, newest first."""
    _blocks, benchmarks, _profiles = _block_stores()
    return json.dumps({"facet": facet, "history": benchmarks.get_facet_history(facet, n=n)})


def _handle_get_goal_projection(facet: str) -> str:
    """PROG-02 project one facet toward its dated goal.

    Validates facet against _BENCHMARK_FACETS (V5 / T-25-05 pattern, mirrors
    _handle_log_benchmark). Returns a JSON ProjectionResult dict. Never raises —
    errors surface as a no_data confidence result (T-25-07).

    Source selection per D-04:
      - threshold_pace: prefers dense Garmin Postgres history (fetch_dense_pace_history),
        falls back to sparse BenchmarkStore only when the Postgres list is empty.
      - strength facets (bench_press_1rm, squat_1rm, push_ups, pull_ups): BenchmarkStore.

    today_iso computed via ZoneInfo("Asia/Jerusalem") — never date.today() (CR-01, T-25-14).
    """
    from memory.firestore_db import _BENCHMARK_FACETS, _jsonsafe_doc
    if facet not in _BENCHMARK_FACETS:
        return json.dumps(
            {"error": f"Unknown facet: {facet!r}. Valid: {sorted(_BENCHMARK_FACETS)}"}
        )

    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core.projection import project_goal_progress

    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    _blocks, benchmarks, profiles = _block_stores()
    profile = _jsonsafe_doc(profiles.load())
    dated_goals = profile.get("dated_goals") or []

    # D-04: threshold_pace uses dense Garmin Postgres points; strength facets use BenchmarkStore.
    if facet == "threshold_pace":
        from core.pace_history import fetch_dense_pace_history
        history = fetch_dense_pace_history(today_iso)
        if not history:
            # Fallback to sparse BenchmarkStore when no Garmin running data exists
            history = benchmarks.get_facet_history(facet, n=10)
    else:
        history = benchmarks.get_facet_history(facet, n=10)

    result = project_goal_progress(facet, history, dated_goals, today_iso)
    return json.dumps(result)


def _handle_start_block(block_id: str) -> str:
    """BLOCK-01 available through Claude MCP bookkeeping: mark block active + set current_block_id FK."""
    blocks, _benchmarks, profiles = _block_stores()
    try:
        blocks.start_block(block_id)
        profiles.update({"current_block_id": block_id})
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _handle_end_block(block_id: str) -> str:
    """BLOCK-01 available through Claude MCP bookkeeping: mark block complete + clear current_block_id FK."""
    blocks, _benchmarks, profiles = _block_stores()
    try:
        blocks.end_block(block_id)
        profiles.update({"current_block_id": None})
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# --- Native HabitStore handlers (Phase 28 Plan 03 — HABIT-05) ---

def _get_habit_store():
    """Return a HabitStore instance using env-driven project/database config."""
    from memory.firestore_db import HabitStore
    return HabitStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _habit_today_iso() -> str:
    """Return today's date in Asia/Jerusalem as YYYY-MM-DD."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()


def _handle_get_habit_adherence(
    slot: str | None = None,
    type: str | None = None,
) -> str:
    """Return pending habits/supplements for today with streaks (HABIT-05).

    Queries HabitStore.get_pending_today for today's Asia/Jerusalem date.
    Optional filters: slot (Morning/Noon/Evening/Bedtime) and type (habit/supplement).
    Returns a JSON list of pending items with streak info (D-16).
    """
    store = _get_habit_store()
    today_iso = _habit_today_iso()
    pending = store.get_pending_today(today_iso)
    if slot:
        pending = [h for h in pending if h.get("slot") == slot]
    if type:
        pending = [h for h in pending if h.get("type") == type]
    return json.dumps(pending)


# ------------------------------------------------------------------ #
# Dispatch table — maps tool names to handler callables.             #
# ------------------------------------------------------------------ #

_HANDLERS: dict[str, object] = {
    "fetch_weather":          lambda args: _handle_fetch_weather(**args),
    "fetch_garmin_today":     lambda args: _handle_fetch_garmin_today(**args),
    "list_calendar_events":   lambda args: _handle_list_calendar_events(**args),
    "create_calendar_event":  lambda args: _handle_create_calendar_event(**args),
    "check_calendar_free":    lambda args: _handle_check_calendar_free(**args),
    "delete_calendar_event":  lambda args: _handle_delete_calendar_event(**args),
    "update_calendar_event":  lambda args: _handle_update_calendar_event(**args),
    # Phase 27 Plan 03 — native TaskStore tools (replaces add_task)
    "task_create":           lambda args: _handle_task_create(**args),
    "task_list":             lambda args: _handle_task_list(**args),
    "task_complete":         lambda args: _handle_task_complete(**args),
    "task_reschedule":       lambda args: _handle_task_reschedule(**args),
    "task_edit":             lambda args: _handle_task_edit(**args),
    "task_delete":           lambda args: _handle_task_delete(**args),
    "remember":              lambda args: _handle_remember(**args),
    "recall":                lambda args: _handle_recall(**args),
    "forget_memory":         lambda args: _handle_forget_memory(**args),
    "get_self_status":         lambda args: _handle_get_self_status(),
    "schedule_followup":       lambda args: _handle_schedule_followup(**args),
    "list_followups":          lambda args: _handle_list_followups(),
    "cancel_followup":         lambda args: _handle_cancel_followup(**args),
    # Phase 19 Plan 02 — training profile + Garmin live
    "get_training_profile":    lambda args: _handle_get_training_profile(),
    "update_training_profile": lambda args: _handle_update_training_profile(**args),
    # Phase 21 Plan 02 — update_plan alias (PLAN-03 / SC-3): same handler as above
    "update_plan":             lambda args: _handle_update_training_profile(**args),
    # Phase 22 — coaching guide on-demand lookup (COACH-01)
    "read_coaching_guide":     lambda args: _handle_read_coaching_guide(**args),
    # docs/USER.md — the single source of ambient facts about Amit.
    "read_user_profile":       lambda args: _handle_read_user_profile(**args),
    "fetch_training_status":   lambda args: _handle_fetch_training_status(),
    "fetch_recent_activities": lambda args: _handle_fetch_recent_activities(**args),
    "get_acwr":                lambda args: _handle_get_acwr(),
    # Phase 19 Plan 03 — Google Fit nutrition (available through Claude MCP)
    "fetch_recent_meals":      lambda args: _handle_fetch_recent_meals(**args),
    "fetch_nutrition_trend":   lambda args: _handle_fetch_nutrition_trend(**args),
    # Phase 20 Plan 01 — training log tools (LOG-03/LOG-04)
    "log_training":            lambda args: _handle_log_training(**args),
    "get_training_history":    lambda args: _handle_get_training_history(**args),
    # Hevy strength — full per-set progression + cross-domain context (available through Claude MCP)
    "get_strength_progress":   lambda args: _handle_get_strength_progress(**args),
    "get_training_context":    lambda args: _handle_get_training_context(**args),
    "get_training_reality":    lambda args: _handle_get_training_reality(**args),
    "get_run_detail":          lambda args: _handle_get_run_detail(**args),
    # Phase 23 — block + benchmark tracking (BLOCK-01/BLOCK-03), available through Claude MCP
    "get_plan":                lambda args: _handle_get_plan(),
    "get_block_status":        lambda args: _handle_get_block_status(),
    "log_benchmark":           lambda args: _handle_log_benchmark(**args),
    "get_benchmark_history":   lambda args: _handle_get_benchmark_history(**args),
    "start_block":             lambda args: _handle_start_block(**args),
    "end_block":               lambda args: _handle_end_block(**args),
    # Phase 25 — progress projection (PROG-02), available through Claude MCP
    "get_goal_projection":     lambda args: _handle_get_goal_projection(**args),
    # Phase 28 Plan 03 — native HabitStore tools (HABIT-05)
    "get_habit_adherence":     lambda args: _handle_get_habit_adherence(**args),
    # Web Push self-awareness.
    "get_push_health":         lambda args: _handle_get_push_health(),
    # Phase 31 — standing directives (DIR-01/DIR-04)
    "set_standing_directive":       lambda args: _handle_set_standing_directive(**args),
    "list_standing_directives":     lambda args: _handle_list_standing_directives(**args),
    "cancel_standing_directive":    lambda args: _handle_cancel_standing_directive(**args),
    # Phase 33 Plan 09 — self-accountability (OCC-07/D-26), available through Claude MCP only
}


def get_all_schemas() -> list[dict]:
    """Return all deterministic tool schemas used by the MCP catalog."""
    return TOOL_SCHEMAS




def dispatch(tool_name: str, args: dict) -> str:
    """Execute a tool by name and return a JSON string result.

    Args:
        tool_name: Registered deterministic tool name.
        args: Arguments matching the tool's input_schema.

    Returns:
        JSON string result from the handler.

    Raises:
        KeyError: If tool_name is not registered.
    """
    if tool_name not in _HANDLERS:
        raise KeyError(
            f"Unknown tool: '{tool_name}'. "
            f"Available: {sorted(_HANDLERS)}"
        )

    logger.info("Tool dispatch: %s args=%s", tool_name, args)
    try:
        result = _HANDLERS[tool_name](args)
        logger.debug("Tool result (%s): %.200s", tool_name, result)
        return result
    except TypeError as exc:
        # WHY: the LLM occasionally passes wrong argument names. Return a clear
        # error so the model can self-correct on the next iteration.
        error_msg = f"Tool '{tool_name}' received unexpected arguments: {exc}"
        logger.warning(error_msg)
        return json.dumps({"error": error_msg})
    except Exception as exc:
        # WHY: catch ValueErrors (like invalid date formats) and network errors
        # so they don't crash the orchestrator. Feed the error back to the LLM
        # so it can self-correct.
        error_msg = f"Tool '{tool_name}' encountered an error: {type(exc).__name__}: {exc}"
        logger.exception(error_msg)
        return json.dumps({"error": error_msg})
