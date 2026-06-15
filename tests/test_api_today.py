"""Tests for GET /api/today aggregator (Plan 26-04 — TIME-01..05/08).

WHY this module exists: Phase 26 (v5.0 Klaus Hub) adds GET /api/today — a
read-only aggregator that composes the Today timeline from existing tools and
Firestore stores behind the require_hub_session auth dependency (26-03). These
tests verify the behavioral contract that plan 26-04 implements.

Pattern: mirrors tests/test_web_server.py (_stub_web_server_imports pattern,
CRON_DEV_BYPASS / TestClient) for routes that import the full web_server module.

Seeded by plan 26-02 Task 3; implemented by plan 26-04 Task 3.

Test isolation note: stubs for google.cloud.firestore and other heavy modules are
injected via patch.dict(sys.modules) inside each test, ensuring sys.modules is
restored on teardown (no cross-test pollution).
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------ #
# Shared test environment                                            #
# ------------------------------------------------------------------ #

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
    """Return a sys.modules-stubs dict that lets interfaces.web_server import
    without real telegram / google-auth / core.main / itsdangerous dependencies.

    Also includes interfaces.hub_auth with a real-enough implementation that
    CRON_DEV_BYPASS=true returns the allowed email (bypassing real session auth).
    Flushes the cached web_server so the next import picks up the stubs.
    """
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "telegram.ext": sys.modules.get("telegram.ext", MagicMock()),
        "telegram.error": sys.modules.get("telegram.error", MagicMock()),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    # Force fresh re-import of web_server (and hub_auth) so the stubs are seen.
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
# Tests — all four Wave 0 stubs flipped to real assertions           #
# ------------------------------------------------------------------ #


def test_today_returns_expected_keys():
    """GET /api/today returns the documented timeline shape.

    Covers TIME-01..05/08: the aggregator response must contain the expected
    top-level keys so the frontend TimelineDay (26-07) can render without
    defensive key-guards. Mocks the 8 per-source helpers at the helper
    boundary so no live Garmin/Routes/Firestore call is made.
    """
    stubs = _stub_web_server_imports()

    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            # Monkeypatch the 8 per-source helpers so no real I/O occurs.
            ws._today_calendar = lambda today_iso: {"all_day": [], "timed": []}
            ws._today_garmin = lambda: {"sleep": 7.5, "hrv": 55,
                                        "body_battery": 78, "resting_hr": 52}
            ws._today_weather = lambda: "Sunny, 28°C, H 31°/L 22°"
            ws._today_meals = lambda today_iso: [
                {"slot_label": "Breakfast", "slot_time": "08:00",
                 "macros": {"kcal": 500, "protein_g": 30, "carbs_g": 60,
                            "fat_g": 15, "fiber_g": 5}}
            ]
            ws._today_training = lambda today_iso: {
                "item": "Upper Body A",
                "block_context": "Week 1 of 16 — Upper Body A",
                "block_label": "Aerobic Base",
                "week_num": 1,
                "split_name": "Upper Body A",
                "benchmark_due": False,
            }
            ws._today_nutrition_totals = lambda today_iso: {
                "kcal": 1800, "protein_g": 140, "carbs_g": 200,
                "fat_g": 60, "fiber_g": 25,
            }
            ws._today_routes = lambda calendar, today_iso: calendar
            ws._today_coach_note = lambda today_iso: "Hit protein target today — +15g above yesterday."

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/today")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        # Verify the expected top-level keys are present (TIME-01..05/08).
        for key in ["today", "calendar", "garmin", "weather", "meals",
                    "training", "coach_note", "nutrition_totals"]:
            assert key in data, f"Missing key '{key}' in /api/today response"
        # calendar should have all_day + timed sub-keys.
        assert "all_day" in data["calendar"]
        assert "timed" in data["calendar"]
        # Nested contract the frontend actually reads (TIME-02/04) — guards
        # against the 26-04/26-07 field-name drift caught in 26-VERIFICATION.md.
        assert set(data["garmin"]) >= {"sleep", "hrv", "body_battery", "resting_hr"}, (
            f"garmin contract drift — frontend reads sleep/hrv/body_battery: {data['garmin']}"
        )
        assert "item" in data["training"], (
            f"training contract drift — frontend reads training.item: {data['training']}"
        )


def test_no_datetimewithnanoseconds_leak():
    """No Firestore DatetimeWithNanoseconds leaks into the JSON response.

    Covers Pitfall 4 / T-26-04-05: every Firestore timestamp must be
    ISO-converted server-side. json.dumps over the /api/today payload must
    not raise on a DatetimeWithNanoseconds-like value. We simulate by
    injecting an object with an isoformat() method (same duck-type as
    DatetimeWithNanoseconds) into the helper return values.
    """
    stubs = _stub_web_server_imports()

    class _FakeDatetimeWithNanoseconds:
        """Duck-type simulation of google.cloud.firestore_v1.DatetimeWithNanoseconds."""
        def isoformat(self):
            return "2026-06-15T08:00:00+03:00"

    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            # Inject DatetimeWithNanoseconds-like object into the garmin response
            # (simulates Firestore SERVER_TIMESTAMP read-back before _jsonsafe_doc).
            ws._today_calendar = lambda today_iso: {"all_day": [], "timed": []}
            ws._today_garmin = lambda: {
                "sleep": 7.0,
                "hrv": 50,
                "body_battery": 75,
                "resting_hr": 55,
                # Simulate a stray DatetimeWithNanoseconds that slipped through
                "_updated_at": _FakeDatetimeWithNanoseconds(),
            }
            ws._today_weather = lambda: "Partly cloudy, 26°C"
            ws._today_meals = lambda today_iso: [{
                "slot_label": "Lunch",
                "slot_time": "12:00",
                "macros": {
                    "kcal": 700,
                    "protein_g": 45,
                    "carbs_g": 80,
                    "fat_g": 20,
                    "fiber_g": 10,
                    # Also simulate a datetime in macros
                    "_ts": _FakeDatetimeWithNanoseconds(),
                },
            }]
            ws._today_training = lambda today_iso: None
            ws._today_nutrition_totals = lambda today_iso: {}
            ws._today_routes = lambda calendar, today_iso: calendar
            ws._today_coach_note = lambda today_iso: None

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/today")

        assert response.status_code == 200, f"Expected 200, got: {response.text}"

        # The key assertion: json.loads must not raise TypeError.
        # TestClient already calls response.json() above, but we explicitly
        # verify the raw text is valid JSON with no serialization error.
        try:
            parsed = json.loads(response.text)
        except (TypeError, json.JSONDecodeError) as exc:
            pytest.fail(f"Response is not valid JSON (DatetimeWithNanoseconds leaked): {exc}")

        # Verify the _updated_at field was coerced to an ISO string, not left as an object.
        garmin = parsed.get("garmin") or {}
        updated_at = garmin.get("_updated_at")
        if updated_at is not None:
            assert isinstance(updated_at, str), (
                f"DatetimeWithNanoseconds leaked into JSON response: "
                f"garmin._updated_at is {type(updated_at).__name__}, not str"
            )


def test_meal_slot_time_not_eating_time():
    """Meal items expose the canonical slot time, never an inferred eating time.

    Covers TIME-03 / T-26-04-03 / CLAUDE.md §6 invariant: HealthKit/Lifesum
    meal timestamps are canonical slot times (08:00/12:00/20:00). /api/today
    must surface the slot label + slot_time identifier only. No field named
    eaten_at or eating_time must appear in any meal dict in the response.
    """
    stubs = _stub_web_server_imports()

    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            # Provide realistic-looking meal data using the canonical slot shape
            # that _today_meals() produces.
            ws._today_calendar = lambda today_iso: {"all_day": [], "timed": []}
            ws._today_garmin = lambda: None
            ws._today_weather = lambda: None
            ws._today_meals = lambda today_iso: [
                {
                    "slot_label": "Breakfast",
                    "slot_time": "08:00",   # canonical slot identifier — NOT eating time
                    "macros": {"kcal": 480, "protein_g": 28, "carbs_g": 55,
                               "fat_g": 14, "fiber_g": 6},
                },
                {
                    "slot_label": "Lunch",
                    "slot_time": "12:00",
                    "macros": {"kcal": 720, "protein_g": 50, "carbs_g": 75,
                               "fat_g": 22, "fiber_g": 9},
                },
                {
                    "slot_label": "Dinner",
                    "slot_time": "20:00",
                    "macros": {"kcal": 600, "protein_g": 40, "carbs_g": 65,
                               "fat_g": 18, "fiber_g": 7},
                },
            ]
            ws._today_training = lambda today_iso: None
            ws._today_nutrition_totals = lambda today_iso: {}
            ws._today_routes = lambda calendar, today_iso: calendar
            ws._today_coach_note = lambda today_iso: None

            client = TestClient(ws.app, raise_server_exceptions=True)
            response = client.get("/api/today")

        assert response.status_code == 200
        data = response.json()
        meals = data.get("meals", [])
        assert len(meals) == 3, f"Expected 3 meals, got {len(meals)}"

        # Every meal must have slot_label (the display label for the canonical slot).
        for i, meal in enumerate(meals):
            assert "slot_label" in meal, f"meal[{i}] missing 'slot_label'"

        # CRITICAL invariant: no field named eaten_at or eating_time (TIME-03 / CLAUDE.md §6).
        # These field names would imply the slot timestamp is an actual eating time — it is NOT.
        forbidden_keys = {"eaten_at", "eating_time"}
        for i, meal in enumerate(meals):
            # Check top-level keys
            found_forbidden = forbidden_keys & set(meal.keys())
            assert not found_forbidden, (
                f"meal[{i}] contains forbidden field(s) {found_forbidden} — "
                "slot timestamps are NOT actual eating times (CLAUDE.md §6 invariant)"
            )
            # Also check nested macros dict
            macros = meal.get("macros") or {}
            found_in_macros = forbidden_keys & set(macros.keys())
            assert not found_in_macros, (
                f"meal[{i}].macros contains forbidden field(s) {found_in_macros}"
            )


def test_unauthenticated_returns_401():
    """GET /api/today without a valid hub session → 401.

    Covers HUB-01 / T-26-04-01: /api/today depends on require_hub_session
    (26-03). A request with no hub_session cookie and CRON_DEV_BYPASS NOT set
    must return HTTPException(status_code=401).
    """
    stubs = _stub_web_server_imports()

    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        # Use the dev-bypass env EXCEPT override CRON_DEV_BYPASS to false
        # so that require_hub_session actually checks for a session cookie.
        env_no_bypass = {**_ENV, "CRON_DEV_BYPASS": "false"}

        with patch.dict(os.environ, env_no_bypass):
            client = TestClient(ws.app, raise_server_exceptions=False)
            # No cookie provided — should 401.
            response = client.get("/api/today")

        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated request, got {response.status_code}: "
            f"{response.text}"
        )


# ------------------------------------------------------------------ #
# Helper-level contract tests — lock the frontend/backend field names #
# at the source (guards against the 26-04/26-07 drift in 26-VERIFICATION.md) #
# ------------------------------------------------------------------ #


def test_today_garmin_maps_to_frontend_contract():
    """_today_garmin maps fetch_garmin_today → the frontend GarminStats keys.

    The frontend reads garmin.sleep / garmin.hrv / garmin.body_battery /
    garmin.resting_hr — NOT sleep_score/hrv_overnight/body_battery_morning.
    """
    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            fake = {
                "sleep_hours": 7.5,
                "hrv_overnight": 55,
                "body_battery_morning": 78,
                "resting_hr": 52,
                "sleep_score": 82,  # extra source fields the frontend never reads
            }
            with patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=fake):
                out = ws._today_garmin()

    assert out == {"sleep": 7.5, "hrv": 55, "body_battery": 78, "resting_hr": 52}


def test_today_routes_computes_iso_leave_by_and_get_ready():
    """_today_routes attaches ISO leave_by + get_ready_at (= leave_by − 45 min).

    The frontend reads event.leave_by / event.get_ready_at as ISO datetimes,
    NOT leave_by_minutes_before (int). Get Ready is 45 min before leaving (USER.md).
    """
    from datetime import datetime, timedelta  # noqa: PLC0415

    stubs = _stub_web_server_imports()
    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            start = "2026-06-15T18:00:00+03:00"
            calendar = {
                "all_day": [],
                "timed": [
                    {
                        "id": "e1",
                        "title": "Gym",
                        "start": start,
                        "end": "2026-06-15T19:00:00+03:00",
                        "location": "Tel Aviv Gym",
                    }
                ],
            }
            with patch(
                "mcp_tools.routes_tool.get_travel_time",
                return_value={"duration_minutes": 30, "summary": "30 min"},
            ):
                out = ws._today_routes(calendar, "2026-06-15")

    ev = out["timed"][0]
    assert "leave_by" in ev and "get_ready_at" in ev
    assert "leave_by_minutes_before" not in ev  # old (broken) contract removed
    leave_by = datetime.fromisoformat(ev["leave_by"])
    get_ready = datetime.fromisoformat(ev["get_ready_at"])
    start_dt = datetime.fromisoformat(start)
    assert leave_by == start_dt - timedelta(minutes=30)
    assert get_ready == leave_by - timedelta(minutes=45)
