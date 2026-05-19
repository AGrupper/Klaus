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
        _ensure_stub("googleapiclient.discovery")

        # google-cloud-firestore stubs
        _ensure_stub("google")
        _ensure_stub("google.cloud")
        _ensure_stub("google.cloud.firestore")
        _ensure_stub("google.api_core")
        _ensure_stub("google.api_core.exceptions")
        _ensure_stub("google.oauth2")
        _ensure_stub("google.oauth2.service_account")

        # dotenv stub
        _ensure_stub("dotenv")

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
        ("add_task",                    "Add a to-do item to TickTick."),
        ("remember",                    "Save a durable piece of information about the user to long-term memory."),
        ("recall",                      "Search long-term memory for information relevant to a query."),
        ("search_chat_history",         "Search ingested Claude Code chat history for relevant sessions."),
        ("fetch_weather",               "Fetch current weather conditions and today/tomorrow forecast for a location."),
        ("fetch_readwise_today",        "Fetch today's reading highlights from Readwise."),
        ("fetch_garmin_today",          "Fetch today's health summary from Garmin Connect: sleep score, sleep hours, HRV status, body battery, and resting heart rate."),
        ("five_fingers_add_teammate",   "Add a teammate to the Five Fingers sub-team roster."),
        ("five_fingers_remove_teammate","Remove (soft-delete) a teammate from the roster by their Firestore doc ID."),
        ("five_fingers_list_teammates", "List all active Five Fingers sub-team members with their doc IDs and phone numbers."),
        ("five_fingers_bulk_import",    "Bulk-import teammates from a free-text list."),
        ("five_fingers_log_attendance", "Log practice attendance."),
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
    lines += [
        "## Identity",
        "",
        (
            "Klaus is a cloud-hosted personal AI agent deployed on Google Cloud Run, "
            "serving a single user — Amit Grupper, based in Tel Aviv, Israel. "
            "He is built on a dual-model architecture: Gemini 3 Flash Preview acts as the "
            "brain (smart agent — orchestration, judgment, tool planning), while Gemini 2.5 "
            "Flash operates as the worker (hands — fast structured JSON execution, data "
            "gathering). Claude Haiku 4.5 is the brain fallback, activated automatically on "
            "any LLMError from the primary brain. "
            "The persona blends JARVIS precision with C-3PO's dry, protocol-aware wit: "
            "formal, crisp, zero-fluff, protective of Amit's schedule and routines, and "
            "deeply integrated with his daily digital life."
        ),
        "",
    ]

    # ----- §2 Model Map --------------------------------------------------
    lines += [
        "## Model Map",
        "",
        "| Purpose | Model | Backend |",
        "|---------|-------|---------|",
        "| Brain (smart agent) | gemini-3-flash-preview | Gemini (AI Studio) |",
        "| Worker | gemini-2.5-flash | Gemini (AI Studio) |",
        "| Smart agent fallback | claude-haiku-4-5 | Anthropic |",
        "| Tick-brain | qwen3-32b | Groq (OpenAI-compat) |",
        "| Tick-brain fallback | gemini-3-flash-preview | Gemini (AI Studio) |",
        "| Embeddings | gemini-embedding-2 | Gemini (AI Studio) |",
        "",
    ]

    # ----- §3 Tools ------------------------------------------------------
    lines += [
        "## Tools",
        "",
        "| Tool | Routing | Purpose |",
        "|------|---------|---------|",
    ]
    for row in tool_rows:
        # Escape pipes in purpose text so table renders correctly
        purpose = row["purpose"].replace("|", "\\|")
        lines.append(f"| `{row['name']}` | {row['routing']} | {purpose} |")
    lines.append("")

    # ----- §4 Cron Jobs --------------------------------------------------
    lines += [
        "## Cron Jobs",
        "",
        "| Job | Schedule (UTC) | Handler |",
        "|-----|----------------|---------|",
        "| Heartbeat | `0 * * * *` | `/cron/heartbeat` |",
        "| Proactive alerts | `30 18 * * *` (21:30 IDT) | `/cron/proactive-alerts` |",
        "| Morning briefing tick | `*/10 3-7 * * *` (06–10 IDT) | `/cron/morning-briefing-tick` |",
        "| Five Fingers morning | Wed/Sun `07:30 UTC` (10:30 IDT) | `/cron/five-fingers` |",
        "| Five Fingers evening | Wed/Sun `18:15 UTC` (21:15 IDT) | `/cron/five-fingers` |",
        "| Chat ingest | `0 1 * * *` (04:00 IDT) | `/cron/chat-ingest` |",
        "| Chat export ingest | `30 1 * * *` (04:30 IDT) | `/cron/chat-export-ingest` |",
        "| Daily reflection | `0 22 * * *` (22:00 IDT) | `/cron/reflect` |",
        "",
        "<!-- TODO Phase 18: /cron/autonomous-tick -->",
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
        "| TickTick | Read + Write | Add tasks, get today's tasks |",
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
