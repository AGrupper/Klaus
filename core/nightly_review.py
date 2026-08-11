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


_TERMINAL_STATUSES = frozenset({"sent", "skipped_by_judgment"})


def was_sent(target_date: str) -> bool:
    """True if the nightly review already reached a terminal outcome for this date.

    "Terminal", not "sent" (D-04/D-12): a judgment skip is just as final as an
    actual send — the 01:00 backstop must never re-litigate a night Klaus
    already decided to stay quiet on, and any second trigger for the same
    date (a snoozed Sleep-Focus toggle, a retried backstop) is a no-op either
    way. It only judges nights where nothing ran at all.
    """
    return _get_state(target_date).get("status") in _TERMINAL_STATUSES


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

# MEM-04 (Phase 32, Plan 04): moved to core/training_checkin.py as the public
# `planned_sessions_for(date_iso)` so core/autonomous.py can consume planned
# training intent without importing this module (locked project decision:
# core/autonomous.py must never import core/nightly_review.py). Re-imported
# here under the original private name so every existing internal call site
# and test (tests/test_nightly_review.py patches `nr._planned_workouts_for`
# directly) keeps working unchanged.
from core.training_checkin import planned_sessions_for as _planned_workouts_for


def _gather_tomorrow(tomorrow_iso: str) -> dict:
    """Gather tomorrow-facing context; each source isolated, silent-omit on failure."""
    data: dict = {"tomorrow_date": tomorrow_iso}

    # Tomorrow's planned workouts from the training program (weekly_split)
    planned = _planned_workouts_for(tomorrow_iso)
    if planned:
        data["planned_workouts"] = planned

    # Phase 31 (DIR-03) — active standing directives, interim CONTEXT for the
    # nightly narrative (5th render_standing_directives_block() call site).
    # The nightly is EXEMPT from directive veto (D-21) — this is context only,
    # never a skip signal. Sentinel []: a gather failure must not remove the
    # section, just leave it empty.
    try:
        from memory.firestore_db import StandingDirectiveStore
        sds = StandingDirectiveStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        data["standing_directives"] = sds.list_active()
    except Exception:
        logger.warning("nightly_review: standing_directives gather failed", exc_info=True)
        data["standing_directives"] = []

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

    # Tasks (overdue + today's open carry into tomorrow) — native TaskStore,
    # evaluated as of tonight (the current day, not tomorrow_iso).
    try:
        from memory.firestore_db import get_task_store
        _today = datetime.now(_TZ).date().isoformat()
        _ts = get_task_store()
        data["tasks"] = _ts.get_today_and_overdue(_today)
    except Exception:
        logger.warning("nightly_review: task fetch failed", exc_info=True)

    # Weather (folds in the old 21:30 proactive weather signal). Phase 32
    # Plan 08 (MEM-07): consumes the derived current_location instead of the
    # hardcoded "Tel Aviv" literal — closes the felt bug of a Paris trip
    # getting a Tel Aviv forecast. RESOLVED (home or a confidently-overriding
    # calendar/directive travel signal) -> fetch that city's forecast; the
    # home case is byte-identical to before (derive_current_location defaults
    # "Tel Aviv" silently). AMBIGUOUS (conflicting signals or a directive-
    # alone unclear trip-end, D-06) -> suppress the weather entirely (never
    # serve a possibly-wrong forecast) and set location_ask so the compose
    # prompt below can ask "still in <city>, Sir?" before saying anything
    # location-dependent. Reuses data["calendar"]/data["standing_directives"]
    # gathered just above — no extra Calendar/Firestore call for this.
    try:
        from core.autonomous import derive_current_location
        from mcp_tools.weather_tool import fetch_weather
        location = derive_current_location(
            data.get("calendar") or [], data.get("standing_directives") or [],
        )
        if location.get("ambiguous"):
            data["location_ask"] = {"candidate": location.get("candidate")}
        else:
            data["weather"] = fetch_weather(location.get("location", "Tel Aviv"))
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

def _compose_nightly(journal: dict | None, tomorrow: dict, target_date: str) -> tuple[str, str]:
    """Compose the nightly message via the brain, with a plain-text fallback.

    Legacy (OCCASION_CASCADE=false) composer — untouched apart from this
    return-shape change (Task 2, D-30's byte-identical-legacy-path contract
    covers everything upstream of this signature).

    Returns:
        ``(text, composed_via)`` where ``composed_via`` is ``"llm"`` when the
        primary or Gemini-fallback compose produced the text, or
        ``"plain_text_fallback"`` when the deterministic template did. SC-1:
        a total LLM failure must still SEND while being greppable as
        degraded — this tuple is how the caller learns which happened.
    """
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
        return _plain_text_fallback(journal, tomorrow), "plain_text_fallback"

    # Phase 31 (DIR-03/DIR-06/DIR-07) — two distinct directive-related keys:
    #   - standing_directives_block: the RAW active directives, rendered via
    #     the shared formatter, as behavioral context (nightly consumer of
    #     DIR-03's every-reasoning-path injection). Nightly is EXEMPT from
    #     veto (D-21) — this never suppresses the message, only informs it.
    #   - directive_items: the DERIVED housekeeping from tonight's reflection
    #     (proposals/expiries/prune-flags — Task 2), reaching here through
    #     `journal["directive_items"]` via the existing _ensure_reflection
    #     handoff. D-19/D-20: woven into the narrative, not a fixed section.
    from core.tools import render_standing_directives_block
    standing_directives_block = render_standing_directives_block(
        tomorrow.get("standing_directives") or [], style="prose",
    )

    payload = {
        "today_recap": {
            "summary": (journal or {}).get("summary", ""),
            "highlights": (journal or {}).get("highlights", []),
        },
        "tomorrow": tomorrow,
        "standing_directives_block": standing_directives_block,
        "directive_items": (journal or {}).get("directive_items", []),
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
            return text, "llm"
    except Exception:
        logger.warning("nightly_review: LLM composition failed", exc_info=True)

    # Phase 30.5 Plan 06 (BRAIN-01) — before dropping to the deterministic
    # plain-text template, try the SMART_AGENT_FALLBACK_* Gemini compose (same
    # 2-tier shape as core/reflection.py::_brain_reflect). Silent try/except —
    # a fallback failure must never crash the nightly-review cron.
    try:
        from core.llm_client import LLMClient
        client_fb = LLMClient(
            backend=os.environ["SMART_AGENT_FALLBACK_BACKEND"],
            model=os.environ["SMART_AGENT_FALLBACK_MODEL"],
            api_key=os.environ["SMART_AGENT_FALLBACK_API_KEY"],
        )
        response_fb = client_fb.chat(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            purpose="nightly_review",
        )
        text_fb = (response_fb.get("text") or "").strip()
        if text_fb:
            return text_fb, "llm"
    except Exception:
        logger.warning("nightly_review: LLM fallback composition failed", exc_info=True)

    return _plain_text_fallback(journal, tomorrow), "plain_text_fallback"


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

    planned = tomorrow.get("planned_workouts") or {}
    if planned:
        am = (planned.get("am") or {}).get("label")
        pm = (planned.get("pm") or {}).get("label")
        sessions = [s for s in (am, pm) if s and s != "—"]
        if sessions:
            lines += ["", f"Tomorrow's training: {' / '.join(sessions)}."]

    tasks = tomorrow.get("tasks") or {}
    overdue = tasks.get("overdue") or []
    if overdue:
        lines += ["", f"{len(overdue)} overdue task(s) still hanging."]

    return "\n".join(lines)


# ------------------------------------------------------------------ #
# Build (blocking) + run (async send)                                #
# ------------------------------------------------------------------ #

def _structured_from_tomorrow(tomorrow_iso: str, tomorrow: dict) -> dict:
    """Build the /api/today `structured` snapshot from a _gather_tomorrow() result.

    Shared by the legacy and cascade branches of ``run_nightly`` (D-05) — one
    source of truth for the exact snapshot shape the Hub reads, whether or
    not the nightly ends up sending anything.
    """
    return {
        "tomorrow_date": tomorrow_iso,
        "tomorrow_events": tomorrow.get("calendar") or [],
        "tomorrow_tasks_overdue": (tomorrow.get("tasks") or {}).get("overdue", []),
        "tomorrow_tasks_today": (tomorrow.get("tasks") or {}).get("today", []),
        "planned_workouts": tomorrow.get("planned_workouts") or {},
    }


def _build_nightly(target_date: str) -> dict:
    """Blocking build: guarantee memory, gather tomorrow, compose. Run in executor.

    Legacy (OCCASION_CASCADE=false) path only — untouched apart from the
    `_compose_nightly`/`_structured_from_tomorrow` plumbing (Task 2).
    """
    journal = _ensure_reflection(target_date)
    tomorrow_iso = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
    tomorrow = _gather_tomorrow(tomorrow_iso)
    text, composed_via = _compose_nightly(journal, tomorrow, target_date)
    structured = _structured_from_tomorrow(tomorrow_iso, tomorrow)
    return {"text": text, "structured": structured, "composed_via": composed_via}


def _gather_for_cascade(target_date: str) -> dict:
    """Blocking pre-cascade gather (OCCASION_CASCADE=true path).

    D-07: the journal (`_ensure_reflection`) runs FIRST, unconditionally,
    before any judgment reaches Layer 1/2 — choosing not to interrupt Amit
    must not give Klaus amnesia about the day. Run in the executor exactly
    like `_build_nightly` does today (blocking Firestore/Calendar/weather
    calls have no place on the event loop).
    """
    journal = _ensure_reflection(target_date)
    tomorrow_iso = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
    tomorrow = _gather_tomorrow(tomorrow_iso)
    return {"journal": journal, "tomorrow": tomorrow, "tomorrow_iso": tomorrow_iso}


async def run_nightly(bot: Bot, target_date: str, *, trigger: str, dedup: bool = True) -> bool:
    """Compose and send the nightly review for target_date.

    Idempotent: if the date already reached a terminal status (`was_sent`,
    now "sent" OR "skipped_by_judgment" — D-04/D-12), returns False without
    running anything, so a later trigger/backstop for the same date is a
    no-op either way.

    Two branches behind the `OCCASION_CASCADE` env flag (D-30):
      - **Flag off** (control arm): the untouched legacy `_build_nightly` ->
        `_compose_nightly` two-tier LLM composer, always sends.
      - **Flag on**: routes through the shared occasion cascade in
        `core.autonomous` (occasion="nightly") — Klaus can legitimately
        decide the night isn't worth interrupting Amit for
        (`skipped_by_judgment`, OCC-01).

    On both branches, the journal (D-07) and the tomorrow `structured`
    snapshot (D-05) are written unconditionally — sent or skipped — before
    any branch-specific state write, so the Hub's `/api/today` and Klaus's
    own continuity never depend on whether he decided to speak.

    Args:
        bot:         Telegram Bot instance.
        target_date: YYYY-MM-DD the wind-down belongs to (see nightly_target_date).
        trigger:     "focus" | "backstop" — recorded for observability.
        dedup:       If True, skip when already terminal. If False, always fire.

    Returns:
        True if a message was sent, False otherwise (dedup short-circuit,
        judgment skip, or an infra failure that produced neither).
    """
    if dedup and was_sent(target_date):
        logger.info("nightly_review: already terminal for %s — skipping (%s)", target_date, trigger)
        return False

    loop = asyncio.get_running_loop()
    _cascade_on = os.getenv("OCCASION_CASCADE", "false").lower() == "true"

    if not _cascade_on:
        # Legacy path — the A/B's control arm, byte-identical to pre-Phase-33
        # behavior apart from the D-05 snapshot-write split below.
        built = await loop.run_in_executor(None, _build_nightly, target_date)

        from core.scheduled_message import send_and_inject
        # WR-02 / D-07: reviews carry the "review" push class (24h TTL).
        await send_and_inject(bot, built["text"], inject_into_conversation=True, message_class="review")

        judged_at = datetime.now(_TZ).isoformat()
        # D-05 — structured snapshot written unconditionally; here that is
        # always alongside a send, but the write is split in two so the
        # payload shape stays consistent with the cascade branch below.
        _set_state(target_date, {"structured": built["structured"], "judged_at": judged_at})
        _set_state(target_date, {
            "status": "sent",
            "trigger": trigger,
            "sent_at": judged_at,
            "composed_via": built["composed_via"],
        })
        logger.info("nightly_review: sent and injected for %s (%s)", target_date, trigger)
        return True

    # Cascade path (OCCASION_CASCADE=true) — Klaus judges whether tonight is
    # worth interrupting Amit for.
    pre = await loop.run_in_executor(None, _gather_for_cascade, target_date)
    journal = pre["journal"]
    tomorrow = pre["tomorrow"]
    tomorrow_iso = pre["tomorrow_iso"]
    structured = _structured_from_tomorrow(tomorrow_iso, tomorrow)

    from core import autonomous as _autonomous
    occasion_prompt = _autonomous._load_prompt("prompts/nightly_occasion.md")
    decision = await _autonomous.run_occasion_cascade(
        bot,
        occasion="nightly",
        target_date=target_date,
        occasion_data={"journal": journal, "tomorrow": tomorrow, **structured},
        occasion_prompt=occasion_prompt,
        advisory_only=False,
    )

    judged_at = datetime.now(_TZ).isoformat()
    # D-05 — the tomorrow snapshot is written unconditionally, sent or
    # skipped, so /api/today always has its day summary.
    _set_state(target_date, {"structured": structured, "judged_at": judged_at})

    if decision.get("sent"):
        _set_state(target_date, {
            "status": "sent",
            "trigger": trigger,
            "sent_at": judged_at,
            # composed_via is "llm" on a normal compose, "draft_fallback" if
            # Layer 2 failed and the Layer-1 draft was sent instead (D-19) —
            # either way a send, never absent.
            "composed_via": decision.get("composed_via") or "llm",
        })
        logger.info("nightly_review: sent (cascade) for %s (%s)", target_date, trigger)
        return True

    if decision.get("skipped") == "judgment":
        # T-33-19 — a judgment skip writes NO composed_via key at all (absent
        # means "no compose was attempted"), keeping it structurally
        # distinguishable from the infra-degraded-but-sent path (SC-1).
        _set_state(target_date, {
            "status": "skipped_by_judgment",
            "trigger": trigger,
            "skip_cause": decision.get("skip_cause", ""),
            # D-06 — Layer 1's own free draft, Klaus's own one-liner for the
            # night he judged wasn't worth interrupting Amit over.
            "draft": decision.get("draft", ""),
        })
        logger.info(
            "nightly_review: skipped_by_judgment for %s (%s, cause=%s)",
            target_date, trigger, decision.get("skip_cause", ""),
        )
        return False

    # Cascade infra failure (Layer-1 exception, empty draft+compose, a send
    # that failed outright) — NOT a judgment skip (mislabeling it would
    # defeat SC-1's whole point) and NOT written as a terminal status, so a
    # later trigger or the 01:00 backstop can still retry the same date.
    logger.warning(
        "nightly_review: cascade produced neither a send nor a judgment skip "
        "for %s (%s) — trail=%s", target_date, trigger, decision.get("trail"),
    )
    return False


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
