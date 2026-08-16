"""Cross-domain training reads: per-set strength progression, the
reconciled training reality, per-run detail, and the wide context
block that joins them to nutrition and recovery.

Split out of core/tools.py; registered automatically on import.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.tools.registry import tool
from core.tools.state import _get_current_user_id

logger = logging.getLogger(__name__)


@tool({
        "name": "get_strength_progress",
        "description": (
            "Read Amit's strength-training history synced from Hevy (full per-set "
            "detail: every exercise, set, rep, weight_kg, RPE — plus derived "
            "top_set, est_1rm, and volume_kg). "
            "Pass `exercise` (e.g. 'Bench Press') to get that lift's progression "
            "over time for trend/stall analysis, or omit it for all recent "
            "sessions. `days` defaults to 30. `detail` defaults to 'full'; pass "
            "'summary' to drop per-set arrays and keep only derived metrics. "
            "Reason over the data yourself — do not expect pre-computed verdicts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "exercise": {
                    "type": "string",
                    "description": "Exercise name to get the progression for (case-insensitive). Omit for all sessions.",
                },
                "days": {
                    "type": "integer",
                    "description": "Days of history to return when no exercise is given. Default 30.",
                },
                "detail": {
                    "type": "string",
                    "description": "'full' (every set) or 'summary' (derived metrics only). Default 'full'.",
                },
            },
            "required": [],
        },
    })
def _handle_get_strength_progress(
    exercise: str | None = None, days: int = 30, detail: str = "full",
) -> str:
    """Brain-direct: read Hevy strength history from StrengthSessionStore.

    With `exercise` → that lift's per-session progression (top_set/est_1rm/volume).
    Without it → recent full sessions (every set unless detail='summary').
    Returns a structured tool-result; never raises (errors become {"error": ...}).
    """
    from memory.firestore_db import StrengthSessionStore
    try:
        store = StrengthSessionStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        if exercise:
            return json.dumps(
                {"exercise": exercise, "history": store.get_exercise_history(exercise)},
                default=str,
            )
        sessions = store.get_recent(days)
        if detail != "full":
            sessions = [
                {
                    "date": s.get("date"),
                    "title": s.get("title"),
                    "duration_min": s.get("duration_min"),
                    "total_volume_kg": s.get("total_volume_kg"),
                    "exercises": [
                        {
                            "name": e.get("name"),
                            "top_set": e.get("top_set"),
                            "est_1rm": e.get("est_1rm"),
                            "volume_kg": e.get("volume_kg"),
                            "set_count": e.get("set_count"),
                        }
                        for e in s.get("exercises") or []
                    ],
                }
                for s in sessions
            ]
        return json.dumps({"window_days": days, "sessions": sessions}, default=str)
    except Exception as exc:  # noqa: BLE001 — structured tool-result, never raise
        return json.dumps({"error": str(exc)})


@tool({
        "name": "get_training_context",
        "description": (
            "Get Amit's FULL cross-domain training picture in one call — strength "
            "(Hevy per-set), session log, running/cardio + training load, ACWR, "
            "Garmin training status/VO2, nutrition totals per day, and recovery "
            "(HRV/RHR/sleep). Use this when Amit asks open-ended "
            "questions about how training is going or what to change, so you can "
            "correlate ACROSS domains and surface non-obvious, individualized "
            "insight rather than siloed per-metric readouts. `days` defaults to 14. "
            "Nothing is filtered — you decide what matters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Look-back window in days across all domains. Default 14.",
                },
            },
            "required": [],
        },
    })
def _handle_get_training_context(days: int = 14) -> str:
    """Brain-direct: assemble the FULL cross-domain training picture in one call.

    Reuses existing reads (strength, training log, Garmin activities/status, ACWR,
    nutrition, biometrics). Every block is best-effort fail-open: one outage sets
    that key to None rather than aborting the whole snapshot, so the brain always
    gets as much of the picture as is available. Nothing is down-sampled.
    """
    from zoneinfo import ZoneInfo

    project_id = os.environ.get("GCP_PROJECT_ID", "")
    database = os.environ.get("FIRESTORE_DATABASE", "(default)")
    tz = ZoneInfo("Asia/Jerusalem")
    today = datetime.now(tz).date()
    ctx: dict = {"window_days": days}

    def load_strength_sessions():
        from memory.firestore_db import StrengthSessionStore
        return StrengthSessionStore(project_id, database).get_recent(days)

    def load_training_log():
        from memory.firestore_db import TrainingLogStore
        return TrainingLogStore(project_id, database).get_recent(days)

    def load_garmin_activities():
        from mcp_tools.garmin_tool import fetch_garmin_activities
        return fetch_garmin_activities(days)

    def load_run_details():
        from memory.firestore_db import RunDetailStore
        return RunDetailStore(project_id, database).get_recent(days)

    def load_training_status():
        from mcp_tools.garmin_tool import fetch_garmin_training_status
        return fetch_garmin_training_status()

    def load_acwr():
        from mcp_tools.garmin_tool import compute_acwr_from_db
        return compute_acwr_from_db()

    def load_nutrition_by_day():
        from memory.firestore_db import MealStore
        store = MealStore(project_id, database)
        nutrition: dict = {}
        for offset in range(days):
            day = (today - timedelta(days=offset)).isoformat()
            aggregate = store.get_day_aggregate(day)
            if aggregate:
                nutrition[day] = aggregate.get("totals", {})
        return nutrition

    def load_biometrics():
        from mcp_tools.database_tool import query_health_database
        start = (today - timedelta(days=days)).isoformat()
        # Bound parameter, not string interpolation: the date is built here from
        # an int, but a query executor should never be handed a value it has to
        # trust. The driver quotes it, so no value can change the statement.
        sql = (
            "SELECT date, resting_hr, hrv_baseline, hrv_overnight, "
            "sleep_duration, sleep_score FROM daily_biometrics "
            "WHERE date >= %s ORDER BY date DESC"
        )
        rows = query_health_database(sql, params=(start,))
        # A blocked or failed query returns an error *string*; only a list is data.
        return rows if isinstance(rows, list) else None

    # Every block is best-effort fail-open: one outage sets its key to None
    # rather than aborting the whole snapshot. Imports stay inside each loader so
    # a missing dependency degrades one key instead of all eight.
    sources = (
        ("strength_sessions", load_strength_sessions),
        ("training_log", load_training_log),
        ("garmin_activities", load_garmin_activities),
        ("run_details", load_run_details),
        ("training_status", load_training_status),
        ("acwr", load_acwr),
        ("nutrition_by_day", load_nutrition_by_day),
        ("biometrics", load_biometrics),
    )

    for key, load in sources:
        try:
            ctx[key] = load()
        except Exception:
            logger.warning("get_training_context: %s fetch failed", key, exc_info=True)
            ctx[key] = None

    return json.dumps(ctx, default=str)


@tool({
        "name": "get_training_reality",
        "description": (
            "THE tool for any question about what training has or has not "
            "happened — 'what did I do this week', 'did I miss anything', "
            "'how has training gone', or before you assert that a session was "
            "missed. Returns a week back through tomorrow with every session "
            "already reconciled across the calendar, the training log, Hevy and "
            "Garmin, so you never have to infer it from raw sources. Each "
            "session carries one status: completed, planned, missed, "
            "unverified, moved, cancelled, skipped, or unplanned — plus the "
            "evidence refs behind it. One session may span several activity "
            "records — a warmup, the effort and a cooldown are grouped into "
            "one session, so report it as one. `unverified` means a source was "
            "unreadable, NOT that the session was skipped; check "
            "`evidence_complete` and say so rather than calling it missed. A "
            "slot with evidence against it is closed — never ask Amit to "
            "confirm it. Use get_training_context instead only for wider "
            "analysis (load, pace trends, nutrition correlation)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "Days before today to reconcile. Default 7.",
                },
                "days_forward": {
                    "type": "integer",
                    "description": "Days after today to include. Default 1.",
                },
            },
            "required": [],
        },
    })
def _handle_get_training_reality(
    days_back: int = 3, days_forward: int = 1,
) -> str:
    """WB-04 return the reconciled planned-vs-actual training window.

    The reconciliation itself lives in ``core.training.reality`` so it stays
    testable without any live store. This handler only adapts it to the tool
    boundary.
    """
    from core.training.reality import build_training_reality

    return json.dumps(build_training_reality(days_back, days_forward))


@tool({
        "name": "get_run_detail",
        "description": (
            "Read Amit's per-run Garmin detail synced from Garmin Connect — the "
            "recorded laps/intervals exactly as the watch captured them (per-km "
            "for easy/tempo runs, per-rep for interval sessions), each with pace, "
            "HR, cadence, stride length and power; plus a whole-run min/avg/max "
            "summary of cadence, stride, vertical oscillation, ground contact, "
            "power and HR; plus derived split_shape (negative/positive/even), "
            "hr_drift, cadence_drift and pace_cv (interval consistency). "
            "Pass `activity_id` for one run, or omit for recent runs "
            "within `days` (default 14). `detail`='full' (every lap + summary) or "
            "'summary' (derived signals + per-run pace only). Reason over the data "
            "yourself — no pre-computed verdicts. Some runs (treadmill, no HRM "
            "strap) lack dynamics; respect `has_dynamics` and never invent cadence "
            "or stride for them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "string",
                    "description": "Garmin activity id for a single run. Omit for recent runs.",
                },
                "days": {
                    "type": "integer",
                    "description": "Look-back window in days when no activity_id is given. Default 14.",
                },
                "detail": {
                    "type": "string",
                    "description": "'full' (every lap + summary) or 'summary' (derived + per-run pace only). Default 'full'.",
                },
            },
            "required": [],
        },
    })
def _handle_get_run_detail(
    activity_id: str | None = None, days: int = 14, detail: str = "full",
) -> str:
    """Brain-direct: read per-run Garmin detail from RunDetailStore.

    With `activity_id` → that single run's full detail. Without it → recent runs
    within `days` (every lap unless detail='summary', which keeps only the
    derived signals + per-run pace). Never raises (errors become {"error": ...}).
    """
    from memory.firestore_db import RunDetailStore
    try:
        store = RunDetailStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        if activity_id:
            return json.dumps({"run": store.get_run(str(activity_id))}, default=str)
        runs = store.get_recent(days)
        if detail != "full":
            runs = [
                {
                    "date": r.get("date"),
                    "type": r.get("type"),
                    "distance_m": r.get("distance_m"),
                    "avg_pace_sec_per_km": r.get("avg_pace_sec_per_km"),
                    "derived": r.get("derived"),
                    "has_dynamics": r.get("has_dynamics"),
                }
                for r in runs
            ]
        return json.dumps({"window_days": days, "runs": runs}, default=str)
    except Exception as exc:  # noqa: BLE001 — structured tool-result, never raise
        return json.dumps({"error": str(exc)})
