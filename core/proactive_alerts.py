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
from datetime import date, datetime, time, timedelta
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
# Phase 24 — NUTR-01/02/03: Nutrition accountability constants       #
# ------------------------------------------------------------------ #

# Blueprint targets (Tier-A, §6 of hybrid_athlete_blueprint.md):
#   150g protein / 350g carbs daily.
#
# MACRO_THRESHOLDS encodes the "structurally meaningful shortfall" floors (D-09).
# Protein floor: 120g = 80% of 150g target — below this, amino acid availability
#   for muscle protein synthesis at Amit's training volume is meaningfully compromised.
# Carb floors by day_type — below these, glycogen replenishment is compromised:
#   normal:   250g (≈71% of 350g)
#   long_run: 300g (≈86% of 350g) — stricter floor for high-volume run days
#   deload:   200g — lower volume day, but still structural
#   rest:     200g — same relaxed floor as deload (no workout to fuel)
MACRO_THRESHOLDS: dict = {
    "protein": {
        "floor_g": 120,           # < 120g → protein-miss flag
        "target_g": 150,          # Tier-A blueprint target
    },
    "carbs": {
        "normal":   {"floor_g": 250, "target_g": 350},
        "long_run": {"floor_g": 300, "target_g": 350},
        "deload":   {"floor_g": 200, "target_g": 350},
        "rest":     {"floor_g": 200, "target_g": 350},
    },
}

# SLOT_SUPPLEMENTS (D-11 / NUTR-03): supplement riders tied to their carrier fueling slot.
# Pre-bed (slot #6) is standalone (has no macro footprint); the others ride on their
# slot miss and are surfaced at compose time by Plan 04 callers.
# Source: hybrid_athlete_blueprint.md §6
SLOT_SUPPLEMENTS: dict[str, str] = {
    "post-am-run": "D3+K2/Omega-3",
    "pm-post-lift": "Creatine",
    "pre-bed": "Mg-Glycinate/Zinc/Copper",
}

# Slot-window definitions for the 6 named fueling slots (D-10, Finding 3).
# Hard slots (#2, #5, #6) are flagged on miss; soft slots (#1, #3, #4) are not nagged.
# Windows for anchor-relative slots: offset_min and window_min from the anchor start.
_HARD_SLOT_AM: dict = {"offset_min": 15, "window_min": 90}   # post-am-run (#2)
_HARD_SLOT_PM: dict = {"offset_min": 15, "window_min": 90}   # pm-post-lift (#5)
_PRE_BED_START_HOUR = 21   # 21:00–23:59 fixed window (slot #6)

# AM types recognised as running activities (Garmin type field).
_GARMIN_AM_TYPES: frozenset[str] = frozenset(
    {"running", "trail_running", "treadmill_running"}
)
# PM types recognised as strength/gym activities (Garmin type field).
_GARMIN_PM_TYPES: frozenset[str] = frozenset(
    {"strength_training", "fitness_equipment"}
)
# Calendar event keywords for anchor resolution (priority 2 fallback).
_CALENDAR_AM_KEYWORDS: tuple[str, ...] = ("run",)
_CALENDAR_PM_KEYWORDS: tuple[str, ...] = ("gym", "lower body", "upper body")


# ------------------------------------------------------------------ #
# Phase 24 — NUTR-01: Macro-gap check (pure, no I/O)                 #
# ------------------------------------------------------------------ #

def _macro_gap_check(
    totals: dict,
    day_type: str,
    targets: dict,
) -> list[dict]:
    """Check daily macro totals against structurally meaningful shortfall floors.

    Args:
        totals:   {"protein_g": N, "carbs_g": N, ...} — today's MealStore aggregate.
        day_type: "long_run" | "normal" | "deload" | "rest" — determines carb floor.
        targets:  {"protein_g": N, "carbs_g": N} — Tier-A blueprint targets for description.

    Returns:
        List of flag dicts [{"topic_key", "description", "severity"}].
        Empty list when all macros meet their floors (no flag for marginal shortfall — D-09).

    Pure function — no Firestore, no Garmin calls, no I/O.
    """
    flags: list[dict] = []

    protein_actual = totals.get("protein_g") or 0
    carbs_actual = totals.get("carbs_g") or 0
    protein_target = targets.get("protein_g") or MACRO_THRESHOLDS["protein"]["target_g"]
    protein_floor = MACRO_THRESHOLDS["protein"]["floor_g"]

    # Protein check: only flag when below the meaningful floor (D-09 — no micro-optimization).
    if protein_actual < protein_floor:
        flags.append({
            "topic_key": "protein-miss",
            "description": (
                f"Protein today: {protein_actual}g vs {protein_target}g target "
                f"(floor {protein_floor}g — 80% of blueprint target). "
                f"Structurally meaningful shortfall for muscle protein synthesis."
            ),
            "severity": "high",
        })

    # Carb check: day-type-aware floor.
    carb_cfg = MACRO_THRESHOLDS["carbs"].get(day_type, MACRO_THRESHOLDS["carbs"]["normal"])
    carb_floor = carb_cfg["floor_g"]
    carb_target = targets.get("carbs_g") or carb_cfg["target_g"]

    if carbs_actual < carb_floor:
        topic_key = "carb-miss:long-run-day" if day_type == "long_run" else "carb-miss"
        flags.append({
            "topic_key": topic_key,
            "description": (
                f"Carbs today: {carbs_actual}g vs {carb_target}g target "
                f"(floor {carb_floor}g for {day_type} day — glycogen replenishment compromised)."
            ),
            "severity": "high" if day_type == "long_run" else "medium",
        })

    return flags


# ------------------------------------------------------------------ #
# Phase 24 — NUTR-02: Fueling-slot helpers (pure, no I/O)            #
# ------------------------------------------------------------------ #

def _to_naive_local(value: str | datetime) -> datetime:
    """Parse an ISO timestamp (or accept a datetime) → NAIVE Asia/Jerusalem datetime.

    CR-01 (Phase 24): HealthKit meal timestamps carry a UTC offset
    (``healthkit_tool._ensure_aware`` attaches Asia/Jerusalem, serialized via
    ``.isoformat()``), while the fueling-slot windows are built naive via
    ``datetime.combine``. Comparing an aware meal timestamp against a naive slot
    window raises ``TypeError``, which the outer try/except in
    ``_gather_nutrition_data`` swallows — silently dropping the entire nutrition
    section whenever real meal data exists. Normalising every datetime to naive
    local wall-clock time before comparison keeps the slot math correct and
    offset-agnostic (anchors, meals, and fixed windows all in the same frame).
    """
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(_TZ).replace(tzinfo=None)
    return dt


def _resolve_anchor_times(
    today_iso: str,
    garmin_activities: list[dict],
    calendar_events: list[dict],
) -> tuple[datetime | None, datetime | None]:
    """Resolve the AM run and PM lift anchor datetimes for today.

    Priority order for AM anchor:
      1. Garmin activity where type in _GARMIN_AM_TYPES (running/trail_running/treadmill)
      2. Calendar event with any _CALENDAR_AM_KEYWORDS in summary ("run")
      3. None — do NOT fabricate an anchor on a true rest day (Pitfall 2, D-10).
         The fallback to 07:30 is at the caller's discretion (plan 04 passes already-fetched data).

    Priority order for PM anchor:
      1. Garmin activity where type in _GARMIN_PM_TYPES (strength_training/fitness_equipment)
      2. Calendar event with any _CALENDAR_PM_KEYWORDS in summary ("gym"/"lower body"/"upper body")
      3. None — do NOT fabricate on a rest day.

    Args:
        today_iso:         YYYY-MM-DD string for date-matching calendar events.
        garmin_activities: Already-fetched list from fetch_garmin_activities(days=1).
                           Each dict has keys: "type", "date" (ISO string), "activity_id", etc.
        calendar_events:   Already-fetched list from calendar tool for today_iso.
                           Each dict has keys: "summary", "start" (ISO string), etc.

    Returns:
        (am_anchor, pm_anchor) — datetime or None for each.

    Pure function — no I/O. Data is passed in as args (testable without mocks).
    """
    am_anchor: datetime | None = None
    pm_anchor: datetime | None = None

    # --- AM anchor (priority 1: Garmin running activity) ---
    for act in (garmin_activities or []):
        if (act.get("type") or "").lower() in _GARMIN_AM_TYPES:
            try:
                am_anchor = _to_naive_local(act["date"])
                break
            except (KeyError, ValueError):
                continue

    # --- AM anchor (priority 2: calendar event with "run" in summary) ---
    if am_anchor is None:
        for event in (calendar_events or []):
            summary_lower = (event.get("summary") or "").lower()
            if any(kw in summary_lower for kw in _CALENDAR_AM_KEYWORDS):
                start = event.get("start") or ""
                if "T" in start:
                    try:
                        am_anchor = _to_naive_local(start)
                        break
                    except ValueError:
                        continue

    # --- PM anchor (priority 1: Garmin strength activity) ---
    for act in (garmin_activities or []):
        if (act.get("type") or "").lower() in _GARMIN_PM_TYPES:
            try:
                pm_anchor = _to_naive_local(act["date"])
                break
            except (KeyError, ValueError):
                continue

    # --- PM anchor (priority 2: calendar event with gym/lower body/upper body) ---
    if pm_anchor is None:
        for event in (calendar_events or []):
            summary_lower = (event.get("summary") or "").lower()
            if any(kw in summary_lower for kw in _CALENDAR_PM_KEYWORDS):
                start = event.get("start") or ""
                if "T" in start:
                    try:
                        pm_anchor = _to_naive_local(start)
                        break
                    except ValueError:
                        continue

    return am_anchor, pm_anchor


def _map_meals_to_slots(
    meals: list[dict],
    am_anchor: datetime | None,
    pm_anchor: datetime | None,
) -> dict[str, list[dict]]:
    """Bucket meals into the 6 named fueling slots based on anchor-relative windows.

    Slot definitions (D-10, Finding 3 table):
      #1 pre-am-run:   [am_anchor - 90min, am_anchor - 15min] (soft, not flagged)
      #2 post-am-run:  [am_anchor + 15min, am_anchor + 90min] (HARD — flag miss)
      #3 midday:       fixed 12:00–14:30 (soft)
      #4 pre-lift:     [pm_anchor - 90min, pm_anchor - 15min] (soft)
      #5 pm-post-lift: [pm_anchor + 15min, pm_anchor + 90min] (HARD — flag miss)
      #6 pre-bed:      fixed 21:00–23:59 (HARD — flag miss)

    Args:
        meals:     List of meal dicts from MealStore.get_day() — each has "timestamp" (ISO).
        am_anchor: AM run start datetime (or None on rest day).
        pm_anchor: PM lift start datetime (or None on rest day).

    Returns:
        dict keyed by slot name, value is list of meals in that slot.
        Slots with no meals are still present (empty list).

    Pure function — no I/O. T-24-05 mitigation: missing/malformed timestamp → meal skipped.
    """
    # Build all slot windows (start, end) — None means no anchor, slot window is empty.
    slots: dict[str, tuple[datetime | None, datetime | None]] = {}

    if am_anchor:
        slots["pre-am-run"] = (
            am_anchor - timedelta(minutes=90),
            am_anchor - timedelta(minutes=15),
        )
        slots["post-am-run"] = (
            am_anchor + timedelta(minutes=_HARD_SLOT_AM["offset_min"]),
            am_anchor + timedelta(minutes=_HARD_SLOT_AM["offset_min"] + _HARD_SLOT_AM["window_min"]),
        )

    if pm_anchor:
        slots["pre-lift"] = (
            pm_anchor - timedelta(minutes=90),
            pm_anchor - timedelta(minutes=15),
        )
        slots["pm-post-lift"] = (
            pm_anchor + timedelta(minutes=_HARD_SLOT_PM["offset_min"]),
            pm_anchor + timedelta(minutes=_HARD_SLOT_PM["offset_min"] + _HARD_SLOT_PM["window_min"]),
        )

    # Fixed-window slots (always present regardless of anchor).
    try:
        _today_date = _to_naive_local(meals[0]["timestamp"]).date() if meals else date.today()
    except (KeyError, ValueError, IndexError):
        _today_date = date.today()

    slots["midday"] = (
        datetime.combine(_today_date, datetime.strptime("12:00", "%H:%M").time()),
        datetime.combine(_today_date, datetime.strptime("14:30", "%H:%M").time()),
    )
    slots["pre-bed"] = (
        datetime.combine(_today_date, time(_PRE_BED_START_HOUR, 0)),
        datetime.combine(_today_date, time(23, 59)),
    )

    # Bucket each meal into its slot(s) — T-24-05: skip on missing/malformed timestamp.
    result: dict[str, list[dict]] = {name: [] for name in slots}
    for meal in (meals or []):
        ts_raw = meal.get("timestamp")
        if not ts_raw:
            continue
        try:
            ts = _to_naive_local(ts_raw)
        except (ValueError, TypeError):
            continue
        for slot_name, (lo, hi) in slots.items():
            if lo is not None and hi is not None and lo <= ts <= hi:
                result[slot_name].append(meal)

    return result


def _detect_slot_misses(
    meals: list[dict],
    am_anchor: datetime | None,
    pm_anchor: datetime | None,
    today_date: str,
) -> list[str]:
    """Detect missed HARD fueling slots (#2, #5, #6) for the nutrition alert.

    Only evaluates a slot when its anchor resolved — Pitfall 2 guard (D-10):
      - post-am-run: only when am_anchor is not None
      - pm-post-lift: only when pm_anchor is not None
      - pre-bed: always evaluated (fixed 21:00–23:59 window, slot #6)

    Args:
        meals:      List of meal dicts from MealStore.get_day() — each has "timestamp" (ISO).
        am_anchor:  AM run start datetime or None.
        pm_anchor:  PM lift start datetime or None.
        today_date: YYYY-MM-DD string used to construct the pre-bed fixed window.

    Returns:
        List of missed hard-slot names: subset of ["post-am-run", "pm-post-lift", "pre-bed"].

    Pure function — no I/O. T-24-05 mitigation: malformed timestamp → meal skipped.
    T-24-07 mitigation (Pitfall 2): guards prevent spurious slot flags on rest days.
    """
    missed: list[str] = []

    # Parse all meal timestamps, skipping malformed ones (T-24-05).
    meal_timestamps: list[datetime] = []
    for m in (meals or []):
        ts_raw = m.get("timestamp")
        if not ts_raw:
            continue
        try:
            meal_timestamps.append(_to_naive_local(ts_raw))
        except (ValueError, TypeError):
            continue

    def _in_window(lo: datetime, hi: datetime) -> bool:
        """Return True if any meal timestamp falls within [lo, hi] inclusive."""
        return any(lo <= t <= hi for t in meal_timestamps)

    # Slot #2 post-am-run: only when AM anchor resolved (Pitfall 2 guard).
    if am_anchor is not None:
        lo = am_anchor + timedelta(minutes=_HARD_SLOT_AM["offset_min"])
        hi = am_anchor + timedelta(minutes=_HARD_SLOT_AM["offset_min"] + _HARD_SLOT_AM["window_min"])
        if not _in_window(lo, hi):
            missed.append("post-am-run")

    # Slot #5 pm-post-lift: only when PM anchor resolved (Pitfall 2 guard).
    if pm_anchor is not None:
        lo = pm_anchor + timedelta(minutes=_HARD_SLOT_PM["offset_min"])
        hi = pm_anchor + timedelta(minutes=_HARD_SLOT_PM["offset_min"] + _HARD_SLOT_PM["window_min"])
        if not _in_window(lo, hi):
            missed.append("pm-post-lift")

    # Slot #6 pre-bed: always evaluated (fixed 21:00–23:59 window).
    try:
        _date_obj = date.fromisoformat(today_date)
    except ValueError:
        _date_obj = date.today()
    prebed_lo = datetime.combine(_date_obj, time(_PRE_BED_START_HOUR, 0))
    prebed_hi = datetime.combine(_date_obj, time(23, 59))
    if not _in_window(prebed_lo, prebed_hi):
        missed.append("pre-bed")

    return missed


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
# Phase 23 — BLOCK-02 end-of-block benchmark state machine           #
# ------------------------------------------------------------------ #

def _evaluate_benchmark_state(
    block: dict | None,
    today_iso: str,
    hrv_overnight: int | None,
    hrv_baseline: int | None,
    acwr_ratio: float | None,
) -> dict | None:
    """Pure end-of-block benchmark state machine (BLOCK-02 / D-02/D-07/D-08/D-09).

    Returns one of three state dicts, or None when no benchmark applies:
      - None: no block, Block 4 (race week — D-02), or end_date more than 3 days ahead.
      - benchmark_stale:  today is past end_date (window closed) — one caveated prompt (D-09).
      - benchmark_deferred: within window but biometrics red (HRV < 70% of baseline OR
                            ACWR > 1.2) — defer with the numeric reason (D-07/D-08).
      - benchmark_window_open: within window and the gate passes (gate-unknown → PASS,
                            erring toward prompting).
    """
    if not block:
        return None
    end_date = block.get("end_date", "")
    label = block.get("label", "")
    if not end_date:
        return None
    # D-02: Block 4 race week is never benchmarked.
    if "Race" in label or end_date == "2026-10-10":
        return None
    facets = block.get("focus_facets", [])
    # Stale: the deload window has already closed — one final caveated prompt (D-09).
    if today_iso > end_date:
        return {"state": "benchmark_stale", "end_date": end_date, "facets": facets}
    # Only fire within 3 days of the block end.
    try:
        days_left = (date.fromisoformat(end_date) - date.fromisoformat(today_iso)).days
    except ValueError:
        return None
    if days_left > 3:
        return None
    # Validity gate (D-07): defer if HRV < 70% of baseline OR ACWR > 1.2.
    hrv_pct = None
    if hrv_overnight is not None and hrv_baseline:
        hrv_pct = hrv_overnight / hrv_baseline
    gate_fail = (hrv_pct is not None and hrv_pct < 0.70) or (
        acwr_ratio is not None and acwr_ratio > 1.2
    )
    if gate_fail:
        return {
            "state": "benchmark_deferred",
            "hrv_overnight": hrv_overnight,
            "hrv_pct": round(hrv_pct * 100) if hrv_pct is not None else None,
            "acwr": acwr_ratio,
            "end_date": end_date,
            "facets": facets,
        }
    return {"state": "benchmark_window_open", "end_date": end_date, "facets": facets}


# ------------------------------------------------------------------ #
# Phase 24 — NUTR-01/02/03: Nutrition data gather helper             #
# ------------------------------------------------------------------ #

def _gather_nutrition_data(today_iso: str, garmin_activities: list[dict] | None = None) -> dict:
    """Gather meal totals, fueling-slot miss detection, and anchor times for today.

    Best-effort: each sub-gather is wrapped; failures return {} / [] / None.
    garmin_activities: pass the already-fetched list to avoid a second API call
    (RESEARCH Open Question 2 — reuse the garmin_activities already fetched).

    Pitfall 7: MealStore.get_day returns [] not None on empty days — guard with
    "if not meals" but always return the result (empty list is valid context).

    Returns:
        {
            "meals": list[dict],           # raw from MealStore.get_day
            "macro_totals": dict,          # totals sub-dict from get_day_aggregate
            "macro_gaps": list[dict],      # from _macro_gap_check
            "slot_misses": list[str],      # from _detect_slot_misses
            "am_anchor": str | None,       # ISO datetime string of AM run start
            "pm_anchor": str | None,       # ISO datetime string of PM lift start
        }

    Pure gather — no LLM calls. T-24-14 mitigation: each source wrapped best-effort.
    """
    result: dict = {
        "meals": [],
        "macro_totals": {},
        "macro_gaps": [],
        "slot_misses": [],
        "am_anchor": None,
        "pm_anchor": None,
    }

    # --- Meals + macro aggregate (MealStore) ---
    # Pitfall 7: get_day returns [] on empty days (not None); guard and continue.
    meals: list[dict] = []
    macro_totals: dict = {}
    try:
        from memory.firestore_db import MealStore
        ms = MealStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        meals = ms.get_day(today_iso) or []
        result["meals"] = meals
        agg = ms.get_day_aggregate(today_iso)
        macro_totals = (agg or {}).get("totals") or {}
        result["macro_totals"] = macro_totals
    except Exception:
        logger.warning("proactive_alerts: nutrition meal fetch failed", exc_info=True)
        result["meals"] = []
        result["macro_totals"] = {}

    # --- Nutrition targets from UserProfileStore (Tier-A, always citable) ---
    nutrition_targets: dict = {"protein_g": 150, "carbs_g": 350}  # blueprint fallback
    day_type: str = "normal"
    try:
        from memory.firestore_db import UserProfileStore
        ups = UserProfileStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        profile = ups.load() or {}
        nt = profile.get("nutrition_targets") or {}
        if nt:
            nutrition_targets = nt
        # Derive day_type from weekly_split or Garmin distance (long-run heuristic).
        # Long-run day: any running activity today with distance > 16km or duration > 70min.
        _acts = garmin_activities or []
        for act in _acts:
            atype = (act.get("type") or "").lower()
            dist_m = act.get("distance_m") or 0
            dur_s = act.get("duration_sec") or 0
            if atype in _GARMIN_AM_TYPES and (dist_m > 16000 or dur_s > 4200):
                day_type = "long_run"
                break
    except Exception:
        logger.warning("proactive_alerts: nutrition targets fetch failed", exc_info=True)

    # --- Anchor resolution (reuses garmin_activities already fetched) ---
    # calendar_events for today's date: not directly available here (cron fetches
    # target_date = tomorrow). Anchor resolution uses garmin_activities only (no calendar
    # fallback at this point — the caller passes the already-fetched garmin list).
    am_anchor: datetime | None = None
    pm_anchor: datetime | None = None
    try:
        am_anchor, pm_anchor = _resolve_anchor_times(
            today_iso,
            garmin_activities=garmin_activities or [],
            calendar_events=[],  # no today-calendar available in this gather path
        )
        result["am_anchor"] = am_anchor.isoformat() if am_anchor else None
        result["pm_anchor"] = pm_anchor.isoformat() if pm_anchor else None
    except Exception:
        logger.warning("proactive_alerts: anchor resolution failed", exc_info=True)

    # --- Slot miss detection (NUTR-02 HARD slots: #2, #5, #6) ---
    try:
        slot_misses = _detect_slot_misses(meals, am_anchor, pm_anchor, today_iso)
        result["slot_misses"] = slot_misses
    except Exception:
        logger.warning("proactive_alerts: slot miss detection failed", exc_info=True)
        result["slot_misses"] = []

    # --- Macro gap check (NUTR-01) ---
    try:
        macro_gaps = _macro_gap_check(macro_totals, day_type, nutrition_targets)
        result["macro_gaps"] = macro_gaps
    except Exception:
        logger.warning("proactive_alerts: macro gap check failed", exc_info=True)
        result["macro_gaps"] = []

    return result


def _collect_detected_topics(alerts_context: dict) -> list[str]:
    """Derive the list of topic_key strings from the composed alerts_context.

    Topic keys follow the D-01 category:subject pattern. This is a pure function
    that reads alerts_context keys to produce canonical topic_key strings for the
    coaching dedup gate.

    Returns:
        List of topic_key strings derived from the context. May be empty.
    """
    topics: list[str] = []

    # Nutrition macro gaps → topic keys from the gap flag dicts
    nutrition = alerts_context.get("nutrition") or {}
    for gap in nutrition.get("macro_gaps") or []:
        tk = gap.get("topic_key")
        if tk:
            topics.append(tk)

    # Fueling slot misses → fueling-miss:{slot} topic keys (NUTR-02)
    for slot_miss in nutrition.get("slot_misses") or []:
        topics.append(f"fueling-miss:{slot_miss}")

    # Recovery concern → recovery-conflict:{level} (existing context)
    rc = alerts_context.get("recovery_concern")
    if rc and isinstance(rc, dict):
        level = rc.get("level") or "moderate"
        topics.append(f"recovery-conflict:{level}")

    return topics


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

    today_iso = datetime.now(_TZ).date().isoformat()

    # Phase 23 — BLOCK-02: end-of-block benchmark trigger. The block-end check + the
    # set_benchmark_due write run BEFORE the dedup gate (Pitfall 3 / T-23-11) so the
    # flag is persisted even on a night the cron has already sent. Best-effort — the
    # whole block is wrapped so a Firestore hiccup never crashes the cron.
    current_block = None
    try:
        from memory.firestore_db import BlockStore
        _bs = BlockStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        current_block = _bs.get_current()
        if current_block and not current_block.get("benchmark_due"):
            _end = current_block.get("end_date", "")
            _label = current_block.get("label", "")
            _is_block4 = "Race" in _label or _end == "2026-10-10"
            if _end and not _is_block4:
                _days_left = (date.fromisoformat(_end) - date.fromisoformat(today_iso)).days
                if 0 <= _days_left <= 3:
                    _bs.set_benchmark_due(
                        current_block.get("doc_id") or current_block.get("block_id"), True
                    )
    except Exception:
        logger.warning("proactive_alerts: block-end benchmark check failed", exc_info=True)

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

    # Phase 23 — BLOCK-02: fetch today's Garmin ONCE (shared by the benchmark validity
    # gate here and recovery_concern further down — Pitfall 5), then evaluate the
    # benchmark state. Both are best-effort; gate-unknown errs toward prompting.
    garmin_data = None
    try:
        from mcp_tools import garmin_tool as _garmin
        garmin_data = _garmin.fetch_garmin_today()
    except Exception:
        logger.warning("proactive_alerts: Garmin fetch failed", exc_info=True)

    benchmark_state = None
    try:
        _hrv_o = garmin_data.get("hrv_overnight") if garmin_data else None
        _hrv_b = garmin_data.get("hrv_baseline") if garmin_data else None
        _acwr = None
        try:
            from mcp_tools.garmin_tool import compute_acwr_from_db
            _acwr = (compute_acwr_from_db() or {}).get("ratio")
        except Exception:
            logger.warning("proactive_alerts: ACWR fetch failed", exc_info=True)
        benchmark_state = _evaluate_benchmark_state(
            current_block, today_iso, _hrv_o, _hrv_b, _acwr
        )
    except Exception:
        logger.warning("proactive_alerts: benchmark gate computation failed", exc_info=True)

    # Widened no-alert early return (BLOCK-02 correctness): a benchmark-only deload
    # night has no weather/overload/travel alert but must still send, so a non-None
    # benchmark_state keeps the cron in the send path.
    if (
        not weather_alerts and not overload_alert and not travel_alerts
        and benchmark_state is None
    ):
        logger.info("Proactive alerts: no issues found for %s", target_date)
        _mark_processed(target_date, alert_sent=False)
        return

    alerts_context = {
        "target_date": target_date,
        "weather_alerts": weather_alerts,
        "overload_alert": overload_alert,
        "travel_alerts": travel_alerts,
    }
    if benchmark_state is not None:
        alerts_context["benchmark"] = benchmark_state

    # Phase 20 — RECOVERY-03 / D-16: surface recovery_concern with full framing in the
    # evening alert too (equal weight with the morning briefing). Best-effort Pattern-C:
    # fetch today's Garmin (HRV/sleep parity with the morning path) and compute the concern;
    # omit the key entirely when there is none (D-13 no-fabrication — the prompt renders the
    # recovery section only when the key is present). Note: this rides along with an alert
    # that is already firing; it does not by itself trigger an evening send.
    try:
        from core.training_checkin import compute_recovery_concern
        # Reuse the single garmin_data fetched above (Pitfall 5 — no second Garmin call).
        rc = compute_recovery_concern(garmin_data=garmin_data, today_iso=today_iso)
        if rc:
            alerts_context["recovery_concern"] = rc
    except Exception:
        logger.warning("proactive_alerts: recovery_concern computation failed", exc_info=True)
        # silent omit — no "all clear" placeholder (D-13 guardrail)

    # Phase 24 — NUTR-01/02/03: nutrition + fueling-slot gather.
    # Fetch today's Garmin activities (separate from biometric garmin_data) for anchor resolution.
    # Wrapped best-effort — a Garmin failure just means no activity-anchored slot checking.
    _garmin_activities: list[dict] = []
    try:
        from mcp_tools.garmin_tool import fetch_garmin_activities
        _garmin_activities = fetch_garmin_activities(days=1) or []
    except Exception:
        logger.warning("proactive_alerts: garmin activities fetch for nutrition failed", exc_info=True)

    try:
        nutrition_data = _gather_nutrition_data(today_iso, garmin_activities=_garmin_activities)
        if nutrition_data:
            alerts_context["nutrition"] = nutrition_data
    except Exception:
        logger.warning("proactive_alerts: nutrition gather failed", exc_info=True)
        # silent omit — no fabrication (D-13 guardrail)

    # Phase 24 — COACH-05: coaching topic dedup gate.
    # Filter detected topics to only un-raised ones before compose context.
    # Fail-open: on any store error, let all topics fire (T-24-14 / T-24-16 mitigation).
    _cts = None
    _today_il = datetime.now(_TZ).date().isoformat()
    _new_topics: list[str] = []
    try:
        from memory.firestore_db import CoachingTopicStore
        _cts = CoachingTopicStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        _detected_topics = _collect_detected_topics(alerts_context)
        _new_topics = [t for t in _detected_topics if not _cts.has_topic(_today_il, t)]
        alerts_context["coaching_topics_new"] = _new_topics
        alerts_context["coaching_topics_already_raised"] = [
            t for t in _detected_topics if t not in _new_topics
        ]
    except Exception:
        logger.warning("proactive_alerts: coaching dedup gate failed", exc_info=True)
        # fail-open: all topics fire; _cts remains None so post-send write is skipped

    message = _compose_alert(alerts_context)

    from core.scheduled_message import send_and_inject
    await send_and_inject(bot, message, inject_into_conversation=False)

    # Phase 24 — COACH-05 post-send write discipline (T-24-12 mitigation):
    # CoachingTopicStore.add_topic called ONLY after send_and_inject succeeds.
    # A crash between write and send would create a false-positive block.
    # Non-fatal: a write failure degrades dedup for this topic on the next cron.
    if _cts is not None and _new_topics:
        try:
            for _topic in _new_topics:
                _cts.add_topic(_today_il, _topic)
        except Exception:
            logger.warning(
                "proactive_alerts: coaching topic write failed — dedup may not fire next cron",
                exc_info=True,
            )

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

    # PHASE 22 — COACH-01: inject slim coaching core before {today_date}
    # (stable-prefix before volatile — same ordering as render_smart_system).
    # Degrade gracefully: a first-call AgentOrchestrator() construction can raise
    # non-OSError (e.g. missing SMART_AGENT_* env) — that must NOT abort the alert
    # send (which would also skip the dedup write), so fetch the slim core
    # independently of the prompt-file read below.
    try:
        from core.autonomous import _get_orchestrator
        coaching_guide_content = _get_orchestrator()._coaching_guide_content
    except Exception:
        logger.warning("proactive_alerts: coaching guide unavailable — proceeding without it")
        coaching_guide_content = ""
    try:
        system_prompt = (
            prompt_path.read_text(encoding="utf-8")
            .replace("{coaching_guide}", coaching_guide_content)
            .replace("{today_date}", today_str)
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
