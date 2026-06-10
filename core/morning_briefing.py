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

    # PHASE 24 — COACH-05 / T-24-17: record any coaching topics included in this
    # briefing to CoachingTopicStore AFTER send succeeds — never before.
    # Write-after-send discipline mirrors OutreachLogStore.append (Phase 18 D-10).
    # Best-effort: a topic write failure is non-fatal (dedup won't fire for that
    # topic on the next cron, but that is preferable to crashing the send path).
    try:
        _topics_included = today_data.get("coaching_topics_included") or []
        if _topics_included:
            from memory.firestore_db import CoachingTopicStore
            _cts = CoachingTopicStore(
                project_id=os.environ["GCP_PROJECT_ID"],
                database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
            )
            for _topic in _topics_included:
                _cts.add_topic(today_iso, _topic)
    except Exception:
        logger.warning("morning_briefing: coaching topic record failed", exc_info=True)

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


def _sync_bodyweight_from_garmin(store, today_iso: str) -> float | None:
    """Refresh the canonical profile ``bodyweight_kg`` from Garmin, at most once/day.

    ``bodyweight_kg`` (top-level profile field) is the single source of truth the
    chat fueling coach and this briefing both read. Sir keeps it current simply by
    entering his weight in Garmin (a weigh-in, or his Garmin profile weight); this
    pulls the latest via :func:`mcp_tools.garmin_tool.fetch_garmin_weight` and
    writes it here. Guarded on a ``bodyweight_synced_on`` date marker so repeated
    morning-briefing fires hit Garmin only once per day.

    Returns the current ``bodyweight_kg`` (freshly synced, or last-known if Garmin
    has no new value), or None if it has never been set. Never raises — any
    Garmin/Firestore failure falls back to the stored value.
    """
    try:
        profile = store.load()
    except Exception:
        logger.warning("bodyweight sync: profile load failed", exc_info=True)
        return None

    current = profile.get("bodyweight_kg")
    # Already synced today → reuse the stored value, skip the Garmin call.
    if profile.get("bodyweight_synced_on") == today_iso:
        return current

    weight = None
    try:
        from mcp_tools.garmin_tool import fetch_garmin_weight
        weight = fetch_garmin_weight()
    except Exception:
        logger.warning("bodyweight sync: Garmin weight fetch failed", exc_info=True)

    # Stamp the attempt (even on no-value) so we don't re-hit Garmin every fire;
    # only overwrite bodyweight_kg when Garmin actually returned a sane value.
    patch: dict = {"bodyweight_synced_on": today_iso}
    if weight is not None:
        patch["bodyweight_kg"] = weight
    try:
        store.update(patch)
    except Exception:
        logger.warning("bodyweight sync: profile update failed", exc_info=True)

    return weight if weight is not None else current


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

    # NOTE: email is intentionally NOT gathered — Amit doesn't use it, so the morning
    # note never surfaces it (the heavy email-list briefing was retired).

    # "What's new since last night" delta — read the snapshot the nightly review stored
    # for tomorrow (= today, from this morning's perspective). The compose prompt diffs
    # today's freshly-gathered calendar/tasks against it to flag only what changed
    # overnight. Best-effort: silent-omit if no nightly ran.
    try:
        from core.nightly_review import _get_state as _nightly_state
        yesterday_iso = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
        nightly = _nightly_state(yesterday_iso)
        structured = nightly.get("structured") if nightly else None
        if structured:
            data["since_last_night"] = structured
    except Exception:
        logger.warning("morning_briefing: nightly snapshot read failed", exc_info=True)

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

    # Phase 20 — RECOVERY-01: compute recovery concern from ACWR + HRV + sleep + today's intensity
    try:
        from core.training_checkin import compute_recovery_concern
        rc = compute_recovery_concern(
            garmin_data=data.get("garmin"),
            today_iso=today_iso,
        )
        if rc:
            data["recovery_concern"] = rc
    except Exception:
        logger.warning("morning_briefing: recovery_concern computation failed", exc_info=True)
        # silent omit — no "all clear" placeholder (D-13 guardrail)

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

    # Performance-fueling anchors + bodyweight for the forward-looking "Fuel plan
    # for today". The briefing is a single tool-less LLM call, so the fueling-coach
    # guidance (meal_audit.md, appended in _compose_briefing) cannot call
    # get_training_profile itself — the anchors must be in today_data. Silent-omit
    # on empty (Pitfall 4): no anchors → no key → the prompt drops the fuel-plan
    # section. This is also the once-daily seam that refreshes bodyweight_kg from
    # Garmin (the single source of truth), guarded so Garmin is hit at most once/day.
    try:
        from memory.firestore_db import UserProfileStore
        store = UserProfileStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        bodyweight = _sync_bodyweight_from_garmin(store, today_iso)
        profile = store.load()
        targets = profile.get("nutrition_targets")
        if targets:
            data["nutrition_targets"] = targets
        if bodyweight is not None:
            data["bodyweight_kg"] = bodyweight
    except Exception:
        logger.warning("morning_briefing: profile/bodyweight fetch failed", exc_info=True)

    # PHASE 23 — BLOCK-01 / D-04: surface the active mesocycle block (date-range
    # resolved, D-01) with a derived "Week N of 16" framing, or a pre-cycle countdown
    # before the 2026-06-21 anchor. Best-effort + silent-omit (Pitfall 4): a None
    # block post-cycle sets NEITHER key; week_num is derived from plan_start_date at
    # gather time, never read from a stored field (D-03).
    try:
        from memory.firestore_db import BlockStore
        bs = BlockStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        block = bs.get_current()
        if block:
            week_num = (date.fromisoformat(today_iso) - date.fromisoformat("2026-06-21")).days // 7 + 1
            data["block"] = {
                "label": block.get("label"),
                "week_num": week_num,
                "benchmark_due": block.get("benchmark_due", False),
                "end_date": block.get("end_date"),
                "block_id": block.get("block_id") or block.get("doc_id"),
            }
        else:
            days_until = (date.fromisoformat("2026-06-21") - date.fromisoformat(today_iso)).days
            if days_until > 0:
                data["pre_cycle_countdown"] = days_until
    except Exception:
        logger.warning("morning_briefing: block state fetch failed", exc_info=True)

    # PHASE 24 — COACH-05 / D-08: gather today's and yesterday's raised coaching
    # topics for cross-cron dedup and prior-day unresolved-miss recap. Both keys
    # fail-open to [] on any error — the cron must never crash on a topic fetch
    # failure (T-24-18 mitigated). yesterday's topics drive the D-08 prior-day recap.
    try:
        from memory.firestore_db import CoachingTopicStore
        _cts = CoachingTopicStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        yesterday_iso = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
        data["coaching_topics_today"] = _cts.topics_today(today_iso)
        data["coaching_topics_yesterday"] = _cts.topics_today(yesterday_iso)
        # D-08: yesterday's topics surfaced so morning briefing can recap unresolved prior-day misses
        # COACH-05 (conservative-writer producer): the unresolved prior-day misses the briefing
        # recaps (D-08) are recorded into TODAY's doc post-send, so the 21:30 cron hard-skips the
        # same accountability topic the same day (briefing→evening dedup direction). These keys
        # share the 21:30 namespace (protein-miss / fueling-miss:* / recovery-conflict:*), so the
        # write is the one that actually closes the cross-cron gap. Idempotent vs already-raised.
        data["coaching_topics_included"] = list(data["coaching_topics_yesterday"])
    except Exception:
        logger.warning("morning_briefing: coaching topics fetch failed", exc_info=True)
        data["coaching_topics_today"] = []
        data["coaching_topics_yesterday"] = []
        data["coaching_topics_included"] = []

    return data


# ------------------------------------------------------------------ #
# LLM composition                                                    #
# ------------------------------------------------------------------ #

def _compose_briefing(today_data: dict, today_iso: str) -> str:
    """Compose the briefing via LLM with plain-text fallback."""
    prompt_path = Path(__file__).parent.parent / "prompts" / "morning_briefing.md"
    # PHASE 22 — COACH-01: inject slim coaching core before {today_date}
    # (stable-prefix before volatile — same ordering as render_smart_system).
    # _get_orchestrator() is a process-wide singleton so no extra startup cost.
    # Degrade gracefully: a first-call AgentOrchestrator() construction can raise
    # non-OSError (e.g. missing SMART_AGENT_* env) — that must NOT crash the cron,
    # so fetch the slim core independently of the prompt-file read below.
    try:
        from core.autonomous import _get_orchestrator
        coaching_guide_content = _get_orchestrator()._coaching_guide_content
    except Exception:
        logger.warning("morning_briefing: coaching guide unavailable — proceeding without it")
        coaching_guide_content = ""
    try:
        system_prompt = (
            prompt_path.read_text(encoding="utf-8")
            .replace("{coaching_guide}", coaching_guide_content)
            .replace("{today_date}", today_iso)
        )
    except OSError:
        logger.warning("morning_briefing: prompt file missing — using fallback")
        return _plain_text_fallback(today_data, today_iso)

    # PHASE 19 — NUTR-08: append non-personalized meal critique guidance so
    # the morning recap LLM can audit yesterday's nutrition with the same
    # heuristics the autonomous tick uses mid-day. Silent-omit semantics
    # (NUTR-07) still hold — if the data block has no `nutrition` key, the
    # briefing prompt instructs the LLM to skip the section.
    meal_audit_path = Path(__file__).parent.parent / "prompts" / "meal_audit.md"
    meal_audit = (
        meal_audit_path.read_text(encoding="utf-8")
        if meal_audit_path.exists() else ""
    )
    if meal_audit:
        system_prompt = system_prompt + "\n\n" + meal_audit

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
    """Deterministic light morning note when the LLM is unavailable."""
    lines = ["Morning. Quick read on today (smart version's down, so here's the plain one).", "", "Today:"]

    events = today_data.get("calendar") or []
    if events:
        for e in events[:6]:
            start = e.get("start", "")
            summary = e.get("summary", "Event")
            # Prefix with LRM (U+200E) if the summary contains RTL characters
            # so Telegram renders time ranges left-to-right.
            lrm = "\u200e" if any("\u0590" <= ch <= "\u08ff" for ch in summary) else ""
            try:
                s = datetime.fromisoformat(start).strftime("%H:%M")
                lines.append(f"{lrm}{s} — {summary}")
            except (ValueError, TypeError):
                lines.append(f"{lrm}— {summary}")
    else:
        lines.append("Nothing on the calendar.")

    tasks = today_data.get("tasks") or {}
    warning = tasks.get("staleness_warning")
    if warning:
        lines += ["", warning]
    else:
        overdue = tasks.get("overdue") or []
        if overdue:
            lines += ["", f"{len(overdue)} overdue — top one: {overdue[0].get('title', '')}."]

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
