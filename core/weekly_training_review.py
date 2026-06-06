"""Weekly training review cron — Sunday 10:00 Asia/Jerusalem.

Phase 20 — REVIEW-01 / REVIEW-02 / REVIEW-03.

Flow:
  1. _gather_week_data — best-effort gather of the previous Sun–Sat window:
     TrainingLogStore, Garmin activities (this week + last week for trends),
     daily_biometrics HRV/RHR/sleep from Postgres, MealStore 7-day totals,
     UserProfileStore.athletic_goals.
  2. _compose_review — brain-composed (SMART_AGENT_* LLMClient) using
     prompts/weekly_training_review.md + prompts/meal_audit.md appended.
  3. send_and_inject — always sends (D-24), injected into conversation.
"""
from __future__ import annotations

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
    # 2. Garmin activities — this week + last week for D-22 trend        #
    # ------------------------------------------------------------------ #
    try:
        from mcp_tools.garmin_tool import fetch_garmin_activities
        # fetch_garmin_activities(14) → last 14 days; covers this-week + last-week
        all_activities = fetch_garmin_activities(14)
        # Split into this-week vs last-week by activity date
        this_start_str = week_start.isoformat()
        this_end_str = week_end.isoformat()
        last_start_str = (week_start - timedelta(days=7)).isoformat()
        last_end_str = (week_start - timedelta(days=1)).isoformat()

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
        last_start_str = (week_start - timedelta(days=7)).isoformat()
        sql = (
            "SELECT date, resting_hr, hrv_baseline, hrv_overnight, "
            "sleep_duration, sleep_score "
            "FROM daily_biometrics "
            f"WHERE date >= '{last_start_str}' AND date <= '{week_end.isoformat()}' "
            "ORDER BY date ASC"
        )
        rows = query_health_database(sql)
        if isinstance(rows, list):
            this_start_str = week_start.isoformat()
            this_end_str = week_end.isoformat()
            data["biometrics_this_week"] = [
                r for r in rows
                if isinstance(r.get("date"), str) and this_start_str <= r["date"][:10] <= this_end_str
            ]
            data["biometrics_last_week"] = [
                r for r in rows
                if isinstance(r.get("date"), str) and last_start_str <= r["date"][:10] <= (week_start - timedelta(days=1)).isoformat()
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
        if block:
            week_num = (today - date.fromisoformat("2026-06-21")).days // 7 + 1
            data["current_block"] = {**block, "week_num": week_num}
            block_id = block.get("block_id") or block.get("doc_id")
            data["block_benchmarks"] = (
                BenchmarkStore(project_id, database).get_block_benchmarks(block_id)
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

    # COACH-05 (conservative-writer producer): derive the structural-critique topic keys this
    # review deterministically raises from already-gathered data, recorded post-send so a later
    # same-day cron hard-skips them (D-12 structural-critique dedup). Derivation is non-projective
    # (current-state only, no Phase-25 deadline framing) and fail-open — never crash the cron.
    try:
        data["coaching_topics_included"] = _derive_structural_topics(data)
    except Exception:
        logger.warning("weekly_review: structural topic derivation failed", exc_info=True)
        data["coaching_topics_included"] = []

    return data


def _derive_structural_topics(week_data: dict) -> list[str]:
    """Derive deterministic `structural-critique:*` topic keys from gathered week data.

    Conservative-writer producer for COACH-05: maps clear, current-state signals the
    review surfaces to canonical topic keys so they can be recorded for cross-cron dedup.
    No projection (Phase 25) — only this-week movement. Order-stable, de-duplicated.

    Currently derives:
    - `structural-critique:session-quality` when any logged session this week graded "grind"
      (the review's signature PROG-04 trend always comments on grind sessions when present).
    """
    topics: list[str] = []
    training_log = week_data.get("training_log") or []
    if any((entry or {}).get("quality") == "grind" for entry in training_log):
        topics.append("structural-critique:session-quality")
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
    try:
        system_prompt = (
            prompt_path.read_text(encoding="utf-8")
            .replace("{coaching_guide}", coaching_guide_content)
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
        response = client.chat(
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
            purpose="weekly_review",
        )
        text = (response.get("text") or "").strip()
        if text:
            return text
        logger.warning("weekly_review: brain returned empty response; using fallback")
    except Exception:
        logger.warning("weekly_review: brain LLM call failed; using fallback", exc_info=True)

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


async def run_weekly_review(bot, today_iso: str) -> None:
    """Entry point called by the /cron/weekly-training-review route.

    D-24: always sends even when the week is sparse or data is unavailable.
    The message is injected into the conversation so the brain can reference
    it in subsequent turns.

    Args:
        bot:       Telegram bot instance (_application.bot).
        today_iso: YYYY-MM-DD string (Asia/Jerusalem date at cron fire time).
    """
    week_data = _gather_week_data(today_iso)
    message = _compose_review(week_data, today_iso)
    from core.scheduled_message import send_and_inject
    await send_and_inject(bot, message, inject_into_conversation=True)  # D-24 always send

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
