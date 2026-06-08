"""Deterministic progress projection helper — Phase 25 PROG-02.

project_goal_progress(facet, history, dated_goals, today_iso) is a pure function:
- No I/O, no LLM calls, no Firestore reads, no network calls.
- Never calls date.today() or datetime.now() — caller provides today_iso (CR-01 lesson).
- Never raises — wraps the entire body in try/except and returns a no_data result on error.
- Returns a plain dict (asdict of ProjectionResult) — JSON-serializable.

Confidence tiers (D-01):
  >= 2 data points: linear least-squares projection to deadline date
  1 data point:     baseline_only — cannot project, no trend yet
  0 data points:    no_data

Direction (FACET_DIRECTION):
  higher-is-better: on_track = projected >= target (e.g. bench_press_1rm, squat_1rm)
  lower-is-better:  on_track = projected <= target (e.g. threshold_pace sec/km = faster = lower)
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level lookup tables
# ---------------------------------------------------------------------------

# Facet → direction: True = higher-is-better, False = lower-is-better
FACET_DIRECTION: dict[str, bool] = {
    "bench_press_1rm": True,   # kg, higher = better
    "squat_1rm":       True,   # kg, higher = better
    "push_ups":        True,   # reps, higher = better
    "pull_ups":        True,   # reps, higher = better
    "threshold_pace":  False,  # sec/km, lower = better (faster pace)
}

# dated_goals.metrics keys → BenchmarkStore facet names.
# half_marathon_time requires a separate unit conversion via _hm_to_sec_per_km.
# 3k_time and 400m_time have no BenchmarkStore facet — intentionally excluded.
GOAL_METRIC_TO_FACET: dict[str, str] = {
    "bench_press_kg": "bench_press_1rm",
    "squat_kg":       "squat_1rm",
    "push_ups":       "push_ups",
    "pull_ups":       "pull_ups",
    # half_marathon_time → threshold_pace (handled via _hm_to_sec_per_km below)
}

# Reverse map: facet → metric key in dated_goals.metrics
# (half_marathon_time is special-cased below)
_FACET_TO_METRIC: dict[str, str] = {v: k for k, v in GOAL_METRIC_TO_FACET.items()}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ProjectionResult:
    facet: str
    confidence: str           # "high" | "medium" | "low" | "baseline_only" | "no_data"
    data_point_count: int
    projected_value: Optional[float]   # None when < 2 unique-date points
    target_value: Optional[float]      # None when no matching dated goal
    target_date: Optional[str]         # ISO YYYY-MM-DD, or None
    gap: Optional[float]               # projected_value - target_value (signed)
    on_track: Optional[bool]           # None when can't project
    unit: str
    confidence_label: str              # human-readable


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _hm_to_sec_per_km(hms: str) -> float:
    """Parse a half-marathon time string 'H:MM:SS' to sec/km.

    Divides total seconds by 21.1 km.
    Example: '1:25:00' → (60+25)*60 / 21.1 ≈ 241.7 sec/km
    """
    parts = hms.strip().split(":")
    if len(parts) == 2:
        # MM:SS format
        minutes, seconds = int(parts[0]), int(parts[1])
        total_seconds = minutes * 60 + seconds
    elif len(parts) == 3:
        # H:MM:SS format
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        total_seconds = hours * 3600 + minutes * 60 + seconds
    else:
        raise ValueError(f"Cannot parse time string: {hms!r}")
    return total_seconds / 21.1


def _linear_project(points: list[tuple[float, float]], target_t: float) -> float:
    """Least-squares linear projection of (t, value) points to target_t.

    Args:
        points:   List of (t, value) tuples where t is days from a fixed epoch.
        target_t: Target time (days from the same fixed epoch).

    Returns:
        Projected value at target_t. Falls back to last value when denominator = 0.
        Never raises.
    """
    n = len(points)
    if n == 1:
        return points[0][1]  # single point — no trend, return its value
    ts = [p[0] for p in points]
    vs = [p[1] for p in points]
    t_mean = sum(ts) / n
    v_mean = sum(vs) / n
    num = sum((ts[i] - t_mean) * (vs[i] - v_mean) for i in range(n))
    den = sum((ts[i] - t_mean) ** 2 for i in range(n))
    slope = num / den if den != 0 else 0.0
    return v_mean + slope * (target_t - t_mean)


def _resolve_target(
    facet: str,
    dated_goals: list[dict],
) -> tuple[Optional[float], Optional[str], str]:
    """Resolve (target_value, target_date, unit) for a facet from dated_goals.

    Returns (None, None, "") when no matching dated goal exists.
    For threshold_pace, converts the half_marathon_time string to sec/km.
    """
    # Special case: threshold_pace maps via half_marathon_time
    if facet == "threshold_pace":
        for goal in dated_goals:
            metrics = goal.get("metrics") or {}
            hm_time = metrics.get("half_marathon_time")
            if hm_time:
                target_value = _hm_to_sec_per_km(hm_time)
                return target_value, goal.get("target_date"), "sec_per_km"
        return None, None, "sec_per_km"

    # Standard facets: look up via _FACET_TO_METRIC
    metric_key = _FACET_TO_METRIC.get(facet)
    if metric_key is None:
        return None, None, ""

    for goal in dated_goals:
        metrics = goal.get("metrics") or {}
        if metric_key in metrics:
            raw_value = metrics[metric_key]
            # Determine unit from facet
            unit = "kg" if facet in ("bench_press_1rm", "squat_1rm") else "reps"
            return float(raw_value), goal.get("target_date"), unit

    return None, None, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def project_goal_progress(
    facet: str,
    history: list[dict],
    dated_goals: list[dict],
    today_iso: str,
) -> dict:
    """Compute a linear trend projection from sparse benchmark history.

    Args:
        facet:       BenchmarkStore facet name (from _BENCHMARK_FACETS).
        history:     List of benchmark entry dicts (date-desc order) from
                     BenchmarkStore.get_facet_history. Each entry has at
                     least: {date: str, facet: str, value: float, unit: str}.
        dated_goals: List of goal dicts from UserProfileStore.load()["dated_goals"].
                     Shape: [{target_date: str, goal_label: str, metrics: {…}}, …]
        today_iso:   Today's date as ISO string "YYYY-MM-DD". NEVER call date.today()
                     internally — caller provides this value (CR-01 tz lesson).

    Returns:
        A JSON-serializable dict (asdict of ProjectionResult) with fields:
          facet, confidence, data_point_count, projected_value, target_value,
          target_date, gap, on_track, unit, confidence_label

    Confidence tiers (D-01):
      >= 2 unique-date points: linear projection + confidence level
      1 unique-date point:     baseline_only
      0 points:                no_data

    Direction (FACET_DIRECTION):
      higher-is-better: on_track = projected >= target
      lower-is-better:  on_track = projected <= target (threshold_pace)

    Never raises — returns a no_data result on any exception.
    """
    try:
        # ------------------------------------------------------------------
        # 1. Resolve target from dated_goals
        # ------------------------------------------------------------------
        target_value, target_date_str, unit = _resolve_target(facet, dated_goals)

        # Infer unit from history if not resolved from goals
        if not unit and history:
            unit = history[0].get("unit", "")

        # ------------------------------------------------------------------
        # 2. Deduplicate history by date (Pitfall 2 — same-date entries)
        #    Keep the most recent value per date (i.e., highest value if dates
        #    are equal, keeping the first in a date-desc sorted list).
        # ------------------------------------------------------------------
        seen_dates: dict[str, float] = {}
        for entry in history:
            entry_date = entry.get("date", "")
            entry_value = entry.get("value")
            if entry_value is None:
                continue
            if entry_date not in seen_dates:
                seen_dates[entry_date] = float(entry_value)

        unique_points_by_date = sorted(seen_dates.items())  # [(date_str, value), ...] asc
        n = len(unique_points_by_date)

        # ------------------------------------------------------------------
        # 3. Branch on point count
        # ------------------------------------------------------------------
        if n == 0:
            return asdict(ProjectionResult(
                facet=facet,
                confidence="no_data",
                data_point_count=0,
                projected_value=None,
                target_value=target_value,
                target_date=target_date_str,
                gap=None,
                on_track=None,
                unit=unit,
                confidence_label="no measured data",
            ))

        if n == 1:
            return asdict(ProjectionResult(
                facet=facet,
                confidence="baseline_only",
                data_point_count=1,
                projected_value=None,
                target_value=target_value,
                target_date=target_date_str,
                gap=None,
                on_track=None,
                unit=unit,
                confidence_label="baseline only, no trend yet",
            ))

        # ------------------------------------------------------------------
        # n >= 2: compute linear projection
        # ------------------------------------------------------------------
        # Use the earliest date in history as the epoch (t=0)
        epoch = date.fromisoformat(unique_points_by_date[0][0])

        # Build (t, value) pairs; t = days from epoch
        points: list[tuple[float, float]] = []
        for date_str, value in unique_points_by_date:
            t = (date.fromisoformat(date_str) - epoch).days
            points.append((float(t), value))

        # Compute target_t (days from epoch to target deadline)
        if target_date_str:
            target_date_obj = date.fromisoformat(target_date_str)
            target_t = float((target_date_obj - epoch).days)
        else:
            # No dated goal — project to today as a fallback
            today_date = date.fromisoformat(today_iso)
            target_t = float((today_date - epoch).days)

        projected_value = _linear_project(points, target_t)

        # ------------------------------------------------------------------
        # 4. Confidence level
        # ------------------------------------------------------------------
        if n == 2:
            confidence = "low"
            confidence_label = "from only 2 benchmarks — low confidence"
        elif n == 3:
            confidence = "medium"
            confidence_label = f"from {n} benchmarks"
        else:
            confidence = "high"
            confidence_label = f"from {n} benchmarks"

        # ------------------------------------------------------------------
        # 5. Direction-aware gap and on_track
        # ------------------------------------------------------------------
        higher_is_better = FACET_DIRECTION.get(facet, True)

        if target_value is not None:
            gap = projected_value - target_value
            if higher_is_better:
                on_track = projected_value >= target_value
            else:
                on_track = projected_value <= target_value
        else:
            gap = None
            on_track = None

        return asdict(ProjectionResult(
            facet=facet,
            confidence=confidence,
            data_point_count=n,
            projected_value=projected_value,
            target_value=target_value,
            target_date=target_date_str,
            gap=gap,
            on_track=on_track,
            unit=unit,
            confidence_label=confidence_label,
        ))

    except Exception:
        logger.warning(
            "projection: unexpected error for facet %s", facet, exc_info=True
        )
        return {
            "facet": facet,
            "confidence": "no_data",
            "data_point_count": 0,
            "projected_value": None,
            "target_value": None,
            "target_date": None,
            "gap": None,
            "on_track": None,
            "unit": "",
            "confidence_label": "projection error",
        }
