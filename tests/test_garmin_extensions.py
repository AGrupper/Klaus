"""Tests for mcp_tools/garmin_tool.py Phase-19 extensions (Plan 02).

Covers GARMIN-01 and GARMIN-02:
  - fetch_garmin_training_status() — returns dict with vo2_max, training_status, load_focus
  - fetch_garmin_activities(days=7) — returns normalized list, default window is 7 days

Mock strategy
-------------
We patch the in-module `_authed_garmin_client` helper so neither garminconnect
nor Firestore is touched.  Each test gets its own MagicMock Garmin API.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import mcp_tools.garmin_tool as gt


# ---------------------------------------------------------------------------
# GARMIN-01 — fetch_garmin_training_status
# ---------------------------------------------------------------------------

def test_training_status_shape():
    """Returns dict with exactly the 3 expected keys."""
    fake_api = MagicMock()
    fake_api.get_training_status.return_value = {
        "envelope": {
            "vO2MaxValue": 51.7,
            "trainingStatus": "PRODUCTIVE",
            "loadFocus": "BALANCED",
        }
    }
    fake_api.get_max_metrics.return_value = {"vO2MaxValue": 51.7}
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        result = gt.fetch_garmin_training_status()
    assert set(result.keys()) == {"vo2_max", "training_status", "load_focus"}


def test_training_status_extracts_values():
    """Verifies values are pulled from the envelope when nested."""
    fake_api = MagicMock()
    fake_api.get_training_status.return_value = {
        "envelope": {
            "vO2MaxValue": 51.7,
            "trainingStatus": "PRODUCTIVE",
            "loadFocus": "BALANCED",
        }
    }
    fake_api.get_max_metrics.return_value = {"vO2MaxValue": 51.7}
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        result = gt.fetch_garmin_training_status()
    assert result["vo2_max"] == 51.7
    assert result["training_status"] == "PRODUCTIVE"
    assert result["load_focus"] == "BALANCED"


def test_training_status_raises_garmin_unavailable():
    """API exception → GarminUnavailableError (caller decides)."""
    fake_api = MagicMock()
    fake_api.get_training_status.side_effect = RuntimeError("net down")
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        with pytest.raises(gt.GarminUnavailableError):
            gt.fetch_garmin_training_status()


# ---------------------------------------------------------------------------
# GARMIN-02 — fetch_garmin_activities
# ---------------------------------------------------------------------------

def test_recent_activities_shape():
    """Normalized dict carries all expected keys + RPE/Feel/training_load."""
    fake_api = MagicMock()
    fake_api.get_activities_by_date.return_value = [
        {
            "activityId": 999,
            "startTimeLocal": "2026-05-26T07:00:00",
            "activityType": {"typeKey": "running"},
            "duration": 1800,
            "distance": 5000.0,
            "directWorkoutRpe": 7,
            "directWorkoutFeel": 4,
            "activityTrainingLoad": 78.3,
        }
    ]
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        result = gt.fetch_garmin_activities(days=7)
    assert isinstance(result, list)
    assert len(result) == 1
    r = result[0]
    expected_keys = {
        "activity_id", "date", "type", "duration_sec", "distance_m",
        "perceived_exertion", "feel", "training_load",
    }
    assert expected_keys.issubset(r.keys())
    assert r["activity_id"] == 999
    assert r["type"] == "running"
    assert r["duration_sec"] == 1800
    assert r["perceived_exertion"] == 7
    assert r["feel"] == 4
    assert r["training_load"] == 78.3


def test_recent_activities_default_days_7():
    """default days=7 → window is today-6..today, inclusive."""
    fake_api = MagicMock()
    fake_api.get_activities_by_date.return_value = []
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        gt.fetch_garmin_activities(days=7)
    args, _ = fake_api.get_activities_by_date.call_args
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    assert args[1] == today.isoformat()
    assert args[0] == (today - timedelta(days=6)).isoformat()


def test_recent_activities_raises_on_fetch_failure():
    """API exception → GarminUnavailableError."""
    fake_api = MagicMock()
    fake_api.get_activities_by_date.side_effect = RuntimeError("net down")
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        with pytest.raises(gt.GarminUnavailableError):
            gt.fetch_garmin_activities(days=7)


# ---------------------------------------------------------------------------
# GARMIN-05 — write_today_biometrics_to_postgres (Plan 19-04)
# ---------------------------------------------------------------------------

def test_write_today_biometrics_executes_upsert(monkeypatch):
    """Happy path: full garmin dict → cur.execute called with INSERT ... ON CONFLICT."""
    import sys
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_psycopg2 = MagicMock()
    fake_psycopg2.connect.return_value = fake_conn
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    garmin = {
        "date": "2026-05-26",
        "resting_hr": 50,
        "hrv_overnight": 60,
        "sleep_score": 80,
        "sleep_duration": 7.5,
        "body_battery_max": 90,
        "training_readiness": 75,
        "vo2_max": 51.7,
        "hrv_baseline": 58,
    }
    gt.write_today_biometrics_to_postgres(garmin)
    assert fake_cursor.execute.called
    args, _ = fake_cursor.execute.call_args
    sql = args[0]
    assert "INSERT INTO daily_biometrics" in sql
    assert "ON CONFLICT (date) DO UPDATE SET" in sql


def test_write_today_biometrics_no_db_url_silent_return(monkeypatch):
    """No DATABASE_URL set → returns None, no DB call, no exception."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PG_CONNECTION_STRING", raising=False)
    result = gt.write_today_biometrics_to_postgres({"date": "2026-05-26"})
    assert result is None


def test_write_today_biometrics_connection_error_silent_log(monkeypatch):
    """psycopg2.connect raises → fn logs warning + returns None (best-effort contract)."""
    import sys
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    fake_psycopg2 = MagicMock()
    fake_psycopg2.connect.side_effect = RuntimeError("network down")
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    # MUST NOT RAISE
    result = gt.write_today_biometrics_to_postgres({"date": "2026-05-26"})
    assert result is None


def test_write_today_biometrics_handles_missing_keys(monkeypatch):
    """Minimal dict with just 'date' → other fields default to None in params."""
    import sys
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_psycopg2 = MagicMock()
    fake_psycopg2.connect.return_value = fake_conn
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    gt.write_today_biometrics_to_postgres({"date": "2026-05-26"})
    args, _ = fake_cursor.execute.call_args
    params = args[1]
    # date is required; everything else should be None
    assert params[0] == "2026-05-26"
    assert all(p is None or p == "2026-05-26" for p in params)


# ---------------------------------------------------------------------------
# _fetch_hrv — numeric HRV extraction (regression: daily_biometrics persistence)
# ---------------------------------------------------------------------------

def test_fetch_hrv_returns_numeric_overnight_and_baseline():
    """hrvSummary numeric fields map to hrv_overnight (lastNightAvg) and
    hrv_baseline (weeklyAvg) so write_today_biometrics_to_postgres can persist
    them. Regression for the weekly-review 'biometrics empty' bug."""
    fake_api = MagicMock()
    fake_api.get_hrv_data.return_value = {
        "hrvSummary": {"status": "BALANCED", "lastNightAvg": 81, "weeklyAvg": 92}
    }
    result = gt._fetch_hrv(fake_api, "2026-06-02")
    assert result == {
        "hrv_status": "BALANCED",
        "hrv_overnight": 81,
        "hrv_baseline": 92,
    }


def test_fetch_hrv_swallows_errors_to_none():
    """API failure → all three HRV keys None, never raises (per-field resilience)."""
    fake_api = MagicMock()
    fake_api.get_hrv_data.side_effect = RuntimeError("net down")
    result = gt._fetch_hrv(fake_api, "2026-06-02")
    assert result == {"hrv_status": None, "hrv_overnight": None, "hrv_baseline": None}


def test_write_today_biometrics_maps_sleep_hours_to_sleep_duration(monkeypatch):
    """fetch_garmin_today emits 'sleep_hours'; the daily write must persist it
    into the sleep_duration column (regression: sleep_duration was always NULL)."""
    import sys
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_psycopg2 = MagicMock()
    fake_psycopg2.connect.return_value = fake_conn
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    # Exactly what fetch_garmin_today produces — note 'sleep_hours', not 'sleep_duration'.
    garmin = {
        "date": "2026-06-02",
        "resting_hr": 40,
        "sleep_score": 81,
        "sleep_hours": 7.8,
        "hrv_status": "BALANCED",
        "hrv_overnight": 81,
        "hrv_baseline": 92,
    }
    gt.write_today_biometrics_to_postgres(garmin)
    args, _ = fake_cursor.execute.call_args
    params = args[1]
    # params order: date, resting_hr, hrv_baseline, hrv_overnight, sleep_score,
    #               sleep_duration, body_battery_max, training_readiness, vo2_max
    assert params[2] == 92      # hrv_baseline
    assert params[3] == 81      # hrv_overnight
    assert params[5] == 7.8     # sleep_duration (mapped from sleep_hours)


# ---------------------------------------------------------------------------
# Bodyweight — _coerce_weight_kg + fetch_garmin_weight
# ---------------------------------------------------------------------------

def test_coerce_weight_kg_grams_and_kg():
    """Grams (>300) are /1000; a plain kg value passes through, rounded to 0.1."""
    assert gt._coerce_weight_kg(73000) == 73.0      # grams
    assert gt._coerce_weight_kg(74.0) == 74.0       # already kg
    assert gt._coerce_weight_kg(73450) == 73.5      # grams, rounded


def test_coerce_weight_kg_rejects_implausible():
    """Fat-finger / unit mistakes / junk are rejected (return None), never stored."""
    assert gt._coerce_weight_kg(974) is None        # 974 -> 0.974 kg -> below band
    assert gt._coerce_weight_kg(740000) is None     # 740 kg -> above band
    assert gt._coerce_weight_kg(0) is None
    assert gt._coerce_weight_kg(None) is None
    assert gt._coerce_weight_kg("abc") is None


def test_fetch_garmin_weight_latest_weigh_in():
    """Returns the most recent weigh-in (grams→kg), newest date wins."""
    fake_api = MagicMock()
    fake_api.get_body_composition.return_value = {
        "dateWeightList": [
            {"date": 1717000000000, "weight": 75000},
            {"date": 1717500000000, "weight": 73200},  # newest
        ]
    }
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        assert gt.fetch_garmin_weight() == 73.2


def test_fetch_garmin_weight_falls_back_to_profile_setting():
    """No weigh-in → fall back to the static Garmin profile-setting weight."""
    fake_api = MagicMock()
    fake_api.get_body_composition.return_value = {"dateWeightList": []}
    fake_api.get_userprofile_settings.return_value = {"userData": {"weight": 74000}}
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        assert gt.fetch_garmin_weight() == 74.0


def test_fetch_garmin_weight_none_on_auth_failure():
    """Auth failure is fail-open → None (caller keeps last-known weight)."""
    with patch.object(gt, "_authed_garmin_client",
                      side_effect=gt.GarminAuthError("no creds")):
        assert gt.fetch_garmin_weight() is None


# ---------------------------------------------------------------------------
# fetch_run_detail_raw — lapDTOs-primary splits strategy
# ---------------------------------------------------------------------------

_LAP_DTOS = {"lapDTOs": [
    {"distance": 400, "duration": 90, "avgHr": 165},
    {"distance": 400, "duration": 92, "avgHr": 168},
]}
_TYPED = {"splits": [
    {"type": "RWD_RUN", "distance": 700, "duration": 170, "averageHR": 166},
    {"type": "RWD_WALK", "distance": 100, "duration": 60, "averageHR": 120},
]}


def test_run_detail_raw_prefers_lapdtos_even_when_typed_succeeds():
    """THE regression: typed splits succeeding must not starve per-lap data.

    Pre-fix, get_activity_typed_splits was called first and its success meant
    get_activity_splits (the real recorded laps) was never fetched — Klaus only
    ever saw run/walk time buckets.
    """
    fake_api = MagicMock()
    fake_api.get_activity_splits.return_value = _LAP_DTOS
    fake_api.get_activity_typed_splits.return_value = _TYPED
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        out = gt.fetch_run_detail_raw(1)
    assert out["splits"] == _LAP_DTOS
    assert out["typed_splits"] == _TYPED


def test_run_detail_raw_falls_back_to_typed_when_no_lapdtos():
    """Empty/absent lapDTOs → typed envelope becomes the splits payload."""
    fake_api = MagicMock()
    fake_api.get_activity_splits.return_value = {"lapDTOs": []}
    fake_api.get_activity_typed_splits.return_value = _TYPED
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        out = gt.fetch_run_detail_raw(1)
    assert out["splits"] == _TYPED
    assert out["typed_splits"] == {}  # splits already IS the typed envelope


def test_run_detail_raw_falls_back_to_typed_when_lapdtos_raise():
    fake_api = MagicMock()
    fake_api.get_activity_splits.side_effect = RuntimeError("500")
    fake_api.get_activity_typed_splits.return_value = _TYPED
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        out = gt.fetch_run_detail_raw(1)
    assert out["splits"] == _TYPED


def test_run_detail_raw_both_splits_fetches_fail_soft():
    fake_api = MagicMock()
    fake_api.get_activity_splits.side_effect = RuntimeError("500")
    fake_api.get_activity_typed_splits.side_effect = RuntimeError("500")
    fake_api.get_activity_details.return_value = {"metricDescriptors": []}
    fake_api.get_activity_hr_in_timezones.return_value = []
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        out = gt.fetch_run_detail_raw(1)
    assert out["splits"] == {}
    assert out["typed_splits"] == {}


# ---------------------------------------------------------------------------
# fetch_garmin_daily — date-parameterized daily biometrics
# ---------------------------------------------------------------------------

def _daily_api():
    fake_api = MagicMock()
    fake_api.get_sleep_data.return_value = {
        "dailySleepDTO": {"sleepScores": {"overall": {"value": 82}},
                          "sleepTimeSeconds": 27000}
    }
    fake_api.get_hrv_data.return_value = {
        "hrvSummary": {"status": "BALANCED", "lastNightAvg": 62, "weeklyAvg": 60}
    }
    fake_api.get_body_battery.return_value = [{"charged": 88}]
    fake_api.get_stats.return_value = {"restingHeartRate": 47}
    fake_api.get_training_readiness.return_value = [{"score": 71}]
    return fake_api


def test_fetch_garmin_daily_threads_date_to_every_endpoint():
    fake_api = _daily_api()
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        out = gt.fetch_garmin_daily("2026-06-20")
    assert out["date"] == "2026-06-20"
    assert out["hrv_overnight"] == 62 and out["resting_hr"] == 47
    assert out["training_readiness"] == 71
    fake_api.get_sleep_data.assert_called_once_with("2026-06-20")
    fake_api.get_hrv_data.assert_called_once_with("2026-06-20")
    fake_api.get_body_battery.assert_called_once_with("2026-06-20", "2026-06-20")
    fake_api.get_stats.assert_called_once_with("2026-06-20")
    fake_api.get_training_readiness.assert_called_once_with("2026-06-20")


def test_fetch_garmin_today_delegates_to_daily():
    with patch.object(gt, "fetch_garmin_daily", return_value={"date": "x"}) as fgd:
        out = gt.fetch_garmin_today()
    fgd.assert_called_once()
    assert out == {"date": "x"}
    # the delegated date is today's ISO date
    arg = fgd.call_args.args[0]
    assert len(arg) == 10 and arg[4] == "-"


def test_fetch_training_readiness_swallows_errors_to_none():
    fake_api = _daily_api()
    fake_api.get_training_readiness.side_effect = RuntimeError("404")
    with patch.object(gt, "_authed_garmin_client", return_value=fake_api):
        out = gt.fetch_garmin_daily("2026-06-20")
    assert out["training_readiness"] is None
