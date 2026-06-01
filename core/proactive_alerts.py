"""Proactive evening alerts — weather conflicts, overloaded days, and travel time checks.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/proactive-alerts  (21:30 daily, Asia/Jerusalem)

Local smoke test:
  python -m core.proactive_alerts --dry-run --date 2026-05-14
  python -m core.proactive_alerts --date 2026-05-14        # live send
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Bot

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

# Additional outdoor keywords beyond WORKOUT_KEYWORDS in calendar_tool.py
_OUTDOOR_EXTRA: tuple[str, ...] = ("outdoor", "park", "beach", "hike", "bike ride")


# ------------------------------------------------------------------ #
# Threshold helpers (env-var configurable)                           #
# ------------------------------------------------------------------ #

def _rain_threshold() -> int:
    return int(os.getenv("PROACTIVE_RAIN_THRESHOLD", "20"))


def _temp_max() -> int:
    return int(os.getenv("PROACTIVE_TEMP_MAX", "38"))


def _temp_min() -> int:
    return int(os.getenv("PROACTIVE_TEMP_MIN", "8"))


def _free_time_min() -> int:
    return int(os.getenv("PROACTIVE_FREE_TIME_MIN", "60"))


def _gap_min() -> int:
    return int(os.getenv("PROACTIVE_GAP_MIN", "30"))


# ------------------------------------------------------------------ #
# Small helpers                                                      #
# ------------------------------------------------------------------ #

def _get_calendar_tool():
    from core.tools import _get_calendar_tool as _ct
    return _ct()


def _home_address() -> str:
    """Return home address from HOME_ADDRESS env var or Secret Manager."""
    addr = os.getenv("HOME_ADDRESS", "")
    if addr:
        return addr
    try:
        from google.cloud import secretmanager
        project_id = os.environ["GCP_PROJECT_ID"]
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/klaus-home-address/versions/latest"
        resp = client.access_secret_version(request={"name": name})
        return resp.payload.data.decode("utf-8").strip()
    except Exception:
        logger.warning("Proactive alerts: could not fetch home address", exc_info=True)
        return ""


def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _mfc(project_id, database)


# ------------------------------------------------------------------ #
# Public entry point                                                 #
# ------------------------------------------------------------------ #

async def run_proactive_alerts(bot: Bot, target_date: str) -> None:
    """Orchestrate all alert detection for target_date and send if any found.

    Args:
        bot:         Telegram Bot instance (from _application.bot in web_server).
        target_date: YYYY-MM-DD of the day to scan (typically tomorrow).
    """
    # Phase 20 — D-09: training check-in folded into the 21:30 proactive-alerts cron.
    # Runs BEFORE the dedup gate below so a same-evening retry is not blocked (Pitfall 5).
    # Idempotent via TrainingLogStore merge=True (Pitfall 4). Scans TODAY's training,
    # whereas the alert scan below targets target_date (tomorrow).
    try:
        from core.training_checkin import run_training_checkin
        today = datetime.now(_TZ).date().isoformat()
        await run_training_checkin(bot, today)
    except Exception:
        logger.warning("proactive_alerts: training check-in failed", exc_info=True)
        # Non-fatal — alert composition continues regardless

    if _already_sent(target_date):
        logger.info("Proactive alerts: already processed for %s — skipping", target_date)
        return

    # Fetch tomorrow's events
    events = _get_calendar_tool().list_events(
        f"{target_date}T00:00:00+03:00",
        f"{target_date}T23:59:59+03:00",
        max_results=50,
    )
    logger.info("Proactive alerts: %d events fetched for %s", len(events), target_date)

    # Fetch weather
    weather: dict | None = None
    try:
        from mcp_tools.weather_tool import fetch_weather
        weather = fetch_weather("Tel Aviv")
    except Exception:
        logger.warning("Proactive alerts: weather fetch failed", exc_info=True)

    # Detect all alert types
    weather_alerts = _detect_weather_conflicts(events, weather) if weather else []
    overload_alert = _detect_overloaded_day(events)
    home = _home_address()
    travel_alerts = _detect_travel_issues(events, home) if home else []

    if not weather_alerts and not overload_alert and not travel_alerts:
        logger.info("Proactive alerts: no issues found for %s", target_date)
        _mark_processed(target_date, alert_sent=False)
        return

    alerts_context = {
        "target_date": target_date,
        "weather_alerts": weather_alerts,
        "overload_alert": overload_alert,
        "travel_alerts": travel_alerts,
    }
    message = _compose_alert(alerts_context)

    from core.scheduled_message import send_and_inject
    await send_and_inject(bot, message, inject_into_conversation=False)
    _mark_processed(target_date, alert_sent=True)
    logger.info("Proactive alerts: sent alert for %s", target_date)


# ------------------------------------------------------------------ #
# Firestore deduplication                                            #
# ------------------------------------------------------------------ #

def _already_sent(target_date: str) -> bool:
    """Return True if we already processed alerts for this date."""
    try:
        client = _make_firestore_client()
        doc = client.collection("proactive_alerts").document(target_date).get()
        return doc.exists
    except Exception:
        logger.warning("Proactive alerts: dedup check failed", exc_info=True)
        return False


def _mark_processed(target_date: str, *, alert_sent: bool) -> None:
    """Record in Firestore that we ran the alert scan for this date."""
    try:
        from google.cloud import firestore as _fs
        client = _make_firestore_client()
        client.collection("proactive_alerts").document(target_date).set({
            "alert_sent": alert_sent,
            "processed_at": _fs.SERVER_TIMESTAMP,
        })
    except Exception:
        logger.warning("Proactive alerts: failed to write dedup record", exc_info=True)


# ------------------------------------------------------------------ #
# Alert detectors                                                    #
# ------------------------------------------------------------------ #

def _detect_weather_conflicts(events: list[dict], weather: dict) -> list[dict]:
    """Find timed outdoor events that conflict with bad weather tomorrow.

    Returns:
        [{"event_summary", "event_time", "issue"}, ...]
    """
    from mcp_tools.calendar_tool import WORKOUT_KEYWORDS

    outdoor_keywords = WORKOUT_KEYWORDS + _OUTDOOR_EXTRA
    tomorrow = weather.get("tomorrow", {})
    rain_chance = tomorrow.get("rain_chance", 0)
    temp_max_c = tomorrow.get("max_c", 20)
    temp_min_c = tomorrow.get("min_c", 20)
    condition = (tomorrow.get("condition") or "").lower()

    issues: list[str] = []
    if rain_chance >= _rain_threshold():
        issues.append(f"rain {rain_chance}%")
    if temp_max_c >= _temp_max():
        issues.append(f"extreme heat {temp_max_c}°C")
    if temp_min_c <= _temp_min():
        issues.append(f"cold {temp_min_c}°C")
    for kw in ("storm", "fog", "heavy wind", "thunder", "hail"):
        if kw in condition:
            issues.append(f"severe conditions: {condition}")
            break

    if not issues:
        return []

    issue_str = ", ".join(issues)
    conflicts: list[dict] = []
    for event in events:
        summary = (event.get("summary") or "").lower()
        start = event.get("start", "")
        if not start or "T" not in start:
            continue
        if any(kw in summary for kw in outdoor_keywords):
            try:
                event_time = datetime.fromisoformat(start).strftime("%H:%M")
            except ValueError:
                event_time = start
            conflicts.append({
                "event_summary": event.get("summary", ""),
                "event_time": event_time,
                "issue": issue_str,
            })

    return conflicts


def _detect_overloaded_day(events: list[dict]) -> dict | None:
    """Check if tomorrow has insufficient breathing room between events.

    Returns:
        {"total_free_minutes", "longest_gap_minutes", "event_count", "events"}
        or None if the day is not overloaded.
    """
    timed: list[tuple[datetime, datetime, str]] = []
    for event in events:
        start = event.get("start", "")
        end = event.get("end", "")
        summary = event.get("summary", "") or ""
        if not start or "T" not in start:
            continue
        if summary.lower().startswith("get ready"):
            continue
        try:
            timed.append((datetime.fromisoformat(start), datetime.fromisoformat(end), summary))
        except ValueError:
            continue

    if len(timed) < 2:
        return None

    timed.sort(key=lambda x: x[0])
    first_start = timed[0][0]
    last_end = timed[-1][1]

    gaps: list[int] = []
    total_event_minutes = 0
    for i, (s, e, _) in enumerate(timed):
        total_event_minutes += max(0, int((e - s).total_seconds() / 60))
        if i + 1 < len(timed):
            gap = max(0, int((timed[i + 1][0] - e).total_seconds() / 60))
            gaps.append(gap)

    total_window = int((last_end - first_start).total_seconds() / 60)
    total_free = total_window - total_event_minutes
    longest_gap = max(gaps) if gaps else 0

    if longest_gap < _gap_min() and total_free < _free_time_min():
        return {
            "total_free_minutes": total_free,
            "longest_gap_minutes": longest_gap,
            "event_count": len(timed),
            "events": [s for _, _, s in timed],
        }

    return None


def _parse_travel_buffer(description: str) -> int | None:
    """Extract the travel buffer minutes Klaus wrote into an event description."""
    m = re.search(r"\[Includes (\d+)-min travel buffer", description or "")
    return int(m.group(1)) if m else None


def _detect_travel_issues(events: list[dict], home_address: str) -> list[dict]:
    """Check Routes API estimates against the travel buffers Klaus wrote.

    Returns:
        [{"event_summary", "location", "buffer_minutes",
          "maps_estimate_minutes", "shortfall_minutes"}, ...]
    """
    from mcp_tools.routes_tool import get_travel_time

    issues: list[dict] = []
    for event in events:
        location = (event.get("location") or "").strip()
        start = event.get("start", "")
        summary = event.get("summary", "") or ""
        description = event.get("description") or ""

        if not location or not start or "T" not in start:
            continue

        buffer = _parse_travel_buffer(description)
        if buffer is None:
            continue

        try:
            start_dt = datetime.fromisoformat(start)
            departure_iso = (start_dt - timedelta(minutes=buffer)).isoformat()
        except ValueError:
            continue

        result = get_travel_time(home_address, location, departure_iso)
        if result is None:
            continue

        estimate = result["duration_minutes"]
        shortfall = estimate - buffer
        if shortfall > 5:
            issues.append({
                "event_summary": summary,
                "location": location,
                "buffer_minutes": buffer,
                "maps_estimate_minutes": estimate,
                "shortfall_minutes": shortfall,
            })

    return issues


# ------------------------------------------------------------------ #
# LLM composition                                                    #
# ------------------------------------------------------------------ #

def _compose_alert(alerts_context: dict) -> str:
    """Compose the alert message via Smart Agent, with plain-text fallback."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "proactive_alert.md"
    today_str = date.today().isoformat()

    try:
        system_prompt = prompt_path.read_text(encoding="utf-8").replace(
            "{today_date}", today_str
        )
    except OSError:
        system_prompt = "You are Klaus, composing a proactive evening alert for Sir."

    user_message = json.dumps(alerts_context, ensure_ascii=False, indent=2)

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
        logger.warning("Proactive alerts: LLM composition failed", exc_info=True)

    return _plain_text_fallback(alerts_context)


def _plain_text_fallback(ctx: dict) -> str:
    """Generate a plain-text alert without LLM."""
    target_date = ctx.get("target_date", "tomorrow")
    lines = [f"Tomorrow ({target_date}) — heads up, Sir:"]

    for wa in ctx.get("weather_alerts") or []:
        lines.append(f"• {wa['event_summary']} at {wa['event_time']}: {wa['issue']}")

    ov = ctx.get("overload_alert")
    if ov:
        lines.append(
            f"• Packed day: {ov['event_count']} events, "
            f"{ov['total_free_minutes']} min free, "
            f"longest gap {ov['longest_gap_minutes']} min."
        )

    for ta in ctx.get("travel_alerts") or []:
        lines.append(
            f"• {ta['event_summary']}: travel buffer is {ta['buffer_minutes']} min "
            f"but estimate is {ta['maps_estimate_minutes']} min "
            f"({ta['shortfall_minutes']} min short)."
        )

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

    tomorrow = (datetime.now(_TZ).date() + timedelta(days=1)).isoformat()
    parser = argparse.ArgumentParser(description="Proactive alerts local smoke test")
    parser.add_argument(
        "--date",
        default=tomorrow,
        help="YYYY-MM-DD to scan (default: tomorrow in Jerusalem time)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect and compose without sending to Telegram or writing to Firestore",
    )
    args = parser.parse_args()

    if args.dry_run:
        from mcp_tools.weather_tool import WeatherUnavailableError, fetch_weather

        events = _get_calendar_tool().list_events(
            f"{args.date}T00:00:00+03:00",
            f"{args.date}T23:59:59+03:00",
            max_results=50,
        )
        print(f"[dry-run] {len(events)} events on {args.date}")

        weather: dict | None = None
        try:
            weather = fetch_weather("Tel Aviv")
            print(f"[dry-run] Weather tomorrow: {weather.get('tomorrow')}")
        except WeatherUnavailableError as exc:
            print(f"[dry-run] Weather unavailable: {exc}")

        weather_alerts = _detect_weather_conflicts(events, weather) if weather else []
        overload_alert = _detect_overloaded_day(events)
        home = _home_address()
        travel_alerts = _detect_travel_issues(events, home) if home else []

        ctx: dict = {
            "target_date": args.date,
            "weather_alerts": weather_alerts,
            "overload_alert": overload_alert,
            "travel_alerts": travel_alerts,
        }

        if not weather_alerts and not overload_alert and not travel_alerts:
            print("[dry-run] No issues found — no alert would be sent.")
            return

        print(f"\n[dry-run] Alerts detected: {json.dumps(ctx, ensure_ascii=False, indent=2)}")
        print("\n[dry-run] Composed message:")
        print(_compose_alert(ctx))
        return

    from telegram.ext import Application

    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(bot_token).build()

    async def _run() -> None:
        await app.initialize()
        await run_proactive_alerts(app.bot, args.date)
        await app.shutdown()

    asyncio.run(_run())
    print("Done.")


if __name__ == "__main__":
    _cli()
