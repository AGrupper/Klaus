"""Tests for core/recovery_metrics.py — recovery-deviation baseline math.

compute_recovery_deviation is pure (no I/O); fetch_biometric_rows is exercised
only for its fail-open contract. Covers: silent-omit (None) within band /
without enough history, boundary behaviour at exactly -10% HRV and +5 bpm RHR,
Garmin weeklyAvg preferred over the computed median, and malformed rows.
"""
from __future__ import annotations

from core.recovery_metrics import (
    DEVIATION_THRESHOLDS,
    compute_recovery_deviation,
    fetch_biometric_rows,
)

_TODAY = "2026-07-05"


def _rows(today_hrv=60, today_rhr=47, today_weekly=None, prior_hrv=60, prior_rhr=47, prior_days=7):
    """Newest-first rows: today + N prior days with flat baseline values."""
    rows = [{
        "date": _TODAY,
        "resting_hr": today_rhr,
        "hrv_overnight": today_hrv,
        "hrv_baseline": today_weekly,
        "sleep_score": 80,
    }]
    for i in range(1, prior_days + 1):
        rows.append({
            "date": f"2026-07-{5 - i:02d}" if 5 - i > 0 else f"2026-06-{30 + (5 - i):02d}",
            "resting_hr": prior_rhr,
            "hrv_overnight": prior_hrv,
            "hrv_baseline": None,
            "sleep_score": 80,
        })
    return rows


def test_none_when_within_band():
    """A normal day is silence — never an 'all clear' payload."""
    assert compute_recovery_deviation(_rows(), _TODAY) is None


def test_hrv_low_fires_below_ratio():
    # baseline 60 → threshold at 0.90 = 54; 53 is below.
    out = compute_recovery_deviation(_rows(today_hrv=53), _TODAY)
    assert out is not None
    assert out["flags"] == ["hrv_low"]
    assert out["hrv_baseline_7d"] == 60
    assert out["hrv_deviation_pct"] < -10


def test_hrv_exactly_at_ratio_boundary_is_silent():
    # 54/60 = exactly 0.90 — strict less-than, so no flag.
    assert compute_recovery_deviation(_rows(today_hrv=54), _TODAY) is None


def test_rhr_elevated_fires_at_plus_five_inclusive():
    # baseline 47 → +5 = 52; >= is inclusive.
    out = compute_recovery_deviation(_rows(today_rhr=52), _TODAY)
    assert out is not None
    assert out["flags"] == ["rhr_elevated"]
    assert out["rhr_delta"] == 5


def test_rhr_four_over_baseline_is_silent():
    assert compute_recovery_deviation(_rows(today_rhr=51), _TODAY) is None


def test_both_flags_together():
    out = compute_recovery_deviation(_rows(today_hrv=50, today_rhr=55), _TODAY)
    assert set(out["flags"]) == {"hrv_low", "rhr_elevated"}


def test_none_without_enough_baseline_days():
    rows = _rows(today_hrv=40, prior_days=DEVIATION_THRESHOLDS["min_baseline_days"] - 1)
    assert compute_recovery_deviation(rows, _TODAY) is None


def test_garmin_weekly_avg_preferred_over_median():
    # Prior median is 60 (would flag 53), but Garmin's own weeklyAvg says 55
    # (53/55 ≈ 0.96 — within band) → silence. weeklyAvg wins.
    assert compute_recovery_deviation(
        _rows(today_hrv=53, today_weekly=55), _TODAY
    ) is None


def test_malformed_and_missing_values_skipped():
    rows = _rows(today_hrv=50)
    rows[2]["hrv_overnight"] = "not-a-number"
    rows[3]["resting_hr"] = None
    out = compute_recovery_deviation(rows, _TODAY)
    assert out is not None and "hrv_low" in out["flags"]


def test_none_when_today_row_absent():
    rows = _rows()[1:]  # history only, no today
    assert compute_recovery_deviation(rows, _TODAY) is None


def test_none_on_empty_inputs():
    assert compute_recovery_deviation([], _TODAY) is None
    assert compute_recovery_deviation(_rows(), "") is None


def test_fetch_rows_fails_open_without_dsn(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_CONNECTION_STRING", raising=False)
    assert fetch_biometric_rows() == []
