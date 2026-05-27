"""Tests for mcp_tools/garmin_tool.py::compute_acwr (Phase 19 Plan 02).

Pure-function tests for the Acute:Chronic Workload Ratio computation.
No mocks needed — compute_acwr has no I/O.

Covers GARMIN-03:
  - Normal ratio with 28 days of equal load → ratio = 1.0
  - Acute spike (7 days at 200 vs 21 days at 50) → ratio > 1.5
  - Insufficient chronic baseline (< 14 days with data) → ratio=None, chronic=None
  - Missing training_load values are skipped (None contributes nothing)
  - today parameter overrides default Asia/Jerusalem 'today'
"""
from __future__ import annotations

from datetime import date, timedelta

from mcp_tools.garmin_tool import compute_acwr


def _build_activities(days: int, load: float, today: date) -> list[dict]:
    """Build a list of activity dicts: one per day for `days` days ending today."""
    return [
        {"date": (today - timedelta(days=i)).isoformat(), "training_load": load}
        for i in range(days)
    ]


# ---------------------------------------------------------------------------
# GARMIN-03 — compute_acwr math
# ---------------------------------------------------------------------------

def test_normal_ratio():
    """28 days of equal load → acute/chronic = 1.0."""
    today = date(2026, 5, 26)
    acts = _build_activities(28, 100.0, today)
    r = compute_acwr(acts, today=today)
    assert r["acute"] == 100.0
    assert r["chronic"] == 100.0
    assert r["ratio"] == 1.0


def test_acute_spike():
    """7 acute days @ 200 vs 21 chronic days @ 50 → ratio > 1.5 (injury risk)."""
    today = date(2026, 5, 26)
    acute = _build_activities(7, 200.0, today)
    chronic = [
        {"date": (today - timedelta(days=i)).isoformat(), "training_load": 50.0}
        for i in range(7, 28)
    ]
    r = compute_acwr(acute + chronic, today=today)
    assert r["ratio"] is not None
    assert r["ratio"] > 1.5


def test_insufficient_baseline_returns_none():
    """Only 10 days of data in 28-day window → chronic=None, ratio=None."""
    today = date(2026, 5, 26)
    acts = _build_activities(10, 100.0, today)
    r = compute_acwr(acts, today=today)
    assert r["chronic"] is None
    assert r["ratio"] is None


def test_missing_training_load_skipped():
    """training_load=None → contributes nothing; with no data → chronic=None."""
    today = date(2026, 5, 26)
    acts = [
        {"date": (today - timedelta(days=i)).isoformat(), "training_load": None}
        for i in range(28)
    ]
    r = compute_acwr(acts, today=today)
    # All Nones → all-zero loads → chronic_days_with_data = 0 → chronic=None.
    assert r["chronic"] is None
    assert r["ratio"] is None


def test_today_parameter_overrides_default():
    """today parameter pins the acute/chronic window starting point."""
    today = date(2026, 5, 26)
    acts = _build_activities(28, 100.0, today)
    r = compute_acwr(acts, today=today)
    assert r["ratio"] == 1.0
