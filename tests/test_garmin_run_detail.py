"""Tests for mcp_tools/garmin_tool.py::normalize_run_detail (pure function).

Covers metricDescriptor extraction into {min,avg,max} summary, recorded-lap
normalization (typed-splits and lapDTOs shapes), active-lap-only derived signals
(split_shape / cadence_drift / hr_drift / pace_cv), the has_dynamics gate for
treadmill / no-strap runs, fail-soft on absent descriptors, and a doc-size bound.

normalize_run_detail is pure (no I/O), so these tests need no mocks.
"""
from __future__ import annotations

import json

from mcp_tools.garmin_tool import normalize_run_detail


def _details(rows: list[list], keys: list[str]) -> dict:
    """Build a get_activity_details envelope from metric rows + descriptor keys."""
    return {
        "metricDescriptors": [
            {"metricsIndex": i, "key": k} for i, k in enumerate(keys)
        ],
        "activityDetailMetrics": [{"metrics": r} for r in rows],
    }


_KEYS = [
    "directHeartRate", "directDoubleCadence", "directStrideLength",
    "directVerticalOscillation", "directGroundContactTime", "directPower",
]


def _interval_session():
    """A 3×800 interval session with recovery laps + a full detail stream."""
    details = _details(
        rows=[
            [150, 176, 1.10, 8.6, 252, 300],
            [160, 178, 1.18, 8.5, 250, 315],
            [170, 180, 1.22, 8.4, 248, 330],
        ],
        keys=_KEYS,
    )
    splits = {"splits": [
        {"type": "INTERVAL_ACTIVE", "distance": 800, "duration": 180, "averageHR": 165,
         "averageRunningCadenceInStepsPerMinute": 182, "strideLength": 120, "averagePower": 320},
        {"type": "INTERVAL_REST", "distance": 200, "duration": 120, "averageHR": 140,
         "averageRunningCadenceInStepsPerMinute": 160, "strideLength": 95},
        {"type": "INTERVAL_ACTIVE", "distance": 800, "duration": 184, "averageHR": 168,
         "averageRunningCadenceInStepsPerMinute": 181, "strideLength": 119, "averagePower": 318},
        {"type": "INTERVAL_ACTIVE", "distance": 800, "duration": 190, "averageHR": 172,
         "averageRunningCadenceInStepsPerMinute": 176, "strideLength": 116, "averagePower": 310},
    ]}
    hr_zones = [{"zoneNumber": 2, "secsInZone": 120}, {"zoneNumber": 4, "secsInZone": 360}]
    activity = {"activity_id": 12345, "type": "running",
                "startTimeLocal": "2026-06-08 07:30:00", "distance_m": 5000, "duration_sec": 1500}
    return activity, details, splits, hr_zones


# ------------------------------------------------------------------ #
# Full-dynamics extraction                                           #
# ------------------------------------------------------------------ #

def test_summary_min_avg_max_per_metric():
    activity, details, splits, hr = _interval_session()
    doc = normalize_run_detail(activity, details, splits, hr)
    assert doc["summary"]["hr_bpm"] == {"min": 150.0, "avg": 160.0, "max": 170.0}
    assert doc["summary"]["cadence_spm"]["max"] == 180.0
    # stride length is converted metres -> cm
    assert doc["summary"]["stride_length_cm"]["min"] == 110.0
    assert doc["summary"]["stride_length_cm"]["max"] == 122.0


def test_splits_are_recorded_laps_with_pace():
    activity, details, splits, hr = _interval_session()
    doc = normalize_run_detail(activity, details, splits, hr)
    assert len(doc["splits"]) == 4
    first = doc["splits"][0]
    assert first["type"] == "INTERVAL_ACTIVE"
    assert first["pace_sec_per_km"] == 225.0     # 180s / 0.8km
    assert first["avg_cadence_spm"] == 182
    assert first["avg_stride_length_cm"] == 120.0  # already cm, unchanged


def test_derived_excludes_rest_laps():
    activity, details, splits, hr = _interval_session()
    doc = normalize_run_detail(activity, details, splits, hr)
    d = doc["derived"]
    # 3 active laps (one REST excluded) — too few to assert a split shape.
    assert d["active_lap_count"] == 3
    assert d["split_shape"] is None
    # cadence fades 182 -> 176 over active laps (rest lap's 160 ignored)
    assert d["cadence_drift"] == -6.0
    assert d["hr_drift"] is not None and d["hr_drift"] > 0
    assert d["pace_cv"] is not None and d["pace_cv"] >= 0


def _run_with_active_paces(paces_sec_per_km, atype="running"):
    """Build a run whose active laps have the given per-km paces (1km each)."""
    splits = {"splits": [
        {"type": "RWD_RUN", "distance": 1000, "duration": p, "averageHR": 150,
         "averageRunningCadenceInStepsPerMinute": 178, "strideLength": 118}
        for p in paces_sec_per_km
    ]}
    total_d = 1000 * len(paces_sec_per_km)
    total_t = sum(paces_sec_per_km)
    activity = {"activity_id": 321, "type": atype,
                "startTimeLocal": "2026-06-08 06:00:00",
                "distance_m": total_d, "duration_sec": total_t}
    details = _details(rows=[[150, 178, 1.18]], keys=["directHeartRate", "directDoubleCadence", "directStrideLength"])
    return normalize_run_detail(activity, details, splits, [])


def test_split_shape_none_from_two_laps():
    # The drink-break case: watch stopped mid-run → 2 laps (4.18km @ 5:36, 3.81 @ 5:28).
    # That 8s/km gap is a pause artifact, not a negative split — must NOT be asserted.
    doc = _run_with_active_paces([336, 328])
    assert doc["derived"]["active_lap_count"] == 2
    assert doc["derived"]["split_shape"] is None


def test_even_when_swing_within_band():
    # 4 laps, sub-4% swing across halves → "even", not a split.
    doc = _run_with_active_paces([300, 302, 301, 303])
    assert doc["derived"]["active_lap_count"] == 4
    assert doc["derived"]["split_shape"] == "even"


def test_split_shape_positive_from_four_laps_with_real_swing():
    # 4 laps slowing well past the band (300 → 330) → positive split.
    doc = _run_with_active_paces([300, 305, 320, 330])
    assert doc["derived"]["split_shape"] == "positive"


def test_split_shape_negative_from_four_laps_with_real_swing():
    # 4 laps progressively faster (330 → 300) → negative split.
    doc = _run_with_active_paces([330, 320, 305, 300])
    assert doc["derived"]["split_shape"] == "negative"


def test_hr_zones_normalized_with_pct():
    activity, details, splits, hr = _interval_session()
    doc = normalize_run_detail(activity, details, splits, hr)
    zones = doc["hr_zones"]
    assert {z["zone"] for z in zones} == {2, 4}
    assert sum(z["pct"] for z in zones) == 100.0


def test_has_dynamics_true_and_date_local():
    activity, details, splits, hr = _interval_session()
    doc = normalize_run_detail(activity, details, splits, hr)
    assert doc["has_dynamics"] is True
    assert doc["date"] == "2026-06-08"
    assert doc["activity_id"] == "12345"
    assert doc["avg_pace_sec_per_km"] == 300.0  # 1500s / 5km


# ------------------------------------------------------------------ #
# Edge cases — treadmill, lapDTOs shape, empty descriptors, size     #
# ------------------------------------------------------------------ #

def test_treadmill_no_dynamics_does_not_fabricate():
    # No running-dynamics descriptors (treadmill / no foot-pod): only HR present.
    details = _details(rows=[[150], [158], [165]], keys=["directHeartRate"])
    splits = {"splits": [
        {"type": "RWD_RUN", "distance": 1000, "duration": 330, "averageHR": 150},
        {"type": "RWD_RUN", "distance": 1000, "duration": 325, "averageHR": 158},
    ]}
    activity = {"activity_id": 9, "type": "treadmill_running",
                "startTimeLocal": "2026-06-08 18:00:00", "distance_m": 2000, "duration_sec": 655}
    doc = normalize_run_detail(activity, details, splits, [])
    assert doc["has_dynamics"] is False
    assert "cadence_spm" not in doc["summary"]
    assert "stride_length_cm" not in doc["summary"]
    # laps still captured for pace reasoning
    assert len(doc["splits"]) == 2 and doc["splits"][0]["pace_sec_per_km"] == 330.0


def test_plain_splits_lapdtos_shape_supported():
    details = _details(rows=[[150, 170, 1.1]], keys=["directHeartRate", "directDoubleCadence", "directStrideLength"])
    splits = {"lapDTOs": [
        {"distance": 1000, "duration": 300, "avgHr": 150, "averageRunCadence": 178},
        {"distance": 1000, "duration": 305, "avgHr": 152, "averageRunCadence": 177},
    ]}
    activity = {"activity_id": 7, "type": "running",
                "startTimeLocal": "2026-06-08 06:00:00", "distance_m": 2000, "duration_sec": 605}
    doc = normalize_run_detail(activity, details, splits, [])
    assert len(doc["splits"]) == 2
    assert doc["splits"][0]["avg_hr"] == 150
    assert doc["splits"][0]["avg_cadence_spm"] == 178


def test_empty_descriptors_fail_soft():
    activity = {"activity_id": 1, "type": "running",
                "startTimeLocal": "2026-06-08 06:00:00", "distance_m": 1000, "duration_sec": 300}
    doc = normalize_run_detail(activity, {}, {}, [])
    assert doc["summary"] == {}
    assert doc["splits"] == []
    assert doc["has_dynamics"] is False
    assert doc["avg_pace_sec_per_km"] == 300.0  # still derivable from the summary


def test_normalized_doc_under_one_megabyte():
    # A long run with many auto-km laps must stay well under the Firestore 1MB cap.
    rows = [[150 + (i % 20), 175, 1.15, 8.5, 250, 300] for i in range(3000)]
    details = _details(rows=rows, keys=_KEYS)
    splits = {"splits": [
        {"type": "RWD_RUN", "distance": 1000, "duration": 300 + i, "averageHR": 150,
         "averageRunningCadenceInStepsPerMinute": 178, "strideLength": 118, "averagePower": 300}
        for i in range(42)
    ]}
    activity = {"activity_id": 99, "type": "running",
                "startTimeLocal": "2026-06-08 06:00:00", "distance_m": 42000, "duration_sec": 13000}
    doc = normalize_run_detail(activity, details, splits, [])
    assert len(json.dumps(doc, default=str)) < 1_000_000


# ------------------------------------------------------------------ #
# splits_source marker + typed_segments companion                    #
# ------------------------------------------------------------------ #

def test_splits_source_laps_for_lapdtos_envelope():
    activity = {"activity_id": 7, "type": "running",
                "startTimeLocal": "2026-07-01 06:00:00", "distance_m": 800, "duration_sec": 182}
    splits = {"lapDTOs": [{"distance": 400, "duration": 90}, {"distance": 400, "duration": 92}]}
    doc = normalize_run_detail(activity, {}, splits, [])
    assert doc["splits_source"] == "laps"


def test_splits_source_typed_for_typed_envelope():
    activity, details, splits, hr = _interval_session()
    doc = normalize_run_detail(activity, details, splits, hr)
    assert doc["splits_source"] == "typed"


def test_splits_source_none_when_no_envelope():
    activity = {"activity_id": 1, "type": "running",
                "startTimeLocal": "2026-07-01 06:00:00", "distance_m": 1000, "duration_sec": 300}
    doc = normalize_run_detail(activity, {}, {}, [])
    assert doc["splits_source"] is None


def test_typed_segments_aggregated_per_type():
    activity = {"activity_id": 8, "type": "track_running",
                "startTimeLocal": "2026-07-01 06:00:00", "distance_m": 3000, "duration_sec": 900}
    splits = {"lapDTOs": [{"distance": 400, "duration": 90}]}
    typed = {"splits": [
        {"type": "RWD_RUN", "distance": 1000, "duration": 280},
        {"type": "RWD_WALK", "distance": 200, "duration": 120},
        {"type": "RWD_RUN", "distance": 1000, "duration": 290},
    ]}
    doc = normalize_run_detail(activity, {}, splits, [], typed_splits=typed)
    assert doc["typed_segments"] == [
        {"type": "RWD_RUN", "distance_m": 2000.0, "duration_sec": 570.0},
        {"type": "RWD_WALK", "distance_m": 200.0, "duration_sec": 120.0},
    ]
    # the per-lap rows stay the primary splits
    assert doc["splits_source"] == "laps" and len(doc["splits"]) == 1


def test_typed_segments_silently_omitted_when_absent():
    activity, details, splits, hr = _interval_session()
    doc = normalize_run_detail(activity, details, splits, hr)          # 4-arg call
    assert "typed_segments" not in doc
    doc2 = normalize_run_detail(activity, details, splits, hr, typed_splits={})
    assert "typed_segments" not in doc2


def test_lapdto_rest_laps_excluded_from_derived():
    # Structured-workout lapDTOs carry intensityType — rest laps must not count
    # as active effort.
    activity = {"activity_id": 11, "type": "track_running",
                "startTimeLocal": "2026-07-01 06:00:00", "distance_m": 1600, "duration_sec": 400}
    splits = {"lapDTOs": [
        {"intensityType": "ACTIVE", "distance": 400, "duration": 88, "avgHr": 168},
        {"intensityType": "REST", "distance": 100, "duration": 60, "avgHr": 130},
        {"intensityType": "ACTIVE", "distance": 400, "duration": 90, "avgHr": 172},
    ]}
    doc = normalize_run_detail(activity, {}, splits, [])
    assert len(doc["splits"]) == 3               # raw laps all kept
    assert doc["derived"]["active_lap_count"] == 2
