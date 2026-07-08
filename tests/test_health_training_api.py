"""Tests for GET /api/health/training aggregator (Plan 30-02 Task 1 — HLTH-01).

WHY this module exists: Phase 30 (Health Pages) adds GET /api/health/training —
a read-only aggregator that merges StrengthSessionStore + RunDetailStore +
BenchmarkStore + BlockStore into a reverse-chronological training log, behind
the require_hub_session auth dependency, mirroring /api/today's composition
pattern.

Pattern: mirrors tests/test_api_today.py's `_stub_web_server_imports` +
monkeypatched-per-source-helper + session-auth-stub pattern. Route-level tests
monkeypatch the `_health_training_*` helpers directly (no real Firestore I/O);
a few tests call `_health_training_blocks` / `_health_training_benchmarks`
directly with `memory.firestore_db.BlockStore`/`BenchmarkStore` monkeypatched,
to lock the block_number/previous_value derivation contract at the helper level.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest


_ENV = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    "CRON_DEV_BYPASS": "true",
    "GCP_PROJECT_ID": "test-project",
    "FIRESTORE_DATABASE": "(default)",
    "TELEGRAM_BOT_TOKEN": "1234:fake",
    "TELEGRAM_ALLOWED_USER_IDS": "123456",
}


def _stub_web_server_imports() -> dict:
    """Mirrors tests/test_api_today.py::_stub_web_server_imports exactly."""
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if (
            key == "interfaces.web_server"
            or key.startswith("interfaces.web_server.")
            or key == "interfaces.hub_auth"
            or key.startswith("interfaces.hub_auth.")
        ):
            del sys.modules[key]
    return stubs


# ------------------------------------------------------------------ #
# Route-level tests (helpers monkeypatched — no real Firestore I/O)   #
# ------------------------------------------------------------------ #


def test_training_returns_expected_keys():
    """GET /api/health/training returns entries/blocks/two trend series."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_training_strength = lambda start, end: [
                {"date": "2026-07-01", "workout_id": "w1", "total_volume_kg": 1000.0},
            ]
            ws._health_training_runs = lambda start, end: [
                {"date": "2026-07-02", "activity_id": "a1", "avg_pace_sec_per_km": 300},
            ]
            ws._health_training_benchmarks = lambda start, end: [
                {"date": "2026-07-03", "facet": "bench_press_1rm", "value": 100.0,
                 "previous_value": 95.0},
            ]
            ws._health_training_blocks = lambda: [
                {"block_id": "b1", "label": "Aerobic Base", "start_date": "2026-06-21",
                 "end_date": "2026-07-18", "block_number": 1},
            ]

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/training?range=30d")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        for key in ["range", "entries", "blocks", "strength_volume", "run_trend"]:
            assert key in data, f"Missing key '{key}' in /api/health/training response"
        assert len(data["entries"]) == 3
        assert len(data["blocks"]) == 1


def test_training_reverse_chronological_interleave():
    """entries interleave strength/run/benchmark, sorted date descending."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_training_strength = lambda start, end: [
                {"date": "2026-07-01", "workout_id": "w1", "total_volume_kg": 1000.0},
            ]
            ws._health_training_runs = lambda start, end: [
                {"date": "2026-07-03", "activity_id": "a1", "avg_pace_sec_per_km": 300},
            ]
            ws._health_training_benchmarks = lambda start, end: [
                {"date": "2026-07-02", "facet": "bench_press_1rm", "value": 100.0,
                 "previous_value": None},
            ]
            ws._health_training_blocks = lambda: []

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/training?range=30d")

        data = response.json()
        dates = [e["date"] for e in data["entries"]]
        modalities = [e["modality"] for e in data["entries"]]
        assert dates == sorted(dates, reverse=True), f"entries not reverse-chronological: {dates}"
        assert modalities == ["run", "benchmark", "strength"]


def test_training_weekly_bucket_selectable():
    """range=1y trend series are weekly-bucketed; range=30d stays daily (D-07)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            # 20 daily strength sessions spanning ~3 weeks — a real analog of a
            # 1y range would span many more weeks, but the bucketing mechanism
            # only depends on the resolved day count, not the payload size.
            strength_data = [
                {"date": f"2026-06-{d:02d}", "workout_id": f"w{d}", "total_volume_kg": 500.0}
                for d in range(1, 21)
            ]
            ws._health_training_strength = lambda start, end: strength_data
            ws._health_training_runs = lambda start, end: []
            ws._health_training_benchmarks = lambda start, end: []
            ws._health_training_blocks = lambda: []

            client = TestClient(ws.app, raise_server_exceptions=True)
            resp_30d = client.get("/api/health/training?range=30d")
            resp_1y = client.get("/api/health/training?range=1y")

        daily_points = resp_30d.json()["strength_volume"]
        weekly_points = resp_1y.json()["strength_volume"]

        assert len(daily_points) == 20, "range=30d must stay daily (one point per date)"
        assert len(weekly_points) < len(daily_points), (
            "range=1y must weekly-bucket (fewer points than daily)"
        )
        # Weekly-bucketed volume is the sum of its constituent days.
        assert sum(p["y"] for p in weekly_points) == pytest.approx(
            sum(p["y"] for p in daily_points)
        )


def test_training_unauthenticated_returns_401():
    """GET /api/health/training without a valid hub session -> 401."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        env_no_bypass = {**_ENV, "CRON_DEV_BYPASS": "false"}
        with patch.dict(os.environ, env_no_bypass):
            client = TestClient(ws.app, raise_server_exceptions=False)
            response = client.get("/api/health/training")

        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated request, got {response.status_code}: {response.text}"
        )


# ------------------------------------------------------------------ #
# Helper-level tests — lock block_number/label + previous_value       #
# derivation contracts (monkeypatch the Store classes directly)       #
# ------------------------------------------------------------------ #


def test_training_blocks_sequential_number_and_label(monkeypatch):
    """_health_training_blocks assigns sequential block_number by start_date asc
    and carries the block's `label` field (not `block_name`, which doesn't exist).
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        import memory.firestore_db as db  # noqa: PLC0415

        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

        class _FakeBlockStore:
            def __init__(self, project_id, database):
                pass

            def get_all(self):
                # Deliberately unsorted / out-of-order input.
                return [
                    {"block_id": "b3", "label": "Peak", "start_date": "2026-08-16", "end_date": "2026-09-12"},
                    {"block_id": "b1", "label": "Aerobic Base", "start_date": "2026-06-21", "end_date": "2026-07-18"},
                    {"block_id": "b2", "label": "Capacity Build", "start_date": "2026-07-19", "end_date": "2026-08-15"},
                ]

        monkeypatch.setattr(db, "BlockStore", _FakeBlockStore)

        blocks = ws._health_training_blocks()

    assert [b["block_number"] for b in blocks] == [1, 2, 3]
    assert [b["label"] for b in blocks] == ["Aerobic Base", "Capacity Build", "Peak"]
    assert [b["start_date"] for b in blocks] == ["2026-06-21", "2026-07-19", "2026-08-16"]
    for b in blocks:
        assert "block_name" not in b, "BlockStore has no block_name field — use label"


def test_training_benchmarks_previous_value_present_and_null(monkeypatch):
    """_health_training_benchmarks attaches previous_value (prior same-facet
    result) — present when a prior exists, None when it does not."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        import memory.firestore_db as db  # noqa: PLC0415

        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

        facet_history = {
            "bench_press_1rm": [
                {"date": "2026-07-15", "facet": "bench_press_1rm", "value": 100.0},
                {"date": "2026-06-01", "facet": "bench_press_1rm", "value": 90.0},
            ],
            "squat_1rm": [
                {"date": "2026-07-10", "facet": "squat_1rm", "value": 140.0},
            ],
        }

        class _FakeBenchmarkStore:
            def __init__(self, project_id, database):
                pass

            def get_range(self, start, end):
                return [
                    {"date": "2026-07-15", "facet": "bench_press_1rm", "value": 100.0},
                    {"date": "2026-07-10", "facet": "squat_1rm", "value": 140.0},
                ]

            def get_facet_history(self, facet, n=10):
                return facet_history.get(facet, [])[:n]

        monkeypatch.setattr(db, "BenchmarkStore", _FakeBenchmarkStore)

        result = ws._health_training_benchmarks("2026-07-01", "2026-07-31")

    by_facet = {b["facet"]: b for b in result}
    assert by_facet["bench_press_1rm"]["previous_value"] == 90.0
    assert by_facet["squat_1rm"]["previous_value"] is None
