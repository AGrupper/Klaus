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
dedup still applies across the day. Layer 2 has three actions — send, defer
(force-fired to send at defer_count >= 3, D-14), and cancel (evidence-first:
the follow-up's subject is moot or demonstrably didn't happen — e.g. a planned
workout with no ``training_evidence``; not overridden by force-fire).

Repeat-suppression (D-06/D-09): per-day ``outreach_log/{date}`` doc; informative
to the triage prompt, never blocking.

Phase 18 — AUTO-01, AUTO-02, AUTO-03.

Phase 33 (OCC-04..07): the same 3-layer body above is generalized behind
``run_occasion_cascade`` (public entry) / ``_run_cascade`` (shared body), so
the nightly review, morning briefing, and Sunday weekly review route through
it as ``occasion="nightly" | "morning" | "weekly_review"`` — parameters, not
separate pipelines. ``run_autonomous_tick`` keeps its exact pre-Phase-33
signature and delegates to ``_run_cascade`` with ``occasion=None`` after its
own tick-only gates (empty signals, change-detection) run. An occasion
bypasses both of those gates structurally (they fire on schedule/trigger, not
signal novelty) and shares the tick's ``OutreachLogStore`` namespace (D-18).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from core import prompt_loader

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")

# Cron */20 7-21 = ticks at 7:00, 7:20, 7:40, 8:00, ..., 21:00 = 43 ticks/day
# inclusive. (21 - 7) * 3 = 42 intervals, plus the 21:00 tick itself = 43.
_TICK_TOTAL_PER_DAY = 43

# Phase 33 (OCC-04..07) — the three occasions ``run_occasion_cascade`` serves,
# and the deterministic ``OutreachLogStore`` topic-key prefix each uses
# (D-18: one shared namespace with the tick, occasions and ticks as peers).
_OCCASIONS = ("nightly", "morning", "weekly_review")
_OCCASION_TOPIC_PREFIX = {
    "nightly": "nightly",
    "morning": "morning",
    "weekly_review": "weekly",
}

# D-14: ``defer_count >= 3`` force-fires on the next due tick.
_DEFER_FORCE_FIRE_THRESHOLD = 3

# Hours of user silence that count as a salient signal — used both by the
# Layer-0 empty gate (wake tick-brain on a silence-only day) and by
# _infer_trigger_type's "silence" label. Judgment about whether the silence
# is actually worth a message belongs to tick-brain, not this threshold.
_SILENCE_TRIGGER_HOURS = 8.0

# Phase 32 (MEM-04) — conversation-tail windows. The gather fetches the widest
# window any renderer needs (paid-compose); the triage-tight render re-trims
# further from that single fetch (no extra Firestore read per render site).
_COMPOSE_TAIL_MAX_HOURS = 48
_COMPOSE_TAIL_MAX_MESSAGES = 40
_TRIAGE_TAIL_MAX_HOURS = 24
_TRIAGE_TAIL_MAX_MESSAGES = 15
_TRIAGE_TAIL_MAX_CHARS = 240

# Phase 32 (MEM-04) — training_reality reconciliation window: today-3d..tomorrow
# inclusive (5 dates).
_TRAINING_REALITY_WINDOW_DAYS = 5

# Phase 32 Plan 08 (MEM-07) — home default for current_location derivation.
# Silent: the 99% case (Amit is in Tel Aviv) never produces any chatter or ask.
_HOME_LOCATION = "Tel Aviv"

# Conservative place-name extraction from directive free text (D-06 §Pattern
# 7, research [ASSUMED]). Deliberately narrow — only the two phrasings the
# research called out ("while I'm in X", "back from X") — under-detect rather
# than over-detect travel intent from prose that was never meant to encode a
# location. `text`/`condition_text` are both free-form (StandingDirectiveStore
# has no structured location field), so a false negative here just means the
# directive-alone case never resolves and the derivation falls through to
# either the calendar signal or the silent home default — never a wrong guess.
_DIRECTIVE_LOCATION_PATTERNS = (
    re.compile(r"while\s+i'?m\s+in\s+([A-Za-z][\w\s]{0,40})", re.IGNORECASE),
    re.compile(r"back\s+from\s+([A-Za-z][\w\s]{0,40})", re.IGNORECASE),
)
# A captured place-name phrase is cut at the first of these boundaries so a
# longer sentence fragment ("France for work this week") doesn't get treated
# as the literal place name — and capped at 3 words as a second conservative
# guard against over-capture.
_DIRECTIVE_LOCATION_STOP_RE = re.compile(
    r"[.,;!?]| for | during | until | because | so | while | and "
    r"| but | when | since ",
    re.IGNORECASE,
)

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
    # Phase 28 Plan 03 (HABIT-05 / D-15): pending habits/supplements are a valid tick trigger.
    # A non-empty list means a scheduled slot has passed without a check-off — salient signal.
    if situation.get("habit_pending"):
        return False
    # Recovery deviation IS a trigger (unlike training_status/acwr above):
    # recovery_metrics only emits flags when today genuinely breaks the 7-day
    # baseline band, so it can't over-fire — and the whole point is warning
    # BEFORE a hard session, which can't wait for Amit to message first.
    # Tick-brain is free (hours_since_contact precedent); the outreach log +
    # a recovery:<date> topic_key handle don't-repeat downstream.
    if (situation.get("recovery") or {}).get("flags"):
        return False
    # Phase 31 (DIR-03) — standing_directives is CONTEXT only, deliberately
    # excluded here, mirroring the training_status/acwr precedent above. An
    # active directive (e.g. "stop nagging about training while I'm in
    # France") must reach triage/compose as context so it can VETO whatever
    # else wakes the tick — but its own presence must never wake the free
    # tier. Adding a check here would let a directive spend money on its own,
    # defeating the D-11/SC-3 cost gate that is Klaus's entire cost model.
    #
    # Phase 32 (MEM-04/MEM-05) — conversation_tail and training_reality are
    # BOTH deliberately excluded here, same rationale as standing_directives
    # above:
    #   - conversation_tail: a recent conversation existing (nearly always
    #     true within 24-48h) is NOT itself a reason to speak up — it reaches
    #     triage/compose purely so continuity/tone can be judged, never as a
    #     trigger. Referencing it here would flip almost every tick to
    #     non-empty (Pitfall 3), defeating the D-11/SC-3 cost gate.
    #   - training_reality: a reconciled per-date training picture is CONTEXT
    #     for judging OTHER signals (e.g. "don't re-ask about a session
    #     already marked done") — never a reason to wake the free tier on its
    #     own, mirroring training_status/acwr/training_evidence above.
    #
    # Phase 32 Plan 08 (MEM-07) — location is deliberately excluded here too,
    # same rationale: a derived current_location (home OR a resolved/ambiguous
    # travel signal) is CONTEXT for weather/travel-time and the nightly
    # location-ask — never a reason to wake the free tier on its own. Even an
    # AMBIGUOUS derivation must not trigger here; the "still in <city>, Sir?"
    # ask only ever fires through the nightly review's own compose payload
    # (core/nightly_review.py), never through this Layer-0 gate.
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
    """(b) Overdue to-dos — replaces the TickTick gather (D-17 / TASK-05).

    Reads ``get_task_store().get_overdue(today_iso)`` — Amit's real Things 3 list
    under the default ``TASK_BACKEND`` — and returns a TickTick-compatible list of
    {"title": str, "due": str} dicts so the situation key 'ticktick_overdue' and
    all downstream triage/compose references need zero changes (Pitfall 3 — exact
    shape preserved).

    Note: Amit dates very few to-dos, so this is usually empty even when his list
    is long.  ``get_today_and_overdue`` carries an ``upcoming`` key that is the
    more useful signal.
    """
    try:
        from zoneinfo import ZoneInfo
        from memory.firestore_db import get_task_store
        today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        store = get_task_store()
        tasks = store.get_overdue(today_iso) or []
        return [{"title": t["title"], "due": t.get("due_date", "")} for t in tasks]
    except Exception:
        logger.warning("autonomous: native overdue gather failed", exc_info=True)
        return []


def _gather_habit_adherence(now: datetime, project_id: str, database: str) -> list[dict]:
    """Layer-0 gather: today's pending habits/supplements with streak (D-15/D-16).

    Returns list of pending items (HabitStore doc shape, keyed "id"):
    [{"id", "name", "type", "slot", "streak", "dose", ...}, ...]
    Filtered by CoachingTopicStore dedup (D-17): items already nudged today are excluded.
    Empty list on any error (sentinel pattern — a HabitStore failure must never break the tick).

    Phase 28 Plan 03 (HABIT-05).
    """
    try:
        from zoneinfo import ZoneInfo
        from memory.firestore_db import HabitStore, CoachingTopicStore
        # Honour the caller's clock (the tick passes one `now` to every gather);
        # a fresh datetime.now() here silently ignored the parameter.
        today_iso = now.astimezone(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        store = HabitStore(project_id=project_id, database=database)
        pending = store.get_pending_today(today_iso)
        # D-17: filter out items already nudged today (per-item-per-day dedup).
        # HabitStore docs are keyed "id" — reading "habit_id" here KeyError'd on
        # every tick since Phase 28 shipped, silently disabling all habit nudges
        # (found 2026-07-05 in production logs). Keep a habit_id fallback for
        # any caller-normalized items.
        cts = CoachingTopicStore(project_id=project_id, database=database)
        return [
            h for h in pending
            if not cts.has_topic(
                today_iso, f"habit-nudge:{h.get('id', h.get('habit_id'))}:{today_iso}"
            )
        ]
    except Exception:
        logger.warning("autonomous: habit_adherence gather failed", exc_info=True)
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


def _gather_standing_directives(project_id: str, database: str) -> list:
    """(o) Phase 31 (DIR-03) — Amit's active standing directives, CONTEXT only.

    Mirrors the ``_gather_due_followups`` try/except -> ``[]`` sentinel shape.
    CRITICAL: this gather is deliberately excluded from ``_is_empty_signals``
    (see the comment at that function's ``standing_directives`` note) — a
    directive's mere presence must never wake the free tier on its own
    (Pitfall 4). It reaches the triage prompt and both Layer-2 composes purely
    as context so a directive like "stop nagging about training while I'm in
    France" can veto (topic-scoped) whatever DOES wake the tick.
    """
    try:
        from memory.firestore_db import StandingDirectiveStore
        sds = StandingDirectiveStore(project_id=project_id, database=database)
        return sds.list_active()
    except Exception:
        logger.warning("autonomous: standing_directives gather failed", exc_info=True)
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


def _gather_recovery() -> dict:
    """(m) Recovery deviation vs 7-day HRV/RHR baseline (Pattern C sentinel).

    Non-empty (has "flags") only when today genuinely deviates — rare by
    construction (core/recovery_metrics.py silent-omit), so it is safe as a
    Layer-0 trigger, unlike raw training_status/acwr context.
    """
    try:
        from datetime import datetime as _dt
        from core.recovery_metrics import get_recovery_deviation
        today_iso = _dt.now(_TZ).date().isoformat()
        return get_recovery_deviation(today_iso) or {}
    except Exception:
        logger.warning("autonomous: recovery gather failed", exc_info=True)
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


def _gather_training_evidence(now: datetime, project_id: str, database: str) -> dict:
    """(n) Today's training ground truth — what was ACTUALLY done (Pattern C sentinel).

    Reads three date-indexed stores for today and returns a compact summary so
    the triage and compose layers can check evidence before assuming a planned
    session happened (or asking "how was the workout?" about one that didn't):

      - ``training_log_today``: TrainingLogStore rows (planned/completed/skipped)
      - ``strength_today``:     Hevy sessions (StrengthSessionStore)
      - ``runs_today``:         Garmin runs (RunDetailStore)

    Empty lists ARE evidence — nothing was logged. Compaction matters: the
    strength/run stores hold full per-set / per-lap detail that must never be
    dumped into a prompt. CONTEXT only, never a trigger (same rule as
    training_status/acwr — see _is_empty_signals).

    Returns ``{}`` on any error so a store failure never breaks the tick.
    """
    try:
        from memory.firestore_db import (
            RunDetailStore,
            StrengthSessionStore,
            TrainingLogStore,
        )
        today_iso = now.astimezone(_TZ).date().isoformat()

        log_rows = TrainingLogStore(
            project_id=project_id, database=database
        ).get_by_date(today_iso)
        training_log_today = [
            {
                "slot": r.get("slot"),
                "type": r.get("type"),
                "planned": r.get("planned"),
                "completed": r.get("completed"),
                "skipped_reason": r.get("skipped_reason"),
                "source": r.get("source"),
            }
            for r in log_rows
        ]

        strength_rows = StrengthSessionStore(
            project_id=project_id, database=database
        ).get_range(today_iso, today_iso)
        strength_today = [
            {
                "title": w.get("title"),
                "start_time": w.get("start_time"),
                "duration_min": w.get("duration_min"),
                "exercise_count": len(w.get("exercises") or []),
                "total_volume_kg": w.get("total_volume_kg"),
            }
            for w in strength_rows
        ]

        run_rows = RunDetailStore(
            project_id=project_id, database=database
        ).get_range(today_iso, today_iso)
        runs_today = [
            {
                "type": r.get("type"),
                "distance_m": r.get("distance_m"),
                "duration_sec": r.get("duration_sec"),
                "avg_pace_sec_per_km": r.get("avg_pace_sec_per_km"),
            }
            for r in run_rows
        ]

        return {
            "training_log_today": training_log_today,
            "strength_today": strength_today,
            "runs_today": runs_today,
        }
    except Exception:
        logger.warning("autonomous: training_evidence gather failed", exc_info=True)
        return {}


def _gather_conversation_tail(now: datetime, project_id: str, database: str) -> list:
    """(o2) Phase 32 (MEM-04) — recent conversation tail, CONTEXT only.

    Fetches the WIDEST window any renderer needs (48h/<=40 msgs — the
    paid-compose cap) once here; the triage-tight render (24h/<=15/240-char)
    and the paid-compose-wide render each re-trim from this single fetch, so
    one Firestore read serves both render sites (no duplicate reads).

    User id resolution mirrors ``_gather_hours_since_contact``'s
    ``TELEGRAM_ALLOWED_USER_IDS`` convention (first entry, single-user
    deployment).

    CONTEXT only, never a trigger (see ``_is_empty_signals``) — a
    conversation existing is not itself a reason to wake the free tier,
    mirroring the ``standing_directives`` precedent (Phase 31).

    Sentinel ``[]`` on any failure (including an unset/unparseable user-id
    env var) — never raises.
    """
    try:
        from memory.firestore_conversation import FirestoreConversationStore
        raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")[0].strip()
        if not raw:
            logger.warning(
                "autonomous: TELEGRAM_ALLOWED_USER_IDS unset — "
                "conversation_tail unknown"
            )
            return []
        user_id = int(raw)
        store = FirestoreConversationStore(project_id=project_id, database=database)
        return store.get_recent_window(
            user_id,
            hours=_COMPOSE_TAIL_MAX_HOURS,
            max_messages=_COMPOSE_TAIL_MAX_MESSAGES,
        )
    except Exception:
        logger.warning("autonomous: conversation_tail gather failed", exc_info=True)
        return []


def _gather_training_reality(now: datetime, project_id: str, database: str) -> dict:
    """(o3) Phase 32 (MEM-04) — reconciled per-date training reality, CONTEXT only.

    Reconciliation window: today-3d..tomorrow (5 dates). Assembles the four
    inputs ``core.training_checkin.build_training_reality`` (Plan 04) expects:

      - **planned intent** — ``training_checkin.planned_sessions_for(date_iso)``
        (the weekly_split recurring template).
      - **calendar intent** — reuses ``_gather_calendar``'s TODAY events only.
        A Training-calendar range query for the other 4 dates isn't wired
        anywhere else in this codebase, so those dates fall back to
        weekly_split-only planned intent; per D-01, calendar only OVERRIDES
        the template when a same-day event exists, so this is still correct,
        just narrower than it could be for non-today dates.
      - **hard evidence + self-report** — loops the existing single-date
        ``_gather_training_evidence(date, project_id, database)`` across the
        window (Pattern 4 — reused verbatim, no new evidence-shape
        derivation).

    Calls the pure ``build_training_reality(...)`` reconciler (Plan 04) to
    merge all four sources under the locked D-01/D-02 precedence.

    CONTEXT only, never a trigger (see ``_is_empty_signals``) — mirrors the
    ``training_status``/``acwr``/``standing_directives`` precedent: a
    reconciled training picture must never wake the free tier on its own.

    Sentinel ``{}`` on any failure — never raises.
    """
    try:
        from core.training_checkin import build_training_reality, planned_sessions_for

        today = now.astimezone(_TZ).date()
        dates = [
            (today + timedelta(days=offset - 3)).isoformat()
            for offset in range(_TRAINING_REALITY_WINDOW_DAYS)
        ]
        today_iso = today.isoformat()

        planned_by_date = {d: planned_sessions_for(d) for d in dates}

        # Reuse the existing calendar gather for today's events — no second
        # calendar API call is issued for the other 4 dates (see docstring).
        today_calendar_events = _gather_calendar(now)
        calendar_by_date = {
            d: (today_calendar_events if d == today_iso else []) for d in dates
        }

        evidence_by_date: dict[str, dict] = {}
        self_report_by_date: dict[str, dict] = {}
        for d in dates:
            d_dt = datetime.fromisoformat(d).replace(tzinfo=_TZ)
            ev = _gather_training_evidence(d_dt, project_id, database)
            evidence_by_date[d] = {
                "strength_today": ev.get("strength_today", []),
                "runs_today": ev.get("runs_today", []),
            }
            self_report_by_date[d] = {
                "training_log_today": ev.get("training_log_today", []),
            }

        return build_training_reality(
            dates,
            planned_by_date,
            calendar_by_date,
            evidence_by_date,
            self_report_by_date,
            today_iso,
        )
    except Exception:
        logger.warning("autonomous: training_reality gather failed", exc_info=True)
        return {}


def _location_from_calendar(calendar_events: list) -> str | None:
    """First today-event location that isn't home — the calendar travel signal.

    A same-day event with a real ``location`` field not naming Tel Aviv is
    treated as a confident travel candidate: unlike a directive, a calendar
    event is dated and scoped to today, so it needs no corroboration to
    override the home default (D-06 §Pattern 7).
    """
    for event in calendar_events or []:
        try:
            loc = (event.get("location") or "").strip()
        except AttributeError:
            continue
        if loc and _HOME_LOCATION.lower() not in loc.lower():
            return loc
    return None


def _location_from_directives(active_directives: list) -> str | None:
    """First place-name matched out of active directive free text.

    Deliberately narrow regex (see ``_DIRECTIVE_LOCATION_PATTERNS``) — a
    directive alone is never enough to resolve current_location (see
    ``derive_current_location``'s "unclear trip-end" ambiguity path); this
    only supplies the ask's ``candidate`` city.
    """
    for directive in active_directives or []:
        if not isinstance(directive, dict):
            continue
        for field in ("text", "condition_text"):
            value = directive.get(field) or ""
            for pattern in _DIRECTIVE_LOCATION_PATTERNS:
                match = pattern.search(value)
                if not match:
                    continue
                candidate = _DIRECTIVE_LOCATION_STOP_RE.split(match.group(1))[0].strip()
                candidate = " ".join(candidate.split()[:3])
                if candidate:
                    return candidate
    return None


def _same_place(a: str, b: str) -> bool:
    """Conservative place-name equality — exact match or substring containment
    (e.g. calendar "Charles de Gaulle Airport, Paris" vs directive "Paris")."""
    a_norm, b_norm = a.strip().lower(), b.strip().lower()
    return bool(a_norm) and bool(b_norm) and (
        a_norm == b_norm or a_norm in b_norm or b_norm in a_norm
    )


def derive_current_location(calendar_events: list, active_directives: list) -> dict:
    """Pure Pattern 7 heuristic (D-06, research [ASSUMED]) — never guesses.

    Reads only already-Amit-scoped sources (today's calendar events, active
    standing directives) — no raw tool output, no new spoofing surface
    (T-32-16). Conservative, under-detect rather than over-detect:

    - No travel signal anywhere               -> home, silently.
    - Calendar signal alone                   -> that location overrides home
      (a same-day dated event needs no corroboration).
    - Calendar + directive AGREE               -> that location (resolved).
    - Calendar + directive CONFLICT            -> ambiguous (never guess which).
    - Directive signal alone, no calendar      -> ambiguous ("unclear trip-end"
      corroboration — the directive's own presence doesn't confirm Amit is
      still there today, or that he hasn't quietly come home).

    Never raises — malformed input (``None``, non-list) degrades to "no
    signal" rather than propagating.

    Returns:
        ``{"location": <str>}`` when resolved (may be the home default).
        ``{"ambiguous": True, "candidate": <str|None>}`` when the caller must
        ask rather than guess (D-06) — ``candidate`` is the best-guess city
        for phrasing the ask, never served as a location itself.
    """
    try:
        calendar_candidate = _location_from_calendar(calendar_events)
    except Exception:
        calendar_candidate = None
    try:
        directive_candidate = _location_from_directives(active_directives)
    except Exception:
        directive_candidate = None

    if not calendar_candidate and not directive_candidate:
        return {"location": _HOME_LOCATION}

    if calendar_candidate and directive_candidate:
        if _same_place(calendar_candidate, directive_candidate):
            return {"location": calendar_candidate}
        return {"ambiguous": True, "candidate": calendar_candidate}

    if calendar_candidate:
        return {"location": calendar_candidate}

    # Directive signal alone — unclear trip-end, never guess.
    return {"ambiguous": True, "candidate": directive_candidate}


def _gather_location(situation: dict) -> dict:
    """(o4) Phase 32 Plan 08 (MEM-07) — derived current_location, CONTEXT only.

    Wraps ``derive_current_location`` over the already-gathered ``calendar``
    (today's events) and ``standing_directives`` values on ``situation`` — no
    new Calendar API call or Firestore read. Deliberately called AFTER
    ``gather_situation``'s thread pool completes (not submitted as one of its
    concurrent jobs) so it can safely read those two sources' now-finished
    results without a race against their own in-flight gathers.

    CONTEXT only, never a trigger (see ``_is_empty_signals``) — deriving a
    location must never wake the free tier on its own (T-32-17).

    Sentinel — the home default dict — on any failure. Never raises.
    """
    try:
        return derive_current_location(
            situation.get("calendar") or [],
            situation.get("standing_directives") or [],
        )
    except Exception:
        logger.warning("autonomous: location derivation failed", exc_info=True)
        return {"location": _HOME_LOCATION}


def gather_situation(now: datetime) -> dict:
    """Layer 0 — aggregate situation snapshot from 14 sources, fanned out in parallel.

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
        # Phase 28 Plan 03 (HABIT-05 / D-15/D-16/D-17): pending habit/supplement adherence
        "habit_pending": lambda: _gather_habit_adherence(now, project_id, database),
        # Recovery deviation vs 7-day baseline — trigger only when flags fire.
        "recovery": _gather_recovery,
        # Today's completed-training ground truth (Garmin runs + Hevy sessions
        # + training log) — CONTEXT only, not a trigger (see _is_empty_signals).
        "training_evidence": lambda: _gather_training_evidence(
            now, project_id, database
        ),
        # Phase 31 (DIR-03): Amit's active standing directives — CONTEXT only,
        # never a trigger (see _is_empty_signals).
        "standing_directives": lambda: _gather_standing_directives(
            project_id, database
        ),
        # Phase 32 (MEM-04): recent conversation tail — CONTEXT only, never a
        # trigger (see _is_empty_signals).
        "conversation_tail": lambda: _gather_conversation_tail(
            now, project_id, database
        ),
        # Phase 32 (MEM-04): reconciled training reality (today-3d..tomorrow)
        # — CONTEXT only, never a trigger (see _is_empty_signals).
        "training_reality": lambda: _gather_training_reality(
            now, project_id, database
        ),
    }

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="gather") as pool:
        futures = {pool.submit(fn): key for key, fn in jobs.items()}
        for fut in as_completed(futures):
            # _gather_* functions never raise (sentinel on failure), so
            # fut.result() is safe; a raise here would indicate a programming
            # error and should surface loudly.
            gathered[futures[fut]] = fut.result()

    # Phase 32 Plan 08 (MEM-07): current_location derived from the calendar +
    # standing_directives results the pool just finished above. Deliberately
    # NOT one of the jobs dict entries — the pool's as_completed loop gives no
    # ordering guarantee, so a concurrent "location" job could read either
    # source before its own gather finished (a real race, not a hypothetical
    # one). Running it here, sequentially, after the pool closes reads their
    # completed values safely with zero extra Calendar/Firestore calls.
    # CONTEXT only, never a trigger (see _is_empty_signals).
    gathered["location"] = _gather_location(gathered)

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


def _format_now_block(situation: dict) -> str:
    """Render the ``now_context`` time block shared by triage AND both
    Layer-2 composes.

    The layer that writes the outgoing message needs the same clock the
    triage layer judged with — otherwise it composes date-aware but
    time-blind (can't tell whether a planned session is behind or ahead).
    One helper, three call sites, no drift.
    """
    nc = situation.get("now_context") or {}
    return (
        f"now: {nc.get('now_local', '')}\n"
        f"tick {nc.get('tick_index', 0)} of {nc.get('tick_total', _TICK_TOTAL_PER_DAY)}\n"
        f"last tick at: {nc.get('last_tick_at', '')}"
    )


def _situation_now(situation: dict) -> datetime:
    """Best-effort datetime reconstruction from ``situation['now_context']['now_iso']``.

    The tail/training_reality renderers need a clock (for the 24h/48h cutoff
    and "today"/"tomorrow" boundaries) but neither ``_build_triage_prompt``
    nor the compose functions carry the original ``now`` datetime through —
    only the already-rendered ``now_context`` dict. Falls back to the current
    wall clock (Asia/Jerusalem) on any parse failure — never raises.
    """
    now_iso = (situation.get("now_context") or {}).get("now_iso", "")
    try:
        return datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.now(_TZ)


def _trim_conversation_tail(
    tail: list[dict],
    now: datetime,
    *,
    hours: float,
    max_messages: int,
    max_chars: int | None = None,
) -> list[dict]:
    """Re-trim the widest-window conversation_tail gather to a render-specific cap.

    The gather (``_gather_conversation_tail``) already fetches the widest
    window any renderer needs (48h/<=40 msgs, the paid-compose cap) in ONE
    Firestore read; each render site re-trims from that single fetch here —
    the triage-tight render (24h/<=15/240-char) and the paid-compose-wide
    render (48h/<=40, uncapped char) both derive from the same list, no extra
    read. Malformed/legacy ``ts`` values are tolerated (kept by position),
    mirroring ``FirestoreConversationStore.get_recent_window``'s own leniency.
    """
    if not tail:
        return []
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=hours)
    trimmed: list[dict] = []
    for m in tail:
        ts_raw = m.get("ts")
        if ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except (ValueError, TypeError):
                pass  # malformed ts — tolerate, keep by position
        content = str(m.get("content", ""))
        if max_chars is not None and len(content) > max_chars:
            content = content[:max_chars]
        trimmed.append({"role": m.get("role", ""), "content": content})
    return trimmed[-max_messages:]


def _render_conversation_tail_tight(tail: list[dict], now: datetime) -> str:
    """Triage-tight render (MEM-04): 24h / <=15 msgs / 240-char-per-message cap."""
    trimmed = _trim_conversation_tail(
        tail,
        now,
        hours=_TRIAGE_TAIL_MAX_HOURS,
        max_messages=_TRIAGE_TAIL_MAX_MESSAGES,
        max_chars=_TRIAGE_TAIL_MAX_CHARS,
    )
    if not trimmed:
        return "(no recent messages)"
    return "\n".join(f"{m['role']}: {m['content']}" for m in trimmed)


def _render_conversation_tail_wide(tail: list[dict], now: datetime) -> str:
    """Paid-compose-wide render (MEM-04): 48h / <=40 msgs, no char cap."""
    trimmed = _trim_conversation_tail(
        tail, now, hours=_COMPOSE_TAIL_MAX_HOURS, max_messages=_COMPOSE_TAIL_MAX_MESSAGES,
    )
    if not trimmed:
        return "(no recent messages)"
    return "\n".join(f"{m['role']}: {m['content']}" for m in trimmed)


def _render_training_reality_tight(training_reality: dict, now: datetime) -> str:
    """Triage-tight render (MEM-04, Research Open Question 2): today + tomorrow
    only, terminal status strings per slot — NO evidence detail. The triage
    layer's job is to know NOT to ask about something already resolved; a
    status string alone accomplishes that within the triage char discipline.
    """
    if not training_reality:
        return "(no training reality data)"
    today = now.astimezone(_TZ).date()
    dates = (today.isoformat(), (today + timedelta(days=1)).isoformat())
    lines: list[str] = []
    for date_iso in dates:
        entry = training_reality.get(date_iso) or {}
        slots = entry.get("slots") or {}
        if not slots:
            continue
        slot_str = ", ".join(f"{slot}: {status}" for slot, status in slots.items())
        lines.append(f"{date_iso}: {slot_str}")
    return "\n".join(lines) if lines else "(no sessions planned today/tomorrow)"


def _render_training_reality_wide(training_reality: dict) -> str:
    """Paid-compose-wide render (MEM-04): full today-3d..tomorrow window with
    evidence detail (session titles/volumes/pace) for coaching quality — the
    version prompts/autonomous.md's Layer-2 compose consumes.
    """
    if not training_reality:
        return "(no training reality data)"
    lines: list[str] = []
    for date_iso in sorted(training_reality.keys()):
        entry = training_reality.get(date_iso) or {}
        slots = entry.get("slots") or {}
        slot_str = ", ".join(f"{slot}: {status}" for slot, status in slots.items()) or "(no sessions)"
        evidence = entry.get("evidence") or {}
        detail_parts: list[str] = []
        for w in evidence.get("strength_today") or []:
            vol = w.get("total_volume_kg", "")
            detail_parts.append(f"strength: {w.get('title', '')} ({vol}kg)".strip())
        for r in evidence.get("runs_today") or []:
            pace = r.get("avg_pace_sec_per_km")
            pace_str = f" @ {pace}s/km" if pace else ""
            detail_parts.append(f"run: {r.get('distance_m', '')}m{pace_str}")
        detail_str = f" [{'; '.join(detail_parts)}]" if detail_parts else ""
        lines.append(f"{date_iso}: {slot_str}{detail_str}")
    return "\n".join(lines)


def _first_prompt_line(text: str) -> str:
    """Return the first non-blank, non-HTML-comment line of a rendered prompt.

    D-35 occasion prompts (``prompts/{nightly,morning,weekly}_occasion.md``)
    open with a one-line HTML comment naming the decision they implement —
    that comment is bookkeeping for humans reading the file, never meant for
    the model. Used by the occasion header in ``_build_triage_prompt``.
    """
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        return stripped
    return ""


# --------------------------------------------------------------------------- #
# CR-01 (33-REVIEW.md) — capped per-occasion digest for the Layer-1 (tick-    #
# brain) triage prompt. The tick-brain has NO tools, so it genuinely cannot   #
# see anything occasion-specific unless it is rendered here; Layer 2 is       #
# agentic and tool-fetches what it needs (out of scope for this fix — see    #
# the review's PRODUCTION CORRECTION block).                                 #
# --------------------------------------------------------------------------- #

# Defense-in-depth hard cap: the per-field clamps below already keep the
# digest's cost FIXED regardless of source-data size (counts instead of full
# lists, single clamped strings instead of free-text dumps) — this final
# char cap is a backstop, not the primary mechanism, so a future field added
# without a clamp still cannot blow the Groq budget (test_token_budget.py).
_OCCASION_DIGEST_MAX_CHARS = 700


def _clamp_text(value, max_chars: int = 80) -> str:
    """Coerce ``value`` to a single-line string, hard-clamped to ``max_chars``.

    Collapses internal whitespace/newlines so one field can never smuggle in
    a multi-line block. Every free-text field in the occasion digest (a
    calendar summary, a coaching-topic key) goes through this.
    """
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _earliest_event(events: "list[dict] | None") -> "dict | None":
    """Return the calendar event with the earliest ``start`` (ISO 8601).

    Best-effort: a missing/unparseable ``start`` sorts last rather than
    raising — a malformed upstream event must never break the digest.
    """
    if not events:
        return None

    def _key(evt: dict) -> datetime:
        start = (evt or {}).get("start") or ""
        try:
            return datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except ValueError:
            return datetime.max.replace(tzinfo=timezone.utc)

    return min(events, key=_key)


def _format_event_time(event: "dict | None") -> str:
    """Render an event's local HH:MM start time, or ``""`` if unparseable/absent."""
    if not event:
        return ""
    start = event.get("start") or ""
    try:
        dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        return dt.astimezone(_TZ).strftime("%H:%M")
    except ValueError:
        return ""


def _digest_morning(situation: dict) -> "list[str]":
    """CR-01 morning digest lines — source: ``morning_briefing._gather_data``'s
    ``today_data`` (merged flat into ``situation`` by ``run_occasion_cascade``).
    """
    lines: list[str] = []
    garmin = situation.get("garmin")
    if garmin is not None:
        if situation.get("garmin_missing"):
            # D-11 — name the gap, never silently omit it.
            lines.append("sleep: Garmin data unavailable today")
        else:
            sleep_score = garmin.get("sleep_score")
            sleep_hours = garmin.get("sleep_hours")
            if sleep_score is not None or sleep_hours is not None:
                lines.append(f"sleep: score={sleep_score} hours={sleep_hours}")
    tasks = situation.get("tasks")
    if isinstance(tasks, dict) and ("today" in tasks or "overdue" in tasks):
        lines.append(
            f"tasks: {len(tasks.get('today') or [])} today, "
            f"{len(tasks.get('overdue') or [])} overdue"
        )
    weather = situation.get("weather")
    if weather:
        current = weather.get("current") or {}
        if current:
            lines.append(
                "weather: " + _clamp_text(
                    f"{current.get('condition', '')}, {current.get('temp_c', '')}°C",
                    60,
                )
            )
    first_time = _format_event_time(_earliest_event(situation.get("calendar")))
    if first_time:
        lines.append(f"first calendar event: {first_time}")
    if "weekly_review_due_today" in situation:
        # D-20 — "stay light on training, the weekly is at 10:00" signal.
        lines.append(
            f"weekly review due today: {bool(situation.get('weekly_review_due_today'))}"
        )
    return lines


def _digest_nightly(situation: dict) -> "list[str]":
    """CR-01 nightly digest lines — source: nightly_review's
    ``{"journal": journal, "tomorrow": tomorrow, **structured}`` (merged flat
    into ``situation`` by ``run_occasion_cascade``).
    """
    lines: list[str] = []
    if "journal" in situation:
        # D-07 — presence only, never content (the journal is private memory).
        lines.append(f"journal: {'written' if situation.get('journal') else 'missing'}")
    tomorrow = situation.get("tomorrow") or {}
    planned = situation.get("planned_workouts") or tomorrow.get("planned_workouts") or {}
    if planned:
        slot_labels = []
        for slot in ("am", "pm"):
            entry = planned.get(slot) or {}
            modality = entry.get("modality") or entry.get("type")
            if modality and str(modality).strip().lower() not in ("", "rest", "off"):
                slot_labels.append(f"{slot}={_clamp_text(modality, 30)}")
        lines.append(
            "tomorrow planned: " + (", ".join(slot_labels) if slot_labels else "rest/none")
        )
    tomorrow_events = situation.get("tomorrow_events")
    if tomorrow_events is None:
        tomorrow_events = tomorrow.get("calendar")
    first_event = _earliest_event(tomorrow_events)
    if first_event:
        first_time = _format_event_time(first_event)
        first_summary = _clamp_text(first_event.get("summary"), 50)
        detail = " ".join(part for part in (first_time, first_summary) if part)
        if detail:
            lines.append(f"tomorrow's first commitment: {detail}")
    if "tomorrow_tasks_today" in situation or "tomorrow_tasks_overdue" in situation:
        lines.append(
            f"tomorrow tasks: {len(situation.get('tomorrow_tasks_today') or [])} due, "
            f"{len(situation.get('tomorrow_tasks_overdue') or [])} overdue"
        )
    return lines


# The five projection facets _gather_week_data always computes (never
# data-dependent), so counting "tracked" facets here is itself a bounded,
# fixed-size operation regardless of how much history exists per facet.
_WEEKLY_PROJECTION_FACETS = (
    "bench_press_1rm", "squat_1rm", "threshold_pace", "push_ups", "pull_ups",
)


def _digest_weekly(situation: dict) -> "list[str]":
    """CR-01 weekly_review digest lines — source: the full ``week_data``
    (merged flat into ``situation`` by ``run_occasion_cascade``; advisory_only
    so Layer 1 cannot suppress the send, but the digest still shapes the
    draft it hands to Layer 2).
    """
    lines: list[str] = []
    training_log = situation.get("training_log")
    if training_log is not None:
        lines.append(f"sessions logged this week: {len(training_log)}")
    elif situation.get("training_log_error"):
        lines.append("sessions logged this week: unavailable (TrainingLogStore error)")
    projections = situation.get("projections")
    if projections:
        tracked = [
            result for facet, result in projections.items()
            if facet in _WEEKLY_PROJECTION_FACETS
            and isinstance(result, dict) and result.get("confidence") != "no_data"
        ]
        if tracked:
            on_track = sum(1 for result in tracked if result.get("on_track"))
            lines.append(f"projections: {on_track}/{len(tracked)} facets on track")
    anomalies = situation.get("coaching_topics_included")
    if anomalies:
        lines.append("flagged: " + _clamp_text(anomalies[0], 70))
    return lines


_OCCASION_DIGEST_BUILDERS = {
    "morning": _digest_morning,
    "nightly": _digest_nightly,
    "weekly_review": _digest_weekly,
}


def _occasion_digest(occasion: str, situation: dict) -> str:
    """CR-01 (33-REVIEW.md) — a SHORT, capped, human-readable digest of the
    occasion's own Layer-0 gather, rendered into the Layer-1 triage prompt
    ONLY on occasion runs (a plain ``*/20`` tick never carries an
    ``occasion`` key, so this is structurally unreachable for it and the
    tick's token total is unaffected — see test_token_budget.py).

    Returns ``""`` for an unknown occasion or when the occasion contributed
    no renderable fields — same "no data -> no block" discipline as the
    ``conversation_tail``/``training_reality`` blocks above.
    """
    builder = _OCCASION_DIGEST_BUILDERS.get(occasion)
    if builder is None:
        return ""
    lines = builder(situation)
    if not lines:
        return ""
    body = "\n".join(lines)
    if len(body) > _OCCASION_DIGEST_MAX_CHARS:
        body = body[: _OCCASION_DIGEST_MAX_CHARS - 1].rstrip() + "…"
    return f"\nOccasion digest:\n{body}\n"


def _build_triage_prompt(
    situation: dict, triage_system: str, *, occasion_prompt: str = "",
) -> str:
    """Build the user-message content for the triage call.

    ``triage_system`` is currently unused — it's passed to
    ``TickBrain.think(..., system_override=triage_system)`` separately, and
    the parameter is kept here so callers don't have to remember which prompt
    template was loaded for which call site. WARNING 4: when
    ``hours_since_contact`` is None, the prompt renders it as ``"unknown"``,
    not ``"999.0"`` (which the LLM would interpret as "Sir vanished").

    ``occasion_prompt`` (plan 33-04, D-35): rendered verbatim's FIRST LINE
    only into a short occasion header, and ONLY when ``situation["occasion"]``
    is set — a plain ``*/20`` tick never carries an ``occasion`` key, so the
    entire occasion branch at the end of this function is unreachable for it
    and the output stays byte-identical to the pre-Phase-33 render.
    """
    _ = triage_system  # reserved
    # Lazy import (avoids an import cycle — core.tools imports core.autonomous
    # indirectly via other call sites) — mirrors the Plan 03 convention.
    from core.tools import render_standing_directives_block

    # CR-01 (33-REVIEW.md) — determined up-front (not just at the addendum
    # branch below) so the tick-only keys can be dropped from `snap` on an
    # occasion run before it's serialized.
    occasion = situation.get("occasion")

    standing_directives = situation.get("standing_directives") or []
    snap = {
        "calendar": situation.get("calendar", []),
        "ticktick_overdue": situation.get("ticktick_overdue", []),
        "due_followups": situation.get("due_followups", []),
        # PHASE 19 — new context surfaces (must stay in sync with
        # _compose_layer2 and tests/test_evals.py::TestFixtureSchema).
        "training_status": situation.get("training_status", {}),
        "acwr": situation.get("acwr", {"ratio": None}),
        # Phase 28 Plan 03 (HABIT-05 / D-15/D-16): pending habit/supplement adherence
        # with streak context so tick-brain can weight long streaks at risk (D-16).
        "habit_pending": situation.get("habit_pending", []),
        # Recovery deviation vs 7-day baseline — {} unless flags fired today.
        "recovery": situation.get("recovery", {}),
        # Today's completed-training ground truth — never assume a planned
        # calendar session happened (or didn't) without checking this.
        "training_evidence": situation.get("training_evidence", {}),
        # Phase 31 (DIR-03) — active standing directives, compact JSON for the
        # snapshot; the Step-0 STANDING ORDERS veto reads this.
        "standing_directives": json.loads(
            render_standing_directives_block(standing_directives, style="json")
        ),
    }
    if not occasion:
        # CR-01 — these three keys are meaningless on a scheduled occasion
        # ("since last tick" has no meaning outside the */20 cadence); drop
        # them so the tick-only budget doesn't fund context an occasion
        # can't use. Correctness/tidiness (~36 tokens total), NOT the
        # occasion digest's funding source below.
        snap["unread_email_count"] = situation.get("unread_email_count", 0)
        snap["meals_since_last_tick"] = situation.get("meals_since_last_tick", [])
        hsc = situation.get("hours_since_contact")
        snap["hours_since_contact"] = "unknown" if hsc is None else hsc
    snap_json = json.dumps(snap, indent=2, ensure_ascii=False)

    self_state = situation.get("self_state") or {}
    self_state_block = (
        f"current_focus: {self_state.get('current_focus', '')}\n"
        f"mood: {self_state.get('mood', '')}"
    )

    journal = situation.get("recent_journal_digest") or "(no recent journal entries)"
    now_context_block = _format_now_block(situation)
    outreach_today = situation.get("today_outreach_log") or []
    outreach_block = ", ".join(outreach_today) if outreach_today else "(none yet)"
    directives_block = render_standing_directives_block(
        standing_directives, style="prose"
    ) or "(none active)"

    # Phase 32 (MEM-04) — triage-tight renders: 24h/<=15/240-char tail;
    # today+tomorrow-only terminal-status training_reality (no evidence detail).
    # Groq tick-efficiency (Task 4, MEM-05): render these two heavy blocks only
    # when salient, so an ordinary/quiet tick sends a lean prompt — a rest day
    # with nothing planned/logged and no genuinely recent exchange contributes
    # NEITHER block (the label/heading line is dropped entirely, not just an
    # empty/"(no data)" body). A busy day (session present + recent exchange)
    # still renders both blocks exactly as before — this is average-case
    # relief, not a cap on the worst case (see test_token_budget.py MEM-05).
    now_for_render = _situation_now(situation)
    conversation_tail = situation.get("conversation_tail") or []
    training_reality = situation.get("training_reality") or {}

    conversation_tail_block = (
        f"Recent conversation with Amit (last 24h, up to 15 messages):\n"
        f"{_render_conversation_tail_tight(conversation_tail, now_for_render)}\n\n"
        if conversation_tail
        else ""
    )

    # Groq tick-efficiency fix-wave Finding 2: restrict the salience predicate
    # to the same today+tomorrow window _render_training_reality_tight actually
    # renders. training_reality spans today-3d..tomorrow (5 dates), but the
    # tight render only ever shows today/tomorrow — without this restriction a
    # session on a PAST in-window date (e.g. today-2) would make _has_training_
    # session True while the render itself finds nothing in today/tomorrow,
    # producing a block that renders with an empty "(no sessions planned
    # today/tomorrow)" body for no reason.
    _render_today = now_for_render.astimezone(_TZ).date()
    _render_dates = {
        _render_today.isoformat(),
        (_render_today + timedelta(days=1)).isoformat(),
    }
    _has_training_session = any(
        any(
            status not in (None, "", "rest")
            for status in ((entry or {}).get("slots") or {}).values()
        )
        for date_iso, entry in training_reality.items()
        if date_iso in _render_dates
    )
    training_reality_block = (
        f"Training reality (today + tomorrow, terminal status only):\n"
        f"{_render_training_reality_tight(training_reality, now_for_render)}\n"
        if _has_training_session
        else ""
    )

    base_prompt = (
        f"Situation snapshot:\n{snap_json}\n\n"
        f"My self-state:\n{self_state_block}\n\n"
        f"My recent journal:\n{journal}\n\n"
        f"Time context:\n{now_context_block}\n\n"
        f"Topics I have already raised today:\n{outreach_block}\n\n"
        f"Active standing directives:\n{directives_block}\n\n"
        f"{conversation_tail_block}{training_reality_block}"
    )

    # Phase 33 (D-01/D-02/D-03, D-35) — occasion judgment addendum, rendered
    # into the USER message ONLY on occasion runs. A plain tick's
    # ``situation`` never carries an ``occasion`` key, so this branch is
    # structurally unreachable for it (33-03's token-budget arbitration kept
    # this content off the always-on Groq system-prompt path — see
    # prompts/occasion_triage_addendum.md's header comment). ``occasion`` is
    # already resolved near the top of this function (CR-01, 33-REVIEW.md).
    if not occasion:
        return base_prompt

    target_date = situation.get("occasion_target_date", "")
    first_line = _first_prompt_line(occasion_prompt)
    header = f"This run is occasion={occasion!r}, target_date={target_date!r}."
    if first_line:
        header += f" {first_line}"
    addendum = _load_prompt("prompts/occasion_triage_addendum.md")
    # D-02 #4 (reaction history) — a compact, one-line signal, rendered only
    # when present (Claude's discretion, 33-CONTEXT.md): no upstream gather
    # populates this key yet, so it costs zero tokens on the common case,
    # matching the same "no data -> no block" discipline as the
    # conversation_tail/training_reality blocks above.
    reaction_note = (situation.get("self_state") or {}).get(
        "occasion_reaction_note"
    ) or ""
    reaction_line = f"\nReaction pattern: {reaction_note}" if reaction_note else ""

    # CR-01 (33-REVIEW.md) — the occasion's own capped Layer-0 digest. This
    # is the actual fix: without it, Layer 1 (no tools) judges every
    # occasion on the SAME generic tick signals a plain */20 tick sees.
    digest_block = _occasion_digest(occasion, situation)

    return f"{base_prompt}\n\n{header}{reaction_line}{digest_block}\n\n{addendum}"


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

    Looks for a fenced ``json {"action": "send"|"defer"|"cancel"}`` block.
    Returns ``(action, polished_text)``. ``polished_text`` is the message
    body BEFORE the JSON block.

    WARNING 5 fix:
      - No JSON block found    -> ``("send", text.strip())``
      - JSON block parse fails -> ``("send", text_BEFORE_the_block.strip())``
        so the malformed JSON internals don't leak to the user.

    Default to ``"send"`` rather than eternally deferring (D-17 spirit +
    Pitfall 6). ``"cancel"`` is the evidence-first escape hatch: the brain may
    drop a follow-up whose subject demonstrably didn't happen (e.g. a planned
    workout with no Garmin/Hevy evidence) instead of asking a false question.
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
        if action not in ("send", "defer", "cancel"):
            action = "send"
    except (json.JSONDecodeError, ValueError):
        # WARNING 5 — strip the malformed JSON from the polished text.
        action = "send"
    polished = text[:m.start()].strip()
    return (action, polished)


# --------------------------------------------------------------------------- #
# Layer 2 — synthetic chat turn via _run_smart_loop                            #
# --------------------------------------------------------------------------- #


def _compose_layer2(
    situation: dict,
    draft: str,
    triage_reason: str,
    *,
    occasion_prompt: str = "",
    max_tokens: int | None = None,
    undisclosed_actions: list[dict] | None = None,
) -> str:
    """Layer 2 — synthetic chat turn via ``AgentOrchestrator._run_smart_loop``.

    BLOCKER 5a fix — uses the module singleton, not per-call ``AgentOrchestrator()``.
    BLOCKER 5b fix — explicitly renders ``smart_system`` placeholders BEFORE
    calling ``_run_smart_loop``. The injection happens in ``handle_message``
    (verified at ``core/main.py:236-275``), NOT inside ``_run_smart_loop`` —
    so the autonomous tick MUST replicate the render step here.

    Pitfall 2 — builds the messages list freshly. Does NOT call
    ``handle_message`` (which would append to conversation history, polluting
    it with the synthetic user message).

    Phase 33 additions (all rendered into the USER message, never
    ``smart_system`` — the Phase-30.5 cached system prefix must stay
    undisturbed and a plain tick must pay nothing for these):
      - ``occasion_prompt`` (D-35): the occasion's few-line identity prompt,
        verbatim.
      - D-16/D-17 fold-in: the full text of today's ``OutreachLogStore``
        entries (capped at the last 5) — rendered for every compose, not just
        occasions.
      - D-25 write-and-disclose: any ``undisclosed_actions`` entries the
        caller already fetched from ``ActionLogStore.undisclosed()``.
      - D-27: no skip record, skip cause, or prior draft is ever rendered
        here — silence is not news.
    """
    orchestrator = _get_orchestrator()
    # Lazy import (avoids an import cycle) — Phase 31 (DIR-03) parity.
    from core.tools import render_standing_directives_block

    # BLOCKER 5b — replicate handle_message's render step before _run_smart_loop.
    smart_system_template = _load_prompt("prompts/autonomous.md")
    # PHASE 19 — NUTR-08: append non-personalized meal critique guidance so the
    # brain's compose layer has the audit heuristics whenever a meal-driven
    # nudge is in play. Defense-in-depth `if` guard: if the file vanishes,
    # we don't append a stray separator.
    meal_audit = _load_prompt("prompts/meal_audit.md")
    if meal_audit:
        smart_system_template = smart_system_template + "\n\n" + meal_audit
    # 32-02: render_smart_system now returns (stable, volatile) — this is
    # assigned straight through, unpacked nowhere here. autonomous.md has no
    # CURRENT TIME heading, so this resolves to (full_content, "") and the
    # Anthropic backend degrades to its existing single cached block; the
    # tuple shape is still handled correctly end-to-end by chat().
    smart_system = orchestrator.render_smart_system(smart_system_template)
    worker_system_template = _load_prompt("prompts/worker_agent.md")
    # worker_system needs {today_date} + {current_time} resolved; reuse the
    # same render path so a future addition of new placeholders to
    # worker_agent.md does not silently bypass them. Also now a (stable, "")
    # tuple (32-02) — the OpenAI-compat worker backend joins it into one
    # string; no cache_control concept there regardless.
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
        # Phase 28 Plan 03 (HABIT-05 / D-15/D-16): pending habits/supplements with streak.
        "habit_pending": situation.get("habit_pending", []),
        # Recovery deviation vs 7-day baseline (parity with triage).
        "recovery": situation.get("recovery", {}),
        # Today's completed-training ground truth (parity with triage).
        "training_evidence": situation.get("training_evidence", {}),
        # Phase 31 (DIR-03) — active standing directives (parity with triage);
        # the system-prompt {standing_directives} injection (Plan 03) already
        # covers the chat-persona voice — this is the situational snapshot copy.
        "standing_directives": json.loads(
            render_standing_directives_block(
                situation.get("standing_directives") or [], style="json"
            )
        ),
    }, indent=2, ensure_ascii=False)

    # Phase 32 (MEM-04) — paid-compose-wide renders: 48h/<=40-msg tail;
    # full today-3d..tomorrow training_reality window with evidence detail.
    now_for_render = _situation_now(situation)
    conversation_tail_block = _render_conversation_tail_wide(
        situation.get("conversation_tail") or [], now_for_render
    )
    training_reality_block = _render_training_reality_wide(
        situation.get("training_reality") or {}
    )

    # D-35 — occasion identity, verbatim, USER-message only.
    occasion_block = (
        f"\n\nOccasion identity:\n{occasion_prompt}\n" if occasion_prompt else ""
    )

    # D-16/D-17 fold-in — full text of today's Klaus-initiated outreach, so a
    # natural back-reference is possible (topic keys alone cannot enable
    # that). Capped at the last 5 entries so a chatty day cannot blow the
    # paid compose context. Rendered for the tick too, not just occasions —
    # this is the same shared-prompt behavior D-36 mandates.
    fold_in_block = ""
    try:
        from memory.firestore_db import OutreachLogStore

        today_iso = _situation_now(situation).astimezone(_TZ).date().isoformat()
        ols = OutreachLogStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        today_entries = ols.get_today(today_iso)[-5:]
        if today_entries:
            fold_lines = [
                f"- [{e.get('time', '')}] {e.get('topic_key', '')}: {e.get('final', '')}"
                for e in today_entries
            ]
            fold_in_block = (
                "\n\nToday's Klaus-initiated outreach (full text — fold "
                "around this, reference rather than restate):\n"
                + "\n".join(fold_lines)
            )
    except Exception:
        logger.warning(
            "autonomous: outreach fold-in fetch failed (non-fatal)", exc_info=True,
        )

    # D-25 write-and-disclose — actions I took but never told Amit about.
    # D-27: this is the ONE exception to "silence stays silent" — an
    # undisclosed *action* always surfaces at the next opportunity.
    disclosure_block = ""
    if undisclosed_actions:
        disclosure_lines = [
            f"- {a.get('action', '')}: {a.get('detail', '')} "
            f"(from {a.get('occasion', '')}, {a.get('at', '')})"
            for a in undisclosed_actions
        ]
        disclosure_block = (
            "\n\nActions I took but never disclosed (disclose now, action-line "
            "format — Created:/Moved:/Deleted:):\n" + "\n".join(disclosure_lines)
        )

    synthetic_content = (
        f"Situation snapshot:\n{snap_summary}\n\n"
        f"Time context:\n{_format_now_block(situation)}\n\n"
        f"Recent conversation with Amit (last 48h, up to 40 messages):\n{conversation_tail_block}\n\n"
        f"Training reality (today-3d..tomorrow, with evidence detail):\n{training_reality_block}\n\n"
        f"Triage layer's draft:\n{draft}\n\n"
        f"Triage reasoning:\n{triage_reason}\n"
        f"{occasion_block}{fold_in_block}{disclosure_block}"
    )
    messages = [{"role": "user", "content": synthetic_content}]
    return orchestrator._run_smart_loop(
        messages, smart_system, worker_system, max_tokens=max_tokens,
    )


def _compose_followup_layer2(followup: dict, situation: dict) -> str:
    """Sync helper called from an executor — synthetic chat turn for a follow-up.

    Uses the module singleton (BLOCKER 5a) and renders ``smart_system``
    (BLOCKER 5b) identically to ``_compose_layer2``.

    Layer 2 should end its response with a fenced JSON block
    ``{"action": "send"|"defer"}`` per the follow-up branch of
    ``prompts/autonomous.md``.
    """
    orchestrator = _get_orchestrator()
    # Lazy import (avoids an import cycle) — Phase 31 (DIR-03) parity.
    from core.tools import render_standing_directives_block

    smart_system_template = _load_prompt("prompts/autonomous.md")
    # PHASE 19 — NUTR-08: same meal_audit append as _compose_layer2. The
    # follow-up compose path is a sibling brain-compose site and must carry
    # the same audit guidance so a meal-adjacent follow-up nudge is critiqued
    # under the same heuristics.
    meal_audit = _load_prompt("prompts/meal_audit.md")
    if meal_audit:
        smart_system_template = smart_system_template + "\n\n" + meal_audit
    # 32-02: render_smart_system now returns (stable, volatile) — passed
    # through unchanged, same as _compose_layer2 above.
    smart_system = orchestrator.render_smart_system(smart_system_template)
    worker_system_template = _load_prompt("prompts/worker_agent.md")
    worker_system = orchestrator.render_smart_system(worker_system_template)

    snap = json.dumps({
        "calendar": situation.get("calendar", []),
        "ticktick_overdue": situation.get("ticktick_overdue", []),
        # Today's completed-training ground truth — a "how was the workout?"
        # follow-up must check this before assuming the session happened.
        "training_evidence": situation.get("training_evidence", {}),
        # Phase 31 (DIR-03) — active standing directives (parity with triage
        # and _compose_layer2).
        "standing_directives": json.loads(
            render_standing_directives_block(
                situation.get("standing_directives") or [], style="json"
            )
        ),
    }, indent=2, ensure_ascii=False)

    # Phase 32 (MEM-04) — paid-compose-wide renders (parity with _compose_layer2).
    now_for_render = _situation_now(situation)
    conversation_tail_block = _render_conversation_tail_wide(
        situation.get("conversation_tail") or [], now_for_render
    )
    training_reality_block = _render_training_reality_wide(
        situation.get("training_reality") or {}
    )

    synthetic = (
        f"Due follow-up:\n"
        f"id: {followup.get('id', '')}\n"
        f"due_at: {followup.get('due_at', '')}\n"
        f"note: {followup.get('note', '')}\n"
        f"defer_count: {followup.get('defer_count', 0)}\n\n"
        f"Current situation:\n{snap}\n\n"
        f"Time context:\n{_format_now_block(situation)}\n\n"
        f"Recent conversation with Amit (last 48h, up to 40 messages):\n{conversation_tail_block}\n\n"
        f"Training reality (today-3d..tomorrow, with evidence detail):\n{training_reality_block}\n"
    )
    messages = [{"role": "user", "content": synthetic}]
    return orchestrator._run_smart_loop(messages, smart_system, worker_system)


# --------------------------------------------------------------------------- #
# Follow-up path (D-13) — dedicated Layer-2 compose, skips tick-brain          #
# --------------------------------------------------------------------------- #


async def _compose_followup(bot, followup: dict, situation: dict, now: datetime) -> str:
    """D-13 — dedicated Layer-2 path for a due follow-up.

    - Layer 2 returns JSON ``{"action": "send"|"defer"|"cancel"}``.
    - D-14 force-fire: if ``defer_count >= _DEFER_FORCE_FIRE_THRESHOLD``
      override defer -> send. Cancel is NOT overridden — force-fire exists to
      stop eternal *deferral*; cancel is a terminal, evidence-justified
      decision (the follow-up's subject is moot or demonstrably didn't
      happen).
    - On send: ``send_and_inject(..., inject_into_conversation=True)`` +
      ``FollowupStore.mark_done`` + ``OutreachLogStore.append`` (success-only,
      D-10).
    - On defer: ``FollowupStore.defer(fid, original_due + 1h)``.
    - On cancel: ``FollowupStore.cancel(fid)`` — no send, no outreach-log
      entry (D-10 symmetry: nothing was delivered).

    Returns ``"sent"`` | ``"deferred"`` | ``"force_fired"`` | ``"cancelled"``
    | ``"failed"``.

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

    # Cancel — terminal, evidence-justified; checked BEFORE force-fire (which
    # exists to stop eternal deferral, not to overrule a reasoned drop).
    if action == "cancel":
        from memory.firestore_db import FollowupStore
        try:
            fs = FollowupStore(
                project_id=os.environ.get("GCP_PROJECT_ID", ""),
                database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
            )
            fs.cancel(fid)
            logger.info("autonomous: follow-up %s cancelled by Layer 2", fid)
            return "cancelled"
        except Exception:
            logger.warning("autonomous: followup cancel failed", exc_info=True)
            return "failed"

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
            # WR-02 / D-07 note: deliberately "default" class — follow-ups
            # have no mapped class in the D-07 taxonomy (not time-critical
            # the way leave_by/habit_nudge are).
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


async def _write_tick_log(
    now: datetime, situation: dict, decision: dict, *, log_key: str | None = None,
) -> None:
    """D-21 — write the per-tick snapshot for retroactive eval-fixture labeling.

    Best-effort. Never raises. Uses ``TickLogStore`` (Plan 01) so every
    persistent collection has a named store (NOTE 1 — keeps the memory-layer
    pattern consistent).

    ``log_key`` (plan 33-04): the ``ticks/{doc_id}`` sub-collection doc id.
    Defaults to ``None``, which resolves to the tick's own ``HH:MM`` — every
    pre-Phase-33 call site keeps this default and stays byte-identical. An
    occasion passes ``f"occasion:{occasion}"`` so it writes to
    ``tick_logs/{date}/ticks/occasion:{occasion}``, a namespace that can
    never collide with a real tick's ``HH:MM`` doc (T-33-14).
    """
    try:
        from memory.firestore_db import TickLogStore
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        today_iso = now.astimezone(_TZ).date().isoformat()
        tick_time = log_key if log_key is not None else now.astimezone(_TZ).strftime("%H:%M")
        snapshot = {k: v for k, v in situation.items() if k != "empty"}
        TickLogStore(project_id=project_id, database=database).write(
            today_iso, tick_time, snapshot, decision,
        )
    except Exception:
        logger.warning("autonomous: tick_log write failed (non-fatal)", exc_info=True)


# --------------------------------------------------------------------------- #
# Top-level entry points — run_autonomous_tick / run_occasion_cascade          #
# (shared 3-layer pipeline, D-20 / plan 33-04)                                 #
# --------------------------------------------------------------------------- #


def _tick_signature_store():
    """Lazy accessor for TickSignatureStore (mirrors the other store accessors)."""
    from memory.firestore_db import TickSignatureStore
    return TickSignatureStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


def _occasion_inflight_store():
    """Lazy accessor for OccasionInFlightStore (D-19, plan 33-04).

    Mirrors ``_tick_signature_store``'s lazy-import + env-var shape.
    """
    from memory.firestore_db import OccasionInFlightStore
    return OccasionInFlightStore(
        project_id=os.environ.get("GCP_PROJECT_ID", ""),
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )


# Design decision 2026-08-03 — the autonomous tick must hold off until the
# morning briefing has reached a terminal status for the day, so the
# briefing owns the start of the day and the tick owns everything after
# (see ``_morning_gate_holds``). Default backstop hour (local Asia/Jerusalem)
# past which the tick proceeds REGARDLESS of morning status.
_MORNING_GATE_DEFAULT_UNTIL_HOUR = 11


def _morning_gate_holds(now: datetime) -> bool:
    """Design decision 2026-08-03 — should ``run_autonomous_tick`` hold off?

    Amit's iPhone wake trigger (Sleep-Schedule "Wake Up") fires around
    10:00, well after the tick's 07:00 window start, so the tick was
    greeting him first every morning and the morning briefing then
    correctly judged itself ``already_covered`` and stayed silent (4
    consecutive mornings, 2026-07-31..2026-08-03 — the briefing has never
    actually delivered). This inverts the order: the briefing gets first
    crack at the day; the tick holds until it has reached a terminal status
    (``core.morning_briefing._TERMINAL_STATUSES``) OR the
    ``TICK_MORNING_GATE_UNTIL_HOUR`` backstop (default 11, Asia/Jerusalem)
    is reached — whichever comes first.

    The backstop is load-bearing (mirrors D-09's no-backstop trap): the
    wake trigger does NOT fire on a day with no Sleep Schedule set, so
    without a release valve a dead trigger would silence Klaus for the
    entire day. A dead trigger must cost a late start, never a silent day.

    Fails OPEN — returns ``False`` (tick proceeds) on any error reading the
    morning briefing's state (Firestore down, missing collection, etc.). A
    broken state read must never be able to silence Klaus.

    ``now`` is normalised to Asia/Jerusalem before the hour comparison so a
    caller-supplied ``now`` in a different tz (e.g. a naive UTC datetime
    from a test) is handled correctly — this codebase was bitten by exactly
    this class of bug once already (heartbeat WR-12).
    """
    try:
        local = now.astimezone(_TZ)
        until_hour = int(os.environ.get(
            "TICK_MORNING_GATE_UNTIL_HOUR", str(_MORNING_GATE_DEFAULT_UNTIL_HOUR)
        ))
        if local.hour >= until_hour:
            return False  # backstop reached — proceed regardless of status

        # Lazy import — avoids a module-load-time cycle (core.morning_briefing
        # already lazy-imports core.autonomous the same way, e.g.
        # ``derive_current_location`` / ``run_occasion_cascade``).
        from core.morning_briefing import _get_state, _TERMINAL_STATUSES
        today_iso = local.date().isoformat()
        status = _get_state(today_iso).get("status")
        return status not in _TERMINAL_STATUSES
    except Exception:
        logger.warning(
            "autonomous: morning gate check failed; proceeding (fail-open)",
            exc_info=True,
        )
        return False


def _compute_signal_signature(situation: dict) -> str:
    """Stable hash over the salient TRIGGER signals (the set ``_is_empty_signals``
    keys on) PLUS active ``standing_directives`` identities. Context-only
    signals (conversation_tail, training_reality, location) remain deliberately
    EXCLUDED (MEM-05 invariant): a change in them alone must not force a paid
    re-eval. ``hours_since_contact`` is reduced to its silence BUCKET (bool over
    the trigger threshold), never the raw float — otherwise it changes every
    tick and the change-detection gate never fires.

    Groq tick-efficiency fix-wave Finding 1: ``standing_directives`` moved from
    excluded to included. Rationale (does NOT violate the MEM-05 context-only
    invariant): this change-detection gate runs AFTER the empty-signals gate,
    so a directive change on an otherwise-empty tick already returned early —
    including directives here only forces a re-evaluation of an ALREADY
    non-empty tick when directive state changes (e.g. one expires). It never
    causes a directive to WAKE an empty tick. Without this, a time-boxed
    directive that vetoed a trigger (e.g. "stop nagging about training while
    I'm in France") could expire while that trigger stays byte-identical,
    leaving the signature unchanged and the now-unblocked escalation silently
    dropped by the change-detection gate.
    """
    import hashlib

    hsc = situation.get("hours_since_contact")
    silence_bucket = bool(
        isinstance(hsc, (int, float)) and hsc >= _SILENCE_TRIGGER_HOURS
    )
    salient = {
        "ticktick_overdue": situation.get("ticktick_overdue") or [],
        "due_followups": [
            f.get("id") for f in (situation.get("due_followups") or [])
        ],
        "calendar_trigger": _calendar_has_gap_or_overload(
            situation.get("calendar") or [], situation.get("now_context") or {}
        ),
        "meals_since_last_tick": len(situation.get("meals_since_last_tick") or []),
        "habit_pending": [
            h.get("id") for h in (situation.get("habit_pending") or [])
        ],
        "recovery_flags": sorted((situation.get("recovery") or {}).get("flags") or []),
        "silence_bucket": silence_bucket,
        "standing_directives": sorted(
            str(d.get("id")) for d in (situation.get("standing_directives") or [])
        ),
    }
    blob = json.dumps(salient, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def _run_cascade(
    bot,
    now: datetime,
    situation: dict,
    *,
    occasion: str | None,
    topic_key: str | None,
    advisory_only: bool,
    occasion_prompt: str,
    max_tokens: int | None,
    log_key: str,
    veto_parser: "Callable[[str], tuple[bool, str, str]] | None" = None,
    prior_trail: list | None = None,
    followup_sent: bool = False,
) -> dict:
    """Shared Layer-1 -> Layer-2 -> send -> log body (plan 33-04).

    ``run_autonomous_tick`` and ``run_occasion_cascade`` both delegate here
    after their own occasion-agnostic/occasion-specific setup. ``occasion is
    None`` is the tick's own call shape; everything occasion-only below is
    gated on ``occasion is not None`` / ``advisory_only`` / ``veto_parser``,
    all of which default to the tick's no-op values, so a plain tick's path
    through this function is byte-identical in behavior to the pre-Phase-33
    ``run_autonomous_tick``.

    Args (WR-09 additions):
        prior_trail: decision-trail entries the CALLER already accumulated
            before delegating here (the tick's D-13 follow-up outcomes). Seeded
            into this call's own trail so ``_write_tick_log`` persists one
            complete record. Previously the caller merged its entries into the
            RETURN value, long after the log had already been written from the
            cascade-only trail — so the Firestore record (the sole backing store
            for ``get_recent_decisions``, D-26) never showed that a follow-up
            fired.
        followup_sent: True when the caller already delivered a message on this
            tick. Recorded as its own key rather than folded into ``sent``,
            whose contract ("this cascade composed and sent") several callers
            and tests depend on — but it means a persisted
            ``{"skipped": "judgment", "sent": false}`` is no longer read as
            "Klaus said nothing this tick", which is exactly the question OCC-07
            exists to answer.
    """
    import asyncio as _asyncio

    decision: dict = {
        "skipped": False,
        "sent": False,
        "occasion": occasion,
        "topic_key": topic_key or "",
        "draft": "",
        "triage_reason": "",
        "skip_cause": "",
        "composed_via": "",
        "final_text": "",
        "trail": list(prior_trail or []),
    }
    if followup_sent:
        decision["followup_sent"] = True

    # Layer 1 — triage. Byte-identical call shape to the tick's pre-existing
    # one; only the CONTENT of triage_user_msg differs (occasion_prompt +
    # the occasion addendum, wired inside _build_triage_prompt).
    try:
        from core.tick_brain import TickBrain
        tb = TickBrain()
        triage_system = _load_prompt("prompts/autonomous_triage.md")
        triage_user_msg = _build_triage_prompt(
            situation, triage_system, occasion_prompt=occasion_prompt,
        )
        verdict = tb.think(triage_user_msg, system_override=triage_system)
    except Exception:
        logger.error("autonomous: Layer 1 (triage) failed entirely", exc_info=True)
        decision["trail"].append("layer1_exception")
        await _write_tick_log(now, situation, decision, log_key=log_key)
        return decision

    decision["trail"].append({"layer1": verdict})

    should_act = bool(verdict.get("should_act"))
    draft = verdict.get("draft", "")
    triage_reason = verdict.get("reason", "")
    decision["draft"] = draft
    decision["triage_reason"] = triage_reason

    if advisory_only and not should_act:
        # D-03 — the weekly occasion never self-skips on Layer-1 judgment;
        # should_act only shapes the draft/reason fed into Layer 2. The only
        # thing that can still silence it is the veto_parser hook below.
        decision["trail"].append("layer1_advisory_no_act")
    elif not should_act:
        decision["skipped"] = "judgment"
        decision["skip_cause"] = verdict.get("skip_cause", "")
        decision["trail"].append("layer1_no_act")
        await _write_tick_log(now, situation, decision, log_key=log_key)
        return decision

    # Layer 2 — compose. Pitfall 2: build messages freshly, NEVER call
    # handle_message (which would append the synthetic message to history).
    if not decision["topic_key"]:
        # Pitfall 4 — tick-only fallback chain (verdict's own topic_key,
        # else synthesise from inferred trigger). Occasions always arrive
        # here with a deterministic topic_key already set by
        # run_occasion_cascade, so this branch is unreachable for them.
        topic_key_value = verdict.get("topic_key") or ""
        if not topic_key_value:
            trigger_hint = _infer_trigger_type(situation)
            topic_key_value = _synthesize_topic_key(trigger_hint, situation)
            decision["trail"].append({"topic_key_synthesised": topic_key_value})
        decision["topic_key"] = topic_key_value

    # D-25 — fetch pending undisclosed actions ONCE, before compose, so
    # Layer 2 can surface them (rendered for the tick too, not just
    # occasions — an orphaned write must not wait for an occasion).
    try:
        from memory.firestore_db import ActionLogStore
        als = ActionLogStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        undisclosed_actions = als.undisclosed()
    except Exception:
        logger.warning(
            "autonomous: ActionLogStore.undisclosed() failed; proceeding "
            "without a disclosure block",
            exc_info=True,
        )
        undisclosed_actions = []

    # BLOCKER 3 — _run_smart_loop RETURNS sentinel on total LLM failure,
    # not raises. MUST detect both exception and sentinel-return as failure.
    try:
        final_text = await _asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _compose_layer2(
                situation, draft, triage_reason,
                occasion_prompt=occasion_prompt, max_tokens=max_tokens,
                undisclosed_actions=undisclosed_actions,
            ),
        )
        if not final_text or any(s in final_text for s in _SMART_LOOP_ERROR_SENTINELS):
            raise RuntimeError(
                f"Layer 2 returned empty or sentinel error text: {final_text!r:.120}"
            )
        decision["composed_via"] = "llm"
    except Exception as exc:
        logger.warning(
            "autonomous: Layer 2 failed; falling back to draft (D-19): %s", exc,
        )
        final_text = draft
        decision["composed_via"] = "draft_fallback" if draft else ""

    if not final_text:
        decision["trail"].append("layer2_and_draft_both_empty")
        await _write_tick_log(now, situation, decision, log_key=log_key)
        return decision

    # veto_parser — post-compose directive veto (D-03 / Phase 31 D-21/D-22).
    # Applied to Layer 2's composed text BEFORE send. Defaults to None, so
    # the tick path never touches this branch.
    if veto_parser is not None:
        veto, veto_reason, polished = veto_parser(final_text)
        _ = veto_reason  # carried by the caller's own logging if it wants it
        if veto:
            decision["skipped"] = "directive"
            decision["skip_cause"] = "standing_directive"
            decision["final_text"] = ""
            decision["trail"].append("directive_veto")
            await _write_tick_log(now, situation, decision, log_key=log_key)
            return decision
        final_text = polished

    decision["final_text"] = final_text

    # Message class — matches what the legacy composers send today (D-30).
    if occasion in ("nightly", "weekly_review"):
        message_class = "review"
    elif occasion == "morning":
        message_class = "briefing"
    else:
        # WR-02 / D-07 note: the plain tick deliberately stays on "default".
        # A composed tick message has no unambiguous class — the tick-brain's
        # topic_key is free-form and one message can mix triggers (habit
        # nudge + overdue + silence), so mapping to "habit_nudge"/"leave_by"
        # here would be guesswork.
        message_class = "default"

    from core.scheduled_message import send_and_inject
    from telegram.error import TimedOut

    try:
        await send_and_inject(
            bot, final_text, inject_into_conversation=True,
            message_class=message_class,
        )
    except TimedOut:
        # Weekly-review 500 incident (2026-06-24) — one retry on a transient
        # Telegram TimedOut, now extended to every occasion AND the tick.
        decision["trail"].append("send_timed_out")
        await _asyncio.sleep(2)
        try:
            await send_and_inject(
                bot, final_text, inject_into_conversation=True,
                message_class=message_class,
            )
        except Exception:
            logger.error(
                "autonomous: send_and_inject retry failed after TimedOut; "
                "outreach_log NOT updated (D-10)",
                exc_info=True,
            )
            decision["trail"].append("send_failed")
            await _write_tick_log(now, situation, decision, log_key=log_key)
            return decision
    except Exception:
        logger.error(
            "autonomous: send_and_inject failed; outreach_log NOT updated (D-10)",
            exc_info=True,
        )
        decision["trail"].append("send_failed")
        await _write_tick_log(now, situation, decision, log_key=log_key)
        return decision

    decision["sent"] = True

    # D-10 — write to outreach_log ONLY after the send succeeded.
    today_iso = now.astimezone(_TZ).date().isoformat()
    try:
        from memory.firestore_db import OutreachLogStore
        ols = OutreachLogStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        ols.append(today_iso, {
            "topic_key": decision["topic_key"],
            "time": now.astimezone(_TZ).strftime("%H:%M"),
            "draft": draft,
            "final": final_text,
            "tick_index": (situation.get("now_context") or {}).get("tick_index", 0),
            "occasion": occasion,
        })
    except Exception:
        logger.warning(
            "autonomous: outreach_log append failed (send already succeeded)",
            exc_info=True,
        )

    # D-25 — mark exactly the undisclosed actions rendered into THIS compose
    # as disclosed. Best-effort: a bookkeeping failure must never affect a
    # message that already went out (self-heals — the entry stays
    # undisclosed and surfaces again next time, per ActionLogStore's own
    # last-writer-wins caveat).
    if undisclosed_actions:
        try:
            from memory.firestore_db import ActionLogStore as _ActionLogStore
            als = _ActionLogStore(
                project_id=os.environ.get("GCP_PROJECT_ID", ""),
                database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
            )
            ids_by_date: dict[str, list[str]] = {}
            for a in undisclosed_actions:
                action_id = a.get("id")
                if not action_id:
                    continue
                action_date = a.get("date") or today_iso
                ids_by_date.setdefault(action_date, []).append(action_id)
            for action_date, ids in ids_by_date.items():
                als.mark_disclosed(action_date, ids)
        except Exception:
            logger.warning(
                "autonomous: mark_disclosed bookkeeping failed (non-fatal)",
                exc_info=True,
            )

    decision["trail"].append({"shipped": decision["topic_key"]})
    await _write_tick_log(now, situation, decision, log_key=log_key)
    return decision


async def run_occasion_cascade(
    bot,
    *,
    occasion: str,
    target_date: str,
    occasion_data: dict,
    occasion_prompt: str = "",
    now: datetime | None = None,
    advisory_only: bool = False,
    max_tokens: int | None = None,
    veto_parser: "Callable[[str], tuple[bool, str, str]] | None" = None,
) -> dict:
    """Route an occasion (nightly / morning / weekly_review) through the same
    3-layer cascade the ``*/20`` tick uses (plan 33-04).

    Args:
        occasion: one of ``_OCCASIONS``.
        target_date: ``YYYY-MM-DD`` — drives the deterministic topic key
            (``f"{prefix}:{target_date}"``, D-18) and the ``outreach_log``/
            ``tick_logs`` date keys.
        occasion_data: the occasion module's own specialised Layer-0 gather
            output (e.g. ``_gather_tomorrow``), merged onto the shared
            ``gather_situation()`` result. Per the RESEARCH anti-pattern
            warning, ``gather_situation()`` itself is never made
            tomorrow/week-aware — each occasion keeps its own gather.
        occasion_prompt: rendered text of ``prompts/<occasion>_occasion.md``
            (D-35) — carried through to both Layer 1 (header only) and
            Layer 2 (verbatim).
        advisory_only: D-03 — when True (the weekly occasion), a
            ``should_act=False`` Layer-1 verdict never suppresses the send;
            it only shapes the draft/reason handed to Layer 2.
        max_tokens: forwarded to ``_run_smart_loop`` (the weekly's
            large-compose budget).
        veto_parser: post-compose directive-veto hook (D-03 / Phase 31
            D-21/D-22), applied to Layer 2's text before send.

    Returns:
        The same decision-trail dict shape ``_run_cascade`` produces.

    Raises:
        ValueError: if ``occasion`` is not one of ``_OCCASIONS`` — a
            caller-supplied string never reaches a Firestore document id
            unvalidated (T-33-13).
    """
    if occasion not in _OCCASIONS:
        raise ValueError(f"occasion must be one of {_OCCASIONS!r}, got {occasion!r}")

    if now is None:
        now = datetime.now(_TZ)

    # Layer 0 — shared gather, PLUS the occasion's own specialised gather.
    # Both efficiency gates that exist purely for tick cost-control (empty
    # signals, change-detection) are structurally ABSENT from this path —
    # not conditionally skipped inside a shared helper — so an "empty" skip
    # or an unchanged-signature skip (see run_autonomous_tick's own gates)
    # are impossible for an occasion (OCC-04).
    situation = gather_situation(now)
    situation.update(occasion_data)
    situation["occasion"] = occasion
    situation["occasion_target_date"] = target_date

    topic_key = f"{_OCCASION_TOPIC_PREFIX[occasion]}:{target_date}"
    log_key = f"occasion:{occasion}"

    # D-19 — mark this occasion in flight for the duration of the cascade so
    # a coincident */20 tick yields. Marking/clearing never abort the
    # occasion (OccasionInFlightStore.mark/clear are themselves never-raise;
    # this try/except is defense-in-depth against a raising constructor).
    store = _occasion_inflight_store()
    try:
        store.mark(occasion, ttl_seconds=900)
    except Exception:
        logger.warning(
            "autonomous: OccasionInFlightStore.mark(%r) failed (non-fatal)",
            occasion, exc_info=True,
        )

    try:
        decision = await _run_cascade(
            bot, now, situation,
            occasion=occasion, topic_key=topic_key, advisory_only=advisory_only,
            occasion_prompt=occasion_prompt, max_tokens=max_tokens,
            log_key=log_key, veto_parser=veto_parser,
        )
    finally:
        try:
            store.clear()
        except Exception:
            logger.warning(
                "autonomous: OccasionInFlightStore.clear() failed (non-fatal)",
                exc_info=True,
            )

    return decision


async def run_autonomous_tick(bot, now: datetime | None = None) -> dict:
    """Top-level autonomous tick orchestrator.

    3-layer pipeline per D-20 (Cloud Scheduler route depends on this exact
    signature — unchanged by plan 33-04):
      1. ``gather_situation`` (Layer 0) — fast, no LLM
      2. D-19 (plan 33-04) — yield if an occasion is mid-compose.
      3. Design decision 2026-08-03 — hold off until the morning briefing
         has reached a terminal status for the day, or the
         ``TICK_MORNING_GATE_UNTIL_HOUR`` backstop is reached (see
         ``_morning_gate_holds``): the briefing owns the start of the day,
         the tick owns everything after.
      4. If empty signals → return early (D-11 gate; cost control SC-3)
      5. Due follow-ups (D-13) → dedicated Layer-2 compose loop (no tick-brain
         FOR THE FOLLOW-UP SEND). Execution then continues into step 6 — a
         follow-up firing does NOT short-circuit the rest of the tick.
      6. Layer 0.5 — change-detection gate (MEM-05 efficiency).
      7. Delegates the remaining Triage -> Compose -> Send -> Log steps to
         ``_run_cascade`` (plan 33-04) with ``occasion=None`` — the exact
         same 3-layer body every occasion now shares.

    Returns a decision-trail dict suitable for ``TickLogStore`` and debugging.
    """
    if now is None:
        now = datetime.now(_TZ)

    situation = gather_situation(now)
    decision: dict = {"skipped": False, "sent": False, "trail": []}

    # D-19 (plan 33-04) — yield to a mid-compose occasion. active() is
    # fail-open by construction (OccasionInFlightStore: any store error, an
    # absent/expired marker, or ANY exception all return None). The
    # try/except here mirrors that same fail-open contract at the call
    # site — not a second, different posture — so a poisoned marker or an
    # unreachable store can never mute the tick.
    try:
        _inflight_occasion = _occasion_inflight_store().active()
    except Exception:
        logger.warning(
            "autonomous: occasion in-flight check failed; proceeding", exc_info=True,
        )
        _inflight_occasion = None
    if _inflight_occasion:
        decision["skipped"] = "occasion_inflight"
        decision["trail"].append({"yielded_to_occasion": _inflight_occasion})
        await _write_tick_log(now, situation, decision)
        return decision

    # Design decision 2026-08-03 — hold off until the morning briefing has
    # run for today (see _morning_gate_holds docstring for the backstop
    # rationale). Checked unconditionally, ahead of the empty-signals gate,
    # because the hold must apply even on a tick with real signals to judge
    # — the briefing gets first crack at the day regardless of what else is
    # going on.
    if _morning_gate_holds(now):
        decision["skipped"] = "morning_gate"
        decision["trail"].append("layer0_morning_gate_hold")
        await _write_tick_log(now, situation, decision)
        return decision

    # Layer 0 gate (D-11 / SC-3) — empty signals = quiet tick, never call LLM.
    if situation.get("empty"):
        decision["skipped"] = "empty"
        decision["trail"].append("layer0_empty_signals")
        await _write_tick_log(now, situation, decision)
        return decision

    # D-13 follow-up path — skip tick-brain entirely for due follow-ups.
    due_followups = situation.get("due_followups") or []
    followup_sent = False
    if due_followups:
        for fu in due_followups:
            fu_outcome = await _compose_followup(bot, fu, situation, now)
            decision["trail"].append({"followup": fu.get("id"), "outcome": fu_outcome})
            if fu_outcome in ("sent", "force_fired"):
                followup_sent = True
        # D-13 intent: follow-up firing does NOT preclude same-tick triage. The
        # follow-up path skipped tick-brain for ITS send (Layer-2 only); Layer 1
        # still runs below so an overdue/silence escalation can also fire on
        # this tick. Per-day D-06 dedup prevents repeats across ticks.

    # Layer 0.5 — change-detection gate (MEM-05 efficiency). If the salient
    # trigger signals are byte-identical to the last tick's, there is nothing
    # new to judge: skip the (costly, TPM-limited) Groq call and stay silent.
    # Fail-open: any store error -> proceed with the normal triage call.
    try:
        _sig_store = _tick_signature_store()
        _signature = _compute_signal_signature(situation)
        _last_signature = _sig_store.get()
        if _last_signature is not None and _signature == _last_signature:
            decision["trail"].append("signals_unchanged_since_last_tick")
            await _write_tick_log(now, situation, decision)
            return decision
        _sig_store.set(_signature)
    except Exception:
        logger.warning(
            "autonomous: change-detection gate errored; proceeding", exc_info=True
        )

    # Layers 1-2 + send + log — shared cascade body (plan 33-04). The tick's
    # own topic_key fallback chain lives inside _run_cascade, gated on an
    # empty decision["topic_key"] (always true for the tick, since
    # topic_key=None here).
    # WR-09 — the follow-up outcomes accumulated above are handed to
    # _run_cascade as prior_trail rather than merged into its RETURN value.
    # _run_cascade writes the tick log from its own decision dict, so merging
    # afterwards meant the persisted record — the sole backing store for
    # get_recent_decisions (D-26) — never showed that a follow-up fired, and a
    # tick that sent a follow-up but then triaged to silence was persisted as
    # {"skipped": "judgment", "sent": false}.
    cascade_decision = await _run_cascade(
        bot, now, situation,
        occasion=None, topic_key=None, advisory_only=False,
        occasion_prompt="", max_tokens=None,
        log_key=now.astimezone(_TZ).strftime("%H:%M"),
        prior_trail=decision["trail"],
        followup_sent=followup_sent,
    )
    return cascade_decision
