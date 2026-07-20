"""Weekly training review cron — Sunday 10:00 Asia/Jerusalem.

Phase 20 — REVIEW-01 / REVIEW-02 / REVIEW-03.

Flow:
  1. _gather_week_data — best-effort gather of the previous Sun–Sat window:
     TrainingLogStore, Garmin activities (this week + last week for trends),
     daily_biometrics HRV/RHR/sleep from Postgres, MealStore 7-day totals,
     UserProfileStore.athletic_goals.
  2. _compose_review — brain-composed (SMART_AGENT_* LLMClient) using
     prompts/weekly_training_review.md + prompts/meal_audit.md appended.
  3. send_and_inject — always sends (D-24), injected into conversation —
     EXCEPT when an active standing directive's scope covers the weekly
     review (Phase 31 DIR-03 / D-21 / D-22): the compose call's own skip
     verdict then vetoes the send, logged as skipped_by_directive.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Jerusalem")


def _prev_sunday(today: date) -> date:
    """Return the most recent Sunday strictly before or on today.

    D-23: week boundary = previous Sun–Sat calendar week.
    isoweekday(): 7 = Sunday, 1 = Monday, …, 6 = Saturday.
    We want the Sunday that began the *last completed* week, so we always
    go back at least one full week (Sun–Sat).
    """
    # isoweekday() 7 = Sunday.  Days since the most recent Sunday:
    days_since_sunday = today.isoweekday() % 7   # Sun→0, Mon→1, …, Sat→6
    # We want the *previous* completed week's Sunday, so go back one more week.
    return today - timedelta(days=days_since_sunday + 7)


def _gather_week_data(today_iso: str) -> dict:
    """Gather all data sources for the previous Sun–Sat week window.

    Best-effort: each source is wrapped in a try/except so one failure
    cannot abort the entire review.  Failures set the key to None and
    log at WARNING level.  The brain's prompt handles the error copy.

    Args:
        today_iso: YYYY-MM-DD string for today (Asia/Jerusalem).

    Returns:
        dict with keys: today_date, week_start, week_end, training_log,
        training_log_error, activities, last_week_activities, garmin_error,
        biometrics_this_week, biometrics_last_week, nutrition_7day,
        athletic_goals.
    """
    from datetime import datetime  # local import avoids module-level dep
    today = date.fromisoformat(today_iso)

    # D-23: previous Sun–Sat window, tz-aware boundary (Pitfall 8)
    # We compute as calendar dates then convert to iso strings.
    week_start = _prev_sunday(today)      # Sunday (start of the completed week)
    week_end = week_start + timedelta(days=6)  # Saturday

    data: dict = {
        "today_date": today_iso,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
    }

    # IN-04: compute the four window-boundary strings once and reuse across the
    # Garmin (block 2) and biometrics (block 3) blocks instead of recomputing.
    this_start_str = week_start.isoformat()
    this_end_str = week_end.isoformat()
    last_start_str = (week_start - timedelta(days=7)).isoformat()
    last_end_str = (week_start - timedelta(days=1)).isoformat()

    # WR-06: load the UserProfile once and share a single BenchmarkStore so the
    # projection block (block 8) reuses the same snapshot/instance rather than
    # re-loading the profile and rebuilding the store. Each block stays fail-open:
    # if an earlier block leaves these None, block 8 lazily builds its own.
    _profile_cache: dict | None = None
    _benchmark_store = None

    # ------------------------------------------------------------------ #
    # 1. TrainingLogStore — reads never raise (LOG-02)                   #
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import TrainingLogStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        store = TrainingLogStore(project_id, database)
        data["training_log"] = store.get_range(week_start.isoformat(), week_end.isoformat())
        data["training_log_error"] = False
    except Exception:
        logger.warning("weekly_review: TrainingLogStore fetch failed", exc_info=True)
        data["training_log"] = None
        data["training_log_error"] = True

    # ------------------------------------------------------------------ #
    # 1b. StrengthSessionStore — full per-set Hevy detail, this week +    #
    #     last week for the top-set / volume / est-1RM trend. Fail-open    #
    #     to [] so the review still runs when Hevy sync is absent. This    #
    #     populates the strength facet the prompt asks for (top_set etc.). #
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import StrengthSessionStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        sstore = StrengthSessionStore(project_id, database)
        data["strength_sessions"] = sstore.get_range(this_start_str, this_end_str)
        data["strength_sessions_prev"] = sstore.get_range(last_start_str, last_end_str)
    except Exception:
        logger.warning("weekly_review: StrengthSessionStore fetch failed", exc_info=True)
        data["strength_sessions"] = []
        data["strength_sessions_prev"] = []

    # ------------------------------------------------------------------ #
    # 1c. RunDetailStore — full per-run Garmin detail (recorded laps +    #
    #     dynamics), this week + last week. Fail-open to [] so the review  #
    #     still runs when run-sync is absent. Lets the prompt reason over  #
    #     actual splits / split-shape / HR-drift instead of total km only. #
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import RunDetailStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        rstore = RunDetailStore(project_id, database)
        data["run_details"] = rstore.get_range(this_start_str, this_end_str)
        data["run_details_prev"] = rstore.get_range(last_start_str, last_end_str)
    except Exception:
        logger.warning("weekly_review: RunDetailStore fetch failed", exc_info=True)
        data["run_details"] = []
        data["run_details_prev"] = []

    # ------------------------------------------------------------------ #
    # 2. Garmin activities — this week + last week for D-22 trend        #
    # ------------------------------------------------------------------ #
    try:
        from mcp_tools.garmin_tool import fetch_garmin_activities
        # fetch_garmin_activities(14) → last 14 days; covers this-week + last-week
        all_activities = fetch_garmin_activities(14)
        # Split into this-week vs last-week by activity date (window strings
        # computed once above — IN-04).

        data["activities"] = [
            a for a in all_activities
            if a.get("date") and this_start_str <= a["date"][:10] <= this_end_str
        ]
        data["last_week_activities"] = [
            a for a in all_activities
            if a.get("date") and last_start_str <= a["date"][:10] <= last_end_str
        ]
        data["garmin_error"] = False
    except Exception:
        logger.warning("weekly_review: Garmin activities fetch failed", exc_info=True)
        data["activities"] = None
        data["last_week_activities"] = None
        data["garmin_error"] = True

    # ------------------------------------------------------------------ #
    # 3. daily_biometrics — HRV/RHR/sleep this week + last week         #
    #    Read from Postgres via query_health_database.                   #
    # ------------------------------------------------------------------ #
    try:
        from mcp_tools.database_tool import query_health_database
        sql = (
            "SELECT date, resting_hr, hrv_baseline, hrv_overnight, "
            "sleep_duration, sleep_score "
            "FROM daily_biometrics "
            f"WHERE date >= '{last_start_str}' AND date <= '{this_end_str}' "
            "ORDER BY date ASC"
        )
        rows = query_health_database(sql)
        if isinstance(rows, list):
            data["biometrics_this_week"] = [
                r for r in rows
                if isinstance(r.get("date"), str) and this_start_str <= r["date"][:10] <= this_end_str
            ]
            data["biometrics_last_week"] = [
                r for r in rows
                if isinstance(r.get("date"), str) and last_start_str <= r["date"][:10] <= last_end_str
            ]
        else:
            # query_health_database returned an error string
            logger.warning("weekly_review: biometrics query returned error: %s", rows)
            data["biometrics_this_week"] = None
            data["biometrics_last_week"] = None
    except Exception:
        logger.warning("weekly_review: daily_biometrics fetch failed", exc_info=True)
        data["biometrics_this_week"] = None
        data["biometrics_last_week"] = None

    # ------------------------------------------------------------------ #
    # 4. MealStore — 7-day totals (D-21), fiber included (Phase 19.2)   #
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import MealStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        meal_store = MealStore(project_id, database)

        # Sum get_day_aggregate across each day of the review window
        totals: dict[str, float] = {
            "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0
        }
        has_data = False
        cursor = week_start
        while cursor <= week_end:
            agg = meal_store.get_day_aggregate(cursor.isoformat())
            if agg:
                has_data = True
                day_totals = agg.get("totals", {})
                for key in totals:
                    totals[key] += day_totals.get(key, 0) or 0
            cursor += timedelta(days=1)

        data["nutrition_7day"] = {k: round(v, 1) for k, v in totals.items()} if has_data else {}
    except Exception:
        logger.warning("weekly_review: MealStore fetch failed", exc_info=True)
        data["nutrition_7day"] = {}

    # ------------------------------------------------------------------ #
    # 5. UserProfileStore.athletic_goals — skip if empty (D-20)         #
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import UserProfileStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        profile = UserProfileStore(project_id, database).load()
        _profile_cache = profile  # WR-06: reused by the projection block
        data["athletic_goals"] = profile.get("athletic_goals") or []
    except Exception:
        logger.warning("weekly_review: UserProfileStore fetch failed", exc_info=True)
        data["athletic_goals"] = []

    # ------------------------------------------------------------------ #
    # 6. BlockStore + BenchmarkStore — current block + this-block        #
    #    benchmarks (BLOCK-01 / BLOCK-03). Best-effort; defaults to       #
    #    None / [] on failure (Pitfall 4). week_num derived from the      #
    #    2026-06-21 anchor at gather time (D-03), never stored. RAW        #
    #    block-over-block deltas only — no projection (Phase 25).         #
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import BlockStore, BenchmarkStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        block = BlockStore(project_id, database).get_current()
        _benchmark_store = BenchmarkStore(project_id, database)  # WR-06: shared
        if block:
            week_num = (today - date.fromisoformat("2026-06-21")).days // 7 + 1
            data["current_block"] = {**block, "week_num": week_num}
            block_id = block.get("block_id") or block.get("doc_id")
            data["block_benchmarks"] = (
                _benchmark_store.get_block_benchmarks(block_id)
                if block_id else []
            )
        else:
            data["current_block"] = None
            data["block_benchmarks"] = []
            days_until = (date.fromisoformat("2026-06-21") - today).days
            if days_until > 0:
                data["pre_cycle_countdown"] = days_until
    except Exception:
        logger.warning("weekly_review: BlockStore/BenchmarkStore fetch failed", exc_info=True)
        data["current_block"] = None
        data["block_benchmarks"] = []

    # ------------------------------------------------------------------ #
    # 7. CoachingTopicStore — today's raised topics for COACH-05 dedup   #
    #    (D-12: structural-critique topics not repeated if already today) #
    #    Best-effort; fail-open to [] (T-24-18 mitigated).               #
    #    NOTE: quality is NOT gathered here — it is already present on   #
    #    training_log entries written by TrainingLogStore.log_session     #
    #    (Plan 01 / PROG-04); no new gather code needed (Finding 10).    #
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import CoachingTopicStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        _cts = CoachingTopicStore(project_id, database)
        data["coaching_topics_today"] = _cts.topics_today(today_iso)
    except Exception:
        logger.warning("weekly_review: coaching topics fetch failed", exc_info=True)
        data["coaching_topics_today"] = []

    # ------------------------------------------------------------------ #
    # 8. Progress projections — PROG-02 (Phase 25)                       #
    #    Computed server-side for each dated-goal facet. Fail-open to    #
    #    {} on any error so the cron always sends.                       #
    #    D-04: threshold_pace prefers dense Garmin running points        #
    #    (fetch_dense_pace_history); strength facets use BenchmarkStore. #
    # ------------------------------------------------------------------ #
    try:
        from core.projection import project_goal_progress
        from core.pace_history import fetch_dense_pace_history
        # WR-06: reuse the profile snapshot from block 5 and the BenchmarkStore
        # from block 6; build fresh only if an earlier block failed (fail-open).
        if _profile_cache is not None:
            _profile = _profile_cache
        else:
            from memory.firestore_db import UserProfileStore as _UPS
            _profile = _UPS(
                os.environ["GCP_PROJECT_ID"],
                os.getenv("FIRESTORE_DATABASE", "(default)"),
            ).load()
        if _benchmark_store is not None:
            _benchmarks = _benchmark_store
        else:
            from memory.firestore_db import BenchmarkStore as _BS
            _benchmarks = _BS(
                os.environ["GCP_PROJECT_ID"],
                os.getenv("FIRESTORE_DATABASE", "(default)"),
            )
        dated_goals = _profile.get("dated_goals") or []
        projections: dict = {}
        for facet in ["bench_press_1rm", "squat_1rm", "threshold_pace", "push_ups", "pull_ups"]:
            if facet == "threshold_pace":
                # D-04: prefer dense Garmin running history; fall back to sparse BenchmarkStore
                history = fetch_dense_pace_history(today_iso)
                if not history:
                    history = _benchmarks.get_facet_history("threshold_pace", n=10)
            else:
                history = _benchmarks.get_facet_history(facet, n=10)
            projections[facet] = project_goal_progress(facet, history, dated_goals, today_iso)
        data["projections"] = projections
    except Exception:
        logger.warning("weekly_review: projection gather failed", exc_info=True)
        data["projections"] = {}

    # COACH-05 (conservative-writer producer): derive the structural-critique topic keys this
    # review deterministically raises from already-gathered data, recorded post-send so a later
    # same-day cron hard-skips them (D-12 structural-critique dedup). Fail-open — never crash.
    try:
        data["coaching_topics_included"] = _derive_structural_topics(data)
    except Exception:
        logger.warning("weekly_review: structural topic derivation failed", exc_info=True)
        data["coaching_topics_included"] = []

    # ------------------------------------------------------------------ #
    # 9. StandingDirectiveStore — DIR-03 / D-21 / D-22 interim veto      #
    #    power over the legacy weekly-review cron. Best-effort; fail-open #
    #    to [] so the review still runs when the directive read fails.    #
    # ------------------------------------------------------------------ #
    try:
        from memory.firestore_db import StandingDirectiveStore
        project_id = os.environ["GCP_PROJECT_ID"]
        database = os.getenv("FIRESTORE_DATABASE", "(default)")
        data["standing_directives"] = StandingDirectiveStore(project_id, database).list_active()
    except Exception:
        logger.warning("weekly_review: standing directives fetch failed", exc_info=True)
        data["standing_directives"] = []

    return data


def _derive_structural_topics(week_data: dict) -> list[str]:
    """Derive deterministic `structural-critique:*` topic keys from gathered week data.

    Conservative-writer producer for COACH-05: maps clear, current-state signals the
    review surfaces to canonical topic keys so they can be recorded for cross-cron dedup.
    Order-stable, de-duplicated.

    Derives:
    - `structural-critique:session-quality` when any logged session this week graded "grind"
      (the review's signature PROG-04 trend always comments on grind sessions when present).
    - `structural-critique:projection:<facet>` for each facet whose projection result has
      confidence != "no_data" (i.e. at least 1 data point exists — Phase 25 PROG-02).
    """
    topics: list[str] = []
    training_log = week_data.get("training_log") or []
    if any((entry or {}).get("quality") == "grind" for entry in training_log):
        topics.append("structural-critique:session-quality")
    # Phase 25 — projection dedup keys (PROG-02 / D-12 COACH-05)
    projections = week_data.get("projections") or {}
    for facet, result in projections.items():
        if isinstance(result, dict) and result.get("confidence") != "no_data":
            topics.append(f"structural-critique:projection:{facet}")
    # De-duplicate while preserving first-seen order.
    seen: set[str] = set()
    return [t for t in topics if not (t in seen or seen.add(t))]


def _compose_review(week_data: dict, today_iso: str) -> str:
    """Brain-compose the weekly review message (D-17 — SMART_AGENT_* LLMClient).

    Loads prompts/weekly_training_review.md, substitutes {today_date},
    appends prompts/meal_audit.md (D-21 nutrition critique reuse), and
    calls the brain LLM.  Falls back to a minimal plain-text summary on
    LLM failure (D-24: always send).

    Args:
        week_data:  Dict from _gather_week_data.
        today_iso:  YYYY-MM-DD used for {today_date} substitution.

    Returns:
        Composed message string — never empty (fallback ensures something is sent).
    """
    prompt_path = Path(__file__).parent.parent / "prompts" / "weekly_training_review.md"
    # PHASE 24 — COACH-01 / D-17: inject slim coaching core before {today_date}.
    # Mirrors morning_briefing._compose_briefing (lines 317–328) and
    # proactive_alerts._compose_alert patterns. Fail-open: a guide fetch failure
    # must NOT crash the weekly review cron (T-24-18 mitigated).
    try:
        from core.autonomous import _get_orchestrator
        coaching_guide_content = _get_orchestrator()._coaching_guide_content
    except Exception:
        logger.warning("weekly_review: coaching guide unavailable — proceeding without it")
        coaching_guide_content = ""

    # PHASE 31 — DIR-03 / D-22: render the active standing-directives block
    # (shared formatter, see core/tools.py) so the compose call can honor a
    # covering directive's veto. Fail-open to "" — a formatter/import failure
    # must never crash the weekly review.
    try:
        from core.tools import render_standing_directives_block
        standing_directives_block = render_standing_directives_block(
            week_data.get("standing_directives") or [], style="prose"
        )
    except Exception:
        logger.warning("weekly_review: standing directives render failed", exc_info=True)
        standing_directives_block = ""

    try:
        system_prompt = (
            prompt_path.read_text(encoding="utf-8")
            .replace("{coaching_guide}", coaching_guide_content)
            .replace("{standing_directives}", standing_directives_block)
            .replace("{today_date}", today_iso)
        )
    except OSError:
        logger.warning(
            "weekly_review: could not read prompts/weekly_training_review.md; "
            "using minimal fallback prompt"
        )
        system_prompt = (
            "You are Klaus. Write a brief weekly training review for Sir. "
            "Use the data provided. Address as 'sir', no exclamation marks."
        )

    # D-21: append meal_audit.md for nutrition critique guidance
    meal_audit_path = Path(__file__).parent.parent / "prompts" / "meal_audit.md"
    meal_audit = (
        meal_audit_path.read_text(encoding="utf-8")
        if meal_audit_path.exists() else ""
    )
    if meal_audit:
        system_prompt = system_prompt + "\n\n" + meal_audit

    user_message = json.dumps(week_data, ensure_ascii=False, indent=2, default=str)

    try:
        from core.llm_client import LLMClient  # D-17: brain model, not tick-brain
        client = LLMClient(
            backend=os.environ["SMART_AGENT_BACKEND"],
            model=os.environ["SMART_AGENT_MODEL"],
            api_key=os.environ["SMART_AGENT_API_KEY"],
        )
        # max_tokens=32000: the weekly review is the largest compose in the
        # system and Sonnet's internal thinking counts against the output
        # budget — at the default 16K it exhausted max_tokens mid-thinking and
        # returned no text block at all (2026-07-19, stop_reason=max_tokens).
        response = client.chat(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            purpose="weekly_review",
            max_tokens=32000,
        )
        text = (response.get("text") or "").strip()
        if text:
            return text
        logger.warning(
            "weekly_review: brain returned empty response (stop_reason=%s); using fallback",
            response.get("stop_reason"),
        )
    except Exception:
        logger.warning("weekly_review: brain LLM call failed; using fallback", exc_info=True)

    # Phase 30.5 D-14 gap fix — before dropping to the deterministic data
    # string, try the SMART_AGENT_FALLBACK_* Gemini compose (same 2-tier shape
    # as morning/nightly from Plan 06 Task 2). Silent try/except — a fallback
    # failure must never crash the weekly cron. Surfaced 2026-07-19 when the
    # Sonnet compose timed out and the review skipped straight to raw data.
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
            purpose="weekly_review",
        )
        text_fb = (response_fb.get("text") or "").strip()
        if text_fb:
            return text_fb
    except Exception:
        logger.warning("weekly_review: LLM fallback composition failed", exc_info=True)

    # Fallback: minimal data-derived string so D-24 (always send) is honoured
    week_start = week_data.get("week_start", "")
    week_end = week_data.get("week_end", "")
    training_log = week_data.get("training_log") or []
    n_sessions = len(training_log)
    return (
        f"Good morning, sir. Here is your training review for the week ending {week_end}.\n\n"
        f"Training log shows {n_sessions} session(s) recorded for the week of {week_start} "
        f"to {week_end}. Full review composition failed — the raw data is available on request."
    )


def _parse_review_skip(text: str) -> tuple[bool, str, str]:
    """Parse a trailing directive-skip verdict from a composed weekly review.

    PHASE 31 — DIR-03 / D-21 / D-22: mirrors ``core.autonomous._parse_followup_action``'s
    and ``core.morning_briefing._parse_briefing_skip``'s fenced-JSON-trailer convention
    EXACTLY — looks for a trailing ``` ```json {"skip": true, "reason": "..."}``` ```
    block. Returns ``(skip, reason, polished_text)`` where ``polished_text`` is the
    message body BEFORE the JSON block (so malformed JSON internals never leak to Amit).

    Defaults to ``(False, "", text.strip())`` when the block is absent or malformed —
    a parse failure must never silently block the review (D-24 always-send spirit).
    """
    import re as _re
    if not text:
        return (False, "", "")
    m = _re.search(r"```json\s*(\{.*?\})\s*```", text, _re.DOTALL)
    if not m:
        return (False, "", text.strip())
    try:
        obj = json.loads(m.group(1))
        skip = bool(obj.get("skip", False))
        reason = str(obj.get("reason", "")) if skip else ""
    except (json.JSONDecodeError, ValueError):
        skip = False
        reason = ""
    polished = text[:m.start()].strip()
    return (skip, reason, polished)


async def run_weekly_review(bot, today_iso: str) -> None:
    """Entry point called by the /cron/weekly-training-review route.

    D-24: always sends even when the week is sparse or data is unavailable —
    EXCEPT when an active standing directive's scope covers the weekly review
    (DIR-03 / D-21 / D-22): the compose call's own skip verdict then vetoes
    the send, logged distinctly as ``skipped_by_directive`` (never conflated
    with an infra failure). The message is injected into the conversation so
    the brain can reference it in subsequent turns.

    Args:
        bot:       Telegram bot instance (_application.bot).
        today_iso: YYYY-MM-DD string (Asia/Jerusalem date at cron fire time).
    """
    # WHY run_in_executor: _gather_week_data does a blocking Garmin login (~28s) +
    # a synchronous requests-based activities fetch (15s read-timeout) + Postgres +
    # Firestore reads, and _compose_review makes a blocking brain-LLM call. Running
    # them directly on the event loop starved it for ~110s, which left the Telegram
    # client's connection unusable so bot.send_message raised TimedOut → the cron
    # 500'd 3 Sundays in a row. Offload both to a thread so the loop stays
    # responsive, mirroring nightly_review.run / autonomous (Pitfall 2).
    loop = asyncio.get_running_loop()
    week_data = await loop.run_in_executor(None, _gather_week_data, today_iso)
    message = await loop.run_in_executor(None, _compose_review, week_data, today_iso)

    # PHASE 31 — DIR-03 / D-21 / D-22: an active standing directive whose scope
    # covers the weekly review gives the brain's own compose call full veto
    # power. Parse a trailing skip verdict; on skip, log distinctly from a send
    # failure and return BEFORE send_and_inject — this is the one exception to
    # D-24's "always send" rule.
    skip, skip_reason, message = _parse_review_skip(message)
    if skip:
        logger.info(
            "weekly_review: skipped_by_directive for %s (%s)", today_iso, skip_reason
        )
        return

    # D-24 always send. One retry on a transient Telegram TimedOut so a single
    # flake never silently costs Amit a whole week's review; a persistent failure
    # still propagates (→ HTTP 500 → heartbeat stale-cron ledger). send_and_inject's
    # re-raise contract is unchanged — the retry lives here in the caller.
    from telegram.error import TimedOut

    from core.scheduled_message import send_and_inject
    # WR-02 / D-07: reviews carry the "review" push class (24h TTL).
    try:
        await send_and_inject(bot, message, inject_into_conversation=True, message_class="review")
    except TimedOut:
        logger.warning("weekly_review: Telegram send timed out — retrying once", exc_info=True)
        await asyncio.sleep(2)
        await send_and_inject(bot, message, inject_into_conversation=True, message_class="review")

    # PHASE 24 — COACH-05 / T-24-17: record any coaching topics included in this
    # review to CoachingTopicStore AFTER send succeeds — never before.
    # Write-after-send discipline mirrors morning_briefing post-send topic write
    # and OutreachLogStore.append (Phase 18 D-10). Best-effort: a write failure
    # is non-fatal (dedup just won't fire for that topic on the next cron).
    try:
        _topics_included = week_data.get("coaching_topics_included") or []
        if _topics_included:
            from memory.firestore_db import CoachingTopicStore
            _cts = CoachingTopicStore(
                project_id=os.environ["GCP_PROJECT_ID"],
                database=os.getenv("FIRESTORE_DATABASE", "(default)"),
            )
            for _topic in _topics_included:
                _cts.add_topic(today_iso, _topic)
    except Exception:
        logger.warning("weekly_review: coaching topic record failed", exc_info=True)
