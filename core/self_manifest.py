"""Klaus capability manifest generator.

Introspects live tool schemas, cron routes, outbound channels, model map, and
memory stores to produce docs/SELF.md — the authoritative, doubt-free manifest
of everything Klaus is and can do.

Run as a script (CI step):
    python core/self_manifest.py
    # → writes docs/SELF.md, prints sha to stdout, exits 0 on success.

The generated file is committed to the repo and refreshed on every deploy.
core/heartbeat.py check_code() performs a weekly SHA staleness check as a
safety net — it does NOT regenerate the file.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source root discovery — identical pattern to mcp_tools/self_inspect.py
# ---------------------------------------------------------------------------

def _get_source_root() -> Path:
    """Return the project root directory.

    Respects the SOURCE_ROOT env var for CI/CD overrides; otherwise resolves
    to the parent of core/ (i.e. the project root).
    """
    env_override = os.environ.get("SOURCE_ROOT")
    if env_override:
        return Path(env_override).resolve()
    # core/self_manifest.py lives in core/, so .parent.parent → project root
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# SHA computation — the hash that heartbeat.check_code() compares against
# ---------------------------------------------------------------------------

def _compute_schema_hash(root: Path) -> str:
    """Compute a deterministic SHA-1 of tool schemas + cron route names.

    Reads the TOOL_SCHEMAS names from core/tools.py (grep for '"name":') and
    cron route paths from interfaces/web_server.py (grep for '/cron/'). This
    hash changes whenever a tool is added/removed or a cron route changes,
    which is the staleness signal heartbeat checks.

    Args:
        root: Project root directory path.

    Returns:
        40-character lowercase hex SHA-1 string.
    """
    fragments: list[str] = []

    tools_file = root / "core" / "tools.py"
    if tools_file.exists():
        text = tools_file.read_text(encoding="utf-8")
        names = sorted(re.findall(r'"name":\s*"([^"]+)"', text))
        fragments.extend(names)

    web_file = root / "interfaces" / "web_server.py"
    if web_file.exists():
        text = web_file.read_text(encoding="utf-8")
        routes = sorted(re.findall(r'"/cron/[^"]*"', text))
        fragments.extend(routes)

    combined = "\n".join(fragments)
    return hashlib.sha1(combined.encode(), usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# Tool introspection helpers
# ---------------------------------------------------------------------------

def _first_sentence(description: str) -> str:
    """Return the first sentence of a tool description string.

    Splits on the first period, question mark, or newline.

    Args:
        description: Full tool description text.

    Returns:
        First sentence, stripped of leading/trailing whitespace.
    """
    # Collapse whitespace from multi-line strings
    text = " ".join(description.split())
    # Split on first sentence terminator
    match = re.search(r"[.!?]", text)
    if match:
        return text[: match.start() + 1].strip()
    return text.strip()


def _load_tool_data(root: Path) -> list[dict]:
    """Dynamically import TOOL_SCHEMAS and SMART_AGENT_DIRECT_TOOLS from core/tools.py.

    Returns a list of dicts with keys: name, routing, purpose.

    Falls back to a hardcoded minimal list if the import fails (e.g. missing
    Google API credentials in CI), so generate_manifest() can still succeed.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "core.tools", root / "core" / "tools.py"
        )
        if spec is None or spec.loader is None:
            raise ImportError("Could not load core/tools.py spec")
        # We must avoid executing module-level side-effects that require
        # credentials. We patch sys.modules so relative imports don't fail.
        import types
        # Provide stub modules for dependencies that require credentials at import.
        # This allows the manifest generator to run in environments without the full
        # dependency stack (e.g. local dev without pip install). Cloud Run has all
        # deps so live imports succeed; the fallback is only for dev/CI dry-runs.
        _stubs: dict[str, types.ModuleType] = {}

        def _ensure_stub(mod_name: str) -> types.ModuleType:
            """Register a stub module if not already present."""
            if mod_name not in sys.modules:
                stub = types.ModuleType(mod_name)
                sys.modules[mod_name] = stub
                _stubs[mod_name] = stub
                return stub
            return sys.modules[mod_name]

        # Ensure the project root is on sys.path so "core" package is found.
        # This is needed when running self_manifest.py directly (not via gunicorn).
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

        # googleapiclient and sub-modules
        gclient_stub = _ensure_stub("googleapiclient")
        errors_stub = _ensure_stub("googleapiclient.errors")
        errors_stub.HttpError = Exception  # type: ignore[attr-defined]
        gclient_stub.errors = errors_stub  # type: ignore[attr-defined]
        discovery_stub = _ensure_stub("googleapiclient.discovery")
        if not hasattr(discovery_stub, "build"):
            discovery_stub.build = lambda *a, **k: None  # type: ignore[attr-defined]

        # google-cloud-firestore stubs
        _ensure_stub("google")
        _ensure_stub("google.cloud")
        _ensure_stub("google.cloud.firestore")
        _ensure_stub("google.api_core")
        api_core_exc_stub = _ensure_stub("google.api_core.exceptions")
        for _name in (
            "GoogleAPICallError", "NotFound", "AlreadyExists", "PermissionDenied",
            "InvalidArgument", "FailedPrecondition", "DeadlineExceeded",
            "ResourceExhausted", "Aborted", "Unknown", "Cancelled",
        ):
            if not hasattr(api_core_exc_stub, _name):
                setattr(api_core_exc_stub, _name, Exception)
        _ensure_stub("google.oauth2")
        _ensure_stub("google.oauth2.service_account")
        _ensure_stub("google.oauth2.credentials")
        # google-auth + oauthlib stubs (transitively imported by core.auth_google
        # via core.tools — needed so the manifest generator's live import path
        # works in local dev where google-auth isn't installed).
        _ensure_stub("google.auth")
        auth_exc_stub = _ensure_stub("google.auth.exceptions")
        # core.auth_google does `from google.auth.exceptions import GoogleAuthError`
        # — attach the symbol to the stub so the live-import path succeeds in
        # environments without the real google-auth library installed.
        if not hasattr(auth_exc_stub, "GoogleAuthError"):
            auth_exc_stub.GoogleAuthError = Exception  # type: ignore[attr-defined]
        if not hasattr(auth_exc_stub, "RefreshError"):
            auth_exc_stub.RefreshError = Exception  # type: ignore[attr-defined]
        _ensure_stub("google.auth.transport")
        auth_req_stub = _ensure_stub("google.auth.transport.requests")
        if not hasattr(auth_req_stub, "Request"):
            auth_req_stub.Request = type("Request", (), {})  # type: ignore[attr-defined]
        _ensure_stub("google_auth_oauthlib")
        oauthlib_flow_stub = _ensure_stub("google_auth_oauthlib.flow")
        if not hasattr(oauthlib_flow_stub, "InstalledAppFlow"):
            oauthlib_flow_stub.InstalledAppFlow = type(  # type: ignore[attr-defined]
                "InstalledAppFlow", (), {}
            )
        oauth2_creds_stub = sys.modules.get("google.oauth2.credentials")
        if oauth2_creds_stub is not None and not hasattr(oauth2_creds_stub, "Credentials"):
            oauth2_creds_stub.Credentials = type(  # type: ignore[attr-defined]
                "Credentials", (), {}
            )

        # dotenv stub — provide load_dotenv shim so core.* imports work.
        dotenv_stub = _ensure_stub("dotenv")
        if not hasattr(dotenv_stub, "load_dotenv"):
            dotenv_stub.load_dotenv = lambda *a, **k: None  # type: ignore[attr-defined]

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception:
            # Clean up stubs on failure
            for mod_name in _stubs:
                sys.modules.pop(mod_name, None)
            raise

        schemas: list[dict] = getattr(module, "TOOL_SCHEMAS", [])
        direct_tools: frozenset = getattr(module, "SMART_AGENT_DIRECT_TOOLS", frozenset())

        rows = []
        for schema in schemas:
            name = schema.get("name", "")
            if name == "delegate_to_worker":
                # Meta-tool, not a real agent tool
                continue
            desc = schema.get("description", "")
            if isinstance(desc, str):
                purpose = _first_sentence(desc)
            else:
                purpose = str(desc)
            routing = "brain-direct" if name in direct_tools else "worker-delegated"
            rows.append({"name": name, "routing": routing, "purpose": purpose})
        return rows

    except Exception as exc:
        logger.warning("_load_tool_data: dynamic import failed (%s) — using fallback", exc)
        return _load_tool_data_fallback()


def _load_tool_data_fallback() -> list[dict]:
    """Return hardcoded tool data as a fallback when live import fails."""
    # Based on core/tools.py TOOL_SCHEMAS as of Phase 15
    direct = {
        "remember", "recall", "run_morning_briefing", "search_chat_history",
        "list_own_files", "read_own_source", "search_own_source",
        "get_self_status",
    }
    tools = [
        ("list_calendar_events",        "List all calendar events within a given date/time window."),
        ("create_calendar_event",       "Create a new event on the user's Google Calendar."),
        ("check_calendar_free",         "Check whether a specific time window is free of calendar events."),
        ("delete_calendar_event",       "Delete an event from the user's Google Calendar by event ID."),
        ("list_unread_emails",          "List recent unread emails from the inbox with sender, subject, and snippet."),
        ("get_email",                   "Fetch the full body and headers of a specific email by its ID."),
        ("task_create",                 "Create a task in the native task store (also: task_list/complete/reschedule/edit/delete)."),
        ("remember",                    "Save a durable piece of information about the user to long-term memory."),
        ("recall",                      "Search long-term memory for information relevant to a query."),
        ("search_chat_history",         "Search ingested Claude Code chat history for relevant sessions."),
        ("fetch_weather",               "Fetch current weather conditions and today/tomorrow forecast for a location."),
        ("fetch_readwise_today",        "Fetch today's reading highlights from Readwise."),
        ("fetch_garmin_today",          "Fetch today's health summary from Garmin Connect: sleep score, sleep hours, HRV status, body battery, and resting heart rate."),

        ("run_morning_briefing",        "Compose and send the morning briefing to Telegram immediately."),
        ("notion_search",               "Search across all Notion pages and databases shared with Klaus."),
        ("notion_get_page",             "Fetch the full content of a Notion page by its ID."),
        ("notion_query_database",       "Query a Notion database."),
        ("notion_create_page",          "Create a new page in Notion — either as a database entry or a sub-page."),
        ("notion_append_blocks",        "Append text content to the end of an existing Notion page."),
        ("list_own_files",              "List Klaus's deployed source files."),
        ("read_own_source",             "Read the contents of one of Klaus's own source files by relative path."),
        ("search_own_source",           "Full-text search across Klaus's source files."),
        ("get_self_status",             "Return today's cost, message count, container uptime, and heartbeat status."),
    ]
    return [
        {
            "name": name,
            "routing": "brain-direct" if name in direct else "worker-delegated",
            "purpose": purpose,
        }
        for name, purpose in tools
    ]


# ---------------------------------------------------------------------------
# Tool grouping — BRAIN-06/D-07 compaction. Rendering-only: the introspected
# data source (_load_tool_data / TOOL_SCHEMAS) is untouched; this just decides
# how to *display* it compactly. Any tool name not recognized below falls back
# to the "Other" category with its full name as the label, so a newly added
# tool can never silently vanish from the manifest even before this map is
# updated for it.
# ---------------------------------------------------------------------------

_TOOL_CATEGORIES: dict[str, str] = {
    # Calendar
    "list_calendar_events": "Calendar", "create_calendar_event": "Calendar",
    "check_calendar_free": "Calendar", "delete_calendar_event": "Calendar",
    "update_calendar_event": "Calendar",
    # Email (read-only)
    "list_unread_emails": "Email", "get_email": "Email",
    # Tasks & habits (native TaskStore/HabitStore — v5.0)
    "task_create": "Tasks & Habits", "task_list": "Tasks & Habits",
    "task_complete": "Tasks & Habits", "task_reschedule": "Tasks & Habits",
    "task_edit": "Tasks & Habits", "task_delete": "Tasks & Habits",
    "get_habit_adherence": "Tasks & Habits",
    # Long-term memory
    "remember": "Memory", "recall": "Memory", "search_chat_history": "Memory",
    # External data feeds
    "fetch_weather": "External Data", "fetch_readwise_today": "External Data",
    "fetch_garmin_today": "External Data",
    # Notion
    "notion_search": "Notion", "notion_get_page": "Notion",
    "notion_query_database": "Notion", "notion_create_page": "Notion",
    "notion_append_blocks": "Notion",
    # Self-inspection (own source code)
    "list_own_files": "Self-Inspection", "read_own_source": "Self-Inspection",
    "search_own_source": "Self-Inspection",
    # Self-status & hub controls
    "get_self_status": "Self-Status & Hub", "toggle_telegram_mirror": "Self-Status & Hub",
    "get_push_health": "Self-Status & Hub",
    # Self-scheduled follow-ups
    "schedule_followup": "Follow-Ups", "list_followups": "Follow-Ups",
    "cancel_followup": "Follow-Ups",
    # Coaching & training data
    "get_training_profile": "Coaching & Training", "read_coaching_guide": "Coaching & Training",
    "update_training_profile": "Coaching & Training", "update_plan": "Coaching & Training",
    "fetch_training_status": "Coaching & Training", "fetch_recent_activities": "Coaching & Training",
    "get_acwr": "Coaching & Training", "fetch_recent_meals": "Coaching & Training",
    "fetch_nutrition_trend": "Coaching & Training", "log_training": "Coaching & Training",
    "get_training_history": "Coaching & Training", "get_strength_progress": "Coaching & Training",
    "get_training_context": "Coaching & Training", "get_run_detail": "Coaching & Training",
    # Training blocks & benchmarks
    "get_plan": "Training Blocks & Benchmarks", "get_block_status": "Training Blocks & Benchmarks",
    "log_benchmark": "Training Blocks & Benchmarks", "get_benchmark_history": "Training Blocks & Benchmarks",
    "get_goal_projection": "Training Blocks & Benchmarks", "start_block": "Training Blocks & Benchmarks",
    "end_block": "Training Blocks & Benchmarks",
    # Briefing
    "run_morning_briefing": "Briefing",
}

# Display order for categories in the compact manifest (stable, readable).
_CATEGORY_ORDER: list[str] = [
    "Calendar", "Tasks & Habits", "Email", "Memory", "Notion",
    "Coaching & Training", "Training Blocks & Benchmarks", "Briefing",
    "External Data", "Follow-Ups", "Self-Inspection", "Self-Status & Hub",
    "Other",
]

# Short action labels for one-liner grouping. Falls back to the full tool
# name when a tool isn't listed here (forward-compat safety net).
_TOOL_SHORT_LABELS: dict[str, str] = {
    "list_calendar_events": "list", "create_calendar_event": "create",
    "check_calendar_free": "free-busy", "delete_calendar_event": "delete",
    "update_calendar_event": "update",
    "list_unread_emails": "list-unread", "get_email": "get",
    "task_create": "create", "task_list": "list", "task_complete": "complete",
    "task_reschedule": "reschedule", "task_edit": "edit", "task_delete": "delete",
    "get_habit_adherence": "habit-adherence",
    "remember": "remember", "recall": "recall", "search_chat_history": "search-chat-history",
    "fetch_weather": "weather", "fetch_readwise_today": "readwise",
    "fetch_garmin_today": "garmin-today",
    "notion_search": "search", "notion_get_page": "get-page",
    "notion_query_database": "query-db", "notion_create_page": "create-page",
    "notion_append_blocks": "append-blocks",
    "list_own_files": "list-files", "read_own_source": "read-source",
    "search_own_source": "search-source",
    "get_self_status": "status", "toggle_telegram_mirror": "toggle-mirror",
    "get_push_health": "push-health",
    "schedule_followup": "schedule", "list_followups": "list", "cancel_followup": "cancel",
    "get_training_profile": "get-profile", "read_coaching_guide": "coaching-guide",
    "update_training_profile": "update-profile", "update_plan": "update-plan",
    "fetch_training_status": "training-status", "fetch_recent_activities": "recent-activities",
    "get_acwr": "acwr", "fetch_recent_meals": "recent-meals",
    "fetch_nutrition_trend": "nutrition-trend", "log_training": "log-session",
    "get_training_history": "history", "get_strength_progress": "strength-progress",
    "get_training_context": "context", "get_run_detail": "run-detail",
    "get_plan": "get-plan", "get_block_status": "block-status",
    "log_benchmark": "log-benchmark", "get_benchmark_history": "benchmark-history",
    "get_goal_projection": "goal-projection", "start_block": "start-block",
    "end_block": "end-block",
    "run_morning_briefing": "send-now",
}


def _group_tools_by_category(tool_rows: list[dict]) -> "dict[str, list[str]]":
    """Group introspected tool rows into category → short-label lists.

    Args:
        tool_rows: Output of ``_load_tool_data`` — unchanged introspection data.

    Returns:
        Ordered mapping of category name to a list of short action labels,
        in ``_CATEGORY_ORDER``. Unrecognized tools land under "Other" using
        their full name as the label, so new tools never silently disappear.
    """
    grouped: dict[str, list[str]] = {cat: [] for cat in _CATEGORY_ORDER}
    for row in tool_rows:
        name = row["name"]
        category = _TOOL_CATEGORIES.get(name, "Other")
        label = _TOOL_SHORT_LABELS.get(name, name)
        grouped.setdefault(category, [])
        grouped[category].append(label)
    return grouped


# ---------------------------------------------------------------------------
# Manifest renderer
# ---------------------------------------------------------------------------

def _render_manifest(root: Path, sha: str) -> str:
    """Build the full SELF.md content string.

    Args:
        root: Project root path.
        sha: 40-character SHA-1 computed by _compute_schema_hash().

    Returns:
        Complete SELF.md content as a string.
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tool_rows = _load_tool_data(root)

    # ----- Front-matter + header -----------------------------------------
    lines: list[str] = [
        "---",
        f"generated_at: {generated_at}",
        f"sha: {sha}",
        "---",
        "",
        "# Klaus — Capability Manifest",
        "",
        f"<!-- sha: {sha} -->",
        "",
        "> This file is auto-generated by `core/self_manifest.py` on every deploy.",
        "> Do not edit manually — changes will be overwritten.",
        "",
    ]

    # ----- §1 Identity ---------------------------------------------------
    # Model strings are read from env so SELF.md never goes stale when the
    # operator swaps backends. Defaults match the current production config
    # (see .env.example).
    brain_model = os.getenv("SMART_AGENT_MODEL", "gemini-3.5-flash")
    brain_backend = os.getenv("SMART_AGENT_BACKEND", "gemini")
    worker_model = os.getenv("WORKER_AGENT_MODEL", "deepseek-v4-flash")
    worker_backend = os.getenv("WORKER_AGENT_BACKEND", "openai")
    fallback_model = os.getenv("SMART_AGENT_FALLBACK_MODEL", "claude-haiku-4-5")
    fallback_backend = os.getenv("SMART_AGENT_FALLBACK_BACKEND", "anthropic")
    tick_model = os.getenv("TICK_BRAIN_MODEL", "openai/gpt-oss-120b")

    def _backend_label(name: str) -> str:
        return {
            "gemini": "Gemini (AI Studio)",
            "anthropic": "Anthropic",
            "openai": "OpenAI-compat (DeepSeek / Groq)",
        }.get(name, name)

    lines += [
        "## Identity",
        "",
        (
            "Klaus is a cloud-hosted personal AI agent deployed on Google Cloud Run, "
            "serving a single user — Amit Grupper, based in Tel Aviv, Israel. "
            f"He is built on a dual-model architecture: {brain_model} acts as the brain "
            f"(smart agent — orchestration, judgment, tool planning), while {worker_model} "
            "operates as the worker (hands — fast structured JSON execution, data gathering). "
            f"{fallback_model} is the brain fallback, activated automatically on any LLMError "
            "from the primary brain. "
            "Klaus talks like Amit's sharpest friend: warm, direct, human, short by "
            "default — plain prose over bulleted readouts, dry humor when it's earned, "
            "no formal salute. He acts autonomously, protects Amit's schedule and "
            "routines, and is deeply integrated with his daily digital life."
        ),
        "",
    ]

    # ----- §2 Model Map --------------------------------------------------
    lines += [
        "## Model Map",
        "",
        "| Purpose | Model | Backend |",
        "|---------|-------|---------|",
        f"| Brain (smart agent) | {brain_model} | {_backend_label(brain_backend)} |",
        f"| Worker | {worker_model} | {_backend_label(worker_backend)} |",
        f"| Smart agent fallback | {fallback_model} | {_backend_label(fallback_backend)} |",
        f"| Tick-brain | {tick_model} | Groq (OpenAI-compat) |",
        f"| Tick-brain fallback | {brain_model} | {_backend_label(brain_backend)} |",
        "| Embeddings | gemini-embedding-2 | Gemini (AI Studio) |",
        "",
    ]

    # ----- §3 Tools (D-07 compact form — grouped category one-liners) ----
    lines += [
        "## Tools",
        "",
        (
            "Grouped by category, one line each (call `list_own_files` / "
            "`read_own_source` for full per-tool schema detail):"
        ),
        "",
    ]
    grouped = _group_tools_by_category(tool_rows)
    for category in _CATEGORY_ORDER:
        labels = grouped.get(category) or []
        if not labels:
            continue
        lines.append(f"- **{category}:** {'/'.join(labels)}")
    lines.append("")

    # ----- §4 Cron Jobs (D-07 compact form — one summary line) -----------
    # Trued against CLAUDE.md §5 (the "current live infrastructure" section):
    # proactive-alerts (21:30) and reflect (22:00) are RETIRED, folded into
    # the nightly review; nightly-backstop/autonomous-tick/strength-sync/
    # run-sync are the current live jobs.
    lines += [
        "## Cron Jobs",
        "",
        (
            "9 scheduled jobs (Asia/Jerusalem): heartbeat (hourly, `/cron/heartbeat`) · "
            "morning-briefing-tick (*/10 6-10, `/cron/morning-briefing-tick`) · "
            "chat-ingest (04:00, `/cron/ingest-chats`) · "
            "chat-export-ingest (04:30, `/cron/ingest-chat-exports`) · "
            "nightly-backstop (01:00, `/cron/nightly-backstop`) · "
            "autonomous-tick (*/20 7-21, `/cron/autonomous-tick`) · "
            "weekly-training-review (Sun 10:00, `/cron/weekly-training-review`) · "
            "strength-sync (05:00, `/cron/strength-sync`) · "
            "run-sync (05:15, `/cron/run-sync`). "
            "Plus push-driven `/cron/healthkit-sync` (see Push endpoints below)."
        ),
        "",
    ]

    # ----- Push endpoints (Phase 19.1 — HEALTHKIT-07 / D-21) -------------
    lines += [
        "## Push endpoints",
        "",
        "| Endpoint | Driver | Auth | Purpose |",
        "|----------|--------|------|---------|",
        "| `/cron/healthkit-sync` | iPhone Shortcut | shared-secret bearer | Lifesum nutrition bridge |",
        "",
    ]

    # ----- §5 Outbound Channels ------------------------------------------
    lines += [
        "## Outbound Channels",
        "",
        "| Channel | Access | Notes |",
        "|---------|--------|-------|",
        "| Telegram | Read + Write | Sends messages to Amit's Telegram account (primary interface) |",
        "| Google Calendar | Read + Write | Create, delete, list events |",
        "| Tasks (native) | Read + Write | Klaus Hub TaskStore — create, list, complete, reschedule, edit, delete |",
        "| Gmail | **Read-only** | List unread, get email by ID — **no send capability** |",
        "| Notion | Read + Write | Search, get page, query database, create page, append blocks |",
        "| Readwise | Read-only | Daily reading highlights |",
        "| Garmin Connect | Read-only | Sleep, HRV, body battery, resting HR |",
        "| Weather API (wttr.in) | Read-only | Current conditions + forecast for Tel Aviv |",
        "",
    ]

    # ----- §6 Memory Layers ----------------------------------------------
    lines += [
        "## Memory Layers",
        "",
        "| Layer | Technology | Purpose |",
        "|-------|------------|---------|",
        "| Conversation store | Firestore `conversations/{user_id}` | Per-session turn history (6h TTL) |",
        "| Long-term facts | Pinecone `kind=fact` | Durable facts about Amit (recall tool) |",
        "| Long-term chunks | Pinecone `kind=chunk` | Narrative context chunks |",
        "| Chat history | Pinecone `kind=chat` | Ingested conversation logs |",
        "| LLM usage | Firestore `llm_usage/{date}` | Daily cost + call accounting |",
        "| Heartbeat state | Firestore `config/heartbeat` | Heartbeat scheduler config |",
        "| Incidents | Firestore `heartbeat_incidents/*` | Signal dedup + escalation tracking |",
        "| Self state | Firestore `config/self_state` | Identity summary + volatile state |",
        "",
    ]

    # ----- §7 Current Limits ---------------------------------------------
    lines += [
        "## Current Limits",
        "",
        (
            "The following limitations are explicit and honest. "
            "They are not bugs — they are the current scope boundary."
        ),
        "",
        "- **Outbound messages:** Telegram-only. No email send. No WhatsApp autonomous outbound.",
        "- **Gmail is read-only** — Klaus cannot send emails via any tool.",
        "- **Pinecone valid `kind` values:** `fact`, `chunk`, `chat`, `self`. (`self` = Klaus's own journal entries.)",
        "- **Max tool iterations per conversation:** 8 (`MAX_TOOL_ITERATIONS` in `core/main.py`)",
        "- **Conversation context reset:** every ~6 hours (Cloud Run container lifecycle)",
        "- **Autonomous proactive outreach:** not yet implemented (Phase 18)",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_manifest(root: Path | None = None) -> dict:
    """Generate docs/SELF.md by introspecting live source.

    Computes a deterministic SHA-1 over tool schema names and cron route strings,
    renders the full manifest with all 7 sections, and writes it to docs/SELF.md.

    Args:
        root: Optional project root override. Defaults to _get_source_root().

    Returns:
        {"path": "docs/SELF.md", "sha": "<40-char-hex>", "sections": N}
        on success, or {"error": "<message>"} on failure.
    """
    try:
        root = root or _get_source_root()
        sha = _compute_schema_hash(root)
        content = _render_manifest(root, sha)
        out_path = root / "docs" / "SELF.md"
        out_path.write_text(content, encoding="utf-8")
        sections = content.count("\n## ")
        logger.info("SELF.md written (%d sections, sha=%s)", sections, sha[:8])
        return {"path": str(out_path.relative_to(root)), "sha": sha, "sections": sections}
    except Exception as exc:
        logger.error("generate_manifest failed: %s", exc, exc_info=True)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = generate_manifest()
    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)
    print(f"SELF.md written — sha={result['sha']}")
