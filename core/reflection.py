"""Daily reflection — gather the day, write a journal entry, evolve self_state.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/reflect  (22:00 daily, Asia/Jerusalem)

Local smoke test:
  python -m core.reflection --dry-run --date 2026-05-19
  python -m core.reflection --date 2026-05-19        # live run
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

# 5 required keys in D-03 brain JSON, with their expected types
_REQUIRED_STR_KEYS = ("summary", "mood", "current_focus", "recent_context")
_HIGHLIGHTS_KEY = "highlights"
_HIGHLIGHTS_CAP = 5


# ------------------------------------------------------------------ #
# Small helpers                                                      #
# ------------------------------------------------------------------ #

def _make_firestore_client():
    """Return a Firestore client built from env vars. Never raises on success."""
    from memory.firestore_db import _make_firestore_client as _mfc
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _mfc(project_id, database)


def _telegram_user_id() -> int:
    """Source the owner user_id from env (cron has no request context)."""
    raw = os.environ["TELEGRAM_ALLOWED_USER_IDS"].split(",")[0].strip()
    return int(raw)


# ------------------------------------------------------------------ #
# JSON parse hardening (D-03 / Pitfall 3)                            #
# ------------------------------------------------------------------ #

def _parse_reflection_json(text: str) -> dict | None:
    """Parse the brain's structured JSON output, hardened against Gemini formatting.

    Steps:
    1. Strip ```json / ``` fences.
    2. Slice from the first '{' to the last '}'.
    3. json.loads.
    4. Validate all 5 D-03 keys; default any missing/wrong-typed field.
    5. Cap highlights to 5 items.

    Returns:
        A dict with all 5 keys guaranteed present, or None on total parse failure
        (signals the caller to use the D-13 minimal fallback).
    """
    if not text:
        return None

    # Strip markdown code fences
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Remove first line (```json or ```) and last line (```)
        inner_lines = []
        skip_first = True
        for line in lines:
            if skip_first:
                skip_first = False
                continue
            if line.strip() == "```":
                break
            inner_lines.append(line)
        stripped = "\n".join(inner_lines).strip()

    # Slice from first '{' to last '}'
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning("_parse_reflection_json: no JSON object found in text")
        return None

    json_str = stripped[start : end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning("_parse_reflection_json: JSONDecodeError: %s", exc)
        return None

    if not isinstance(data, dict):
        logger.warning("_parse_reflection_json: parsed value is not a dict")
        return None

    # Validate and default the 5 D-03 keys
    result: dict = {}
    for key in _REQUIRED_STR_KEYS:
        val = data.get(key)
        result[key] = val if isinstance(val, str) else ""

    highlights = data.get(_HIGHLIGHTS_KEY)
    if not isinstance(highlights, list):
        highlights = []
    # Ensure all items are strings; cap to 5
    highlights = [str(h) for h in highlights if h is not None][:_HIGHLIGHTS_CAP]
    result[_HIGHLIGHTS_KEY] = highlights

    return result


# ------------------------------------------------------------------ #
# Best-effort day gather (D-01)                                      #
# ------------------------------------------------------------------ #

def _gather_day(target_date: str) -> dict:
    """Gather today's raw metrics from all sources, each in its own try/except.

    A failed source is logged as a warning and omitted — the run continues.
    Returns a dict with the raw metrics needed for the journal entry.

    Args:
        target_date: YYYY-MM-DD (Asia/Jerusalem) — the day being reflected on.
    """
    gathered: dict = {
        "message_count": 0,
        "cost_usd": 0.0,
        "conversation": [],
        "calendar_event_count": 0,
        "tasks_completed": 0,
        "heartbeat_ok": False,
    }

    # (a) LLM usage: message count + cost
    try:
        from memory.firestore_db import LLMUsageStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        usage = LLMUsageStore(project_id=project_id, database=database).summary("today")
        gathered["message_count"] = int(usage.get("smart_calls", 0))
        gathered["cost_usd"] = float(usage.get("total_cost_usd", 0.0))
    except Exception:
        logger.warning("reflection: LLM usage gather failed", exc_info=True)

    # (b) Conversation history (best-effort; 6h session window may return [])
    try:
        from memory.firestore_conversation import FirestoreConversationStore
        user_id = _telegram_user_id()
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        conv_store = FirestoreConversationStore(project_id=project_id, database=database)
        gathered["conversation"] = conv_store.get(user_id) or []
    except Exception:
        logger.warning("reflection: conversation history gather failed", exc_info=True)

    # (c) Calendar events for today
    try:
        from mcp_tools.calendar_tool import GoogleCalendarManager
        cal = GoogleCalendarManager()
        events = cal.list_events(
            f"{target_date}T00:00:00+03:00",
            f"{target_date}T23:59:59+03:00",
            max_results=50,
        )
        gathered["calendar_event_count"] = len(events)
    except Exception:
        logger.warning("reflection: calendar gather failed", exc_info=True)

    # (d) TickTick tasks due today (RESOLVED: count of today's due tasks — no "completed today" accessor)
    try:
        from mcp_tools.ticktick_tool import get_today_tasks
        tasks_data = get_today_tasks()
        gathered["tasks_completed"] = len(tasks_data.get("today", []))
    except Exception:
        logger.warning("reflection: TickTick gather failed", exc_info=True)

    # (e) Heartbeat cron status
    try:
        from core.heartbeat import _read_cron_ledger
        ledger = _read_cron_ledger()
        # heartbeat is "ok" if any recent heartbeat entry exists and is not an error
        gathered["heartbeat_ok"] = bool(ledger)
    except Exception:
        logger.warning("reflection: heartbeat ledger gather failed", exc_info=True)

    return gathered


# ------------------------------------------------------------------ #
# Worker conversation summarization (D-02)                           #
# ------------------------------------------------------------------ #

def _summarize_conversation(raw_conversation: list) -> str:
    """Summarize today's conversations on the worker model (D-02).

    If the conversation list is empty (stale 6h window), return a fixed
    degradation string — never fail.

    Args:
        raw_conversation: List of conversation message dicts (may be []).

    Returns:
        A one-paragraph summary string, or the no-conversations sentinel.
    """
    if not raw_conversation:
        return "No conversations recorded in the active session today."

    # Build a plain text transcript for the worker
    lines = []
    for msg in raw_conversation:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            lines.append(f"{role.capitalize()}: {content.strip()}")
    transcript = "\n".join(lines) if lines else ""

    if not transcript:
        return "No conversations recorded in the active session today."

    try:
        from core.llm_client import LLMClient
        client = LLMClient(
            backend=os.environ["WORKER_AGENT_BACKEND"],
            model=os.environ["WORKER_AGENT_MODEL"],
            api_key=os.environ["WORKER_AGENT_API_KEY"],
        )
        response = client.chat(
            messages=[{"role": "user", "content": transcript}],
            system="Summarize this day's conversation in one short paragraph.",
            purpose="reflect_summary",
        )
        text = (response.get("text") or "").strip()
        if text:
            return text
    except Exception:
        logger.warning("reflection: worker conversation summarization failed", exc_info=True)

    return "Conversation summary unavailable."


# ------------------------------------------------------------------ #
# D-13 minimal fallback                                              #
# ------------------------------------------------------------------ #

def _minimal_fallback_entry(gathered_day: dict) -> dict:
    """Build a minimal journal entry when LLM calls fail (D-13).

    Stores raw metrics + placeholder LLM fields so the journal stays gap-free.
    """
    return {
        "summary": "reflection unavailable",
        "mood": "",
        "current_focus": "",
        "recent_context": "",
        "highlights": [],
        "message_count": gathered_day.get("message_count", 0),
        "cost_usd": gathered_day.get("cost_usd", 0.0),
        "calendar_event_count": gathered_day.get("calendar_event_count", 0),
        "tasks_completed": gathered_day.get("tasks_completed", 0),
        "heartbeat_ok": gathered_day.get("heartbeat_ok", False),
    }


# ------------------------------------------------------------------ #
# Brain reflection call (D-02 / D-13)                                #
# ------------------------------------------------------------------ #

def _brain_reflect(user_message: str, today_str: str) -> dict | None:
    """Call the brain model to produce structured JSON reflection.

    Falls back to the SMART_AGENT_FALLBACK_* model on brain failure (D-13).

    Args:
        user_message: JSON blob of the gathered day metrics.
        today_str:    YYYY-MM-DD used for {today_date} substitution.

    Returns:
        Parsed reflection dict (5 D-03 keys) on success, or None on total failure.
    """
    prompt_path = Path(__file__).parent.parent / "prompts" / "reflection.md"
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8").replace(
            "{today_date}", today_str
        )
    except OSError:
        logger.warning("reflection: could not read prompts/reflection.md; using fallback system prompt")
        system_prompt = (
            "You are Klaus, writing your daily reflection journal. "
            "Return ONLY a JSON object with keys: summary, mood, current_focus, "
            "recent_context, highlights."
        )

    from core.llm_client import LLMClient

    # Brain call
    try:
        client = LLMClient(
            backend=os.environ["SMART_AGENT_BACKEND"],
            model=os.environ["SMART_AGENT_MODEL"],
            api_key=os.environ["SMART_AGENT_API_KEY"],
        )
        response = client.chat(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            purpose="reflect",
        )
        text = (response.get("text") or "").strip()
        if text:
            parsed = _parse_reflection_json(text)
            if parsed is not None:
                return parsed
            logger.warning("reflection: brain returned unparseable JSON; trying fallback")
    except Exception:
        logger.warning("reflection: brain LLM call failed; trying fallback", exc_info=True)

    # Fallback brain call (D-13)
    try:
        client_fb = LLMClient(
            backend=os.environ["SMART_AGENT_FALLBACK_BACKEND"],
            model=os.environ["SMART_AGENT_FALLBACK_MODEL"],
            api_key=os.environ["SMART_AGENT_FALLBACK_API_KEY"],
        )
        response_fb = client_fb.chat(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            purpose="reflect",
        )
        text_fb = (response_fb.get("text") or "").strip()
        if text_fb:
            parsed_fb = _parse_reflection_json(text_fb)
            if parsed_fb is not None:
                return parsed_fb
            logger.warning("reflection: fallback LLM returned unparseable JSON")
    except Exception:
        logger.warning("reflection: fallback LLM call failed", exc_info=True)

    # Both failed
    return None


# ------------------------------------------------------------------ #
# Public entry point                                                 #
# ------------------------------------------------------------------ #

def run_reflection(target_date: str) -> None:
    """Gather the day, produce a journal entry, write 3 targets, evolve self_state.

    Synchronous (not async) — run in a thread-pool executor from the cron route.

    Write targets (each isolated so one failure does not prevent the others):
      1. JournalStore.set(target_date, entry)          — Firestore journal/{date}
      2. MemoryStore.remember_self(user_id, date, txt) — Pinecone self-{date} vector
      3. SelfStateStore.set(patch)                     — focus/mood/rolling context

    Args:
        target_date: YYYY-MM-DD in Asia/Jerusalem. Used as the journal doc key.
    """
    logger.info("run_reflection: starting for %s", target_date)

    # --- Gather (D-01: each source isolated) ---
    gathered = _gather_day(target_date)

    # --- Worker conversation summary (D-02) ---
    raw_conv = gathered.get("conversation", [])
    conversation_summary = _summarize_conversation(raw_conv)
    gathered["conversation_summary"] = conversation_summary

    # --- D-18: load yesterday's journal for continuity ---
    yesterday_str = (date.fromisoformat(target_date) - timedelta(days=1)).isoformat()
    prev_entry: dict | None = None
    try:
        from memory.firestore_db import JournalStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        js = JournalStore(project_id=project_id, database=database)
        prev_entry = js.get(yesterday_str)
    except Exception:
        logger.warning("reflection: could not load yesterday's journal entry", exc_info=True)

    # Build the user message for the brain (gathered metrics + optional yesterday)
    brain_input: dict = {
        "date": target_date,
        "message_count": gathered["message_count"],
        "cost_usd": gathered["cost_usd"],
        "conversation_summary": conversation_summary,
        "calendar_event_count": gathered["calendar_event_count"],
        "tasks_completed": gathered["tasks_completed"],
        "heartbeat_ok": gathered["heartbeat_ok"],
    }
    if prev_entry is not None:
        brain_input["yesterday"] = {
            "summary": prev_entry.get("summary", ""),
            "current_focus": prev_entry.get("current_focus", ""),
        }

    user_message = json.dumps(brain_input, ensure_ascii=False, indent=2)

    # --- Brain reflection call (D-02 / D-13) ---
    llm_result = _brain_reflect(user_message, target_date)

    # --- Build full journal entry ---
    raw_metrics: dict = {
        "message_count": gathered["message_count"],
        "cost_usd": gathered["cost_usd"],
        "calendar_event_count": gathered["calendar_event_count"],
        "tasks_completed": gathered["tasks_completed"],
        "heartbeat_ok": gathered["heartbeat_ok"],
    }

    if llm_result is not None:
        entry = {**llm_result, **raw_metrics}
    else:
        logger.warning("reflection: both LLM calls failed — writing minimal fallback doc (D-13)")
        entry = _minimal_fallback_entry(gathered)

    # --- Write target 1: JournalStore (source of truth) ---
    try:
        from memory.firestore_db import JournalStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        journal_store = JournalStore(project_id=project_id, database=database)
        journal_store.set(target_date, entry)
        logger.info("run_reflection: journal entry written for %s", target_date)
    except Exception:
        logger.error("run_reflection: JournalStore.set failed", exc_info=True)
        raise  # Journal write failure is fatal — the cron ledger must record it

    # --- Write target 2: Pinecone remember_self (D-07) ---
    try:
        from memory.pinecone_db import MemoryStore
        pinecone_api_key = os.environ["PINECONE_API_KEY"]
        pinecone_index = os.environ.get("PINECONE_INDEX", "klausai")
        mem_store = MemoryStore(api_key=pinecone_api_key, index_name=pinecone_index)
        content_parts = [entry.get("summary", "")]
        for h in entry.get("highlights", []):
            content_parts.append(h)
        content = " ".join(p for p in content_parts if p)
        mem_store.remember_self(
            user_id=_telegram_user_id(),
            date_str=target_date,
            content=content,
        )
        logger.info("run_reflection: Pinecone self-%s upserted", target_date)
    except Exception:
        logger.warning("run_reflection: Pinecone remember_self failed (non-fatal)", exc_info=True)

    # --- Write target 3: SelfStateStore (D-05) ---
    try:
        from memory.firestore_db import SelfStateStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        self_store = SelfStateStore(project_id=project_id, database=database)

        # Rolling 3-day recent_context window
        current_state = self_store.get() or {}
        existing_rc = current_state.get("recent_context", "")
        # Store as JSON list; if existing is a plain string (legacy), wrap it
        try:
            rc_list: list[str] = json.loads(existing_rc) if existing_rc else []
            if not isinstance(rc_list, list):
                rc_list = [existing_rc] if existing_rc else []
        except (json.JSONDecodeError, TypeError):
            rc_list = [existing_rc] if existing_rc else []

        # Append today's entry tagged with date, trim to 3
        today_rc = f"[{target_date}] {entry.get('recent_context', '')}".strip()
        rc_list.append(today_rc)
        rc_list = rc_list[-3:]  # keep most recent 3

        self_store.set({
            "current_focus": entry.get("current_focus", ""),
            "mood": entry.get("mood", ""),
            "recent_context": json.dumps(rc_list),
        })
        logger.info("run_reflection: SelfStateStore updated for %s", target_date)
    except Exception:
        logger.warning("run_reflection: SelfStateStore update failed (non-fatal)", exc_info=True)

    logger.info("run_reflection: complete for %s", target_date)


# ------------------------------------------------------------------ #
# CLI smoke test                                                     #
# ------------------------------------------------------------------ #

def _cli() -> None:
    """CLI smoke test: python -m core.reflection --dry-run --date 2026-05-19"""
    import argparse
    from dotenv import load_dotenv

    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    today = datetime.now(_TZ).date().isoformat()
    parser = argparse.ArgumentParser(description="Reflection cron local smoke test")
    parser.add_argument(
        "--date",
        default=today,
        help="YYYY-MM-DD to reflect on (default: today in Jerusalem time)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Gather and print gathered data without calling the LLM or writing to stores",
    )
    args = parser.parse_args()

    if args.dry_run:
        gathered = _gather_day(args.date)
        print(f"[dry-run] Gathered day data for {args.date}:")
        print(json.dumps(
            {k: v for k, v in gathered.items() if k != "conversation"},
            ensure_ascii=False, indent=2
        ))
        conv = gathered.get("conversation", [])
        print(f"[dry-run] Conversation messages: {len(conv)}")
        summary = _summarize_conversation(conv)
        print(f"[dry-run] Conversation summary: {summary}")
        return

    run_reflection(args.date)
    print(f"Done — journal entry written for {args.date}.")


if __name__ == "__main__":
    _cli()
