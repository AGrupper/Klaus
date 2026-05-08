"""Tool registry — schemas, real handlers, and dispatch.

Defines the full set of tools available to the agent in Anthropic's tool_use
JSON format.  Phase 3 replaced the Gmail/Calendar mock handlers with real
Google API calls.  Phase 4 replaced the add_task mock with a real Firestore
queue via `FirestoreQueue` and `ThingsQueueWriter`.  Phase 6 adds remember
and recall tools for long-term Pinecone-backed memory.

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
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({"remember", "recall"})

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
            "Add a to-do item to the Things 3 task queue. The local Mac poller will "
            "inject it into Things 3 automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title."},
                "notes": {"type": "string", "description": "Optional notes or details."},
                "deadline": {
                    "type": "string",
                    "description": "Optional deadline, YYYY-MM-DD format.",
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
            },
            "required": ["query"],
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
    if s["name"] not in {"delegate_to_worker", "remember", "recall"}
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
from memory.firestore_db import FirestoreQueue          # noqa: E402
from mcp_tools.things_queue import ThingsQueueWriter    # noqa: E402
from memory.pinecone_db import MemoryStore              # noqa: E402
from mcp_tools.memory import MemoryTool                 # noqa: E402
import os                                               # noqa: E402

_auth_manager: GoogleAuthManager | None = None
_gmail_tool: GmailTool | None = None
_calendar_tool: GoogleCalendarManager | None = None
_firestore_queue: FirestoreQueue | None = None
_things_queue_writer: ThingsQueueWriter | None = None
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


def _get_firestore_queue() -> FirestoreQueue:
    """Return the shared FirestoreQueue instance, building it on first call."""
    global _firestore_queue
    if _firestore_queue is None:
        project_id = os.getenv("GCP_PROJECT_ID")
        if not project_id:
            raise RuntimeError("GCP_PROJECT_ID env var is required for add_task")
        collection = os.getenv("FIRESTORE_COLLECTION_THINGS_QUEUE", "things_queue")
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        _firestore_queue = FirestoreQueue(
            project_id=project_id, collection=collection, database=database,
        )
    return _firestore_queue


def _get_things_queue_writer() -> ThingsQueueWriter:
    """Return the shared ThingsQueueWriter instance, building it on first call."""
    global _things_queue_writer
    if _things_queue_writer is None:
        _things_queue_writer = ThingsQueueWriter(firestore_queue=_get_firestore_queue())
    return _things_queue_writer


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
    """Delegate to GoogleCalendarManager.list_events and serialise the result."""
    events = _get_calendar_tool().list_events(time_min_iso, time_max_iso)
    return json.dumps({"events": events, "count": len(events)})


def _handle_create_calendar_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    travel_minutes_each_way: int | None = None,
) -> str:
    """Delegate to GoogleCalendarManager.create_event and serialise the result."""
    result = _get_calendar_tool().create_event(
        summary=summary,
        start_iso=start_iso,
        end_iso=end_iso,
        description=description,
        travel_minutes_each_way=travel_minutes_each_way,
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
                     tags: list[str] | None = None) -> str:
    """Delegate to ThingsQueueWriter.add_todo and serialise the result."""
    result = _get_things_queue_writer().add_todo(
        title=title, notes=notes, deadline=deadline, tags=tags,
    )
    return json.dumps(result)


def _handle_remember(content: str, kind: str) -> str:
    """Delegate to MemoryTool.remember and serialise the result."""
    result = _get_memory_tool().remember(_get_current_user_id(), content, kind)
    return json.dumps(result)


def _handle_recall(query: str, k: int = 5) -> str:
    """Delegate to MemoryTool.recall and serialise the result."""
    result = _get_memory_tool().recall(_get_current_user_id(), query, k)
    return json.dumps(result)


# ------------------------------------------------------------------ #
# Dispatch table — maps tool names to handler callables.             #
# ------------------------------------------------------------------ #

_HANDLERS: dict[str, object] = {
    "list_calendar_events":   lambda args: _handle_list_calendar_events(**args),
    "create_calendar_event":  lambda args: _handle_create_calendar_event(**args),
    "check_calendar_free":    lambda args: _handle_check_calendar_free(**args),
    "delete_calendar_event":  lambda args: _handle_delete_calendar_event(**args),
    "list_unread_emails":    lambda args: _handle_list_unread_emails(**args),
    "get_email":             lambda args: _handle_get_email(**args),
    "add_task":              lambda args: _handle_add_task(**args),
    "remember":              lambda args: _handle_remember(**args),
    "recall":                lambda args: _handle_recall(**args),
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
