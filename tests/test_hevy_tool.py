"""Tests for mcp_tools/hevy_tool.py — Hevy strength-data client + normalizer.

Covers:
  - normalize_workout: top_set (heaviest working set), est_1rm (max Epley),
    volume_kg, warmup exclusion, bodyweight/cardio sets, tz-aware date,
    duration, total session volume.
  - fetch_workouts / fetch_workout_events: api-key header, params, error mapping.
  - HevyAuthError when key missing / 401, HevyUnavailableError on 5xx / network.

No network, no Firestore — requests is patched at the module level.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import mcp_tools.hevy_tool as hevy


# ------------------------------------------------------------------ #
# normalize_workout — derived strength metrics                       #
# ------------------------------------------------------------------ #

def _bench_workout() -> dict:
    return {
        "id": "w1",
        "title": "Upper A",
        "start_time": "2026-06-07T17:00:00Z",   # 20:00 Asia/Jerusalem (UTC+3)
        "end_time": "2026-06-07T18:15:00Z",
        "exercises": [
            {
                "title": "Bench Press",
                "exercise_template_id": "tmpl_bench",
                "sets": [
                    {"index": 0, "type": "warmup", "weight_kg": 40, "reps": 10},
                    {"index": 1, "type": "normal", "weight_kg": 90, "reps": 5, "rpe": 8},
                    {"index": 2, "type": "normal", "weight_kg": 92.5, "reps": 3, "rpe": 9},
                    {"index": 3, "type": "normal", "weight_kg": 80, "reps": 8},
                ],
            },
            {
                "title": "Plank",
                "exercise_template_id": "tmpl_plank",
                "sets": [
                    {"index": 0, "type": "normal", "duration_seconds": 60,
                     "weight_kg": None, "reps": None},
                ],
            },
        ],
    }


def test_normalize_top_set_is_heaviest_working_set():
    n = hevy.normalize_workout(_bench_workout())
    bench = n["exercises"][0]
    assert bench["top_set"] == {"weight_kg": 92.5, "reps": 3}


def test_normalize_est_1rm_is_max_epley_across_working_sets():
    # 90*(1+5/30)=105.0 is higher than 92.5*(1+3/30)=101.75 and 80*(1+8/30)=101.33
    n = hevy.normalize_workout(_bench_workout())
    assert n["exercises"][0]["est_1rm"] == 105.0


def test_normalize_volume_excludes_warmup():
    n = hevy.normalize_workout(_bench_workout())
    bench = n["exercises"][0]
    assert bench["volume_kg"] == 90 * 5 + 92.5 * 3 + 80 * 8  # 1367.5
    assert bench["set_count"] == 3  # working sets only


def test_normalize_bodyweight_set_has_no_weight_metrics():
    n = hevy.normalize_workout(_bench_workout())
    plank = n["exercises"][1]
    assert plank["top_set"] is None
    assert plank["est_1rm"] is None
    assert plank["volume_kg"] == 0.0


def test_normalize_date_is_local_jerusalem():
    n = hevy.normalize_workout(_bench_workout())
    assert n["date"] == "2026-06-07"
    assert n["duration_min"] == 75.0
    assert n["workout_id"] == "w1"


def test_normalize_total_volume_sums_exercises():
    n = hevy.normalize_workout(_bench_workout())
    assert n["total_volume_kg"] == 1367.5


def test_normalize_handles_missing_times_gracefully():
    n = hevy.normalize_workout({"id": "w2", "exercises": []})
    assert n["date"] is None
    assert n["duration_min"] is None
    assert n["total_volume_kg"] == 0.0


def test_epley_standard_form():
    # Classic Epley: w*(1 + reps/30). At 5 reps → 100*(1+5/30)=116.67.
    assert round(hevy._epley_1rm(100.0, 5), 2) == 116.67
    assert round(hevy._epley_1rm(100.0, 1), 2) == 103.33


# ------------------------------------------------------------------ #
# fetch_workouts / fetch_workout_events — HTTP contract              #
# ------------------------------------------------------------------ #

def _resp(status: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.ok = 200 <= status < 300
    r.json.return_value = json_body if json_body is not None else {}
    r.text = text
    return r


def _patch_session_get(**get_kwargs):
    """Patch hevy._get_session with a mock session; returns the session's
    ``get`` mock via the context manager (HTTP calls now go through a shared
    requests.Session rather than module-level requests.get)."""
    session = MagicMock(name="requests-session")
    session.get = MagicMock(**get_kwargs)
    ctx = patch.object(hevy, "_get_session", return_value=session)

    class _Ctx:
        def __enter__(self):
            ctx.__enter__()
            return session.get

        def __exit__(self, *exc):
            return ctx.__exit__(*exc)

    return _Ctx()


def test_fetch_workouts_sends_api_key_header(monkeypatch):
    monkeypatch.setenv("HEVY_API_KEY", "uuid-123")
    with _patch_session_get(return_value=_resp(200, {"workouts": []})) as g:
        hevy.fetch_workouts(page=2)
    _, kwargs = g.call_args
    assert kwargs["headers"]["api-key"] == "uuid-123"
    assert kwargs["params"]["page"] == 2
    assert kwargs["params"]["pageSize"] == 10


def test_fetch_workout_events_passes_since(monkeypatch):
    monkeypatch.setenv("HEVY_API_KEY", "uuid-123")
    with _patch_session_get(return_value=_resp(200, {"events": []})) as g:
        hevy.fetch_workout_events(since="2026-06-01T00:00:00Z", page=1)
    _, kwargs = g.call_args
    assert kwargs["params"]["since"] == "2026-06-01T00:00:00Z"
    assert g.call_args[0][0].endswith("/workouts/events")


def test_missing_api_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("HEVY_API_KEY", raising=False)
    with pytest.raises(hevy.HevyAuthError):
        hevy.fetch_workouts()


def test_401_raises_auth_error(monkeypatch):
    monkeypatch.setenv("HEVY_API_KEY", "bad")
    with _patch_session_get(return_value=_resp(401, text="Unauthorized")):
        with pytest.raises(hevy.HevyAuthError):
            hevy.fetch_workouts()


def test_500_raises_unavailable(monkeypatch):
    monkeypatch.setenv("HEVY_API_KEY", "ok")
    with _patch_session_get(return_value=_resp(500, text="boom")):
        with pytest.raises(hevy.HevyUnavailableError):
            hevy.fetch_workouts()


def test_network_error_raises_unavailable(monkeypatch):
    monkeypatch.setenv("HEVY_API_KEY", "ok")
    import requests as _rq
    with _patch_session_get(side_effect=_rq.RequestException("timeout")):
        with pytest.raises(hevy.HevyUnavailableError):
            hevy.fetch_workout_events(since="x")
