"""Time-series aggregation behind the Hub's health charts.

Backs `GET /api/health/training`, `/api/health/nutrition` and `/api/health/sleep`.
Turns raw store rows into the bucketed, axis-aligned series the charts expect,
including the weekly bucketing that keeps a 1-year range readable.

The `range` parameter is an allowlist, never int()-parsed from client input.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# Process-local TTL for Hub health aggregation. Nothing behind it is billable
# per-call any more — the Routes API and its persisted cost ledger are gone.
# It lived beside the /api/today helpers before this split, several hundred
# lines from the only cache that reads it.
_HEALTH_CACHE_TTL_SECONDS = 1800  # 30 minutes


_VALID_RANGES: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}


_WEEKLY_BUCKET_THRESHOLD_DAYS = 90  # D-07: >90d ranges bucket to weekly points


_MILEAGE_WEEKLY_THRESHOLD_DAYS = 7  # mileage buckets to weekly beyond the 7d view


def _resolve_range(range_param: str) -> int:
    """Map a client range string to a day count. Defaults to 30 on any invalid input.

    Allowlist `.get()` only — never `int()`-parse an arbitrary client-supplied
    value into date arithmetic (T-30-02-01).
    """
    return _VALID_RANGES.get(range_param, 30)


def _range_bounds(range_param: str) -> tuple[str, str]:
    """Resolve a range param to inclusive (start_iso, end_iso), Asia/Jerusalem 'today'."""
    days = _resolve_range(range_param)
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    start = today - timedelta(days=days - 1)
    return start.isoformat(), today.isoformat()


def _week_axis_for_dates(date_isos: list[str]) -> list[tuple[tuple[int, int], str]]:
    """Ordered ``[((iso_year, iso_week), representative_label), ...]`` for a set of
    ISO dates — a shared weekly x-axis so series meant to be overlaid/index-aligned
    (HRV overnight+baseline, sleep score+duration) bucket onto the SAME weeks,
    with ``y=None`` filling any week a given series happens to lack (WR-04). Label
    = earliest date in each week, matching ``_weekly_bucket_points``.
    """
    from datetime import date as _date

    label: dict[tuple[int, int], str] = {}
    for x in date_isos:
        try:
            key = _date.fromisoformat(x).isocalendar()[:2]
        except (ValueError, TypeError):
            continue
        if key not in label or x < label[key]:
            label[key] = x
    return [(k, label[k]) for k in sorted(label.keys())]


def _weekly_bucket_points(
    points: list[dict],
    agg: str = "avg",
    week_axis: list[tuple[tuple[int, int], str]] | None = None,
) -> list[dict]:
    """Bucket ``{"x": date_iso, "y": number|None}`` points into weekly points.

    Keyed on ``date.fromisoformat(x).isocalendar()`` (year, week) per D-07 — call
    only when the resolved day count exceeds _WEEKLY_BUCKET_THRESHOLD_DAYS. Points
    with ``y=None`` never contribute to a bucket's aggregate (D-08 — a gap must
    never masquerade as a zero). agg="sum" sums the week's values instead of
    averaging (used for weekly mileage).

    Without ``week_axis`` a week with zero non-null contributions is omitted
    entirely (stays a gap). With ``week_axis`` (a fixed ordered week list from
    ``_week_axis_for_dates``) the output has exactly one point per axis week — the
    aggregate, or ``y=None`` for an empty week — so multiple series bucketed
    against the SAME axis stay index-aligned when overlaid (WR-04).
    """
    from datetime import date as _date

    buckets: dict[tuple[int, int], list[float]] = {}
    week_label: dict[tuple[int, int], str] = {}
    for p in points:
        y = p.get("y")
        if y is None:
            continue
        try:
            d = _date.fromisoformat(p["x"])
        except (KeyError, ValueError, TypeError):
            continue
        key = d.isocalendar()[:2]
        buckets.setdefault(key, []).append(float(y))
        if key not in week_label or p["x"] < week_label[key]:
            week_label[key] = p["x"]

    def _agg(vals: list[float]) -> float:
        return round(sum(vals) if agg == "sum" else sum(vals) / len(vals), 1)

    if week_axis is not None:
        return [
            {"x": lbl, "y": _agg(buckets[key]) if buckets.get(key) else None}
            for key, lbl in week_axis
        ]

    out = []
    for key in sorted(buckets.keys()):
        out.append({"x": week_label[key], "y": _agg(buckets[key])})
    return out


def _health_training_strength(start: str, end: str) -> list[dict]:
    """Strength sessions in [start, end], newest-first. Never raises — [] on error."""
    try:
        from memory.firestore_db import StrengthSessionStore  # lazy import
        store = StrengthSessionStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        return store.get_range(start, end)
    except Exception:
        logger.warning("_health_training_strength(%r, %r) failed", start, end, exc_info=True)
        return []


def _health_training_runs(start: str, end: str) -> list[dict]:
    """Runs in [start, end], newest-first. Never raises — [] on error."""
    try:
        from memory.firestore_db import RunDetailStore  # lazy import
        store = RunDetailStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        return store.get_range(start, end)
    except Exception:
        logger.warning("_health_training_runs(%r, %r) failed", start, end, exc_info=True)
        return []


def _health_training_benchmarks(start: str, end: str) -> list[dict]:
    """Benchmarks in [start, end], each augmented with `previous_value`.

    previous_value is the prior same-facet result (via get_facet_history), i.e.
    the newest entry strictly older than this one's date — None when no prior
    exists. Never raises — [] on error.
    """
    try:
        from memory.firestore_db import BenchmarkStore  # lazy import
        store = BenchmarkStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        benchmarks = store.get_range(start, end)
        result = []
        for b in benchmarks:
            facet = b.get("facet")
            prev_value = None
            if facet:
                # get_facet_history is newest-first; the first entry strictly
                # older than this benchmark's date is the "previous" result.
                history = store.get_facet_history(facet, n=1000)
                this_date = b.get("date", "")
                for h in history:
                    if h.get("date", "") < this_date:
                        prev_value = h.get("value")
                        break
            result.append({**b, "previous_value": prev_value})
        return result
    except Exception:
        logger.warning(
            "_health_training_benchmarks(%r, %r) failed", start, end, exc_info=True
        )
        return []


def _health_training_blocks() -> list[dict]:
    """All training blocks, sorted start_date ascending, each carrying a
    sequential 1-based block_number (BlockStore stores no number field) and its
    `label` (NOT `block_name`, which does not exist). Never raises — [] on error.
    """
    try:
        from memory.firestore_db import BlockStore  # lazy import
        store = BlockStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        blocks = store.get_all()
        blocks_sorted = sorted(blocks, key=lambda b: b.get("start_date", ""))
        return [
            {**b, "block_number": i + 1, "label": b.get("label")}
            for i, b in enumerate(blocks_sorted)
        ]
    except Exception:
        logger.warning("_health_training_blocks() failed", exc_info=True)
        return []


_NUTRITION_MACRO_KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g")


# The canonical slot mapping is owned by the today view, which is where a meal's
# slot is first named. This used to be `_SLOT_LABELS_HEALTH = _SLOT_LABELS`, an
# alias inside one huge module that quietly tied the health section to the today
# section hundreds of lines above it. Now it is an ordinary import, and there is
# still exactly one mapping.
from core.hub.today import _SLOT_LABELS as _SLOT_LABELS_HEALTH  # noqa: E402


# Single per-day read pass cache (Pitfall 1 — MealStore has no range-read method;
# a 1y nutrition request would otherwise be ~365 sequential Firestore reads on
# every request). The cache is process-local because this endpoint is not a
# paid provider boundary (T-30-02-03).
_nutrition_daily_cache: dict = {}


def _slot_label_for_meal(meal: dict) -> str:
    """Derive the canonical fueling-slot LABEL from a meal's timestamp.

    Mirrors _today_meals' inline slot-label derivation. Per CLAUDE.md §6: the
    HH:MM portion is a canonical slot identifier, NOT an eating time — only the
    LABEL (e.g. "Breakfast") may ever appear on the wire, never the HH:MM itself.
    """
    ts = meal.get("timestamp", "")
    try:
        time_part = ts[11:16] if len(ts) >= 16 else ts[:5]
    except (IndexError, TypeError):
        time_part = ""
    return _SLOT_LABELS_HEALTH.get(time_part, "Meal")


def _health_nutrition_daily(start: str, end: str) -> dict:
    """Single per-day Firestore pass feeding BOTH the macro series and the
    slot-adherence matrix (RESEARCH.md Pitfall 1 — never two independent
    ~365-read loops over the same range). TTL-cached per (start, end) so a
    repeated 1y request is served from cache (T-30-02-03 / mandatory for >90d).

    Returns {"day_records": [...], "missing_dates": [...], "slot_records": [...]}.
    day_records only contains dates WITH logged meals (D-08 — an unlogged day is
    a gap, never a zero-fill). Never raises — degrades to all-empty on error.
    """
    import time as _time
    from datetime import date as _date, timedelta as _td

    cache_key = (start, end)
    now_epoch = _time.time()
    cached = _nutrition_daily_cache.get(cache_key)
    if cached is not None:
        cache_ts, cached_result = cached
        if now_epoch - cache_ts < _HEALTH_CACHE_TTL_SECONDS:
            return cached_result

    try:
        from memory.firestore_db import MealStore  # lazy import
        store = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        start_d = _date.fromisoformat(start)
        end_d = _date.fromisoformat(end)
        dates = []
        d = start_d
        while d <= end_d:
            dates.append(d.isoformat())
            d += _td(days=1)

        day_records: list[dict] = []
        missing_dates: list[str] = []
        slot_records: list[dict] = []
        for d_iso in dates:
            meals = store.get_day(d_iso)
            if not meals:
                missing_dates.append(d_iso)  # D-08 — a gap, never a zero-fill
                continue
            totals = {
                k: sum(m.get(k) or 0 for m in meals) for k in _NUTRITION_MACRO_KEYS
            }
            day_records.append({"date": d_iso, "meal_count": len(meals), **totals})
            seen_slots: set[str] = set()
            for m in meals:
                label = _slot_label_for_meal(m)
                if label and label not in seen_slots:
                    seen_slots.add(label)
                    slot_records.append({"date": d_iso, "slot_label": label})

        result = {
            "day_records": day_records,
            "missing_dates": missing_dates,
            "slot_records": slot_records,
        }
    except Exception:
        logger.warning("_health_nutrition_daily(%r, %r) failed", start, end, exc_info=True)
        # Do NOT cache the degraded result — a transient Firestore error would
        # otherwise poison the nutrition page for the full TTL window (WR-01).
        return {"day_records": [], "missing_dates": [], "slot_records": []}

    _nutrition_daily_cache[cache_key] = (now_epoch, result)
    return result


def _health_nutrition_profile() -> dict:
    """UserProfileStore.load() — nutrition_targets + bodyweight_kg. {} on error."""
    try:
        from memory.firestore_db import UserProfileStore  # lazy import
        return UserProfileStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        ).load()
    except Exception:
        logger.warning("_health_nutrition_profile() failed", exc_info=True)
        return {}


def _resolve_calories_target(targets: dict) -> tuple[float | None, bool]:
    """Return (calories_target, derived_bool).

    Reads a stored `calories` key if present; else derives
    protein_g*4 + carbs_g*4 + fat_g*9 from whatever macro-gram target keys exist
    and tags the result as derived (RESEARCH.md Open Question A4 — the live
    `nutrition_targets` profile has NO literal `calories` key). Returns
    (None, False) when neither a stored key nor any macro-gram key exists —
    never silently omits the target line when derivation is possible.
    """
    if not targets:
        return None, False
    if targets.get("calories") is not None:
        return targets["calories"], False
    protein_g = targets.get("protein_g")
    carbs_g = targets.get("carbs_g")
    fat_g = targets.get("fat_g")
    if protein_g is None and carbs_g is None and fat_g is None:
        return None, False
    calories = (protein_g or 0) * 4 + (carbs_g or 0) * 4 + (fat_g or 0) * 9
    return round(calories, 0), True


def _health_nutrition_slots(daily: dict) -> dict:
    """Shape slot_records (from _health_nutrition_daily's single pass) into the
    D-13 per-slot-per-day hit matrix. Issues NO additional Firestore reads.

    Cells are keyed on slot LABEL only — never a derived clock time (CLAUDE.md §6).
    """
    slot_records = daily["slot_records"]
    labels = sorted({r["slot_label"] for r in slot_records})
    dates = sorted({r["date"] for r in slot_records})
    hit_set = {(r["date"], r["slot_label"]) for r in slot_records}
    grid = [
        {
            "slot_label": label,
            "cells": [{"date": d, "hit": (d, label) in hit_set} for d in dates],
        }
        for label in labels
    ]
    return {"slot_labels": labels, "dates": dates, "grid": grid}


def _health_sleep_data(start: str, end: str) -> list[dict]:
    """daily_biometrics rows in [start, end], oldest-first. Never raises — [] on error.

    Thin wrapper over core.health_reads.fetch_biometric_range (itself never
    raises) so this module keeps the same lazy-import + try/except discipline
    as every other _health_* helper in this file.
    """
    try:
        from core.health_reads import fetch_biometric_range  # lazy import
        return fetch_biometric_range(start, end)
    except Exception:
        logger.warning("_health_sleep_data(%r, %r) failed", start, end, exc_info=True)
        return []


def _health_sleep_pipeline_active() -> bool:
    """True iff daily_biometrics has EVER had a row — distinct from "no rows in
    this specific range" (RESEARCH.md Pitfall 4 / D-19). Reuses
    fetch_biometric_range with a maximally wide bound rather than adding a new
    Postgres reader. Never raises — False on error.
    """
    try:
        from core.health_reads import fetch_biometric_range  # lazy import
        return bool(fetch_biometric_range("1970-01-01", "2099-12-31"))
    except Exception:
        logger.warning("_health_sleep_pipeline_active() failed", exc_info=True)
        return False


def _hrv_baseline_with_fallback(rows: list[dict]) -> dict[str, float | None]:
    """Per-date HRV baseline: prefer the stored `hrv_baseline` column (Garmin's
    own rolling weekly average); when that column is sparse (fewer than half of
    the given rows have a value), fall back to a rolling median of
    `hrv_overnight` over the prior <=7 days — mirrors
    core.training.recovery.compute_recovery_deviation's own fallback
    (`median(prior_hrv)`), reused rather than reinvented (RESEARCH.md Pitfall 5).

    Args:
        rows: daily_biometrics rows, sorted ascending by date (fetch_biometric_range's
              contract).

    Returns:
        {date: baseline_value_or_None} — one entry per row.
    """
    from statistics import median

    if not rows:
        return {}

    non_null = sum(1 for r in rows if r.get("hrv_baseline") is not None)
    sparse = non_null < (len(rows) / 2)

    out: dict[str, float | None] = {}
    if not sparse:
        for r in rows:
            out[r["date"]] = r.get("hrv_baseline")
        return out

    for i, r in enumerate(rows):
        prior = [
            rr["hrv_overnight"]
            for rr in rows[max(0, i - 7):i]
            if rr.get("hrv_overnight") is not None
        ]
        out[r["date"]] = round(median(prior), 1) if prior else None
    return out
