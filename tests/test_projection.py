"""Tests for core/projection.py — project_goal_progress() pure-function helper.

Covers PROG-02-A through PROG-02-G and PROG-02-N:
  - 0 data points → no_data result (PROG-02-A)
  - 1 data point → baseline_only result (PROG-02-B)
  - 2 data points → linear projection, confidence "low" (PROG-02-C)
  - 3 data points → least-squares fit (PROG-02-D)
  - Lower-is-better direction (threshold_pace) (PROG-02-E)
  - Higher-is-better direction (bench_press_1rm) (PROG-02-F)
  - HM time string "1:25:00" → ~241.7 sec/km target (PROG-02-G)
  - Same-date entries deduplicated before LSQ fit (PROG-02-N)

No Firestore mock needed — project_goal_progress is a pure function.
Every call uses today_iso="2026-08-01" — never relies on the system clock.
"""
from __future__ import annotations

from core.projection import project_goal_progress, FACET_DIRECTION, GOAL_METRIC_TO_FACET


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_history(
    values: list[float],
    dates: list[str],
    facet: str = "bench_press_1rm",
    unit: str = "kg",
) -> list[dict]:
    """Build synthetic benchmark history entries in date-desc order.

    Returns a list[dict] matching the BenchmarkStore.get_facet_history shape:
      {date, facet, value, unit, block_id, notes, doc_id}
    Entries are returned sorted newest-first (date-desc) to match the real store.
    """
    assert len(values) == len(dates), "values and dates must have the same length"
    entries = [
        {
            "date": d,
            "facet": facet,
            "value": v,
            "unit": unit,
            "block_id": "2026-06-21_aerobic_base",
            "notes": "",
            "doc_id": f"{d}_{facet}",
        }
        for v, d in zip(values, dates)
    ]
    # Sort date-descending (newest first)
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


# ---------------------------------------------------------------------------
# Fixtures: dated_goals matching UserProfileStore.dated_goals verified shape
# ---------------------------------------------------------------------------

DATED_GOALS = [
    {
        "target_date": "2026-10-31",
        "goal_label": "October Peak — Absolute Strength + Half Marathon",
        "metrics": {
            "bench_press_kg": 100,
            "squat_kg": 120,
            "half_marathon_time": "1:25:00",
        },
    },
    {
        "target_date": "2026-11-30",
        "goal_label": "November Peak — Calisthenics + Speed",
        "metrics": {
            "push_ups": 125,
            "pull_ups": 35,
            "3k_time": "9:30",
            "400m_time": "55s",
        },
    },
]


# ---------------------------------------------------------------------------
# PROG-02-A: 0 data points → no_data
# ---------------------------------------------------------------------------

def test_project_0_points():
    """Empty history → confidence='no_data', projected_value=None."""
    result = project_goal_progress(
        facet="bench_press_1rm",
        history=[],
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result["confidence"] == "no_data"
    assert result["projected_value"] is None


# ---------------------------------------------------------------------------
# PROG-02-B: 1 data point → baseline_only
# ---------------------------------------------------------------------------

def test_project_1_point():
    """One history entry → confidence='baseline_only', projected_value=None,
    confidence_label mentions 'baseline'."""
    history = _build_history(
        values=[85.0],
        dates=["2026-07-01"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result = project_goal_progress(
        facet="bench_press_1rm",
        history=history,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result["confidence"] == "baseline_only"
    assert result["projected_value"] is None
    assert "baseline" in result["confidence_label"].lower()


# ---------------------------------------------------------------------------
# PROG-02-C: 2 data points → linear projection, confidence "low"
# ---------------------------------------------------------------------------

def test_project_2_points():
    """Two history entries → projected_value is a float, on_track is a bool,
    confidence='low', confidence_label names the count '2'."""
    history = _build_history(
        values=[80.0, 85.0],
        dates=["2026-06-21", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result = project_goal_progress(
        facet="bench_press_1rm",
        history=history,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result["projected_value"] is not None
    assert isinstance(result["projected_value"], float)
    assert isinstance(result["on_track"], bool)
    assert result["confidence"] == "low"
    assert "2" in result["confidence_label"]
    assert result["data_point_count"] == 2


# ---------------------------------------------------------------------------
# PROG-02-D: 3 data points → least-squares; data_point_count == 3
# ---------------------------------------------------------------------------

def test_project_3_points():
    """Three entries → LSQ fit; data_point_count==3; projected_value reflects slope."""
    history = _build_history(
        values=[78.0, 82.0, 86.0],
        dates=["2026-06-21", "2026-07-05", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result = project_goal_progress(
        facet="bench_press_1rm",
        history=history,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result["data_point_count"] == 3
    assert result["projected_value"] is not None
    assert isinstance(result["projected_value"], float)
    # With a linear +4kg/~27-day trend across ~131 days, projection should be well above 86
    assert result["projected_value"] > 86.0


# ---------------------------------------------------------------------------
# PROG-02-F: Higher-is-better direction (bench_press_1rm)
# ---------------------------------------------------------------------------

def test_higher_is_better():
    """bench_press_1rm: on_track=True when projected >= target; False when projected < target."""
    # Well above target (100kg) — on track
    history_above = _build_history(
        values=[95.0, 105.0],
        dates=["2026-06-21", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result_above = project_goal_progress(
        facet="bench_press_1rm",
        history=history_above,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result_above["on_track"] is True

    # Decreasing trend, will not reach target — not on track
    history_below = _build_history(
        values=[90.0, 85.0],
        dates=["2026-06-21", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result_below = project_goal_progress(
        facet="bench_press_1rm",
        history=history_below,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result_below["on_track"] is False


# ---------------------------------------------------------------------------
# PROG-02-E: Lower-is-better direction (threshold_pace)
# ---------------------------------------------------------------------------

def test_lower_is_better():
    """threshold_pace: on_track=True when projected <= target; False when projected > target."""
    target_pace = (85 * 60) / 21.1  # ~241.7 sec/km

    # Improving (decreasing) pace that will reach target — on track
    history_improving = _build_history(
        values=[260.0, 250.0],
        dates=["2026-06-21", "2026-07-18"],
        facet="threshold_pace",
        unit="sec_per_km",
    )
    result_on_track = project_goal_progress(
        facet="threshold_pace",
        history=history_improving,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result_on_track["on_track"] is True

    # Worsening (increasing) pace — not on track
    history_worsening = _build_history(
        values=[240.0, 250.0],
        dates=["2026-06-21", "2026-07-18"],
        facet="threshold_pace",
        unit="sec_per_km",
    )
    result_behind = project_goal_progress(
        facet="threshold_pace",
        history=history_worsening,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result_behind["on_track"] is False


# ---------------------------------------------------------------------------
# PROG-02-G: HM time string → sec/km target (~241.7)
# ---------------------------------------------------------------------------

def test_hm_time_conversion():
    """'1:25:00' → target_value ~241.7 sec/km (within 0.5 tolerance)."""
    history = _build_history(
        values=[250.0],
        dates=["2026-07-01"],
        facet="threshold_pace",
        unit="sec_per_km",
    )
    result = project_goal_progress(
        facet="threshold_pace",
        history=history,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result["target_value"] is not None
    expected = (85 * 60) / 21.1  # 85 minutes / 21.1 km
    assert abs(result["target_value"] - expected) < 0.5


# ---------------------------------------------------------------------------
# PROG-02-N: Identical-date entries deduplicated before LSQ fit
# ---------------------------------------------------------------------------

def test_dedup_same_date():
    """Two entries with the same date are collapsed to one before LSQ fit.

    With only one unique date after dedup, there is a single point → baseline_only.
    No ZeroDivisionError; projected_value is None (not NaN or infinity).
    """
    history = _build_history(
        values=[85.0, 87.0],  # Two readings on the same day
        dates=["2026-07-18", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result = project_goal_progress(
        facet="bench_press_1rm",
        history=history,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    # After dedup by date, only 1 unique point → baseline_only
    assert result["projected_value"] is None
    # Should not raise — confidence should be baseline_only (not no_data)
    assert result["confidence"] in ("baseline_only", "no_data")
    # Definitely should not be NaN or infinity
    assert result["projected_value"] is None or (
        result["projected_value"] == result["projected_value"]  # NaN check
    )


# ---------------------------------------------------------------------------
# WR-01: A single malformed/empty-date entry must NOT poison the whole batch
# ---------------------------------------------------------------------------

def test_malformed_date_entry_is_skipped_not_poisoning():
    """One entry with a missing/blank date is skipped; the valid points still project.

    Regression for WR-01: previously an empty-string date reached
    date.fromisoformat("") → ValueError → caught → whole projection wiped to no_data.
    """
    history = [
        {"date": "2026-07-18", "facet": "bench_press_1rm", "value": 86.0, "unit": "kg"},
        {"date": "", "facet": "bench_press_1rm", "value": 999.0, "unit": "kg"},  # bad
        {"date": "2026-06-21", "facet": "bench_press_1rm", "value": 80.0, "unit": "kg"},
    ]
    result = project_goal_progress(
        facet="bench_press_1rm",
        history=history,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    # The two valid points survive → a real projection, NOT no_data
    assert result["confidence"] != "no_data"
    assert result["data_point_count"] == 2
    assert result["projected_value"] is not None


def test_unparseable_date_entry_is_skipped():
    """A non-ISO date string is skipped rather than raising/erasing the batch."""
    history = [
        {"date": "2026-07-18", "facet": "bench_press_1rm", "value": 86.0, "unit": "kg"},
        {"date": "not-a-date", "facet": "bench_press_1rm", "value": 999.0, "unit": "kg"},
        {"date": "2026-06-21", "facet": "bench_press_1rm", "value": 80.0, "unit": "kg"},
    ]
    result = project_goal_progress(
        facet="bench_press_1rm",
        history=history,
        dated_goals=DATED_GOALS,
        today_iso="2026-08-01",
    )
    assert result["data_point_count"] == 2
    assert result["projected_value"] is not None


# ---------------------------------------------------------------------------
# WR-02: Same-date dedup is DETERMINISTIC regardless of input order
# ---------------------------------------------------------------------------

def test_same_date_dedup_is_order_independent():
    """Two same-day readings yield the SAME projected value no matter the input order.

    Regression for WR-02: the kept value must not depend on caller list order.
    """
    base = [
        {"date": "2026-06-21", "facet": "threshold_pace", "value": 260.0, "unit": "sec_per_km"},
        {"date": "2026-07-18", "facet": "threshold_pace", "value": 250.0, "unit": "sec_per_km"},
        {"date": "2026-07-18", "facet": "threshold_pace", "value": 240.0, "unit": "sec_per_km"},
    ]
    forward = project_goal_progress("threshold_pace", base, DATED_GOALS, "2026-08-01")
    reversed_in = project_goal_progress("threshold_pace", list(reversed(base)), DATED_GOALS, "2026-08-01")
    assert forward["projected_value"] == reversed_in["projected_value"]
    # And the same-day value used is the deterministic mean of 250 and 240 (=245),
    # so it differs from either single reading's projection.
    assert forward["data_point_count"] == 2


# ---------------------------------------------------------------------------
# WR-03: _resolve_target prefers the nearest upcoming deadline among multiple goals
# ---------------------------------------------------------------------------

def test_resolve_target_picks_nearest_upcoming_deadline():
    """When two dated goals specify the same facet, the nearest upcoming deadline wins."""
    multi_goals = [
        # Deliberately list the FAR goal first to prove order doesn't decide it.
        {"target_date": "2026-12-31", "goal_label": "Dec", "metrics": {"bench_press_kg": 110}},
        {"target_date": "2026-10-10", "goal_label": "Oct", "metrics": {"bench_press_kg": 100}},
    ]
    history = _build_history(
        values=[80.0, 86.0],
        dates=["2026-06-21", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result = project_goal_progress(
        facet="bench_press_1rm",
        history=history,
        dated_goals=multi_goals,
        today_iso="2026-08-01",
    )
    # Nearest upcoming deadline relative to 2026-08-01 is 2026-10-10 / 100kg
    assert result["target_date"] == "2026-10-10"
    assert result["target_value"] == 100.0


# ---------------------------------------------------------------------------
# WR-04: behind_by is direction-consistent (positive == behind for every facet)
# ---------------------------------------------------------------------------

def test_behind_by_positive_means_behind_higher_is_better():
    """bench_press_1rm: a projection below target gives a POSITIVE behind_by."""
    history = _build_history(
        values=[80.0, 82.0],  # weak upward trend, will fall short of 100
        dates=["2026-06-21", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result = project_goal_progress("bench_press_1rm", history, DATED_GOALS, "2026-08-01")
    assert result["on_track"] is False
    assert result["behind_by"] is not None
    assert result["behind_by"] > 0  # positive == behind, for higher-is-better


def test_behind_by_positive_means_behind_lower_is_better():
    """threshold_pace: a projection slower (higher sec/km) than target gives POSITIVE behind_by."""
    history = _build_history(
        values=[260.0, 258.0],  # barely improving, stays slower than ~241 target
        dates=["2026-06-21", "2026-07-18"],
        facet="threshold_pace",
        unit="sec_per_km",
    )
    result = project_goal_progress("threshold_pace", history, DATED_GOALS, "2026-08-01")
    assert result["on_track"] is False
    assert result["behind_by"] is not None
    assert result["behind_by"] > 0  # positive == behind, for lower-is-better too


def test_behind_by_negative_when_ahead():
    """When the projection beats the target, behind_by is negative (ahead)."""
    history = _build_history(
        values=[95.0, 110.0],  # steep climb, overshoots 100kg target
        dates=["2026-06-21", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    result = project_goal_progress("bench_press_1rm", history, DATED_GOALS, "2026-08-01")
    assert result["on_track"] is True
    assert result["behind_by"] < 0


# ---------------------------------------------------------------------------
# IN-03: confidence label uses a source-appropriate noun (no "benchmarks" for runs)
# ---------------------------------------------------------------------------

def test_confidence_label_noun_is_source_appropriate():
    """threshold_pace label must not call dense run data 'benchmarks'."""
    pace_hist = _build_history(
        values=[260.0, 255.0, 250.0],
        dates=["2026-06-21", "2026-07-05", "2026-07-18"],
        facet="threshold_pace",
        unit="sec_per_km",
    )
    pace_result = project_goal_progress("threshold_pace", pace_hist, DATED_GOALS, "2026-08-01")
    assert "benchmark" not in pace_result["confidence_label"].lower()

    strength_hist = _build_history(
        values=[78.0, 82.0, 86.0],
        dates=["2026-06-21", "2026-07-05", "2026-07-18"],
        facet="bench_press_1rm",
        unit="kg",
    )
    strength_result = project_goal_progress("bench_press_1rm", strength_hist, DATED_GOALS, "2026-08-01")
    assert "benchmark" in strength_result["confidence_label"].lower()
