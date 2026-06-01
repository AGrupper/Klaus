"""Tests for RECOVERY_THRESHOLDS dict + compute_recovery_concern function.

Phase 20 Plan 05 — RECOVERY-01, RECOVERY-02.

Tests cover:
  - RECOVERY_THRESHOLDS dict shape (7 required keys + v0 docstring)
  - None returned when no trigger (ACWR low, sleep fine, HRV fine, no heavy session)
  - strong level: ACWR >= 1.8 + high-intensity keyword event
  - mild level: ACWR >= 1.5 (but < 1.8) + high-intensity keyword event
  - D-15: 2 consecutive nights sleep_score < 70 + intense session today → at least mild
  - D-13/strong: HRV flagged + sleep_score < 70 + heavy lifting → strong
  - returned dict carries contributing metrics (acwr ratio, hrv_status, sleep_score)
    but no prescriptive numeric targets
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy dependencies at module level before importing training_checkin
# ---------------------------------------------------------------------------

def _stub_heavy_imports():
    """Install lightweight stubs for google/telegram/psycopg2 so the module
    imports without crashing in the test environment."""
    # google.cloud.firestore
    if "google" not in sys.modules:
        goog = types.ModuleType("google")
        goog.cloud = types.ModuleType("google.cloud")
        sys.modules["google"] = goog
        sys.modules["google.cloud"] = goog.cloud

    for mod in [
        "google.cloud.firestore",
        "google.api_core",
        "google.api_core.exceptions",
        "googleapiclient",
        "googleapiclient.errors",
        "googleapiclient.discovery",
        "telegram",
    ]:
        if mod not in sys.modules:
            m = types.ModuleType(mod)
            sys.modules[mod] = m

    # Minimal telegram stubs used by training_checkin. Only fill in attributes that
    # are missing — never overwrite an existing telegram module's keyboard classes.
    # test_training_checkin installs a *functional* fake (real _FakeInlineKeyboard*
    # classes its keyboard-layout tests assert on); clobbering them with bare
    # MagicMocks here breaks that file when both run in one process (test pollution).
    t = sys.modules["telegram"]
    if not hasattr(t, "InlineKeyboardMarkup"):
        t.InlineKeyboardMarkup = MagicMock()
    if not hasattr(t, "InlineKeyboardButton"):
        t.InlineKeyboardButton = MagicMock()

    gf = sys.modules["google.cloud.firestore"]
    gf.SERVER_TIMESTAMP = object()


_stub_heavy_imports()


# Now we can safely import the module under test
from core.training_checkin import RECOVERY_THRESHOLDS, compute_recovery_concern  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = "2026-06-01"

_GARMIN_FINE = {
    "state": 1,
    "date": TODAY,
    "sleep_score": 80,     # above threshold (70)
    "hrv_status": "BALANCED",
}

_GARMIN_LOW_SLEEP = {
    "state": 1,
    "date": TODAY,
    "sleep_score": 60,     # below threshold
    "hrv_status": "BALANCED",
}

_GARMIN_HRV_FLAGGED = {
    "state": 1,
    "date": TODAY,
    "sleep_score": 60,     # below threshold
    "hrv_status": "unbalanced",  # in hrv_flag_values
}

_EVENT_HIGH = [{"summary": "Heavy lifting session", "start": f"{TODAY}T07:00:00+03:00"}]
_EVENT_MODERATE = [{"summary": "Morning run", "start": f"{TODAY}T07:00:00+03:00"}]
_EVENT_REST = [{"summary": "Rest day", "start": f"{TODAY}T09:00:00+03:00"}]


# ---------------------------------------------------------------------------
# Task 1a: RECOVERY_THRESHOLDS dict shape
# ---------------------------------------------------------------------------

class TestRecoveryThresholdsShape:
    """RECOVERY-02: dict must exist with all 7 documented keys + v0 docstring."""

    def test_thresholds_dict_shape(self):
        required_keys = {
            "acwr_mild",
            "acwr_strong",
            "sleep_low",
            "consecutive_low_sleep_nights",
            "intensity_keywords_high",
            "intensity_keywords_moderate",
            "hrv_flag_values",
        }
        assert isinstance(RECOVERY_THRESHOLDS, dict)
        assert required_keys.issubset(RECOVERY_THRESHOLDS.keys()), (
            f"Missing keys: {required_keys - RECOVERY_THRESHOLDS.keys()}"
        )

    def test_thresholds_acwr_values_sensible(self):
        assert RECOVERY_THRESHOLDS["acwr_mild"] < RECOVERY_THRESHOLDS["acwr_strong"]
        assert RECOVERY_THRESHOLDS["acwr_mild"] >= 1.0
        assert RECOVERY_THRESHOLDS["acwr_strong"] >= 1.0

    def test_thresholds_sleep_low(self):
        assert isinstance(RECOVERY_THRESHOLDS["sleep_low"], (int, float))
        assert RECOVERY_THRESHOLDS["sleep_low"] > 0

    def test_thresholds_consecutive_low_sleep_nights(self):
        assert isinstance(RECOVERY_THRESHOLDS["consecutive_low_sleep_nights"], int)
        assert RECOVERY_THRESHOLDS["consecutive_low_sleep_nights"] >= 1

    def test_thresholds_keyword_tuples(self):
        assert isinstance(RECOVERY_THRESHOLDS["intensity_keywords_high"], tuple)
        assert isinstance(RECOVERY_THRESHOLDS["intensity_keywords_moderate"], tuple)
        assert len(RECOVERY_THRESHOLDS["intensity_keywords_high"]) > 0
        assert len(RECOVERY_THRESHOLDS["intensity_keywords_moderate"]) > 0

    def test_thresholds_hrv_flag_values(self):
        assert isinstance(RECOVERY_THRESHOLDS["hrv_flag_values"], tuple)
        assert len(RECOVERY_THRESHOLDS["hrv_flag_values"]) > 0


# ---------------------------------------------------------------------------
# Task 1b: None on no-trigger
# ---------------------------------------------------------------------------

class TestNoTrigger:
    """compute_recovery_concern returns None when nothing fires."""

    def test_none_when_acwr_low_sleep_fine_hrv_fine(self):
        # ACWR ratio < mild threshold, sleep fine, HRV fine, moderate session
        with (
            patch("core.training_checkin.compute_acwr_from_db", return_value={"ratio": 1.2}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_MODERATE),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is None, f"Expected None, got {result}"

    def test_none_when_no_events(self):
        # No training events today
        with (
            patch("core.training_checkin.compute_acwr_from_db", return_value={"ratio": 1.6}),
            patch("core.training_checkin._get_todays_training_events", return_value=[]),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        # ACWR high but no intense event → None (or at most mild via other triggers)
        # With no events classified as high/moderate: depends on implementation
        # The key is no "all clear" object — None or None-equivalent
        assert result is None, f"Expected None when no events, got {result}"

    def test_none_when_acwr_none_sleep_fine_hrv_fine(self):
        # ACWR insufficient baseline (ratio=None)
        with (
            patch("core.training_checkin.compute_acwr_from_db", return_value={"ratio": None}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is None, f"Expected None when ACWR ratio is None, got {result}"


# ---------------------------------------------------------------------------
# Task 1c: strong level (ACWR >= acwr_strong + high-intensity)
# ---------------------------------------------------------------------------

class TestStrongLevel:
    """Strong severity on ACWR >= 1.8 + high-intensity keyword event."""

    def test_strong_acwr_strong_threshold_high_intensity(self):
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": RECOVERY_THRESHOLDS["acwr_strong"]}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is not None
        assert result["level"] == "strong", f"Expected strong, got {result}"

    def test_strong_acwr_above_strong_threshold(self):
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": 2.1}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is not None
        assert result["level"] == "strong"

    def test_strong_hrv_flagged_sleep_low_heavy_lifting(self):
        """D-13/strong: HRV flagged + sleep_score < 70 + high-intensity → strong."""
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": 1.2}),  # ACWR not a trigger
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 55]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_HRV_FLAGGED,
                today_iso=TODAY,
            )
        assert result is not None
        assert result["level"] == "strong", f"Expected strong, got {result}"


# ---------------------------------------------------------------------------
# Task 1d: mild level (ACWR >= 1.5 but < 1.8 + high-intensity)
# ---------------------------------------------------------------------------

class TestMildLevel:
    """Mild severity on ACWR >= acwr_mild + high-intensity keyword event."""

    def test_mild_acwr_mild_threshold_high_intensity(self):
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": RECOVERY_THRESHOLDS["acwr_mild"]}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is not None
        assert result["level"] == "mild", f"Expected mild, got {result}"

    def test_mild_acwr_just_below_strong_threshold(self):
        """ACWR 1.7 (above mild, below strong) + high intensity → mild."""
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": 1.7}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is not None
        assert result["level"] == "mild"

    def test_mild_acwr_moderate_intensity_at_mild_threshold(self):
        """ACWR >= mild threshold + moderate event → mild."""
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": RECOVERY_THRESHOLDS["acwr_mild"]}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_MODERATE),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is not None
        assert result["level"] == "mild"


# ---------------------------------------------------------------------------
# Task 1e: D-15 — consecutive low-sleep nights
# ---------------------------------------------------------------------------

class TestConsecutiveLowSleep:
    """D-15: 2 consecutive nights sleep < 70 + intense session today → at least mild."""

    def test_consecutive_low_sleep_high_intensity_yields_at_least_mild(self):
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": 1.0}),  # ACWR not a trigger
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[65, 62]),  # 2 nights below 70
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_LOW_SLEEP,
                today_iso=TODAY,
            )
        assert result is not None
        assert result["level"] in ("mild", "strong"), f"Expected mild or strong, got {result}"

    def test_consecutive_low_sleep_moderate_intensity_yields_at_least_mild(self):
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": 1.0}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_MODERATE),
            patch("core.training_checkin._recent_sleep_scores", return_value=[65, 62]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_LOW_SLEEP,
                today_iso=TODAY,
            )
        assert result is not None
        assert result["level"] in ("mild", "strong")

    def test_only_one_night_low_sleep_no_other_triggers_is_none(self):
        """One night below threshold (not 2 consecutive) + moderate session → None."""
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": 1.0}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_MODERATE),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 62]),  # only 1 of 2 nights low
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,  # today's sleep is fine
                today_iso=TODAY,
            )
        assert result is None, f"Expected None for single-night dip, got {result}"


# ---------------------------------------------------------------------------
# Task 1f: returned dict carries metrics, no prescriptive numeric targets
# ---------------------------------------------------------------------------

class TestReturnedDictShape:
    """Returned dict must carry contributing metrics; must NOT have prescriptive targets."""

    def test_dict_has_required_metric_keys(self):
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": RECOVERY_THRESHOLDS["acwr_mild"]}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is not None
        assert "level" in result
        assert "acwr" in result
        assert "hrv_status" in result
        assert "sleep_score" in result
        assert "intensity" in result

    def test_dict_has_no_prescriptive_numeric_keys(self):
        """D-13: no fabricated numeric targets in the returned dict."""
        prescriptive_keys = {
            "target_reps", "target_weight", "target_hr", "target_pace",
            "max_hr", "recommended_load", "suggested_weight",
        }
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": RECOVERY_THRESHOLDS["acwr_strong"]}),
            patch("core.training_checkin._get_todays_training_events", return_value=_EVENT_HIGH),
            patch("core.training_checkin._recent_sleep_scores", return_value=[80, 82]),
        ):
            result = compute_recovery_concern(
                garmin_data=_GARMIN_FINE,
                today_iso=TODAY,
            )
        assert result is not None
        overlap = prescriptive_keys & result.keys()
        assert not overlap, f"Prescriptive keys found: {overlap}"

    def test_garmin_none_does_not_crash(self):
        """compute_recovery_concern with garmin_data=None must not raise."""
        with (
            patch("core.training_checkin.compute_acwr_from_db",
                  return_value={"ratio": None}),
            patch("core.training_checkin._get_todays_training_events", return_value=[]),
            patch("core.training_checkin._recent_sleep_scores", return_value=[]),
        ):
            result = compute_recovery_concern(
                garmin_data=None,
                today_iso=TODAY,
            )
        assert result is None
