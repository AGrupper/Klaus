"""Tests for Phase 19 Garmin parser extensions in scripts/ingest_garmin_zip.py.

Covers INGEST-01/02:
- parse_and_ingest_activities extracts activityTrainingLoad / workoutRpe /
  workoutFeel NULL-safely (keys missing → None at the end of the tuple).
- parse_and_ingest_wellness extracts UDS-side fields cleanly.
- parse_and_ingest_vo2_max extracts vo2MaxValue from
  DI-Connect-Metrics/MetricsMaxMetData_*.json and UPSERTs into daily_biometrics.

Field-name corrections vs the original Wave-0 ASSUMED plan (verified against a
real 2023-2026 Garmin export on 2026-05-27):
- activities live in *summarizedActivities.json (NOT *summaries.json) and are
  nested inside [{"summarizedActivitiesExport": [...]}, ...].
- RPE / Feel keys are workoutRpe / workoutFeel (NOT directWorkoutRpe / Feel).
- VO2 max is in DI-Connect-Metrics/MetricsMaxMetData_*.json::vo2MaxValue
  (lowercase v) — UDS files no longer carry VO2 directly.
- UDS files live in DI-Connect-Aggregator/ (NOT DI-Connect-User/).
- Activity HR keys are avgHr / maxHr (NOT averageHeartRate / maxHeartRate),
  training effect is aerobicTrainingEffect (NOT trainingEffect), startTime is
  startTimeGmt (lowercase mt), duration is in ms, distance in cm.
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


def _write_summaries(tmp_path, entries, *, wrapped=True):
    """Mirror real Garmin export layout.

    When wrapped=True (default — modern export shape), entries are nested under
    [{"summarizedActivitiesExport": entries}]. When wrapped=False, the legacy
    flat-list shape is written for backward-compat tests.
    """
    fitness_dir = tmp_path / "DI_CONNECT" / "DI-Connect-Fitness"
    fitness_dir.mkdir(parents=True, exist_ok=True)
    summary_file = fitness_dir / "amit_0_summarizedActivities.json"
    if wrapped:
        payload = [{"summarizedActivitiesExport": entries}]
    else:
        payload = entries
    summary_file.write_text(json.dumps(payload))
    return summary_file


def _write_uds(tmp_path, payload):
    # Real Garmin exports place UDS under DI-Connect-Aggregator. Create both
    # Wellness (empty — parse_and_ingest_wellness early-returns if absent) and
    # Aggregator (with the UDS file) to mirror the live layout.
    wellness_dir = tmp_path / "DI_CONNECT" / "DI-Connect-Wellness"
    wellness_dir.mkdir(parents=True, exist_ok=True)
    aggregator_dir = tmp_path / "DI_CONNECT" / "DI-Connect-Aggregator"
    aggregator_dir.mkdir(parents=True, exist_ok=True)
    uds_file = aggregator_dir / "UDSFile_2026-02-12_2026-05-23.json"
    uds_file.write_text(json.dumps(payload))
    return uds_file


def _write_maxmet(tmp_path, payload):
    metrics_dir = tmp_path / "DI_CONNECT" / "DI-Connect-Metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    f = metrics_dir / "MetricsMaxMetData_20260203_20260514_117289774.json"
    f.write_text(json.dumps(payload))
    return f


def _make_activity(activity_id, **overrides):
    """Build a fixture activity entry with the modern Garmin field names."""
    base = {
        "activityId": activity_id,
        "startTimeGmt": 1748246400000,  # ms epoch
        "startTimeLocal": "2026-05-26 07:00:00",
        "activityType": "running",
        "sportType": "RUNNING",
        "duration": 1800000.0,  # ms → 1800s
        "distance": 500000.0,  # cm → 5000m
        "avgHr": 150.0,
        "maxHr": 175.0,
        "averagePace": 6.0,
        "aerobicTrainingEffect": 3.2,
        "activityTrainingLoad": 78.3,
        "workoutRpe": 70,
        "workoutFeel": 50,
    }
    base.update(overrides)
    return base


def test_activity_phase19_fields_modern_shape(tmp_path):
    """Modern export — nested wrapper, lowercase field names."""
    mod = _import_module()

    _write_summaries(tmp_path, [_make_activity(12345)])

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
    # Tuple shape: (activity_id, dt, type, duration_sec, distance_m, avg_hr,
    #               max_hr, avg_pace, training_effect, training_load,
    #               perceived_exertion, feel)
    assert row[0] == 12345
    assert row[2] == "running"
    assert row[3] == 1800  # ms → seconds
    assert row[4] == 5000.0  # cm → meters
    assert row[5] == 150  # avg_hr coerced to int
    assert row[6] == 175  # max_hr coerced to int
    assert row[8] == 3.2  # aerobicTrainingEffect → training_effect
    assert row[-3] == 78.3, f"training_load wrong: {row}"
    assert row[-2] == 70, f"perceived_exertion wrong: {row}"
    assert row[-1] == 50, f"feel wrong: {row}"


def test_activity_phase19_fields_null_safe(tmp_path):
    """When the Phase-19 keys are absent, parser writes None — no KeyError."""
    mod = _import_module()
    entry = _make_activity(99999)
    for k in ("activityTrainingLoad", "workoutRpe", "workoutFeel"):
        entry.pop(k)
    _write_summaries(tmp_path, [entry])

    captured = {}

    def _capture_values(cur, sql, values, **kw):
        captured["values"] = list(values)

    with patch.object(mod, "execute_values", _capture_values):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        mod.parse_and_ingest_activities(conn, str(tmp_path))

    row = captured["values"][0]
    assert row[-3] is None and row[-2] is None and row[-1] is None, (
        f"NULL-safety failed: {row}"
    )


def test_activity_legacy_flat_shape(tmp_path):
    """Legacy export shape (flat list of activities) must still parse."""
    mod = _import_module()
    _write_summaries(tmp_path, [_make_activity(55555)], wrapped=False)

    captured = {}

    def _capture_values(cur, sql, values, **kw):
        captured["values"] = list(values)

    with patch.object(mod, "execute_values", _capture_values):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        mod.parse_and_ingest_activities(conn, str(tmp_path))

    assert captured.get("values"), "no rows written from legacy flat shape"
    assert captured["values"][0][0] == 55555


def test_uds_fields_from_aggregator(tmp_path):
    """UDS files in DI-Connect-Aggregator/ are read; resting_hr flows through."""
    mod = _import_module()
    uds = [
        {
            "calendarDate": "2026-05-26",
            "restingHeartRate": 50,
            "bodyBattery": {
                "bodyBatteryStatList": [
                    {"bodyBatteryStatType": "HIGHEST", "statsValue": 92},
                    {"bodyBatteryStatType": "LOWEST", "statsValue": 18},
                ]
            },
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
    # Tuple shape: (date, resting_hr, hrv_baseline, hrv_overnight, sleep_score,
    #               sleep_duration, body_battery_max, training_readiness)
    row = captured[0]
    assert row[0] == "2026-05-26"
    assert row[1] == 50  # resting_hr
    assert row[6] == 92  # body_battery_max (from HIGHEST stat)


def test_vo2_max_from_metrics(tmp_path):
    """parse_and_ingest_vo2_max reads MetricsMaxMetData and UPSERTs vo2_max."""
    mod = _import_module()
    payload = [
        {"calendarDate": "2026-02-06", "sport": "RUNNING", "vo2MaxValue": 62.0},
        {"calendarDate": "2026-02-08", "sport": "RUNNING", "vo2MaxValue": 63.0},
    ]
    _write_maxmet(tmp_path, payload)

    captured = []

    def _capture(cur, sql, values, **kw):
        captured.extend(values)

    with patch.object(mod, "execute_values", _capture):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        mod.parse_and_ingest_vo2_max(conn, str(tmp_path))

    assert len(captured) == 2, f"expected 2 rows, got {captured}"
    rows = {r[0]: r[1] for r in captured}
    assert rows["2026-02-06"] == 62.0
    assert rows["2026-02-08"] == 63.0


def test_vo2_max_same_date_picks_max_across_sports(tmp_path):
    """When the same date has running + cycling VO2 entries, keep the MAX."""
    mod = _import_module()
    payload = [
        {"calendarDate": "2026-02-06", "sport": "RUNNING", "vo2MaxValue": 60.0},
        {"calendarDate": "2026-02-06", "sport": "CYCLING", "vo2MaxValue": 65.0},
    ]
    _write_maxmet(tmp_path, payload)

    captured = []

    def _capture(cur, sql, values, **kw):
        captured.extend(values)

    with patch.object(mod, "execute_values", _capture):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        mod.parse_and_ingest_vo2_max(conn, str(tmp_path))

    assert len(captured) == 1, f"expected 1 deduped row, got {captured}"
    assert captured[0] == ("2026-02-06", 65.0)


def test_vo2_max_missing_dir_is_no_op(tmp_path):
    """Missing Metrics dir → no crash, no rows."""
    mod = _import_module()
    captured = []

    def _capture(cur, sql, values, **kw):
        captured.extend(values)

    with patch.object(mod, "execute_values", _capture):
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = MagicMock()
        mod.parse_and_ingest_vo2_max(conn, str(tmp_path))

    assert captured == []
