"""Tests for core/weekly_training_review.py — Phase 20 weekly review gather.

Focus: the biometrics + Garmin-activities gather paths, which produced the
"Garmin data unavailable" / empty-biometrics symptom in production.

Root cause covered here:
  - The biometrics SQL selected phantom columns (hrv_status, sleep_hours) that
    do not exist in daily_biometrics, so Postgres rejected the whole query and
    biometrics came back None. The regression guard below asserts the SQL only
    references real columns.

Mock strategy
-------------
_gather_week_data imports its data sources lazily (inside the function), so we
patch the names on their *source* modules. Garmin/Postgres/Firestore are never
touched.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import core.weekly_training_review as wtr


@pytest.fixture
def patched_sources(monkeypatch):
    """Patch all five gather sources to benign defaults; yield handles so each
    test can override the one it cares about."""
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")

    handles = {
        "training_log": MagicMock(),
        "fetch_garmin_activities": MagicMock(return_value=[]),
        "query_health_database": MagicMock(return_value=[]),
        "meal_store": MagicMock(),
        "user_profile": MagicMock(),
    }
    handles["training_log"].return_value.get_range.return_value = []
    handles["meal_store"].return_value.get_day_aggregate.return_value = None
    handles["user_profile"].return_value.load.return_value = {}

    with patch("memory.firestore_db.TrainingLogStore", handles["training_log"]), \
         patch("mcp_tools.garmin_tool.fetch_garmin_activities",
               handles["fetch_garmin_activities"]), \
         patch("mcp_tools.database_tool.query_health_database",
               handles["query_health_database"]), \
         patch("memory.firestore_db.MealStore", handles["meal_store"]), \
         patch("memory.firestore_db.UserProfileStore", handles["user_profile"]):
        yield handles


# ---------------------------------------------------------------------------
# Biometrics SQL — regression guard for the phantom-column bug
# ---------------------------------------------------------------------------

def test_biometrics_sql_uses_only_real_columns(patched_sources):
    """The biometrics query must not reference columns absent from
    daily_biometrics. This is the exact bug that returned 'column "hrv_status"
    does not exist' and made biometrics come back empty."""
    wtr._gather_week_data("2026-06-07")  # a Sunday
    sql = patched_sources["query_health_database"].call_args[0][0]
    # Phantom columns that broke the query:
    assert "hrv_status" not in sql
    assert "sleep_hours" not in sql
    # Real daily_biometrics columns that must be present:
    for col in ("hrv_baseline", "hrv_overnight", "sleep_duration",
                "resting_hr", "sleep_score"):
        assert col in sql


def test_biometrics_split_this_vs_last_week(patched_sources):
    """Rows are bucketed into this-week vs last-week by date, and the query
    succeeding means no error sentinel."""
    # today = Sunday 2026-06-07 → _prev_sunday → week 2026-05-31..2026-06-06;
    # last week → 2026-05-24..2026-05-30.
    patched_sources["query_health_database"].return_value = [
        {"date": "2026-06-02", "resting_hr": 40, "sleep_score": 81},  # this week
        {"date": "2026-05-26", "resting_hr": 42, "sleep_score": 70},  # last week
    ]
    data = wtr._gather_week_data("2026-06-07")
    assert [r["date"] for r in data["biometrics_this_week"]] == ["2026-06-02"]
    assert [r["date"] for r in data["biometrics_last_week"]] == ["2026-05-26"]


def test_biometrics_query_error_string_sets_none(patched_sources):
    """If query_health_database returns an error *string* (not a list), both
    biometrics buckets become None rather than raising."""
    patched_sources["query_health_database"].return_value = (
        'Error executing query: column "hrv_status" does not exist'
    )
    data = wtr._gather_week_data("2026-06-07")
    assert data["biometrics_this_week"] is None
    assert data["biometrics_last_week"] is None


# ---------------------------------------------------------------------------
# Garmin activities — split + graceful degradation
# ---------------------------------------------------------------------------

def test_garmin_activities_split_and_no_error(patched_sources):
    """Activities split across this/last week; garmin_error stays False on success."""
    patched_sources["fetch_garmin_activities"].return_value = [
        {"date": "2026-06-02T18:30:00", "type": "running", "training_load": 6.0},
        {"date": "2026-05-26T19:00:00", "type": "strength_training", "training_load": 3.0},
    ]
    data = wtr._gather_week_data("2026-06-07")
    assert data["garmin_error"] is False
    assert [a["date"][:10] for a in data["activities"]] == ["2026-06-02"]
    assert [a["date"][:10] for a in data["last_week_activities"]] == ["2026-05-26"]


def test_garmin_activities_failure_sets_error_flag(patched_sources):
    """fetch_garmin_activities raising → garmin_error True, gather still returns."""
    patched_sources["fetch_garmin_activities"].side_effect = RuntimeError("garmin down")
    data = wtr._gather_week_data("2026-06-07")
    assert data["garmin_error"] is True
    assert data["activities"] is None
    assert data["last_week_activities"] is None
    # Other sources are unaffected — the gather is best-effort per-source.
    assert "biometrics_this_week" in data
