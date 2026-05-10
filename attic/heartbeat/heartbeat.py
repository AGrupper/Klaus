"""Heartbeat engine — proactive calendar and task detection.

Runs one detection tick: loads config, checks quiet hours, queries calendar
and the Things 3 Firestore queue for time-sensitive signals, and composes a
Telegram ping via Gemini Flash if anything warrants attention.

Called from interfaces.web_server POST /cron/heartbeat (every 30 min via
Cloud Scheduler). Returns the message text to send, or None if silent.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Events starting within this many minutes trigger an "upcoming" flag.
_UPCOMING_WINDOW_MINUTES = 75

# Pending tasks with deadline this many days in the past are "overdue".
# 0 = due today is also flagged.


def run_tick() -> str | None:
    """Run one heartbeat detection cycle.

    Returns:
        Message text to send via Telegram, or None if nothing warrants attention.
        Never raises — all errors are logged and treated as silent.
    """
    try:
        config = _load_config()
    except Exception:
        logger.exception("Heartbeat: failed to load config")
        return None

    if not config.get("enabled", True):
        logger.info("Heartbeat: disabled in config")
        return None

    if _in_quiet_hours(config):
        logger.info("Heartbeat: quiet hours — skipping")
        return None

    try:
        signals = _detect_signals()
    except Exception:
        logger.exception("Heartbeat: signal detection failed")
        return None

    if not signals:
        logger.info("Heartbeat: no signals — silent tick")
        return None

    logger.info("Heartbeat: %d signal(s) detected — composing ping", len(signals))

    try:
        return _compose_ping(signals)
    except Exception:
        logger.exception("Heartbeat: ping composition failed")
        return None


# ------------------------------------------------------------------ #
# Config                                                              #
# ------------------------------------------------------------------ #

def _load_config() -> dict:
    """Load heartbeat config from Firestore. Returns defaults on error."""
    from memory.firestore_db import HeartbeatConfigStore

    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    store = HeartbeatConfigStore(project_id=project_id, database=database)
    return store.get()


def _in_quiet_hours(config: dict) -> bool:
    """Return True if the current local time falls within the configured quiet window."""
    tz_name = config.get("timezone", "Asia/Jerusalem")
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        logger.warning("Heartbeat: unknown timezone %r — defaulting to UTC", tz_name)
        tz = ZoneInfo("UTC")

    now = datetime.now(tz)
    now_hm = now.hour * 60 + now.minute

    quiet_start = _parse_hm(config.get("quiet_start", "22:00"))
    quiet_end = _parse_hm(config.get("quiet_end", "07:00"))

    # Quiet window can span midnight (e.g. 22:00 → 07:00).
    if quiet_start <= quiet_end:
        return quiet_start <= now_hm < quiet_end
    else:
        return now_hm >= quiet_start or now_hm < quiet_end


def _parse_hm(hm_str: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    try:
        h, m = hm_str.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        logger.warning("Heartbeat: could not parse time %r", hm_str)
        return 0


# ------------------------------------------------------------------ #
# Signal detection                                                    #
# ------------------------------------------------------------------ #

def _detect_signals() -> list[dict]:
    signals: list[dict] = []
    signals.extend(_check_upcoming_events())
    signals.extend(_check_due_tasks())
    return signals


def _check_upcoming_events() -> list[dict]:
    """Return signals for calendar events starting within _UPCOMING_WINDOW_MINUTES."""
    from core.tools import _get_calendar_tool  # reuse shared singleton

    tz = ZoneInfo("Asia/Jerusalem")
    now = datetime.now(tz)
    window_end = now + timedelta(minutes=_UPCOMING_WINDOW_MINUTES)

    try:
        events = _get_calendar_tool().list_events(
            now.isoformat(),
            window_end.isoformat(),
        )
    except Exception:
        logger.warning("Heartbeat: calendar fetch failed", exc_info=True)
        return []

    signals = []
    for event in events:
        title = event.get("summary", "Untitled event")
        start_str = event.get("start", "")
        if not start_str:
            continue
        try:
            # list_events returns ISO strings; parse and compute minutes until start.
            start_dt = datetime.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=tz)
            minutes_away = int((start_dt - now).total_seconds() / 60)
            if minutes_away < 0:
                continue
            signals.append({
                "type": "upcoming_event",
                "title": title,
                "starts_in_minutes": minutes_away,
            })
        except Exception:
            logger.debug("Heartbeat: could not parse event start %r", start_str)

    return signals


def _check_due_tasks() -> list[dict]:
    """Return signals for pending Things-queue tasks with deadline <= today."""
    from core.tools import _get_firestore_queue  # reuse shared singleton

    from datetime import date
    today_str = date.today().isoformat()

    try:
        pending = _get_firestore_queue().fetch_pending(limit=50)
    except Exception:
        logger.warning("Heartbeat: things queue fetch failed", exc_info=True)
        return []

    signals = []
    for task in pending:
        deadline = task.get("deadline")
        if not deadline:
            continue
        if deadline <= today_str:
            signal_type = "overdue_task" if deadline < today_str else "due_today_task"
            signals.append({
                "type": signal_type,
                "title": task.get("title", "Untitled task"),
                "deadline": deadline,
            })

    return signals


# ------------------------------------------------------------------ #
# Ping composition                                                    #
# ------------------------------------------------------------------ #

def _compose_ping(signals: list[dict]) -> str:
    """Call Gemini Flash to compose a short Telegram message from the signals."""
    from core.llm_client import LLMClient

    api_key = os.environ["WORKER_AGENT_API_KEY"]
    model = os.getenv("WORKER_AGENT_MODEL", "gemini-2.5-flash")
    client = LLMClient(backend="gemini", model=model, api_key=api_key)

    system_prompt = Path(__file__).parent.parent / "prompts" / "heartbeat_composer.md"
    system_text = system_prompt.read_text(encoding="utf-8")

    signals_json = json.dumps(signals, ensure_ascii=False)
    response = client.chat(
        messages=[{"role": "user", "content": signals_json}],
        system=system_text,
    )

    text = (response.get("text") or "").strip()
    if not text:
        # Fallback: plain-text summary if the model returned nothing.
        parts = []
        for s in signals:
            if s["type"] == "upcoming_event":
                parts.append(f"{s['title']} in {s['starts_in_minutes']} min")
            else:
                parts.append(f"{s['title']} — {s['type'].replace('_', ' ')}")
        text = " · ".join(parts)

    return text
