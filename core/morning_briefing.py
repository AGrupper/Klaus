# core/morning_briefing.py
"""Morning briefing — Garmin-sync-anchored daily briefing via Telegram.

Cloud Scheduler polls every 10 min (06:00–10:15 Asia/Jerusalem):
  POST /cron/morning-briefing-tick

Local smoke test:
  python -m core.morning_briefing --dry-run --date 2026-05-12
  python -m core.morning_briefing --send --date 2026-05-12  (requires KLAUS_DEV=1)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Bot

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")
_COLLECTION = "morning_briefings"

# ------------------------------------------------------------------ #
# Firestore helpers                                                  #
# ------------------------------------------------------------------ #

def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    return _mfc(os.environ["GCP_PROJECT_ID"], os.getenv("FIRESTORE_DATABASE", "(default)"))


def _get_state(today_iso: str) -> dict:
    try:
        client = _make_firestore_client()
        snap = client.collection(_COLLECTION).document(today_iso).get()
        return snap.to_dict() or {} if snap.exists else {}
    except Exception:
        logger.warning("morning_briefing: failed to read state for %s", today_iso, exc_info=True)
        return {}


def _set_state(today_iso: str, fields: dict) -> None:
    try:
        client = _make_firestore_client()
        client.collection(_COLLECTION).document(today_iso).set(fields, merge=True)
    except Exception:
        logger.warning("morning_briefing: failed to write state for %s", today_iso, exc_info=True)


# ------------------------------------------------------------------ #
# Cron tick handler                                                  #
# ------------------------------------------------------------------ #

async def handle_tick(bot: Bot) -> None:
    """Called by /cron/morning-briefing-tick every 10 min.

    State machine:
      pending       → check Garmin; if sync found, set sync_detected
      sync_detected → fire the briefing (next tick after detection)
      sent/manual   → exit silently (already done today)
    """
    now = datetime.now(_TZ)
    today_iso = now.date().isoformat()

    # Hard cutoff: ticks past 10:15 are no-ops.
    if (now.hour, now.minute) > (10, 15):
        logger.debug("morning_briefing: past 10:15 cutoff — skipping tick")
        return

    state = _get_state(today_iso)
    status = state.get("status", "pending")

    if status in {"sent", "manual"}:
        logger.debug("morning_briefing: already done for %s (%s)", today_iso, status)
        return

    if status == "pending":
        sleep_data = _fetch_garmin_safe(today_iso)
        if not sleep_data:
            logger.debug("morning_briefing: Garmin sync not detected yet")
            return

        # Garmin sync detected. Should we fire now or wait one tick?
        next_tick = now + timedelta(minutes=10)
        if (next_tick.hour, next_tick.minute) > (10, 15):
            # Fast-path: firing now because next tick would be past cutoff.
            logger.info("morning_briefing: fast-path fire for %s", today_iso)
            await run_morning_briefing(bot, today_iso, dedup=False)
            _set_state(today_iso, {"status": "sent", "trigger": "cron_fast_path",
                                   "sent_at": now.isoformat()})
        else:
            logger.info("morning_briefing: Garmin sync detected for %s — will fire next tick", today_iso)
            _set_state(today_iso, {"status": "sync_detected",
                                   "sync_detected_at": now.isoformat()})
        return

    if status == "sync_detected":
        retry_count = state.get("retry_count", 0)
        if retry_count >= 3:
            logger.error("morning_briefing: max retries reached for %s — giving up", today_iso)
            _set_state(today_iso, {"status": "failed"})
            return
        try:
            logger.info("morning_briefing: firing briefing for %s (retry=%d)", today_iso, retry_count)
            await run_morning_briefing(bot, today_iso, dedup=False)
            _set_state(today_iso, {"status": "sent", "trigger": "cron",
                                   "sent_at": datetime.now(_TZ).isoformat()})
        except Exception:
            logger.warning("morning_briefing: send failed for %s — will retry next tick",
                           today_iso, exc_info=True)
            _set_state(today_iso, {"retry_count": retry_count + 1})


# ------------------------------------------------------------------ #
# Main entry point (cron + manual tool)                              #
# ------------------------------------------------------------------ #

async def run_morning_briefing(bot: Bot, today_iso: str, *, dedup: bool = True) -> None:
    """Compose and send the morning briefing for today_iso.

    Args:
        bot:       Telegram Bot instance.
        today_iso: YYYY-MM-DD date to compose the briefing for.
        dedup:     If True, skip if already sent. If False, always fire.
    """
    if dedup:
        state = _get_state(today_iso)
        if state.get("status") in {"sent", "manual"}:
            logger.info("morning_briefing: dedup — already sent for %s", today_iso)
            return

    today_data = _gather_data(today_iso)
    text = _compose_briefing(today_data, today_iso)

    from core.scheduled_message import send_and_inject
    await send_and_inject(bot, text, inject_into_conversation=True)

    # Store structured data alongside the state doc for follow-up replies.
    # Note: status is the caller's responsibility — do NOT set it here.
    _set_state(today_iso, {
        "structured": {
            "events": today_data.get("calendar") or [],
            "tasks_today": (today_data.get("tasks") or {}).get("today", []),
            "tasks_overdue": (today_data.get("tasks") or {}).get("overdue", []),
        },
    })
    logger.info("morning_briefing: sent and injected for %s", today_iso)


# ------------------------------------------------------------------ #
# Data gathering                                                     #
# ------------------------------------------------------------------ #

def _fetch_garmin_safe(today_iso: str | None = None) -> dict | None:
    """Return Garmin data if today's sync has happened (has sleep data), else None."""
    try:
        from mcp_tools.garmin_tool import fetch_garmin_today
        today = today_iso or datetime.now(_TZ).date().isoformat()
        data = fetch_garmin_today()
        if data and data.get("date") == today and (
            data.get("sleep_score") is not None or data.get("sleep_hours") is not None
        ):
            return data
        return None
    except Exception:
        logger.warning("morning_briefing: Garmin fetch failed in _fetch_garmin_safe", exc_info=True)
        return None


def _gather_data(today_iso: str) -> dict:
    """Fetch all data sources; each catches its own errors."""
    data: dict = {"today_date": today_iso}

    # Weather
    try:
        from mcp_tools.weather_tool import fetch_weather
        data["weather"] = fetch_weather("Tel Aviv")
    except Exception:
        logger.warning("morning_briefing: weather fetch failed", exc_info=True)
        data["weather"] = None

    # Calendar — _get_calendar_tool() is a module-level function in core/tools.py
    try:
        from core.tools import _get_calendar_tool
        tz_start = datetime.fromisoformat(today_iso).replace(tzinfo=_TZ)
        tz_end = datetime(tz_start.year, tz_start.month, tz_start.day, 23, 59, 59, tzinfo=_TZ)
        events = _get_calendar_tool().list_events(
            tz_start.isoformat(),
            tz_end.isoformat(),
            max_results=20,
        )
        data["calendar"] = events
    except Exception:
        logger.warning("morning_briefing: calendar fetch failed", exc_info=True)
        data["calendar"] = None

    # Email — _get_gmail_tool() is a module-level function in core/tools.py
    try:
        from core.tools import _get_gmail_tool
        emails = _get_gmail_tool().list_unread(max_results=10)
        data["email"] = emails
    except Exception:
        logger.warning("morning_briefing: email fetch failed", exc_info=True)
        data["email"] = None

    # Garmin
    try:
        from mcp_tools.garmin_tool import fetch_garmin_today
        garmin = fetch_garmin_today()
        if garmin and garmin.get("date") == today_iso:
            data["garmin"] = {"state": 1, **garmin}
        else:
            data["garmin"] = {"state": 2}
    except Exception:
        logger.warning("morning_briefing: Garmin data fetch failed", exc_info=True)
        data["garmin"] = {"state": 2}

    # PHASE 19 — GARMIN-05: best-effort write of today's biometrics to Postgres
    # so future ACWR queries see fresh data. write_today_biometrics_to_postgres
    # already swallows its own exceptions; outer try/except is defense-in-depth.
    try:
        from mcp_tools.garmin_tool import write_today_biometrics_to_postgres
        if data.get("garmin", {}).get("state") == 1:
            write_today_biometrics_to_postgres(data["garmin"])
    except Exception:
        logger.warning(
            "morning_briefing: Postgres biometrics writeback failed",
            exc_info=True,
        )

    # TickTick tasks
    try:
        from mcp_tools.ticktick_tool import get_today_tasks
        data["tasks"] = get_today_tasks()
    except Exception:
        logger.warning("morning_briefing: TickTick task fetch failed", exc_info=True)
        data["tasks"] = {"staleness_warning": "Task data unavailable, sir."}

    # PHASE 19 — NUTR-05: yesterday's nutrition recap. NUTR-07 silent-omit
    # precondition: only write data['nutrition'] when get_day_aggregate
    # returns a TRUTHY dict (Pitfall 4 — empty dict means no meals, not
    # {"meal_count": 0}).
    try:
        from memory.firestore_db import MealStore
        yesterday = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
        ms = MealStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        agg = ms.get_day_aggregate(yesterday)
        if agg:  # NUTR-07: silent omit on empty
            data["nutrition"] = agg
    except Exception:
        logger.warning("morning_briefing: meals aggregate failed", exc_info=True)

    return data


# ------------------------------------------------------------------ #
# LLM composition                                                    #
# ------------------------------------------------------------------ #

def _compose_briefing(today_data: dict, today_iso: str) -> str:
    """Compose the briefing via LLM with plain-text fallback."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "morning_briefing.md"
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8").replace(
            "{today_date}", today_iso
        )
    except OSError:
        logger.warning("morning_briefing: prompt file missing — using fallback")
        return _plain_text_fallback(today_data, today_iso)

    user_message = json.dumps(today_data, ensure_ascii=False, default=str)

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
        )
        text = (response.get("text") or "").strip()
        if text:
            return text
    except Exception:
        logger.warning("morning_briefing: LLM composition failed", exc_info=True)

    return _plain_text_fallback(today_data, today_iso)


def _plain_text_fallback(today_data: dict, today_iso: str) -> str:
    """Deterministic plain-text briefing when LLM is unavailable."""
    lines = ["Good morning, sir. Briefing service degraded today; here is the raw data.", ""]

    lines.append("📅 Schedule")
    events = today_data.get("calendar") or []
    if events:
        for e in events[:10]:
            start = e.get("start", "")
            end = e.get("end", "")
            summary = e.get("summary", "Event")
            # Prefix with LRM (U+200E) if the summary contains RTL characters
            # so Telegram renders time ranges left-to-right.
            lrm = "\u200e" if any("\u0590" <= ch <= "\u08ff" for ch in summary) else ""
            try:
                s = datetime.fromisoformat(start).strftime("%H:%M")
                en = datetime.fromisoformat(end).strftime("%H:%M")
                lines.append(f"{lrm}{s}–{en} — {summary}")
            except (ValueError, TypeError):
                lines.append(f"{lrm}— {summary}")
    else:
        lines.append("Nothing on the calendar today, sir.")

    lines.append("")
    lines.append("📧 Email")
    emails = today_data.get("email") or []
    if emails:
        for em in emails[:8]:
            sender = em.get("sender") or em.get("from", "Unknown")
            subject = em.get("subject", "—")
            lines.append(f"• {sender} — {subject}")
    else:
        lines.append("No actionable email this morning, sir.")

    lines.append("")
    lines.append("✅ Tasks")
    tasks = today_data.get("tasks") or {}
    warning = tasks.get("staleness_warning")
    if warning:
        lines.append(warning)
    else:
        overdue = tasks.get("overdue") or []
        today_tasks = tasks.get("today") or []
        due_today = tasks.get("due_today") or []
        if overdue:
            lines.append("Overdue")
            for t in overdue[:4]:
                lines.append(f"• [!] {t.get('title', '')} ({t.get('area', '')})")
        if today_tasks:
            lines.append("Today")
            for t in today_tasks[:4]:
                lines.append(f"• {t.get('title', '')}")
        if due_today:
            lines.append("Due today")
            for t in due_today[:2]:
                lines.append(f"• {t.get('title', '')} ({t.get('area', '')})")
        if not overdue and not today_tasks and not due_today:
            lines.append("No tasks today, sir.")

    lines.append("")
    lines.append("📚 https://readwise.io/dailyreview")
    return "\n".join(lines)


# ------------------------------------------------------------------ #
# CLI smoke test                                                     #
# ------------------------------------------------------------------ #

def _cli() -> None:
    import argparse
    import asyncio
    from dotenv import load_dotenv
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    today = datetime.now(_TZ).date().isoformat()
    parser = argparse.ArgumentParser(description="Morning briefing local smoke test")
    parser.add_argument("--date", default=today, help="YYYY-MM-DD to compose for")
    parser.add_argument("--dry-run", action="store_true", help="Print without sending")
    parser.add_argument("--send", action="store_true", help="Actually send (requires KLAUS_DEV=1)")
    args = parser.parse_args()

    if args.dry_run:
        data = _gather_data(args.date)
        print(f"[dry-run] Data gathered for {args.date}:")
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        print("\n[dry-run] Composed message:")
        print(_compose_briefing(data, args.date))
        return

    if args.send:
        if os.getenv("KLAUS_DEV") != "1":
            print("ERROR: --send requires KLAUS_DEV=1")
            return
        from telegram.ext import Application
        app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
        async def _run():
            await app.initialize()
            await run_morning_briefing(app.bot, args.date, dedup=False)
            await app.shutdown()
        asyncio.run(_run())
        print("Sent.")
        return

    parser.print_help()


if __name__ == "__main__":
    _cli()
