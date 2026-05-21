"""Tool registry — schemas, real handlers, and dispatch.

Defines the full set of tools available to the agent in Anthropic's tool_use
JSON format.  Phase 3 replaced the Gmail/Calendar mock handlers with real
Google API calls.  Phase 4 added the add_task tool (originally Firestore/Things 3
queue; now replaced by TickTick Open API).  Phase 6 adds remember and recall tools
for long-term Pinecone-backed memory.

Switching tool backends requires only editing this file — the orchestrator,
LLM client, and callers do not need to change.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import timezone, timedelta

from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Thread-local storage for the current user_id, set by AgentOrchestrator
# before each handle_message call so memory handlers can scope queries correctly.
_thread_local = threading.local()


def set_current_user_id(user_id: int) -> None:
    """Called by AgentOrchestrator at the start of each handle_message."""
    _thread_local.user_id = user_id


def _get_current_user_id() -> int:
    return getattr(_thread_local, "user_id", 0)


# Tools that Claude calls directly (not via delegate_to_worker).
# The orchestrator uses this set to suppress spurious "unexpected direct call" warnings.
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    "remember",
    "recall",
    "run_morning_briefing",
    "search_chat_history",
    "list_own_files",
    "read_own_source",
    "search_own_source",
    "get_self_status",
})

# ------------------------------------------------------------------ #
# Tool schemas in Anthropic tool_use format.                         #
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
            "For workout events (run, bike, basketball, gym, five fingers), a 15-minute travel buffer "
            "is automatically embedded on each side of the event and a 45-minute 'Get Ready' prep "
            "block is created immediately before it — pass travel_minutes_each_way to override the "
            "default 15 min. For any other event type, pass travel_minutes_each_way whenever the "
            "user explicitly states travel time to embed it inside the event window."
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
                        "Optional boolean. Set to true if the event represents a physical workout or run "
                        "that requires travel buffers and pre-workout prep blocks. Pass false to suppress "
                        "them for standard meetings/events. If omitted, uses the automatic keyword heuristic."
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
            "Delete an event from the user's Google Calendar by event ID. "
            "First call list_calendar_events to obtain the event_id. "
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
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "list_unread_emails",
        "description": "List recent unread emails from the inbox with sender, subject, and snippet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of emails to return. Defaults to 10.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_email",
        "description": "Fetch the full body and headers of a specific email by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "The unique email message ID.",
                },
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "add_task",
        "description": (
            "Add a to-do item to TickTick. Tasks appear immediately on all of Amit's "
            "TickTick devices (phone, web, etc.). Use 'reminder' (YYYY-MM-DDTHH:MM) "
            "for a time-specific push notification; use 'deadline' (YYYY-MM-DD) for a "
            "silent hard due date. If both are supplied, reminder takes precedence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title."},
                "notes": {"type": "string", "description": "Optional notes or details."},
                "deadline": {
                    "type": "string",
                    "description": (
                        "Optional hard deadline (YYYY-MM-DD). Shows as a due date in "
                        "TickTick. Date-only — no push notification fires."
                    ),
                },
                "reminder": {
                    "type": "string",
                    "description": (
                        "Optional scheduled time (YYYY-MM-DDTHH:MM, local time). "
                        "TickTick will fire a push notification at this exact time. "
                        "Use for 'remind me at HH:MM' requests."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of tag strings.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "remember",
        "description": (
            "Save a durable piece of information about the user to long-term memory. "
            "Call this directly — do NOT delegate to the worker. "
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
            "Call this directly — do NOT delegate to the worker. "
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
        "name": "search_chat_history",
        "description": (
            "Search ingested Claude Code chat history for relevant sessions. "
            "Call this directly — do NOT delegate to the worker. "
            "Returns semantically similar chat chunks from past Claude Code sessions. "
            "Use when the user asks what they worked on, asks about a past decision, "
            "or wants to find a specific past conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query (e.g. 'OAuth flow implementation').",
                },
                "k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5, max 10).",
                },
                "project": {
                    "type": "string",
                    "description": "Optional project path to narrow results (e.g. '/Users/amit/Desktop/Klaus').",
                },
            },
            "required": ["query"],
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
        "name": "fetch_readwise_today",
        "description": (
            "Fetch today's reading highlights from Readwise. "
            "Returns the most recent highlights updated today. "
            "Use when the user asks about their reading, highlights, or daily brief."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of highlights to return (default 5).",
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
        "name": "five_fingers_add_teammate",
        "description": (
            "Add a teammate to the Five Fingers sub-team roster. "
            "Phone accepts Israeli formats (05X…, +972…). "
            "Returns the Firestore doc ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name (Hebrew or English)."},
                "phone": {
                    "type": "string",
                    "description": "Phone number in any Israeli format (05X…, +972…).",
                },
                "nickname": {
                    "type": "string",
                    "description": "Optional nickname used in outbound messages.",
                },
                "notes": {"type": "string", "description": "Optional free-text notes."},
            },
            "required": ["name", "phone"],
        },
    },
    {
        "name": "five_fingers_remove_teammate",
        "description": (
            "Remove (soft-delete) a teammate from the roster by their Firestore doc ID. "
            "Use five_fingers_list_teammates to find the ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "roster_id": {
                    "type": "string",
                    "description": "Firestore document ID of the teammate to remove.",
                },
            },
            "required": ["roster_id"],
        },
    },
    {
        "name": "five_fingers_list_teammates",
        "description": (
            "List all active Five Fingers sub-team members with their doc IDs and phone numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "five_fingers_bulk_import",
        "description": (
            "Bulk-import teammates from a free-text list. "
            "Format: one per line or comma-separated, 'Name Phone'. "
            "Phone accepts Israeli formats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Free-text list of teammates. One per line or comma-separated. "
                        "Each entry: 'Name Phone' where phone is in any Israeli format."
                    ),
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "five_fingers_log_attendance",
        "description": (
            "Log practice attendance. Pass 'came' and 'missed' as lists of teammate "
            "names or roster doc IDs. Date is YYYY-MM-DD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Practice date in YYYY-MM-DD format.",
                },
                "came": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Teammate names or roster doc IDs who attended.",
                },
                "missed": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Teammate names or roster doc IDs who were absent.",
                },
                "notes": {"type": "string", "description": "Optional notes about the practice."},
            },
            "required": ["date"],
        },
    },
    {
        "name": "run_morning_briefing",
        "description": (
            "Compose and send the morning briefing to Telegram immediately. "
            "Fetches weather, calendar, email, Garmin health, and TickTick tasks "
            "for today, then sends a single briefing message. "
            "Use when the user asks for the morning briefing, daily briefing, "
            "or any variant of 'morning briefing' / 'give me my briefing'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "notion_search",
        "description": (
            "Search across all Notion pages and databases shared with Klaus. "
            "Returns matching pages/databases with their IDs, titles, and URLs. "
            "Use filter_type='page' to search only pages, 'database' to search only databases."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."},
                "filter_type": {
                    "type": "string",
                    "enum": ["page", "database"],
                    "description": "Optional. Narrow results to 'page' or 'database'.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "notion_get_page",
        "description": (
            "Fetch the full content of a Notion page by its ID. "
            "Returns the page title, readable text, flattened properties, "
            "and a list of child pages/databases for PARA tree traversal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "Notion page ID (32-char UUID, from notion_search results).",
                },
            },
            "required": ["page_id"],
        },
    },
    {
        "name": "notion_query_database",
        "description": (
            "Query a Notion database. Returns the schema (property names and types) "
            "and all matching rows. Call this before notion_create_page to understand "
            "property names. Supports Notion filter objects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "database_id": {"type": "string", "description": "Notion database ID."},
                "filter": {
                    "type": "object",
                    "description": "Optional Notion filter object (e.g. {\"property\": \"Date\", \"date\": {\"equals\": \"2026-05-15\"}}).",
                },
                "sorts": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Optional Notion sort objects.",
                },
                "page_size": {
                    "type": "integer",
                    "description": "Results per page, default 100.",
                },
            },
            "required": ["database_id"],
        },
    },
    {
        "name": "notion_create_page",
        "description": (
            "Create a new page in Notion — either as a database entry or a sub-page. "
            "For database parents, call notion_query_database first to get the schema, "
            "then pass properties in Notion API format. "
            "content is plain text or light markdown (# headings, - bullets, [ ] todos)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "parent_id": {
                    "type": "string",
                    "description": "ID of the parent database or page.",
                },
                "parent_type": {
                    "type": "string",
                    "enum": ["database", "page"],
                    "description": "'database' for a database entry, 'page' for a sub-page.",
                },
                "title": {"type": "string", "description": "Page title."},
                "content": {
                    "type": "string",
                    "description": "Optional body text in plain text or light markdown.",
                },
                "properties": {
                    "type": "object",
                    "description": "Optional Notion properties dict in API format (overrides default title property).",
                },
            },
            "required": ["parent_id", "parent_type", "title"],
        },
    },
    {
        "name": "notion_append_blocks",
        "description": (
            "Append text content to the end of an existing Notion page. "
            "Use for adding to journal entries, logging notes, or extending any page. "
            "Supports plain text or light markdown (# headings, - bullets, [ ] todos)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "Notion page ID to append to.",
                },
                "content": {
                    "type": "string",
                    "description": "Text to append (plain text or light markdown).",
                },
            },
            "required": ["page_id", "content"],
        },
    },
    {
        "name": "list_own_files",
        "description": (
            "List Klaus's deployed source files. "
            "Call this directly — do NOT delegate to the worker. "
            "Returns a sorted list of relative file paths from the project root. "
            "Use when asked about project structure, what files exist, or to discover "
            "what modules are available. Pass subdir to narrow to a specific directory "
            "(e.g. 'mcp_tools', 'core', 'memory')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subdir": {
                    "type": "string",
                    "description": "Optional relative subdirectory path (e.g. 'mcp_tools'). "
                                   "When omitted, all project files are listed.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_own_source",
        "description": (
            "Read the contents of one of Klaus's own source files by relative path. "
            "Call this directly — do NOT delegate to the worker. "
            "Use when asked how something works, to answer questions about implementation, "
            "or to inspect a specific file. "
            "Paths are relative to the project root (e.g. 'core/tools.py'). "
            "Secrets and credentials are blocked and will return an error."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from the project root (e.g. 'core/tools.py').",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_own_source",
        "description": (
            "Full-text search across Klaus's source files. "
            "Call this directly — do NOT delegate to the worker. "
            "Returns line-level matches: file path, line number, and the matching line. "
            "Use when asked where a specific class, function, variable, or string appears "
            "in the codebase. Case-insensitive substring match."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Substring to search for (case-insensitive).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 20).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_self_status",
        "description": (
            "Return Klaus's current operational status: container uptime, today's "
            "conversation message count (proxied via LLM call count), today's and "
            "month's LLM cost in USD, and latest heartbeat status. "
            "Call this directly — do NOT delegate to the worker. "
            "Use when asked about current status, costs, uptime, or health. "
            "Journal field will be blank until Phase 17 (reflection) is deployed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "delegate_to_worker",
        "description": (
            "Delegate a task to your worker agent (Gemini Flash) for tool execution "
            "or data gathering. The worker has access to all other tools listed above. "
            "Use this for any operation requiring calendar, email, or task tools. "
            "Do NOT use for remember or recall — call those directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "Clear, detailed instruction for the worker. Include all "
                        "necessary context (dates, names, parameters)."
                    ),
                },
                "respond_directly": {
                    "type": "boolean",
                    "description": (
                        "If true, the worker's response is sent directly to the user "
                        "without your review. Use ONLY for simple CRUD with no "
                        "scheduling judgment needed."
                    ),
                },
            },
            "required": ["task"],
        },
    },
]

# Schemas passed to the worker agent — excludes meta tool and memory tools
# (memory tools require Claude's judgment; the worker must not call them).
WORKER_TOOL_SCHEMAS: list[dict] = [
    s for s in TOOL_SCHEMAS
    if s["name"] not in {
        "delegate_to_worker",
        "remember",
        "recall",
        "search_chat_history",
        "list_own_files",
        "read_own_source",
        "search_own_source",
        "get_self_status",
    }
]


# ------------------------------------------------------------------ #
# Lazy singletons for real tool instances.                           #
# ------------------------------------------------------------------ #
# WHY lazy: importing core.tools must never trigger OAuth or network
# I/O (e.g. during tests or early import cycles). The singletons are
# built on the first actual tool call, not at module load time.

from core.auth_google import GoogleAuthManager, build_auth_manager_from_env  # noqa: E402 (post-constant import)
from mcp_tools.gmail_tool import GmailTool              # noqa: E402
from mcp_tools.calendar_tool import GoogleCalendarManager  # noqa: E402
from mcp_tools.weather_tool import fetch_weather        # noqa: E402
from mcp_tools.readwise_tool import fetch_readwise_today  # noqa: E402
from mcp_tools.garmin_tool import fetch_garmin_today    # noqa: E402
from memory.firestore_db import RosterStore, AttendanceStore  # noqa: E402
from mcp_tools.ticktick_tool import add_task as _ticktick_add_task  # noqa: E402
from mcp_tools.self_inspect import (                                 # noqa: E402
    list_own_files as _list_own_files,
    read_own_source as _read_own_source,
    search_own_source as _search_own_source,
)
from memory.pinecone_db import MemoryStore              # noqa: E402
from mcp_tools.memory import MemoryTool                 # noqa: E402
from mcp_tools.five_fingers.composer import normalize_phone  # noqa: E402
from mcp_tools.notion_tool import (                     # noqa: E402
    search as _notion_search,
    get_page as _notion_get_page,
    query_database as _notion_query_database,
    create_page as _notion_create_page,
    append_blocks as _notion_append_blocks,
)
import os                                               # noqa: E402

_auth_manager: GoogleAuthManager | None = None
_gmail_tool: GmailTool | None = None
_calendar_tool: GoogleCalendarManager | None = None
_memory_store: MemoryStore | None = None
_memory_tool: MemoryTool | None = None
_roster_store: RosterStore | None = None
_attendance_store: AttendanceStore | None = None


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


def _get_gmail_tool() -> GmailTool:
    """Return the shared GmailTool instance, building it on first call."""
    global _gmail_tool
    if _gmail_tool is None:
        _gmail_tool = GmailTool(auth_manager=_get_auth_manager())
    return _gmail_tool


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


def _get_roster_store() -> RosterStore:
    """Return the shared RosterStore instance, building it on first call."""
    global _roster_store
    if _roster_store is None:
        project_id = os.getenv("GCP_PROJECT_ID")
        if not project_id:
            raise RuntimeError("GCP_PROJECT_ID env var is required for five_fingers tools")
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        _roster_store = RosterStore(project_id=project_id, database=database)
    return _roster_store


def _get_attendance_store() -> AttendanceStore:
    """Return the shared AttendanceStore instance, building it on first call."""
    global _attendance_store
    if _attendance_store is None:
        project_id = os.getenv("GCP_PROJECT_ID")
        if not project_id:
            raise RuntimeError("GCP_PROJECT_ID env var is required for five_fingers tools")
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        _attendance_store = AttendanceStore(project_id=project_id, database=database)
    return _attendance_store


# ------------------------------------------------------------------ #
# Real handler functions — thin bridges to the tool classes.        #
# ------------------------------------------------------------------ #

def _handle_list_calendar_events(time_min_iso: str, time_max_iso: str) -> str:
    """Delegate to GoogleCalendarManager.list_events and serialise the result."""
    events = _get_calendar_tool().list_events(time_min_iso, time_max_iso)
    return json.dumps({"events": events, "count": len(events)})


def _handle_create_calendar_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    travel_minutes_each_way: int | None = None,
    is_workout: bool | None = None,
) -> str:
    """Delegate to GoogleCalendarManager.create_event and serialise the result."""
    result = _get_calendar_tool().create_event(
        summary=summary,
        start_iso=start_iso,
        end_iso=end_iso,
        description=description,
        travel_minutes_each_way=travel_minutes_each_way,
        is_workout=is_workout,
    )
    return json.dumps(result)


def _handle_check_calendar_free(start_iso: str, end_iso: str) -> str:
    """Delegate to GoogleCalendarManager.is_free and serialise the result."""
    result = _get_calendar_tool().is_free(start_iso, end_iso)
    return json.dumps(result)


def _handle_delete_calendar_event(event_id: str) -> str:
    """Delegate to GoogleCalendarManager.delete_event and serialise the result."""
    result = _get_calendar_tool().delete_event(event_id)
    return json.dumps(result)


def _handle_list_unread_emails(max_results: int = 10) -> str:
    """Delegate to GmailTool.list_unread and serialise the result."""
    emails = _get_gmail_tool().list_unread(max_results=max_results)
    return json.dumps({"emails": emails, "count": len(emails)})


def _handle_get_email(message_id: str) -> str:
    """Delegate to GmailTool.get_message and serialise the result."""
    result = _get_gmail_tool().get_message(message_id)
    return json.dumps(result)


def _handle_add_task(title: str, notes: str = "", deadline: str | None = None,
                     reminder: str | None = None,
                     tags: list[str] | None = None) -> str:
    """Delegate to ticktick_tool.add_task and serialise the result."""
    result = _ticktick_add_task(
        title=title, notes=notes or None, deadline=deadline, reminder=reminder, tags=tags,
    )
    return json.dumps(result)


def _handle_fetch_weather(location: str = "Tel Aviv") -> str:
    result = fetch_weather(location=location)
    return json.dumps(result)


def _handle_fetch_readwise_today(limit: int = 5) -> str:
    result = fetch_readwise_today(limit=limit)
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


def _handle_search_chat_history(query: str, k: int = 5, project: str | None = None) -> str:
    """Delegate to MemoryTool.search_chat_history and serialise the result."""
    result = _get_memory_tool().search_chat_history(_get_current_user_id(), query, k, project)
    return json.dumps(result)


def _handle_five_fingers_add_teammate(
    name: str,
    phone: str,
    nickname: str | None = None,
    notes: str | None = None,
) -> str:
    """Normalise phone and add a teammate to the roster."""
    try:
        phone_e164 = normalize_phone(phone)
    except ValueError as exc:
        return json.dumps({"error": f"Invalid phone number: {exc}"})
    doc_id = _get_roster_store().add(name, phone_e164, nickname, notes)
    return json.dumps({
        "doc_id": doc_id,
        "name": name,
        "confirmation": f"Added {name} to the Five Fingers roster.",
    })


def _handle_five_fingers_remove_teammate(roster_id: str) -> str:
    """Soft-delete a roster entry by Firestore doc ID."""
    from google.api_core.exceptions import GoogleAPICallError
    try:
        _get_roster_store().deactivate(roster_id)
    except GoogleAPICallError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"removed": True, "roster_id": roster_id})


def _handle_five_fingers_list_teammates() -> str:
    """Return all active roster entries."""
    teammates = _get_roster_store().list_active()
    return json.dumps({"teammates": teammates, "count": len(teammates)})


def _handle_five_fingers_bulk_import(text: str) -> str:
    """Parse a free-text list of Name Phone pairs and add each to the roster."""
    errors: list[str] = []
    imported = 0

    # Split on newlines first, then on commas, to support both delimiters.
    raw_tokens: list[str] = []
    for line in text.splitlines():
        raw_tokens.extend(line.split(","))

    for token in raw_tokens:
        token = token.strip()
        if not token:
            continue
        parts = token.split()
        if len(parts) < 2:
            errors.append(f"Cannot parse (need name + phone): {token!r}")
            continue
        phone_raw = parts[-1]
        name = " ".join(parts[:-1])
        try:
            phone_e164 = normalize_phone(phone_raw)
        except ValueError as exc:
            errors.append(f"Bad phone for {name!r}: {exc}")
            continue
        try:
            _get_roster_store().add(name, phone_e164)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Store error for {name!r}: {exc}")

    return json.dumps({"imported": imported, "skipped": errors})


def _handle_five_fingers_log_attendance(
    date: str,
    came: list[str] | None = None,
    missed: list[str] | None = None,
    notes: str | None = None,
) -> str:
    """Resolve teammate names/IDs and record attendance in Firestore."""
    roster = _get_roster_store().list_active()

    def _resolve(identifier: str) -> str | None:
        """Return roster doc_id for a name (case-insensitive) or direct doc_id."""
        identifier_lower = identifier.lower()
        for member in roster:
            if member.get("doc_id") == identifier:
                return identifier
            if member.get("name", "").lower() == identifier_lower:
                return member["doc_id"]
        return None

    store = _get_attendance_store()
    logged = 0
    warnings: list[str] = []

    for identifier in (came or []):
        doc_id = _resolve(identifier)
        if doc_id is None:
            warnings.append(f"Unresolved (came): {identifier!r}")
            continue
        store.mark_attendance(date, doc_id, "came")
        logged += 1

    for identifier in (missed or []):
        doc_id = _resolve(identifier)
        if doc_id is None:
            warnings.append(f"Unresolved (missed): {identifier!r}")
            continue
        store.mark_attendance(date, doc_id, "missed")
        logged += 1

    if notes:
        store.upsert_practice(date, notes=notes)

    return json.dumps({"date": date, "logged": logged, "warnings": warnings})


def _handle_run_morning_briefing() -> str:
    """Trigger run_morning_briefing as a background task on the running event loop."""
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        from interfaces.web_server import _application
        if _application is None:
            return json.dumps({"error": "Application not initialised — use CLI smoke test instead."})
        today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        loop = asyncio.get_event_loop()
        from core.morning_briefing import run_morning_briefing
        loop.create_task(run_morning_briefing(_application.bot, today_iso, dedup=False))
        # Mark as manual trigger in Firestore so dedup knows it was user-triggered.
        from core.morning_briefing import _set_state
        _set_state(today_iso, {"status": "manual", "trigger": "manual",
                               "sent_at": datetime.now(ZoneInfo("Asia/Jerusalem")).isoformat()})
        return json.dumps({"status": "composing", "message": "Composing your morning briefing now, sir — it will arrive in Telegram shortly."})
    except Exception as exc:
        logger.warning("run_morning_briefing tool error: %s", exc)
        return json.dumps({"error": str(exc)})


def _handle_notion_search(query: str, filter_type: str | None = None) -> str:
    result = _notion_search(query=query, filter_type=filter_type)
    return json.dumps(result)


def _handle_notion_get_page(page_id: str) -> str:
    result = _notion_get_page(page_id=page_id)
    return json.dumps(result)


def _handle_notion_query_database(
    database_id: str,
    filter: dict | None = None,
    sorts: list | None = None,
    page_size: int = 100,
) -> str:
    result = _notion_query_database(
        database_id=database_id, filter=filter, sorts=sorts, page_size=page_size
    )
    return json.dumps(result)


def _handle_notion_create_page(
    parent_id: str,
    parent_type: str,
    title: str,
    content: str | None = None,
    properties: dict | None = None,
) -> str:
    result = _notion_create_page(
        parent_id=parent_id,
        parent_type=parent_type,
        title=title,
        content=content,
        properties=properties,
    )
    return json.dumps(result)


def _handle_notion_append_blocks(page_id: str, content: str) -> str:
    result = _notion_append_blocks(page_id=page_id, content=content)
    return json.dumps(result)


def _handle_list_own_files(subdir: str | None = None) -> str:
    """List Klaus's source files, optionally filtered to a subdirectory."""
    result = _list_own_files(subdir=subdir)
    return json.dumps(result)


def _handle_read_own_source(path: str) -> str:
    """Return the contents of a source file, with denylist and traversal protection."""
    result = _read_own_source(path=path)
    return json.dumps(result)


def _handle_search_own_source(query: str, max_results: int = 20) -> str:
    """Full-text search across source files; returns line-level matches."""
    result = _search_own_source(query=query, max_results=max_results)
    return json.dumps(result)


def _handle_get_self_status() -> str:
    """Return Klaus's operational status: uptime, message count, costs, heartbeat."""
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

    # --- LLM usage: today's cost and message count proxy ---
    try:
        project_id = _os.environ.get("GCP_PROJECT_ID")
        database = _os.environ.get("FIRESTORE_DATABASE", "(default)")
        if project_id:
            from memory.firestore_db import LLMUsageStore
            store = LLMUsageStore(project_id=project_id, database=database)
            today_data = store.summary("today")
            month_data = store.summary("month")
            # smart_calls proxy for "messages from user" — one smart call ≈ one user message
            result["today_messages"] = today_data.get("smart_calls", 0)
            result["today_cost_usd"] = round(today_data.get("total_cost_usd", 0.0), 6)
            result["month_cost_usd"] = round(month_data.get("total_cost_usd", 0.0), 4)
            result["today_llm_calls"] = today_data.get("call_count", 0)
        else:
            result["today_messages"] = "unavailable (GCP_PROJECT_ID not set)"
            result["today_cost_usd"] = "unavailable"
            result["month_cost_usd"] = "unavailable"
    except Exception as exc:
        result["cost_error"] = str(exc)

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
# Dispatch table — maps tool names to handler callables.             #
# ------------------------------------------------------------------ #

_HANDLERS: dict[str, object] = {
    "fetch_weather":          lambda args: _handle_fetch_weather(**args),
    "fetch_readwise_today":   lambda args: _handle_fetch_readwise_today(**args),
    "fetch_garmin_today":     lambda args: _handle_fetch_garmin_today(**args),
    "list_calendar_events":   lambda args: _handle_list_calendar_events(**args),
    "create_calendar_event":  lambda args: _handle_create_calendar_event(**args),
    "check_calendar_free":    lambda args: _handle_check_calendar_free(**args),
    "delete_calendar_event":  lambda args: _handle_delete_calendar_event(**args),
    "list_unread_emails":    lambda args: _handle_list_unread_emails(**args),
    "get_email":             lambda args: _handle_get_email(**args),
    "add_task":              lambda args: _handle_add_task(**args),
    "remember":              lambda args: _handle_remember(**args),
    "recall":                lambda args: _handle_recall(**args),
    "search_chat_history":   lambda args: _handle_search_chat_history(**args),
    "list_own_files":          lambda args: _handle_list_own_files(**args),
    "read_own_source":         lambda args: _handle_read_own_source(**args),
    "search_own_source":       lambda args: _handle_search_own_source(**args),
    "get_self_status":         lambda args: _handle_get_self_status(),
    "five_fingers_add_teammate":    lambda args: _handle_five_fingers_add_teammate(**args),
    "five_fingers_remove_teammate": lambda args: _handle_five_fingers_remove_teammate(**args),
    "five_fingers_list_teammates":  lambda args: _handle_five_fingers_list_teammates(**args),
    "five_fingers_bulk_import":     lambda args: _handle_five_fingers_bulk_import(**args),
    "five_fingers_log_attendance":  lambda args: _handle_five_fingers_log_attendance(**args),
    "run_morning_briefing":         lambda args: _handle_run_morning_briefing(),
    "notion_search":          lambda args: _handle_notion_search(**args),
    "notion_get_page":        lambda args: _handle_notion_get_page(**args),
    "notion_query_database":  lambda args: _handle_notion_query_database(**args),
    "notion_create_page":     lambda args: _handle_notion_create_page(**args),
    "notion_append_blocks":   lambda args: _handle_notion_append_blocks(**args),
}


def get_all_schemas() -> list[dict]:
    """Return all tool schemas, including the delegate_to_worker meta-tool."""
    return TOOL_SCHEMAS


def get_worker_schemas() -> list[dict]:
    """Return tool schemas for the worker agent (excludes delegate_to_worker)."""
    return WORKER_TOOL_SCHEMAS


def dispatch(tool_name: str, args: dict) -> str:
    """Execute a tool by name and return a JSON string result.

    Args:
        tool_name: Registered tool name. Must not be 'delegate_to_worker'
            (that meta-tool is intercepted by the orchestrator before dispatch).
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
