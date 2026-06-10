# core/nightly_review.py
"""Nightly review + tomorrow prep — sent when Amit winds down for the night.

Triggered two ways (both idempotent — first one to fire wins for the day):
  POST /trigger/nightly        — iOS Sleep-Focus automation (organic, when he winds down)
  POST /cron/nightly-backstop  — ~01:00 Asia/Jerusalem safety net if the trigger never fired

The nightly message recaps how the day went and preps tomorrow (schedule, tasks,
weather, recovery), folding in the signals the old 21:30 proactive-alert used to send
so there is one clean night message instead of two.

Klaus's private memory (journal + self_state) is written by the daily reflection.
This module guarantees it ran for the day before composing, so memory never skips —
that guarantee is independent of whether the Sleep-Focus trigger fired.

Local smoke test:
  python -m core.nightly_review --dry-run --date 2026-06-10
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Bot

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")
_COLLECTION = "nightly_reviews"

# A wind-down between, say, 18:00 and 05:00 belongs to the calendar day it started on.
# Shifting "now" back 5h maps a 00:30 trigger (or a 01:00 backstop) onto the prior day,
# while a 22:00 trigger stays on the same day.
_WINDDOWN_SHIFT_HOURS = 5


# ------------------------------------------------------------------ #
# Date helper                                                        #
# ------------------------------------------------------------------ #

def nightly_target_date(now: datetime) -> str:
    """Return the YYYY-MM-DD the wind-down belongs to (handles after-midnight fires)."""
    return (now - timedelta(hours=_WINDDOWN_SHIFT_HOURS)).date().isoformat()


# ------------------------------------------------------------------ #
# Firestore state (idempotency + morning-delta snapshot)             #
# ------------------------------------------------------------------ #

def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    return _mfc(os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)"))


def _get_state(target_date: str) -> dict:
    try:
        client = _make_firestore_client()
        snap = client.collection(_COLLECTION).document(target_date).get()
        return (snap.to_dict() or {}) if snap.exists else {}
    except Exception:
        logger.warning("nightly_review: failed to read state for %s", target_date, exc_info=True)
        return {}


def _set_state(target_date: str, fields: dict) -> None:
    try:
        client = _make_firestore_client()
        client.collection(_COLLECTION).document(target_date).set(fields, merge=True)
    except Exception:
        logger.warning("nightly_review: failed to write state for %s", target_date, exc_info=True)


def was_sent(target_date: str) -> bool:
    """True if the nightly review already sent for this date (idempotency gate)."""
    return _get_state(target_date).get("status") == "sent"


# ------------------------------------------------------------------ #
# Memory guarantee — reflection must run for the day                 #
# ------------------------------------------------------------------ #

def _ensure_reflection(target_date: str) -> dict | None:
    """Make sure today's journal/self_state exist, then return today's journal entry.

    The journal is the source of the "how today went" recap. If the daily reflection
    already wrote it (e.g. a 22:00 reflect cron), reuse it — no second brain call.
    Otherwise run the reflection now so memory never skips a day.
    """
    try:
        from memory.firestore_db import JournalStore
        js = JournalStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        entry = js.get(target_date)
        if entry is not None:
            return entry
    except Exception:
        logger.warning("nightly_review: journal presence check failed", exc_info=True)

    # Journal missing (or unreadable) — run the reflection to write it.
    try:
        from core.reflection import run_reflection
        run_reflection(target_date)
    except Exception:
        logger.warning("nightly_review: reflection run failed (non-fatal)", exc_info=True)

    # Re-read whatever the reflection managed to write.
    try:
        from memory.firestore_db import JournalStore
        js = JournalStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        return js.get(target_date)
    except Exception:
        logger.warning("nightly_review: journal re-read failed", exc_info=True)
        return None


# ------------------------------------------------------------------ #
# Tomorrow gather (schedule, tasks, weather, recovery)               #
# ------------------------------------------------------------------ #

def _gather_tomorrow(tomorrow_iso: str) -> dict:
    """Gather tomorrow-facing context; each source isolated, silent-omit on failure."""
    data: dict = {"tomorrow_date": tomorrow_iso}

    # Tomorrow's calendar
    try:
        from core.tools import _get_calendar_tool
        start = datetime.fromisoformat(tomorrow_iso).replace(tzinfo=_TZ)
        end = datetime(start.year, start.month, start.day, 23, 59, 59, tzinfo=_TZ)
        data["calendar"] = _get_calendar_tool().list_events(
            start.isoformat(), end.isoformat(), max_results=20
        )
    except Exception:
        logger.warning("nightly_review: tomorrow calendar fetch failed", exc_info=True)

    # Tasks (overdue + today's open carry into tomorrow)
    try:
        from mcp_tools.ticktick_tool import get_today_tasks
        data["tasks"] = get_today_tasks()
    except Exception:
        logger.warning("nightly_review: task fetch failed", exc_info=True)

    # Weather (folds in the old 21:30 proactive weather signal)
    try:
        from mcp_tools.weather_tool import fetch_weather
        data["weather"] = fetch_weather("Tel Aviv")
    except Exception:
        logger.warning("nightly_review: weather fetch failed", exc_info=True)

    # Recovery concern for tomorrow's intensity (folds in overload/recovery signal)
    try:
        from core.training_checkin import compute_recovery_concern
        from mcp_tools.garmin_tool import fetch_garmin_today
        garmin = fetch_garmin_today()
        rc = compute_recovery_concern(garmin_data=garmin, today_iso=tomorrow_iso)
        if rc:
            data["recovery_concern"] = rc
    except Exception:
        logger.warning("nightly_review: recovery concern computation failed", exc_info=True)

    return data


# ------------------------------------------------------------------ #
# Composition                                                        #
# ------------------------------------------------------------------ #

def _compose_nightly(journal: dict | None, tomorrow: dict, target_date: str) -> str:
    """Compose the nightly message via the brain, with a plain-text fallback."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "nightly_review.md"
    try:
        from core.autonomous import _get_orchestrator
        coaching_guide = _get_orchestrator()._coaching_guide_content
    except Exception:
        coaching_guide = ""

    try:
        system_prompt = (
            prompt_path.read_text(encoding="utf-8")
            .replace("{coaching_guide}", coaching_guide)
            .replace("{today_date}", target_date)
        )
    except OSError:
        logger.warning("nightly_review: prompt file missing — using fallback")
        return _plain_text_fallback(journal, tomorrow)

    payload = {
        "today_recap": {
            "summary": (journal or {}).get("summary", ""),
            "highlights": (journal or {}).get("highlights", []),
        },
        "tomorrow": tomorrow,
    }
    user_message = json.dumps(payload, ensure_ascii=False, default=str)

    try:
        from core.llm_client import LLMClient
        client = LLMClient(
            backend=os.environ["SMART_AGENT_BACKEND"],
            model=os.environ["SMART_AGENT_MODEL"],
            api_key=os.environ["SMART_AGENT_API_KEY"],
        )
        response = client.chat(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            purpose="nightly_review",
        )
        text = (response.get("text") or "").strip()
        if text:
            return text
    except Exception:
        logger.warning("nightly_review: LLM composition failed", exc_info=True)

    return _plain_text_fallback(journal, tomorrow)


def _plain_text_fallback(journal: dict | None, tomorrow: dict) -> str:
    """Deterministic nightly note when the LLM is unavailable."""
    lines = ["Quick rundown before you wind down."]
    summary = (journal or {}).get("summary", "")
    if summary and summary != "reflection unavailable":
        lines += ["", summary]

    events = tomorrow.get("calendar") or []
    lines += ["", "Tomorrow:"]
    if events:
        for e in events[:8]:
            start = e.get("start", "")
            label = e.get("summary", "Event")
            try:
                s = datetime.fromisoformat(start).strftime("%H:%M")
                lines.append(f"{s} — {label}")
            except (ValueError, TypeError):
                lines.append(f"— {label}")
    else:
        lines.append("Nothing on the calendar.")

    tasks = tomorrow.get("tasks") or {}
    overdue = tasks.get("overdue") or []
    if overdue:
        lines += ["", f"{len(overdue)} overdue task(s) still hanging."]

    return "\n".join(lines)


# ------------------------------------------------------------------ #
# Build (blocking) + run (async send)                                #
# ------------------------------------------------------------------ #

def _build_nightly(target_date: str) -> dict:
    """Blocking build: guarantee memory, gather tomorrow, compose. Run in executor."""
    journal = _ensure_reflection(target_date)
    tomorrow_iso = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
    tomorrow = _gather_tomorrow(tomorrow_iso)
    text = _compose_nightly(journal, tomorrow, target_date)
    structured = {
        "tomorrow_date": tomorrow_iso,
        "tomorrow_events": tomorrow.get("calendar") or [],
        "tomorrow_tasks_overdue": (tomorrow.get("tasks") or {}).get("overdue", []),
        "tomorrow_tasks_today": (tomorrow.get("tasks") or {}).get("today", []),
    }
    return {"text": text, "structured": structured}


async def run_nightly(bot: Bot, target_date: str, *, trigger: str, dedup: bool = True) -> bool:
    """Compose and send the nightly review for target_date.

    Idempotent: if already sent today, returns False without sending (the backstop
    relies on this so it never double-sends after the Sleep-Focus trigger fired).

    Args:
        bot:         Telegram Bot instance.
        target_date: YYYY-MM-DD the wind-down belongs to (see nightly_target_date).
        trigger:     "focus" | "backstop" — recorded for observability.
        dedup:       If True, skip when already sent. If False, always fire.

    Returns:
        True if a message was sent, False if skipped (already sent).
    """
    if dedup and was_sent(target_date):
        logger.info("nightly_review: already sent for %s — skipping (%s)", target_date, trigger)
        return False

    loop = asyncio.get_running_loop()
    built = await loop.run_in_executor(None, _build_nightly, target_date)

    from core.scheduled_message import send_and_inject
    await send_and_inject(bot, built["text"], inject_into_conversation=True)

    # Mark sent + persist tomorrow snapshot AFTER the send succeeds (write-after-send).
    _set_state(target_date, {
        "status": "sent",
        "trigger": trigger,
        "sent_at": datetime.now(_TZ).isoformat(),
        "structured": built["structured"],
    })
    logger.info("nightly_review: sent and injected for %s (%s)", target_date, trigger)
    return True


# ------------------------------------------------------------------ #
# CLI smoke test                                                     #
# ------------------------------------------------------------------ #

def _cli() -> None:
    import argparse
    from dotenv import load_dotenv
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    today = nightly_target_date(datetime.now(_TZ))
    parser = argparse.ArgumentParser(description="Nightly review local smoke test")
    parser.add_argument("--date", default=today, help="YYYY-MM-DD wind-down date")
    parser.add_argument("--dry-run", action="store_true", help="Build and print without sending")
    args = parser.parse_args()

    if args.dry_run:
        built = _build_nightly(args.date)
        print(f"[dry-run] Nightly for {args.date}:\n")
        print(built["text"])
        print("\n[dry-run] structured snapshot:")
        print(json.dumps(built["structured"], ensure_ascii=False, indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    _cli()
