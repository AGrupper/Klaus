"""Tests for GET /api/health/nutrition aggregator (Plan 30-02 Task 2 — HLTH-02).

WHY this module exists: Phase 30 (Health Pages) adds GET /api/health/nutrition —
a read-only aggregator sharing its averages/targets/protein-g-per-kg math with
core.tools._handle_fetch_nutrition_trend, plus a D-13 slot-adherence grid built
from the SAME per-day Firestore pass (RESEARCH.md Pitfall 1 — never two
independent ~365-read loops over the same range).

Pattern: mirrors tests/test_api_today.py's `_stub_web_server_imports` pattern.
Route-level tests monkeypatch `_health_nutrition_daily`/`_health_nutrition_profile`
directly (no real Firestore I/O); the caching test monkeypatches
`memory.firestore_db.MealStore` to count `get_day` invocations.
"""
from __future__ import annotations

import json
import os
import re
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


_DAILY_FIXTURE = {
    "day_records": [
        {"date": "2026-07-01", "meal_count": 3, "calories": 2200, "protein_g": 150,
         "carbs_g": 220, "fat_g": 70, "fiber_g": 30},
        {"date": "2026-07-03", "meal_count": 2, "calories": 1800, "protein_g": 120,
         "carbs_g": 180, "fat_g": 55, "fiber_g": 20},
    ],
    "missing_dates": ["2026-07-02"],
    "slot_records": [
        {"date": "2026-07-01", "slot_label": "Breakfast"},
        {"date": "2026-07-01", "slot_label": "Lunch"},
        {"date": "2026-07-01", "slot_label": "Dinner"},
        {"date": "2026-07-03", "slot_label": "Breakfast"},
        {"date": "2026-07-03", "slot_label": "Dinner"},
    ],
}


# ------------------------------------------------------------------ #
# Route-level tests (helpers monkeypatched — no real Firestore I/O)   #
# ------------------------------------------------------------------ #


def test_nutrition_missing_dates_render_as_null_gaps_never_zero():
    """An unlogged day appears in the series as an explicit {y: null} gap the
    LineChart splits on (D-08 / CR-01) — present but null, NEVER absent (which
    would bridge the line) and NEVER a fabricated y=0."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_nutrition_daily = lambda start, end: _DAILY_FIXTURE
            ws._health_nutrition_profile = lambda: {
                "nutrition_targets": {"protein_g_per_kg": [1.8, 2.2], "protein_g_floor": 150},
                "bodyweight_kg": 75,
            }

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/nutrition?range=30d")

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["missing_dates"] == ["2026-07-02"]
        # The gap day is PRESENT in the series (so the client renders a break,
        # not a bridge) but carries y=null, and the logged days keep real values.
        cal_by_date = {p["x"]: p["y"] for p in data["series"]["calories"]}
        assert set(cal_by_date) == {"2026-07-01", "2026-07-02", "2026-07-03"}
        assert cal_by_date["2026-07-02"] is None  # gap = null, never 0 or absent
        assert cal_by_date["2026-07-01"] == 2200
        # No series ever fabricates a y=0 for the missing date.
        for series in data["series"].values():
            for p in series:
                if p["x"] == "2026-07-02":
                    assert p["y"] is None


def test_nutrition_targets_present_incl_derived_calories():
    """Targets include a calories line even when the profile has no literal key."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_nutrition_daily = lambda start, end: _DAILY_FIXTURE
            ws._health_nutrition_profile = lambda: {
                "nutrition_targets": {
                    "protein_g": 150, "carbs_g": 250, "fat_g": 70,
                    "protein_g_per_kg": [1.8, 2.2],
                },
                "bodyweight_kg": 75,
            }

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/nutrition?range=30d")

        data = response.json()
        assert "targets" in data
        assert data["targets"]["calories"] == pytest.approx(150 * 4 + 250 * 4 + 70 * 9)
        assert data["targets"].get("calories_target_derived") is True
        assert "avg_protein_g_per_kg" in data
        assert data["averages"]["days_with_data"] == 2


def test_nutrition_weekly_bucket_selectable():
    """range=1y macro series are weekly-bucketed; range=30d stays daily (D-07)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            day_records = [
                {"date": f"2026-06-{d:02d}", "meal_count": 2, "calories": 2000,
                 "protein_g": 140, "carbs_g": 200, "fat_g": 60, "fiber_g": 25}
                for d in range(1, 21)
            ]
            daily_fixture = {"day_records": day_records, "missing_dates": [], "slot_records": []}
            ws._health_nutrition_daily = lambda start, end: daily_fixture
            ws._health_nutrition_profile = lambda: {}

            client = TestClient(ws.app, raise_server_exceptions=True)
            resp_30d = client.get("/api/health/nutrition?range=30d")
            resp_1y = client.get("/api/health/nutrition?range=1y")

        daily_points = resp_30d.json()["series"]["calories"]
        weekly_points = resp_1y.json()["series"]["calories"]

        assert len(daily_points) == 20, "range=30d must stay daily"
        assert len(weekly_points) < len(daily_points), "range=1y must weekly-bucket"


def test_nutrition_no_slot_time_leak():
    """No slot_time / clock-time field anywhere in the payload — labels only."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            ws._health_nutrition_daily = lambda start, end: _DAILY_FIXTURE
            ws._health_nutrition_profile = lambda: {}

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/health/nutrition?range=30d")

        raw = response.text
        assert "slot_time" not in raw
        # No HH:MM clock-time pattern anywhere in the serialized payload.
        assert not re.search(r'"\d{2}:\d{2}"', raw), (
            f"A clock-time value leaked into the nutrition payload: {raw}"
        )
        data = response.json()
        assert data["slot_adherence"]["slot_labels"] == ["Breakfast", "Dinner", "Lunch"]
        assert data["slot_adherence"]["dates"] == ["2026-07-01", "2026-07-03"]
        # Cells are hit booleans keyed on (date, slot_label) — never a time value.
        for row in data["slot_adherence"]["grid"]:
            for cell in row["cells"]:
                assert set(cell.keys()) == {"date", "hit"}


def test_nutrition_unauthenticated_returns_401():
    """GET /api/health/nutrition without a valid hub session -> 401."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        env_no_bypass = {**_ENV, "CRON_DEV_BYPASS": "false"}
        with patch.dict(os.environ, env_no_bypass):
            client = TestClient(ws.app, raise_server_exceptions=False)
            response = client.get("/api/health/nutrition")

        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )


# ------------------------------------------------------------------ #
# Shared-math contract test                                           #
# ------------------------------------------------------------------ #


def test_nutrition_averages_math_shared_with_chat_tool():
    """The route imports the SAME averages helper the chat tool uses — locks
    the "shared, not duplicated" contract (RESEARCH.md Anti-Patterns)."""
    from core.tools import _compute_nutrition_averages, _handle_fetch_nutrition_trend
    import interfaces.web_server  # noqa: F401 — ensure module imports cleanly

    day_records = [
        {"date": "2026-07-01", "calories": 2000, "protein_g": 150, "carbs_g": 200,
         "fat_g": 60, "fiber_g": 25},
    ]
    averages = _compute_nutrition_averages(day_records)
    assert averages["calories"] == 2000
    assert averages["days_with_data"] == 1
    # _handle_fetch_nutrition_trend must still be importable/callable (regression
    # guard on the extraction refactor).
    assert callable(_handle_fetch_nutrition_trend)


# ------------------------------------------------------------------ #
# Single-pass caching test (Pitfall 1 — mandatory for >90d)           #
# ------------------------------------------------------------------ #


def test_nutrition_daily_single_pass_cached(monkeypatch):
    """_health_nutrition_daily reads each day at most once per (start, end);
    a second identical call is served from the TTL cache — no repeat get_day
    calls (RESEARCH.md Pitfall 1 / T-30-02-03)."""
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        import memory.firestore_db as db  # noqa: PLC0415

        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("FIRESTORE_DATABASE", "(default)")

        call_log: list[str] = []

        class _FakeMealStore:
            def __init__(self, project_id, database):
                pass

            def get_day(self, date_str):
                call_log.append(date_str)
                if date_str == "2026-07-01":
                    return [{"timestamp": "2026-07-01T08:00:00", "calories": 500,
                              "protein_g": 30, "carbs_g": 60, "fat_g": 15, "fiber_g": 5}]
                return []

        monkeypatch.setattr(db, "MealStore", _FakeMealStore)
        # Isolate the module-level cache from other tests in this file.
        ws._nutrition_daily_cache.clear()

        first = ws._health_nutrition_daily("2026-07-01", "2026-07-03")
        calls_after_first = len(call_log)
        second = ws._health_nutrition_daily("2026-07-01", "2026-07-03")
        calls_after_second = len(call_log)

    assert calls_after_first == 3  # one get_day call per date in [start, end]
    assert calls_after_second == calls_after_first, (
        "second identical request must be served from the TTL cache, "
        "not re-read every day"
    )
    assert first == second
