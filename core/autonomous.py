"""Autonomous tick orchestrator — Klaus's judgment-driven proactive outreach.

Called by Cloud Scheduler via Cloud Run:
  POST /cron/autonomous-tick  (*/20 7-21 * * *, Asia/Jerusalem)

3-layer design (D-20):
  Layer 0 — ``gather_situation()``: free aggregation from 8 sources, per-source
            isolation; flags ``empty=True`` when no overdue, no due follow-ups,
            and no calendar gap/overload (D-11 / SC-3 cost-control gate).
  Layer 1 — ``TickBrain.think(prompt, system_override=<autonomous_triage.md>)``
            with the rendered triage prompt; returns
            ``{should_act, reason, draft, topic_key}``.
  Layer 2 — ``AgentOrchestrator._run_smart_loop`` with a synthetic
            ``[{role: user, content: ...}]`` and ``prompts/autonomous.md`` as
            smart_system (placeholders resolved up-front via
            ``render_smart_system`` — BLOCKER 5b). Full tool-loop bounded by
            ``MAX_TOOL_ITERATIONS``.

D-13 (follow-up path): due follow-ups go through their own Layer-2 compose
(``_compose_followup``) and SKIP tick-brain for that send. They do NOT short-
circuit the rest of the tick — Layer 1 triage still runs afterwards so an
overdue task or long-silence escalation can fire on the same tick. A tick with
a due follow-up can therefore emit two outreach messages (the follow-up plus
a triage-judged proactive nudge). Both go through ``OutreachLogStore`` so D-06
dedup still applies across the day.

Repeat-suppression (D-06/D-09): per-day ``outreach_log/{date}`` doc; informative
to the triage prompt, never blocking.

Phase 18 — AUTO-01, AUTO-02, AUTO-03.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core import prompt_loader

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

# Cron */20 7-21 = ticks at 7:00, 7:20, 7:40, 8:00, ..., 21:00 = 43 ticks/day
# inclusive. (21 - 7) * 3 = 42 intervals, plus the 21:00 tick itself = 43.
_TICK_TOTAL_PER_DAY = 43

# D-14: ``defer_count >= 3`` force-fires on the next due tick.
_DEFER_FORCE_FIRE_THRESHOLD = 3

# Hours of user silence that count as a salient signal — used both by the
# Layer-0 empty gate (wake tick-brain on a silence-only day) and by
# _infer_trigger_type's "silence" label. Judgment about whether the silence
# is actually worth a message belongs to tick-brain, not this threshold.
_SILENCE_TRIGGER_HOURS = 8.0

# BLOCKER 3 guard — ``_run_smart_loop`` RETURNS this sentinel string on total
# LLM exhaustion. The full canned text lives in ``core.main.CONNECTIVITY_ERROR_TEXT``
# (M-5 fix) — any edit to that constant is caught by
# ``tests/test_autonomous.py::test_sentinel_substring_matches_main_constant``,
# which imports ``core.main`` lazily at test time and asserts substring
# containment. Layer-2 callers MUST detect this prefix and treat as failure
# (D-19 fallback to triage draft).
_SMART_LOOP_ERROR_SENTINELS = (
    "I'm afraid I encountered a connectivity",
)


def _load_prompt(relative_path: str) -> str:
    """Load a prompt file by project-root-relative path (cached per process).

    Thin delegate to :func:`core.prompt_loader.load_prompt` — kept under the
    original name because callers and tests reference it directly. The cache
    matters here: each compose path loads three prompt files, 43 ticks a day.

    Raises:
        FileNotFoundError: If the prompt file does not exist.
    """
    return prompt_loader.load_prompt(relative_path)


def _now_context(now: datetime) -> dict:
    """Build the ``now_context`` block per D-08.

    Tick window 07:00..21:00 every 20 minutes inclusive = 43 ticks (WARNING 3).
    ``tick_index`` is 1-indexed for display ("tick 22 of 43"). For hours < 7
    (manual test invocations), clamps to ``tick_index = 1``.
    """
    local = now.astimezone(_TZ)
    # WARNING 3 guard — avoid negative minutes when called pre-7:00 from a
    # manual test or debug script.
    minutes_into_window = max(0, (local.hour - 7) * 60 + local.minute)
    tick_index = max(1, (minutes_into_window // 20) + 1)
    # Cap at the total — late ticks past 21:00 (manual test) shouldn't display
    # "tick 50 of 43".
    tick_index = min(tick_index, _TICK_TOTAL_PER_DAY)
    last_tick_local = local - timedelta(minutes=20)
    return {
        "now_iso": now.isoformat(),
        "now_local": local.strftime("%H:%M %Z"),
        "tick_index": tick_index,
        "tick_total": _TICK_TOTAL_PER_DAY,
        "last_tick_at": last_tick_local.strftime("%H:%M"),
    }


def _calendar_has_gap_or_overload(events: list[dict], now_ctx: dict) -> bool:
    """BLOCKER 2 fix — narrow calendar-signal detection.

    Returns ``True`` only if at least one of:
      - Two events overlap (``start_a < end_b`` AND ``start_b < end_a``), OR
      - More than 2 events fall in the next 2 hours from ``now``.

    A single non-conflicting event ("Standup 10:00-10:30") is NOT a signal —
    normal workdays have events all day; treating "any event" as signal
    would defeat SC-3 cost control.

    (Gap detection — a 90+ min gap between events during the productive
    window — is intentionally deferred to a future iteration; would be
    Claude's discretion if added later.)
    """
    if not events:
        return False

    # Parse start/end pairs into tz-aware datetimes for comparison.
    parsed: list[tuple[datetime, datetime]] = []
    for e in events:
        s_raw = (e.get("start") or "").strip()
        e_raw = (e.get("end") or "").strip()
        try:
            s = datetime.fromisoformat(s_raw.replace("Z", "+00:00")) if s_raw else None
            en = datetime.fromisoformat(e_raw.replace("Z", "+00:00")) if e_raw else None
        except (ValueError, TypeError):
            continue
        if s and en:
            if s.tzinfo is None:
                s = s.replace(tzinfo=_TZ)
            if en.tzinfo is None:
                en = en.replace(tzinfo=_TZ)
            parsed.append((s, en))

    # (1) Pairwise overlap detection.
    for i, (a_s, a_e) in enumerate(parsed):
        for (b_s, b_e) in parsed[i + 1:]:
            if a_s < b_e and b_s < a_e:
                return True

    # (2) > 2 events in the next 2 hours.
    try:
        now_local = datetime.fromisoformat(
            (now_ctx.get("now_iso") or "").replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return False
    horizon = now_local + timedelta(hours=2)
    upcoming_count = 0
    for (s, _e) in parsed:
        # Normalise tz: compare aware<->aware. If event has no tz info, skip.
        if s.tzinfo is None:
            continue
        if now_local <= s <= horizon:
            upcoming_count += 1
    if upcoming_count > 2:
        return True

    return False


def _is_empty_signals(situation: dict) -> bool:
    """D-11 Layer-0 gate. Return ``True`` if nothing salient is present.

    BLOCKER 2 fix: calendar signal is "GAP / OVERLOAD" per D-01/D-11 — NOT
    "any calendar event exists". A normal workday with a standup and a
    workout block must be treated as quiet unless those events overlap,
    overload the next 2h, or there's an actionable overdue/followup.
    """
    if situation.get("ticktick_overdue"):
        return False
    if situation.get("due_followups"):
        return False
    if _calendar_has_gap_or_overload(
        situation.get("calendar") or [],
        situation.get("now_context") or {},
    ):
        return False
    # PHASE 19 — meals_since_last_tick is a proactive trigger (NUTR-04).
    # NOTE: training_status and acwr are CONTEXT only — not triggers.
    # Adding them here would over-fire the autonomous tick (a single high
    # ACWR ratio would force a speak-up on every tick of the day).
    if situation.get("meals_since_last_tick"):
        return False
    # Silence is a trigger, not just context: a long gap since Amit's last
    # message must wake tick-brain even on an otherwise empty day — that is
    # exactly when a check-in is worth judging (fixture 0004). Without this,
    # silence-only days are structurally unreachable: the gather bug fixed
    # 2026-06-12 starved the signal of data, and this gate skipped it anyway.
    # Tick-brain is the free layer, so waking it costs nothing; its tuned
    # prompt + the outreach log handle don't-repeat judgment downstream.
    hsc = situation.get("hours_since_contact")
    if isinstance(hsc, (int, float)) and hsc >= _SILENCE_TRIGGER_HOURS:
        return False
    return True


# --------------------------------------------------------------------- #
# Layer-0 per-source gather functions                                    #
#                                                                        #
# Each function owns its try/except and returns a sentinel on failure    #
# (empty list / 0 / "" / None) so one failed source never masks another  #
# — critical for D-11 empty-signals detection. gather_situation runs     #
# them in a thread pool; isolation is preserved by construction because  #
# the functions never raise.                                             #
# --------------------------------------------------------------------- #

def _gather_calendar(now: datetime) -> list:
    """(a) Today's calendar events via the shared core.tools singleton."""
    try:
        from core.tools import _get_calendar_tool
        cal = _get_calendar_tool()
        local = now.astimezone(_TZ)
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        return cal.list_events(
            day_start.isoformat(),
            day_end.isoformat(),
            max_results=50,
        ) or []
    except Exception:
        logger.warning("autonomous: calendar gather failed", exc_info=True)
        return []


def _gather_native_overdue() -> list:
    """(b) Native TaskStore overdue — replaces TickTick gather (D-17 / TASK-05).

    Reads TaskStore.get_overdue(today_iso) and returns a TickTick-compatible
    list of {"title": str, "due": str} dicts so the situation key
    'ticktick_overdue' and all downstream triage/compose references need zero
    changes (Pitfall 3 — exact shape preserved).
    """
    try:
        from zoneinfo import ZoneInfo
        from memory.firestore_db import TaskStore
        today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        store = TaskStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        tasks = store.get_overdue(today_iso) or []
        return [{"title": t["title"], "due": t.get("due_date", "")} for t in tasks]
    except Exception:
        logger.warning("autonomous: native overdue gather failed", exc_info=True)
        return []


def _gather_unread_email_count() -> int:
    """(c) Unread email count (BLOCKER 1 — GmailTool.list_unread length)."""
    try:
        from core.tools import _get_gmail_tool
        gm = _get_gmail_tool()
        return len(gm.list_unread(max_results=50))
    except Exception:
        logger.warning("autonomous: gmail gather failed", exc_info=True)
        return 0


def _gather_due_followups(now: datetime, project_id: str, database: str) -> list:
    """(d) Due follow-ups."""
    try:
        from memory.firestore_db import FollowupStore
        fs = FollowupStore(project_id=project_id, database=database)
        return fs.list_due(now.astimezone(timezone.utc).isoformat())
    except Exception:
        logger.warning("autonomous: followup gather failed", exc_info=True)
        return []


def _gather_hours_since_contact(
    now: datetime, project_id: str, database: str
) -> float | None:
    """(e) Hours since last user contact (WARNING 4 — None == unknown, not 999).

    The user id comes from the first entry of ``TELEGRAM_ALLOWED_USER_IDS`` —
    the same convention as every other single-user call site (e.g.
    ``core/scheduled_message.py``). This function originally read a
    ``TELEGRAM_USER_ID`` var that exists nowhere in the deployment, so it
    queried user 0 and returned None on every live tick (823/823 null,
    2026-05-23 → 2026-06-10) — the silence trigger never had data.
    """
    try:
        from memory.firestore_conversation import FirestoreConversationStore
        raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")[0].strip()
        if not raw:
            logger.warning(
                "autonomous: TELEGRAM_ALLOWED_USER_IDS unset — "
                "hours_since_contact unknown"
            )
            return None
        user_id = int(raw)
        store = FirestoreConversationStore(project_id=project_id, database=database)
        last_ts = store.get_last_user_timestamp(user_id)
        if last_ts:
            delta = now.astimezone(timezone.utc) - last_ts.astimezone(timezone.utc)
            return round(delta.total_seconds() / 3600.0, 2)
        return None  # WARNING 4
    except Exception:
        logger.warning("autonomous: hours_since_contact gather failed", exc_info=True)
        return None


def _gather_journal_digest(now: datetime, project_id: str, database: str) -> str:
    """(f) Recent journal digest (last 3 entries)."""
    try:
        from memory.firestore_db import JournalStore
        js = JournalStore(project_id=project_id, database=database)
        digest_parts: list[str] = []
        for days_back in range(0, 3):
            d = (now.astimezone(_TZ).date() - timedelta(days=days_back)).isoformat()
            entry = js.get(d)
            if entry:
                digest_parts.append(f"[{d}] {entry.get('summary', '')}")
        return "\n".join(digest_parts)
    except Exception:
        logger.warning("autonomous: journal digest gather failed", exc_info=True)
        return ""


def _gather_self_state(project_id: str, database: str) -> dict:
    """(g) Self-state (current_focus, mood)."""
    try:
        from memory.firestore_db import SelfStateStore
        ss = SelfStateStore(project_id=project_id, database=database)
        return ss.get() or {}
    except Exception:
        logger.warning("autonomous: self_state gather failed", exc_info=True)
        return {}


def _gather_outreach_log(now: datetime, project_id: str, database: str) -> list:
    """(h) Today's outreach log topics."""
    try:
        from memory.firestore_db import OutreachLogStore
        ols = OutreachLogStore(project_id=project_id, database=database)
        today_iso = now.astimezone(_TZ).date().isoformat()
        return ols.topics_today(today_iso)
    except Exception:
        logger.warning("autonomous: outreach_log gather failed", exc_info=True)
        return []


def _gather_meals_since_last_tick(
    now: datetime, project_id: str, database: str
) -> list:
    """(i) PHASE 19.3 — recent meals read from MealStore (NUTR-04).

    The iOS HealthKit bridge (/cron/healthkit-sync) writes meals into
    MealStore directly, so we READ from the store rather than re-syncing
    from Google Fit (dead on iOS — returned []). Keep only meals within the
    last hour so `meals_since_last_tick` retains its "since last tick"
    trigger semantics (the tick runs */20 7-21, so a 1h window never needs
    to straddle midnight). Same store the morning briefing reads.
    """
    try:
        from memory.firestore_db import MealStore
        ms = MealStore(project_id=project_id, database=database)
        today_iso = now.astimezone(_TZ).date().isoformat()
        cutoff = now.astimezone(_TZ) - timedelta(hours=1)
        recent: list[dict] = []
        for m in ms.get_day(today_iso):
            try:
                ts = datetime.fromisoformat(m["timestamp"])
                if ts >= cutoff:
                    recent.append(m)
            except (KeyError, ValueError, TypeError):
                continue
        return recent
    except Exception:
        logger.warning("autonomous: meals gather failed", exc_info=True)
        return []


def _gather_training_status() -> dict:
    """(j) PHASE 19 — Garmin training status (live)."""
    try:
        from mcp_tools.garmin_tool import fetch_garmin_training_status
        return fetch_garmin_training_status() or {}
    except Exception:
        logger.warning("autonomous: training_status gather failed", exc_info=True)
        return {}


def _gather_acwr() -> dict:
    """(k) PHASE 19 — ACWR from Postgres activities (live).

    compute_acwr_from_db swallows its own exceptions and returns the
    sentinel {"acute": 0.0, "chronic": None, "ratio": None}; the outer
    try/except is defense-in-depth (Pattern C symmetry).
    """
    try:
        from mcp_tools.garmin_tool import compute_acwr_from_db
        return compute_acwr_from_db() or {"ratio": None}
    except Exception:
        logger.warning("autonomous: acwr gather failed", exc_info=True)
        return {"ratio": None}


def gather_situation(now: datetime) -> dict:
    """Layer 0 — aggregate situation snapshot from 11 sources, fanned out in parallel.

    Each source lives in its own ``_gather_*`` function with its own
    try/except and sentinel fallback, so one failure does NOT mask others —
    critical for D-11 empty-signals detection. The sources are independent
    network/Firestore calls, so they run concurrently in a thread pool:
    sequential execution cost ~1s per tick × 43 ticks/day.

    Uses REAL APIs verified from source (BLOCKER 1 fix):
      - ``GoogleCalendarManager.list_events(time_min_iso, time_max_iso)``
      - ``ticktick_tool.get_today_tasks()`` (module-level, returns dict
        with ``'overdue'`` key)
      - ``GmailTool(auth_manager).list_unread(max_results)``
      - ``FirestoreConversationStore.get_last_user_timestamp(user_id)``
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    gathered: dict = {"now_context": _now_context(now)}

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")

    # Pre-warm the shared Google auth singleton before the fan-out: the lazy
    # singletons in core.tools (_get_auth_manager → calendar/gmail) have no
    # locks, so two threads constructing them concurrently on a cold instance
    # could double-build. Warming once on this thread removes the race.
    try:
        from core.tools import _get_auth_manager
        _get_auth_manager()
    except Exception:
        logger.warning("autonomous: auth manager pre-warm failed", exc_info=True)

    jobs: dict[str, callable] = {
        "calendar": lambda: _gather_calendar(now),
        "ticktick_overdue": _gather_native_overdue,
        "unread_email_count": _gather_unread_email_count,
        "due_followups": lambda: _gather_due_followups(now, project_id, database),
        "hours_since_contact": lambda: _gather_hours_since_contact(
            now, project_id, database
        ),
        "recent_journal_digest": lambda: _gather_journal_digest(
            now, project_id, database
        ),
        "self_state": lambda: _gather_self_state(project_id, database),
        "today_outreach_log": lambda: _gather_outreach_log(now, project_id, database),
        "meals_since_last_tick": lambda: _gather_meals_since_last_tick(
            now, project_id, database
        ),
        "training_status": _gather_training_status,
        "acwr": _gather_acwr,
    }

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="gather") as pool:
        futures = {pool.submit(fn): key for key, fn in jobs.items()}
        for fut in as_completed(futures):
            # _gather_* functions never raise (sentinel on failure), so
            # fut.result() is safe; a raise here would indicate a programming
            # error and should surface loudly.
            gathered[futures[fut]] = fut.result()

    # D-11 Layer-0 gate (BLOCKER 2 — narrow calendar detection).
    gathered["empty"] = _is_empty_signals(gathered)
    if gathered["empty"]:
        gathered["raw_signals"] = {
            "ticktick_overdue_count": len(gathered.get("ticktick_overdue") or []),
            "due_followups_count": len(gathered.get("due_followups") or []),
            "calendar_count": len(gathered.get("calendar") or []),
            "hours_since_contact": gathered.get("hours_since_contact"),
        }
    return gathered


def _synthesize_topic_key(trigger_hint: str, situation: dict) -> str:
    """Pitfall 4 fallback — synthesise a ``topic_key`` when tick-brain returns empty.

    Examples::

        _synthesize_topic_key("overdue", sit)  -> "overdue:auto-<task-slug>"
        _synthesize_topic_key("silence", sit)  -> "silence:tick-<N>"
        _synthesize_topic_key("gap",     sit)  -> "gap:tick-<N>"
        _synthesize_topic_key("followup", sit) -> "followup:<id>"
        _synthesize_topic_key("quiet",   sit)  -> "quiet:tick-<N>"

    Never returns an empty string.
    """
    tick_idx = (situation.get("now_context") or {}).get("tick_index", 0)
    trigger = (trigger_hint or "general").lower().strip()
    if trigger == "overdue":
        overdue = situation.get("ticktick_overdue") or []
        if overdue:
            title = str(overdue[0].get("title") or overdue[0].get("id") or "0")
            slug = "".join(
                c if c.isalnum() else "-" for c in title.lower()
            )[:30].strip("-") or "0"
            return f"overdue:auto-{slug}"
        return f"overdue:auto-tick-{tick_idx}"
    if trigger == "followup":
        fus = situation.get("due_followups") or []
        if fus:
            return f"followup:{fus[0].get('id', 'unknown')}"
        return f"followup:tick-{tick_idx}"
    return f"{trigger}:tick-{tick_idx}"


def _build_triage_prompt(situation: dict, triage_system: str) -> str:
    """Build the user-message content for the triage call.

    ``triage_system`` is currently unused — it's passed to
    ``TickBrain.think(..., system_override=triage_system)`` separately, and
    the parameter is kept here so callers don't have to remember which prompt
    template was loaded for which call site. WARNING 4: when
    ``hours_since_contact`` is None, the prompt renders it as ``"unknown"``,
    not ``"999.0"`` (which the LLM would interpret as "Sir vanished").
    """
    _ = triage_system  # reserved
    snap = {
        "calendar": situation.get("calendar", []),
        "ticktick_overdue": situation.get("ticktick_overdue", []),
        "unread_email_count": situation.get("unread_email_count", 0),
        "due_followups": situation.get("due_followups", []),
        # PHASE 19 — new context surfaces (must stay in sync with
        # _compose_layer2 and tests/test_evals.py::TestFixtureSchema).
        "meals_since_last_tick": situation.get("meals_since_last_tick", []),
        "training_status": situation.get("training_status", {}),
        "acwr": situation.get("acwr", {"ratio": None}),
    }
    hsc = situation.get("hours_since_contact")
    snap["hours_since_contact"] = "unknown" if hsc is None else hsc
    snap_json = json.dumps(snap, indent=2, ensure_ascii=False)

    self_state = situation.get("self_state") or {}
    self_state_block = (
        f"current_focus: {self_state.get('current_focus', '')}\n"
        f"mood: {self_state.get('mood', '')}"
    )

    journal = situation.get("recent_journal_digest") or "(no recent journal entries)"
    nc = situation.get("now_context") or {}
    now_context_block = (
        f"now: {nc.get('now_local', '')}\n"
        f"tick {nc.get('tick_index', 0)} of {nc.get('tick_total', _TICK_TOTAL_PER_DAY)}\n"
        f"last tick at: {nc.get('last_tick_at', '')}"
    )
    outreach_today = situation.get("today_outreach_log") or []
    outreach_block = ", ".join(outreach_today) if outreach_today else "(none yet)"

    return (
        f"Situation snapshot:\n{snap_json}\n\n"
        f"My self-state:\n{self_state_block}\n\n"
        f"My recent journal:\n{journal}\n\n"
        f"Time context:\n{now_context_block}\n\n"
        f"Topics I have already raised today:\n{outreach_block}\n"
    )


# --------------------------------------------------------------------------- #
# Module-level AgentOrchestrator singleton (BLOCKER 5a fix)                   #
# --------------------------------------------------------------------------- #

_orchestrator_singleton = None  # type: ignore[var-annotated]
_orchestrator_lock = threading.Lock()


def _get_orchestrator():
    """Return the process-wide ``AgentOrchestrator`` singleton.

    ``AgentOrchestrator.__init__`` reads SELF.md from disk, bootstraps
    ``SelfStateStore``, and constructs 3 LLMClients — instantiating once per
    tick (~43 times/day) is wasteful. The singleton lives for the Cloud Run
    instance lifetime (typically many ticks before scale-to-zero).

    Double-checked-locking (M-1 fix): Cloud Run concurrency is unpinned, so two
    coincident requests can both pass the first ``is None`` check. The lock
    serializes construction; the second ``is None`` check inside the lock
    prevents a duplicate ``AgentOrchestrator()`` (which would leak a SelfState
    client and 3 LLMClients).

    BLOCKER 5a fix.
    """
    global _orchestrator_singleton
    if _orchestrator_singleton is None:
        with _orchestrator_lock:
            if _orchestrator_singleton is None:
                from core.main import AgentOrchestrator
                _orchestrator_singleton = AgentOrchestrator()
    return _orchestrator_singleton


# --------------------------------------------------------------------------- #
# Trigger inference + follow-up action parser                                 #
# --------------------------------------------------------------------------- #


def _infer_trigger_type(situation: dict) -> str:
    """Return a coarse trigger-type label from the situation.

    Used for ``_synthesize_topic_key`` when tick-brain returns an empty/missing
    ``topic_key`` (Pitfall 4 fallback).
    """
    if situation.get("ticktick_overdue"):
        return "overdue"
    if situation.get("due_followups"):
        return "followup"
    hsc = situation.get("hours_since_contact")
    if hsc is not None and hsc >= _SILENCE_TRIGGER_HOURS:
        return "silence"
    if _calendar_has_gap_or_overload(
        situation.get("calendar") or [],
        situation.get("now_context") or {},
    ):
        return "gap"
    return "quiet"


def _parse_followup_action(text: str) -> tuple[str, str]:
    """Parse the trailing JSON action from a Layer-2 follow-up response.

    Looks for a fenced ``json {"action": "send"|"defer"}`` block. Returns
    ``(action, polished_text)``. ``polished_text`` is the message body BEFORE
    the JSON block.

    WARNING 5 fix:
      - No JSON block found    -> ``("send", text.strip())``
      - JSON block parse fails -> ``("send", text_BEFORE_the_block.strip())``
        so the malformed JSON internals don't leak to the user.

    Default to ``"send"`` rather than eternally deferring (D-17 spirit +
    Pitfall 6).
    """
    import re as _re
    if not text:
        return ("send", "")
    m = _re.search(r"```json\s*(\{.*?\})\s*```", text, _re.DOTALL)
    if not m:
        return ("send", text.strip())
    try:
        obj = json.loads(m.group(1))
        action = str(obj.get("action", "send")).lower()
        if action not in ("send", "defer"):
            action = "send"
    except (json.JSONDecodeError, ValueError):
        # WARNING 5 — strip the malformed JSON from the polished text.
        action = "send"
    polished = text[:m.start()].strip()
    return (action, polished)


# --------------------------------------------------------------------------- #
# Layer 2 — synthetic chat turn via _run_smart_loop                            #
# --------------------------------------------------------------------------- #


def _compose_layer2(situation: dict, draft: str, triage_reason: str) -> str:
    """Layer 2 — synthetic chat turn via ``AgentOrchestrator._run_smart_loop``.

    BLOCKER 5a fix — uses the module singleton, not per-call ``AgentOrchestrator()``.
    BLOCKER 5b fix — explicitly renders ``smart_system`` placeholders BEFORE
    calling ``_run_smart_loop``. The injection happens in ``handle_message``
    (verified at ``core/main.py:236-275``), NOT inside ``_run_smart_loop`` —
    so the autonomous tick MUST replicate the render step here.

    Pitfall 2 — builds the messages list freshly. Does NOT call
    ``handle_message`` (which would append to conversation history, polluting
    it with the synthetic user message).
    """
    orchestrator = _get_orchestrator()

    # BLOCKER 5b — replicate handle_message's render step before _run_smart_loop.
    smart_system_template = _load_prompt("prompts/autonomous.md")
    # PHASE 19 — NUTR-08: append non-personalized meal critique guidance so the
    # brain's compose layer has the audit heuristics whenever a meal-driven
    # nudge is in play. Defense-in-depth `if` guard: if the file vanishes,
    # we don't append a stray separator.
    meal_audit = _load_prompt("prompts/meal_audit.md")
    if meal_audit:
        smart_system_template = smart_system_template + "\n\n" + meal_audit
    smart_system = orchestrator.render_smart_system(smart_system_template)
    worker_system_template = _load_prompt("prompts/worker_agent.md")
    # worker_system only needs {today_date} resolved; reuse the same render
    # path so a future addition of new placeholders to worker_agent.md does
    # not silently bypass them.
    worker_system = orchestrator.render_smart_system(worker_system_template)

    snap_summary = json.dumps({
        "calendar": situation.get("calendar", []),
        "ticktick_overdue": situation.get("ticktick_overdue", []),
        "unread_email_count": situation.get("unread_email_count", 0),
        "due_followups": situation.get("due_followups", []),
        "hours_since_contact": situation.get("hours_since_contact"),
        # PHASE 19 — parity with _build_triage_prompt so the brain's compose
        # layer sees the same context the tick-brain saw at triage.
        "meals_since_last_tick": situation.get("meals_since_last_tick", []),
        "training_status": situation.get("training_status", {}),
        "acwr": situation.get("acwr", {"ratio": None}),
    }, indent=2, ensure_ascii=False)

    synthetic_content = (
        f"Situation snapshot:\n{snap_summary}\n\n"
        f"Triage layer's draft:\n{draft}\n\n"
        f"Triage reasoning:\n{triage_reason}\n"
    )
    messages = [{"role": "user", "content": synthetic_content}]
    return orchestrator._run_smart_loop(messages, smart_system, worker_system)


def _compose_followup_layer2(followup: dict, situation: dict) -> str:
    """Sync helper called from an executor — synthetic chat turn for a follow-up.

    Uses the module singleton (BLOCKER 5a) and renders ``smart_system``
    (BLOCKER 5b) identically to ``_compose_layer2``.

    Layer 2 should end its response with a fenced JSON block
    ``{"action": "send"|"defer"}`` per the follow-up branch of
    ``prompts/autonomous.md``.
    """
    orchestrator = _get_orchestrator()
    smart_system_template = _load_prompt("prompts/autonomous.md")
    # PHASE 19 — NUTR-08: same meal_audit append as _compose_layer2. The
    # follow-up compose path is a sibling brain-compose site and must carry
    # the same audit guidance so a meal-adjacent follow-up nudge is critiqued
    # under the same heuristics.
    meal_audit = _load_prompt("prompts/meal_audit.md")
    if meal_audit:
        smart_system_template = smart_system_template + "\n\n" + meal_audit
    smart_system = orchestrator.render_smart_system(smart_system_template)
    worker_system_template = _load_prompt("prompts/worker_agent.md")
    worker_system = orchestrator.render_smart_system(worker_system_template)

    snap = json.dumps({
        "calendar": situation.get("calendar", []),
        "ticktick_overdue": situation.get("ticktick_overdue", []),
    }, indent=2, ensure_ascii=False)
    synthetic = (
        f"Due follow-up:\n"
        f"id: {followup.get('id', '')}\n"
        f"due_at: {followup.get('due_at', '')}\n"
        f"note: {followup.get('note', '')}\n"
        f"defer_count: {followup.get('defer_count', 0)}\n\n"
        f"Current situation:\n{snap}\n"
    )
    messages = [{"role": "user", "content": synthetic}]
    return orchestrator._run_smart_loop(messages, smart_system, worker_system)


# --------------------------------------------------------------------------- #
# Follow-up path (D-13) — dedicated Layer-2 compose, skips tick-brain          #
# --------------------------------------------------------------------------- #


async def _compose_followup(bot, followup: dict, situation: dict, now: datetime) -> str:
    """D-13 — dedicated Layer-2 path for a due follow-up.

    - Layer 2 returns JSON ``{"action": "send"}`` or ``{"action": "defer"}``.
    - D-14 force-fire: if ``defer_count >= _DEFER_FORCE_FIRE_THRESHOLD``
      override defer -> send.
    - On send: ``send_and_inject(..., inject_into_conversation=True)`` +
      ``FollowupStore.mark_done`` + ``OutreachLogStore.append`` (success-only,
      D-10).
    - On defer: ``FollowupStore.defer(fid, original_due + 1h)``.

    Returns ``"sent"`` | ``"deferred"`` | ``"force_fired"`` | ``"failed"``.

    BLOCKER 3 — detects ``_run_smart_loop``'s sentinel-return string and
    treats it as Layer-2 failure (falls through to defer / mark failed).
    """
    import asyncio as _asyncio
    defer_count = int(followup.get("defer_count", 0))
    fid = followup.get("id") or ""

    try:
        text = await _asyncio.get_running_loop().run_in_executor(
            None, _compose_followup_layer2, followup, situation,
        )
        # BLOCKER 3 — sentinel detection.
        if text and any(s in text for s in _SMART_LOOP_ERROR_SENTINELS):
            logger.warning(
                "autonomous: followup Layer 2 returned sentinel; treating as failure",
            )
            text = ""
    except Exception:
        logger.warning("autonomous: followup Layer 2 failed", exc_info=True)
        text = ""

    action, polished = _parse_followup_action(text)

    # D-14 force-fire — defer_count >= threshold overrides "defer".
    force_fired = False
    if action == "defer" and defer_count >= _DEFER_FORCE_FIRE_THRESHOLD:
        logger.info(
            "autonomous: follow-up %s force-fired (defer_count=%d >= %d)",
            fid, defer_count, _DEFER_FORCE_FIRE_THRESHOLD,
        )
        action = "send"
        force_fired = True

    if action == "send":
        from core.scheduled_message import send_and_inject
        from memory.firestore_db import FollowupStore, OutreachLogStore

        final_text = polished or followup.get("note", "")
        try:
            await send_and_inject(bot, final_text, inject_into_conversation=True)
        except Exception:
            logger.error("autonomous: followup send_and_inject failed", exc_info=True)
            return "failed"

        # D-10 — mark_done + outreach_log append only AFTER send success.
        try:
            fs = FollowupStore(
                project_id=os.environ.get("GCP_PROJECT_ID", ""),
                database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
            )
            fs.mark_done(fid)
        except Exception:
            logger.warning("autonomous: mark_done failed", exc_info=True)
        try:
            ols = OutreachLogStore(
                project_id=os.environ.get("GCP_PROJECT_ID", ""),
                database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
            )
            today_iso = now.astimezone(_TZ).date().isoformat()
            ols.append(today_iso, {
                "topic_key": f"followup:{fid}",
                "time": now.astimezone(_TZ).strftime("%H:%M"),
                "draft": followup.get("note", ""),
                "final": final_text,
                "tick_index": (situation.get("now_context") or {}).get(
                    "tick_index", 0,
                ),
            })
        except Exception:
            logger.warning(
                "autonomous: outreach_log append (followup) failed",
                exc_info=True,
            )
        return "force_fired" if force_fired else "sent"

    # action == "defer" — push original due_at + 1h, not now + 1h.
    # NOTE 2 — using now+1h would drift the cadence further with each defer;
    # original_due+1h preserves the user's intended cadence.
    from memory.firestore_db import FollowupStore
    try:
        original_due = datetime.fromisoformat(followup.get("due_at"))
        new_due = (original_due + timedelta(hours=1)).isoformat()
        fs = FollowupStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        fs.defer(fid, new_due)
    except Exception:
        logger.error("autonomous: followup defer failed", exc_info=True)
        return "failed"
    return "deferred"


# --------------------------------------------------------------------------- #
# Best-effort tick log writer (D-21)                                          #
# --------------------------------------------------------------------------- #


async def _write_tick_log(now: datetime, situation: dict, decision: dict) -> None:
    """D-21 — write the per-tick snapshot for retroactive eval-fixture labeling.

    Best-effort. Never raises. Uses ``TickLogStore`` (Plan 01) so every
    persistent collection has a named store (NOTE 1 — keeps the memory-layer
    pattern consistent).
    """
    try:
        from memory.firestore_db import TickLogStore
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        today_iso = now.astimezone(_TZ).date().isoformat()
        tick_time = now.astimezone(_TZ).strftime("%H:%M")
        snapshot = {k: v for k, v in situation.items() if k != "empty"}
        TickLogStore(project_id=project_id, database=database).write(
            today_iso, tick_time, snapshot, decision,
        )
    except Exception:
        logger.warning("autonomous: tick_log write failed (non-fatal)", exc_info=True)


# --------------------------------------------------------------------------- #
# Top-level entry point — run_autonomous_tick (3-layer pipeline, D-20)         #
# --------------------------------------------------------------------------- #


async def run_autonomous_tick(bot, now: datetime | None = None) -> dict:
    """Top-level autonomous tick orchestrator.

    3-layer pipeline per D-20:
      1. ``gather_situation`` (Layer 0) — fast, no LLM
      2. If empty signals → return early (D-11 gate; cost control SC-3)
      3. Due follow-ups (D-13) → dedicated Layer-2 compose loop (no tick-brain
         FOR THE FOLLOW-UP SEND). Execution then continues into step 4 — a
         follow-up firing does NOT short-circuit the rest of the tick.
      4. Triage (Layer 1) — ``TickBrain.think`` with ``autonomous_triage`` as
         ``system_override``; purpose ``tick_autonomous`` (fallback
         ``tick_autonomous_fallback``). Runs regardless of whether step 3
         fired, so a tick can emit BOTH a follow-up and a triage-judged
         escalation (e.g. overdue task on the same tick).
      5. If ``should_act=False`` → log + return.
      6. Compose (Layer 2) — synthetic ``[{role:user, content}]`` via
         ``_run_smart_loop`` with ``autonomous.md`` as ``smart_system``.
         On total failure (raise OR sentinel return), fall back to the
         tick-brain ``draft`` (D-19, BLOCKER 3).
      7. Send via ``send_and_inject(..., inject_into_conversation=True)``
         (D-18).
      8. ONLY on send success: append to ``outreach_log`` (D-10). Same-tick
         double-sends are de-duplicated across the day by D-06 ``topic_key``
         logic on the next tick, not within this one.

    Returns a decision-trail dict suitable for ``TickLogStore`` and debugging.
    """
    import asyncio as _asyncio

    if now is None:
        now = datetime.now(_TZ)

    situation = gather_situation(now)
    decision: dict = {"skipped": False, "sent": False, "trail": []}

    # Layer 0 gate (D-11 / SC-3) — empty signals = quiet tick, never call LLM.
    if situation.get("empty"):
        decision["skipped"] = "empty"
        decision["trail"].append("layer0_empty_signals")
        await _write_tick_log(now, situation, decision)
        return decision

    # D-13 follow-up path — skip tick-brain entirely for due follow-ups.
    due_followups = situation.get("due_followups") or []
    if due_followups:
        for fu in due_followups:
            fu_outcome = await _compose_followup(bot, fu, situation, now)
            decision["trail"].append({"followup": fu.get("id"), "outcome": fu_outcome})
        # D-13 intent: follow-up firing does NOT preclude same-tick triage. The
        # follow-up path skipped tick-brain for ITS send (Layer-2 only); Layer 1
        # still runs below so an overdue/silence escalation can also fire on
        # this tick. Per-day D-06 dedup prevents repeats across ticks.

    # Layer 1 — triage. tick_brain.think wraps both purpose='tick_autonomous'
    # (primary) and 'tick_autonomous_fallback' (fallback) internally (Plan 05).
    try:
        from core.tick_brain import TickBrain
        tb = TickBrain()
        triage_system = _load_prompt("prompts/autonomous_triage.md")
        triage_user_msg = _build_triage_prompt(situation, triage_system)
        verdict = tb.think(triage_user_msg, system_override=triage_system)
    except Exception:
        logger.error("autonomous: Layer 1 (triage) failed entirely", exc_info=True)
        decision["trail"].append("layer1_exception")
        await _write_tick_log(now, situation, decision)
        return decision

    decision["trail"].append({"layer1": verdict})

    if not verdict.get("should_act"):
        decision["trail"].append("layer1_no_act")
        await _write_tick_log(now, situation, decision)
        return decision

    # Layer 2 — compose. Pitfall 2: build messages freshly, NEVER call
    # handle_message (which would append the synthetic message to history).
    draft = verdict.get("draft", "")
    triage_reason = verdict.get("reason", "")
    topic_key = verdict.get("topic_key") or ""
    if not topic_key:
        # Pitfall 4 — synthesise from inferred trigger.
        trigger_hint = _infer_trigger_type(situation)
        topic_key = _synthesize_topic_key(trigger_hint, situation)
        decision["trail"].append({"topic_key_synthesised": topic_key})

    # BLOCKER 3 — _run_smart_loop RETURNS sentinel on total LLM failure,
    # not raises. MUST detect both exception and sentinel-return as failure.
    try:
        final_text = await _asyncio.get_running_loop().run_in_executor(
            None, _compose_layer2, situation, draft, triage_reason,
        )
        if not final_text or any(s in final_text for s in _SMART_LOOP_ERROR_SENTINELS):
            raise RuntimeError(
                f"Layer 2 returned empty or sentinel error text: {final_text!r:.120}"
            )
    except Exception as exc:
        logger.warning(
            "autonomous: Layer 2 failed; falling back to draft (D-19): %s", exc,
        )
        final_text = draft

    if not final_text:
        decision["trail"].append("layer2_and_draft_both_empty")
        await _write_tick_log(now, situation, decision)
        return decision

    # Send (D-18: inject_into_conversation=True).
    from core.scheduled_message import send_and_inject
    try:
        await send_and_inject(bot, final_text, inject_into_conversation=True)
    except Exception:
        logger.error(
            "autonomous: send_and_inject failed; outreach_log NOT updated (D-10)",
            exc_info=True,
        )
        decision["trail"].append("send_failed")
        await _write_tick_log(now, situation, decision)
        return decision

    decision["sent"] = True

    # D-10 — write to outreach_log ONLY after the send succeeded.
    try:
        from memory.firestore_db import OutreachLogStore
        ols = OutreachLogStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        today_iso = now.astimezone(_TZ).date().isoformat()
        ols.append(today_iso, {
            "topic_key": topic_key,
            "time": now.astimezone(_TZ).strftime("%H:%M"),
            "draft": draft,
            "final": final_text,
            "tick_index": (situation.get("now_context") or {}).get("tick_index", 0),
        })
    except Exception:
        logger.warning(
            "autonomous: outreach_log append failed (send already succeeded)",
            exc_info=True,
        )

    decision["trail"].append({"shipped": topic_key})
    await _write_tick_log(now, situation, decision)
    return decision
