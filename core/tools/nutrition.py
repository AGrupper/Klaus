"""Logged meals and nutrition trends against target.

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


_NUTRITION_MACRO_KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")


def _compute_nutrition_averages(day_records: list[dict], macro_keys=_NUTRITION_MACRO_KEYS) -> dict:
    """Average each macro key across day_records that HAVE data.

    Shared by _handle_fetch_nutrition_trend (chat tool) and
    interfaces.web_server's GET /api/health/nutrition route (Phase 30 HLTH-02) so
    the two paths compute identical numbers — extracted specifically so the
    "server computes, client renders" invariant cannot drift into two slightly
    different reimplementations (RESEARCH.md Anti-Patterns / the 2026-06-09
    drifting-numbers lesson).

    Days with no logged meals are simply absent from `day_records` (the
    caller's missing_dates contract) — never averaged in as zero.
    """
    averages: dict = {"days_with_data": len(day_records)}
    if day_records:
        for k in macro_keys:
            vals = [d.get(k) or 0 for d in day_records]
            averages[k] = round(sum(vals) / len(vals), 1)
    return averages


def _nutrition_targets_and_protein_ratio(profile: dict, averages: dict) -> dict:
    """Silent-omit `targets` + `avg_protein_g_per_kg` (mirrors D-15).

    Shared by _handle_fetch_nutrition_trend and the /api/health/nutrition route
    — see _compute_nutrition_averages docstring for why this is extracted.
    Returns {} when the profile carries no nutrition_targets / bodyweight_kg.
    """
    out: dict = {}
    targets = profile.get("nutrition_targets")
    if targets:
        out["targets"] = targets
    bodyweight = profile.get("bodyweight_kg")
    if bodyweight and averages.get("protein_g"):
        out["avg_protein_g_per_kg"] = round(averages["protein_g"] / float(bodyweight), 2)
    return out


@tool({
        "name": "fetch_recent_meals",
        "description": (
            "Get the user's logged nutrition from the last N hours "
            "(Lifesum → Apple HealthKit → Klaus on iOS, or Google Fit on Android; "
            "both land in the same meal store). Returns an object with: `meals` "
            "(per-meal entries — calories, protein_g, carbs_g, fat_g, fiber_g, "
            "meal_type, optional food_item), `totals_by_day` (exact macro totals "
            "per calendar date, SERVER-COMPUTED in Python), and `window_totals` "
            "(exact macro totals across the whole window). For any nutrition "
            "total/status question, report the server-computed totals VERBATIM — "
            "never sum the meals yourself. CAUTION: HealthKit/Lifesum meal "
            "timestamps are canonical slot times (breakfast=08:00, lunch=12:00, "
            "dinner=20:00), NOT the actual eating time — never infer when the "
            "user actually ate from them. Meals also only sync when the user "
            "closes Lifesum, so a just-eaten meal may not be here yet. "
            "Default hours=24. "
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "Hours back to fetch. Default 24.",
                },
            },
            "required": [],
        },
    })
def _handle_fetch_recent_meals(hours: int = 24) -> str:
    """Brain-direct: recent meals + SERVER-COMPUTED macro totals from MealStore.

    Reads ``MealStore.get_day()`` for the Asia/Jerusalem calendar date(s) the
    requested window touches, then filters per-meal entries to the last ``hours``.
    Lifesum on iPhone writes to Apple HealthKit, surfaced into MealStore by
    ``/cron/healthkit-sync``; MealStore is the shared, source-agnostic store the
    morning briefing already reads, so meals from either source are visible here.

    Returns a JSON object (NOT a bare list) with three keys:

    - ``meals``: per-meal entries within the last ``hours`` (each includes
      ``fiber_g`` alongside the core macros — Phase 19.2), ascending by time.
    - ``totals_by_day``: exact macro totals per calendar date the window
      touches, computed in **Python** by ``MealStore.get_day_aggregate`` (the
      same source of truth the morning briefing and ``get_training_context``
      use, so chat and briefing can never disagree). These are FULL-calendar-day
      totals — the authoritative "how much did I eat on date X" number.
    - ``window_totals``: those per-day totals summed across the window, in Python.

    The brain MUST report these totals verbatim and never sum the ``meals`` list
    itself — LLM column-summing was the source of the wrong/drifting numbers this
    tool was rebuilt to fix. On error returns ``{"error": ...}`` so the brain
    gets a structured tool-result rather than a raised exception.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Jerusalem")
    now = datetime.now(tz)
    cutoff = now - timedelta(hours=hours)
    try:
        from memory.firestore_db import MealStore
        ms = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
            database=os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
        )
        # Enumerate EVERY calendar date the window touches (a >48h window has
        # dates strictly between cutoff-day and today — the old two-endpoint
        # union silently skipped them). MealStore.get_day never raises.
        span = (now.date() - cutoff.date()).days
        dates = [
            (cutoff.date() + timedelta(days=i)).isoformat() for i in range(span + 1)
        ]
        meals: list[dict] = []
        for d in dates:
            meals.extend(ms.get_day(d))
        out: list[dict] = []
        for m in meals:
            try:
                ts = datetime.fromisoformat(m["timestamp"])
                if ts >= cutoff:
                    out.append(m)
            except (KeyError, ValueError, TypeError):
                # Malformed timestamp on one entry → skip it, keep the rest.
                continue

        # Server-computed totals — reuse get_day_aggregate (Python arithmetic),
        # never leave macro-summing to the LLM. totals_by_day is keyed only by
        # dates that actually have logged meals (get_day_aggregate returns {}
        # for an empty day — Pitfall 4 contract).
        totals_by_day: dict[str, dict] = {}
        for d in dates:
            agg = ms.get_day_aggregate(d)
            if agg:
                totals_by_day[d] = agg["totals"]
        macro_keys = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
        window_totals = {
            k: sum(day.get(k, 0) or 0 for day in totals_by_day.values())
            for k in macro_keys
        }

        return json.dumps({
            "meals": out,
            "totals_by_day": totals_by_day,
            "window_totals": window_totals,
            # WHY: Lifesum stamps HealthKit samples with canonical meal-slot
            # times, not the moment the user ate (verified 2026-06-12: every
            # synced meal sits exactly on 08:00/10:00/12:00/20:00). Without
            # this note the brain reasons about digestion windows from times
            # the user never ate at.
            "timestamp_note": (
                "HealthKit (Lifesum) meal timestamps are canonical SLOT times "
                "(breakfast=08:00, lunch=12:00, dinner=20:00) — NOT the actual "
                "eating time. Do not infer when the user actually ate from "
                "them; if timing matters, ask."
            ),
        })
    except Exception as exc:  # noqa: BLE001 — structured tool-result, never raise
        return json.dumps({"error": str(exc)})


@tool({
        "name": "fetch_nutrition_trend",
        "description": (
            "Get the user's nutrition TREND over the last N days: a per-day "
            "series of daily totals (calories, protein_g, carbs_g, fat_g, "
            "fiber_g, meal_count) plus SERVER-COMPUTED `averages` over the days "
            "that have logged meals (`days_with_data`). Use this for any "
            "weekly/multi-day question — average protein, calorie balance, "
            "consistency of a build phase; use fetch_recent_meals for what was "
            "eaten today/yesterday. Report the server-computed averages "
            "VERBATIM — never average the series yourself. `missing_dates` are "
            "days with NO logged meals — treat them as unlogged, never as "
            "zero-calorie days. When the profile has targets, `targets` and "
            "`avg_protein_g_per_kg` are included for comparison. "
            "Default days=14 (max 60). "
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Days back to aggregate. Default 14, max 60.",
                },
            },
            "required": [],
        },
    })
def _handle_fetch_nutrition_trend(days: int = 14) -> str:
    """Brain-direct: per-day nutrition series + server-computed averages.

    The trend companion to _handle_fetch_recent_meals: answers "how has he
    been eating this week/fortnight" (average protein, calorie balance,
    logging consistency) with all arithmetic done here in Python. Averages
    divide by days WITH data; unlogged days are reported as missing_dates,
    never counted as zero-calorie days.
    """
    from zoneinfo import ZoneInfo
    try:
        days = max(1, min(int(days), 60))  # clamp — each day is a Firestore read
    except (TypeError, ValueError):
        days = 14
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    try:
        from memory.firestore_db import MealStore
        ms = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
            database=os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
        )
        macro_keys = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")
        series: list[dict] = []
        missing_dates: list[str] = []
        for i in range(days - 1, -1, -1):  # oldest → newest
            d = (today - timedelta(days=i)).isoformat()
            agg = ms.get_day_aggregate(d)
            if agg:
                totals = agg.get("totals", {})
                series.append({
                    "date": d,
                    "meal_count": agg.get("meal_count"),
                    **{k: totals.get(k) for k in macro_keys},
                })
            else:
                missing_dates.append(d)

        averages = _compute_nutrition_averages(series, macro_keys)

        out: dict = {
            "window_days": days,
            "series": series,
            "missing_dates": missing_dates,
            "averages": averages,
        }

        # Targets comparison — silent-omit when the profile carries none.
        try:
            from memory.firestore_db import UserProfileStore
            profile = UserProfileStore(
                project_id=os.environ.get("GCP_PROJECT_ID", "klaus-agent"),
                database=os.environ.get("FIRESTORE_DATABASE", "klaus-firestore"),
            ).load()
            out.update(_nutrition_targets_and_protein_ratio(profile, averages))
        except Exception:
            logger.warning("fetch_nutrition_trend: profile read failed", exc_info=True)

        return json.dumps(out)
    except Exception as exc:  # noqa: BLE001 — structured tool-result, never raise
        return json.dumps({"error": str(exc)})
