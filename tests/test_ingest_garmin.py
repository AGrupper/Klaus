"""Tests for Phase 19 Garmin parser extensions in scripts/ingest_garmin_zip.py.

Covers INGEST-01/02:
- parse_and_ingest_activities extracts activityTrainingLoad / directWorkoutRpe
  / directWorkoutFeel NULL-safely (keys missing → None at the end of the tuple).
- parse_and_ingest_wellness extracts vO2MaxValue from UDS entries and writes
  it to the daily_biometrics UPSERT.

Uses fixture *summaries.json and *UDSFile.json built in tmp_path with the
expected DI_CONNECT/DI-Connect-{Fitness,User} layout.
"""

import importlib.util
import json
import sys
from unittest.mock import MagicMock, patch

import pytest  # noqa: F401 -- pytest discovery marker


def _import_module():
    if "psycopg2" not in sys.modules:
        psy = MagicMock()
        psy.extras = MagicMock()
        psy.extras.execute_values = MagicMock()
        psy.tz = MagicMock()
        psy.tz.FixedOffset = MagicMock(return_value=None)
        sys.modules["psycopg2"] = psy
        sys.modules["psycopg2.extras"] = psy.extras
    spec = importlib.util.spec_from_file_location(
        "ingest_garmin_zip", "scripts/ingest_garmin_zip.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_summaries(tmp_path, payload):
    """Mirror real Garmin export layout."""
    fitness_dir = tmp_path / "DI_CONNECT" / "DI-Connect-Fitness"
    fitness_dir.mkdir(parents=True, exist_ok=True)
    summary_file = fitness_dir / "activities_summaries.json"
    summary_file.write_text(json.dumps(payload))
    return summary_file


def _write_uds(tmp_path, payload):
    user_dir = tmp_path / "DI_CONNECT" / "DI-Connect-User"
    user_dir.mkdir(parents=True, exist_ok=True)
    uds_file = user_dir / "user_UDSFile.json"
    uds_file.write_text(json.dumps(payload))
    return uds_file


def test_activity_phase19_fields(tmp_path):
    mod = _import_module()

    fixture = [{
        "activityId": 12345,
        "startTimeGMT": 1748246400000,  # ms epoch — script divides by 1000
        "startTimeLocal": "2026-05-26 07:00:00",
        "activityType": {"typeKey": "running"},
        "duration": 1800,
        "distance": 5000.0,
        "averageHeartRate": 150,
        "maxHeartRate": 175,
        "averagePace": 6.0,
        "trainingEffect": 3.2,
        "activityTrainingLoad": 78.3,
        "directWorkoutRpe": 7,
        "directWorkoutFeel": 4,
    }]
    _write_summaries(tmp_path, fixture)

    captured = {}

    def _capture_values(cur, sql, values, **kw):
        captured["sql"] = sql
        captured["values"] = list(values)

    with patch.object(mod, "execute_values", _capture_values):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        mod.parse_and_ingest_activities(conn, str(tmp_path))

    assert captured.get("values"), "no rows written"
    row = captured["values"][0]
    # Tuple shape: (activity_id, dt, type, duration, distance, avg_hr, max_hr,
    #               avg_pace, training_effect, training_load, perceived_exertion, feel)
    assert row[-3] == 78.3, f"training_load wrong: {row}"
    assert row[-2] == 7, f"perceived_exertion wrong: {row}"
    assert row[-1] == 4, f"feel wrong: {row}"

    # NULL-safe: entry missing the keys → None
    fixture2 = [{**fixture[0], "activityId": 99999}]
    for k in ("activityTrainingLoad", "directWorkoutRpe", "directWorkoutFeel"):
        fixture2[0].pop(k)
    _write_summaries(tmp_path, fixture2)
    captured.clear()
    with patch.object(mod, "execute_values", _capture_values):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        mod.parse_and_ingest_activities(conn, str(tmp_path))
    row = captured["values"][0]
    assert row[-3] is None and row[-2] is None and row[-1] is None, (
        f"NULL-safety failed: {row}"
    )


def test_uds_vo2_max(tmp_path):
    mod = _import_module()
    uds = [
        {
            "calendarDate": "2026-05-26",
            "vO2MaxValue": 51.7,
            "restingHeartRate": 50,
        }
    ]
    _write_uds(tmp_path, uds)

    captured = []

    def _capture(cur, sql, values, **kw):
        captured.extend(values)

    with patch.object(mod, "execute_values", _capture):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        mod.parse_and_ingest_wellness(conn, str(tmp_path))

    assert captured, "no biometric rows written"
    # vo2_max must appear in at least one tuple
    assert any(51.7 in tuple(row) for row in captured), (
        f"vO2 max not in any tuple: {captured}"
    )
