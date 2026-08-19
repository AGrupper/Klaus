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
    "KLAUS_USER_ID": "123456",
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
        "core.auth.google": MagicMock(name="core.auth.google"),
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


def test_today_calendar_uses_the_process_shared_calendar_client():
    """Repeated snapshots use the shared Calendar client and its in-memory token."""
    stubs = _stub_web_server_imports()
    shared_calendar = MagicMock()
    shared_calendar.list_all_events.return_value = [
        {
            "id": "event-1",
            "summary": "Static OAuth design review",
            "start": "2026-08-14T15:00:00+03:00",
            "end": "2026-08-14T15:30:00+03:00",
            "location": "",
            "calendar": "primary",
        }
    ]
    shared_tools = MagicMock(name="core.tools")
    shared_tools._get_calendar_tool.return_value = shared_calendar
    stubs["core.tools"] = shared_tools

    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from interfaces.routes import hub_today
        first = hub_today._today_calendar("2026-08-14")
        second = hub_today._today_calendar("2026-08-14")

    expected = {
        "all_day": [],
        "timed": [
            {
                "id": "event-1",
                "title": "Static OAuth design review",
                "start": "2026-08-14T15:00:00+03:00",
                "end": "2026-08-14T15:30:00+03:00",
                "calendar": "primary",
            }
        ],
    }
    assert first == expected
    assert second == expected


def test_today_calendar_reads_secondary_calendars_not_just_primary():
    """Events on a non-primary calendar must reach the snapshot.

    Regression: this read used list_events (primary only) while every training
    session lives on a separate "Training" calendar. The Hub therefore showed an
    empty day, and because core.routines.alerts reads this same snapshot,
    conflict and leave-by pushes could never fire for a workout. Verified live on
    2026-08-16: three real events, snapshot returned zero. Claude masked it by
    reaching the calendar through list_all_events instead.
    """
    stubs = _stub_web_server_imports()
    shared_calendar = MagicMock()
    shared_calendar._list_primary_events.side_effect = AssertionError(
        "the primary-only fallback must not be used for the Hub snapshot"
    )
    shared_calendar.list_all_events.return_value = [
        {
            "id": "run-1",
            "summary": "Easy Run (Treadmill)",
            "start": "2026-08-16T10:00:00+03:00",
            "end": "2026-08-16T10:45:00+03:00",
            "location": "",
            "calendar": "Training",
        }
    ]
    shared_tools = MagicMock(name="core.tools")
    shared_tools._get_calendar_tool.return_value = shared_calendar
    stubs["core.tools"] = shared_tools

    with patch.dict(sys.modules, stubs):
        import interfaces.web_server as ws  # noqa: PLC0415
        from interfaces.routes import hub_today

        out = hub_today._today_calendar("2026-08-16")

    assert len(out["timed"]) == 1, "secondary-calendar event was dropped"
    assert out["timed"][0]["title"] == "Easy Run (Treadmill)"
    assert out["timed"][0]["calendar"] == "Training"


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
        from interfaces.routes import hub_today
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            # Monkeypatch the 8 per-source helpers so no real I/O occurs.
            hub_today._today_calendar = lambda today_iso: {"all_day": [], "timed": []}
            hub_today._today_garmin = lambda: {"sleep": 7.5, "hrv": 55,
                                        "body_battery": 78, "resting_hr": 52}
            hub_today._today_weather = lambda: "Sunny, 28°C, H 31°/L 22°"
            hub_today._today_meals = lambda today_iso: [
                {"slot_label": "Breakfast", "slot_time": "08:00",
                 "macros": {"kcal": 500, "protein_g": 30, "carbs_g": 60,
                            "fat_g": 15, "fiber_g": 5}}
            ]
            hub_today._today_training = lambda today_iso: {
                "item": "Upper Body A",
                "block_context": "Week 1 of 16 — Upper Body A",
                "block_label": "Aerobic Base",
                "week_num": 1,
                "split_name": "Upper Body A",
                "benchmark_due": False,
            }
            hub_today._today_nutrition_totals = lambda today_iso: {
                "kcal": 1800, "protein_g": 140, "carbs_g": 200,
                "fat_g": 60, "fiber_g": 25,
            }
            hub_today._today_departure_windows = lambda calendar: calendar
            hub_today._today_coach_note = lambda today_iso: "Hit protein target today — +15g above yesterday."

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
        from interfaces.routes import hub_today
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            # Inject DatetimeWithNanoseconds-like object into the garmin response
            # (simulates Firestore SERVER_TIMESTAMP read-back before _jsonsafe_doc).
            hub_today._today_calendar = lambda today_iso: {"all_day": [], "timed": []}
            hub_today._today_garmin = lambda: {
                "sleep": 7.0,
                "hrv": 50,
                "body_battery": 75,
                "resting_hr": 55,
                # Simulate a stray DatetimeWithNanoseconds that slipped through
                "_updated_at": _FakeDatetimeWithNanoseconds(),
            }
            hub_today._today_weather = lambda: "Partly cloudy, 26°C"
            hub_today._today_meals = lambda today_iso: [{
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
            hub_today._today_training = lambda today_iso: None
            hub_today._today_nutrition_totals = lambda today_iso: {}
            hub_today._today_departure_windows = lambda calendar: calendar
            hub_today._today_coach_note = lambda today_iso: None

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
        from interfaces.routes import hub_today
        from fastapi.testclient import TestClient  # noqa: PLC0415

        with patch.dict(os.environ, _ENV):
            # Provide realistic-looking meal data using the canonical slot shape
            # that _today_meals() produces.
            hub_today._today_calendar = lambda today_iso: {"all_day": [], "timed": []}
            hub_today._today_garmin = lambda: None
            hub_today._today_weather = lambda: None
            hub_today._today_meals = lambda today_iso: [
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
            hub_today._today_training = lambda today_iso: None
            hub_today._today_nutrition_totals = lambda today_iso: {}
            hub_today._today_departure_windows = lambda calendar: calendar
            hub_today._today_coach_note = lambda today_iso: None

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
        from interfaces.routes import hub_today
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
        from interfaces.routes import hub_today

        with patch.dict(os.environ, _ENV):
            fake = {
                "sleep_hours": 7.5,
                "hrv_overnight": 55,
                "body_battery_morning": 78,
                "resting_hr": 52,
                "sleep_score": 82,  # extra source fields the frontend never reads
            }
            with patch("mcp_tools.garmin_tool.fetch_garmin_today", return_value=fake):
                out = hub_today._today_garmin()

    assert out == {"sleep": 7.5, "hrv": 55, "body_battery": 78, "resting_hr": 52}


def _located_calendar(start="2026-06-15T18:00:00+03:00"):
    """One located timed event — the only shape that earns a departure window."""
    return {
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


def _departure_windows(calendar, env_extra=None):
    """Run _today_departure_windows with web_server's imports stubbed out."""
    with patch.dict(sys.modules, _stub_web_server_imports()):
        import interfaces.web_server as ws  # noqa: PLC0415
        from interfaces.routes import hub_today

        with patch.dict(os.environ, {**_ENV, **(env_extra or {})}):
            return hub_today._today_departure_windows(calendar)


def test_departure_windows_use_the_configured_travel_time():
    """leave_by = start − configured travel; get_ready_at = leave_by − 45 min.

    The frontend reads event.leave_by / event.get_ready_at as ISO datetimes,
    NOT leave_by_minutes_before (int). Get Ready is 45 min before leaving
    (USER.md). This contract outlived the Google Routes API that used to
    produce the travel number.
    """
    from datetime import datetime, timedelta  # noqa: PLC0415

    start = "2026-06-15T18:00:00+03:00"
    out = _departure_windows(
        _located_calendar(start), {"KLAUS_TRAVEL_MINUTES_DEFAULT": "30"}
    )

    ev = out["timed"][0]
    assert "leave_by" in ev and "get_ready_at" in ev
    assert "leave_by_minutes_before" not in ev  # old (broken) contract removed
    leave_by = datetime.fromisoformat(ev["leave_by"])
    get_ready = datetime.fromisoformat(ev["get_ready_at"])
    assert leave_by == datetime.fromisoformat(start) - timedelta(minutes=30)
    assert get_ready == leave_by - timedelta(minutes=45)


def test_departure_windows_fall_back_to_the_default_travel_time():
    """An unset override still produces leave_by — the alert depends on it."""
    from datetime import datetime, timedelta  # noqa: PLC0415

    start = "2026-06-15T18:00:00+03:00"
    out = _departure_windows(_located_calendar(start), {"KLAUS_TRAVEL_MINUTES_DEFAULT": ""})

    leave_by = datetime.fromisoformat(out["timed"][0]["leave_by"])
    assert leave_by == datetime.fromisoformat(start) - timedelta(minutes=15)


def test_departure_windows_survive_a_malformed_travel_override():
    """A bad env value must not strip leave_by from the whole day.

    leave_by is what core.routines.alerts fires the "leave now" push on,
    and that path has no LLM fallback — losing it fails silently.
    """
    from datetime import datetime, timedelta  # noqa: PLC0415

    start = "2026-06-15T18:00:00+03:00"
    for bad in ("not-a-number", "-5"):
        out = _departure_windows(
            _located_calendar(start), {"KLAUS_TRAVEL_MINUTES_DEFAULT": bad}
        )
        leave_by = datetime.fromisoformat(out["timed"][0]["leave_by"])
        assert leave_by == datetime.fromisoformat(start) - timedelta(minutes=15), bad


def test_departure_windows_skip_events_without_a_location():
    """No location means no journey, so no leave_by and no Get Ready block."""
    calendar = {
        "all_day": [],
        "timed": [{
            "id": "no-location",
            "title": "Call",
            "start": "2026-06-15T18:00:00+03:00",
            "end": "2026-06-15T19:00:00+03:00",
        }],
    }
    out = _departure_windows(calendar)

    assert out is calendar
    assert "leave_by" not in out["timed"][0]
    assert "get_ready_at" not in out["timed"][0]


def test_departure_window_actually_fires_the_deterministic_leave_now_push():
    """End-to-end seam: the field this computes is the field the alert reads.

    These two halves live in different modules and could drift on field name or
    timestamp format with every unit test still green. The push has no LLM
    fallback, so drift here fails silently — the user simply stops being told
    to leave. Feed the real producer's output to the real consumer.
    """
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    from core.routines.alerts import evaluate_daytime_rules  # noqa: PLC0415

    tz = ZoneInfo("Asia/Jerusalem")
    # Departure is 15 min before an 18:00 event, so 17:45. "Now" is 17:50:
    # leave_by has passed but the event has not started — the alert window.
    calendar = _departure_windows(_located_calendar("2026-06-15T18:00:00+03:00"))
    now = datetime(2026, 6, 15, 17, 50, tzinfo=tz)

    alerts = evaluate_daytime_rules(
        {"tasks": [], "habits_pending": [], "today": {"calendar": calendar}},
        [],
        [],
        now=now,
    )

    travel = [a for a in alerts if a["kind"] == "travel_conflict"]
    assert travel, f"no travel_conflict raised from {calendar['timed'][0]}"
    assert "Gym" in travel[0]["text"]


def test_departure_windows_skip_an_unparseable_start_without_losing_the_day():
    """One bad event must not prevent the rest of the calendar rendering."""
    calendar = {
        "all_day": [],
        "timed": [
            {"id": "bad", "title": "Broken", "start": "not-a-date",
             "end": "", "location": "Jaffa"},
            {"id": "good", "title": "Gym", "start": "2026-06-15T18:00:00+03:00",
             "end": "2026-06-15T19:00:00+03:00", "location": "Tel Aviv Gym"},
        ],
    }
    out = _departure_windows(calendar)

    assert "leave_by" not in out["timed"][0]
    assert "leave_by" in out["timed"][1]


def test_sanitize_coach_note_strips_controls_and_markdown_header():
    """_sanitize_coach_note strips bidi/format control chars + a leading # (CR-04)."""
    # A pure string function: call it where it is defined rather than through a
    # route module that has no reason to import it.
    from core.hub.today import _sanitize_coach_note

    # "## " markdown header + LRM (U+200E) + RLM (U+200F) format controls.
    raw = "## ‎Hit your protein target‏ today"
    out = _sanitize_coach_note(raw)

    assert out == "Hit your protein target today"
    assert "‎" not in out and "‏" not in out
    assert not out.startswith("#")
    # Length is clamped.
    assert len(_sanitize_coach_note("x" * 1000)) <= 280


# ------------------------------------------------------------------ #
# Coach note derivation (restored after the 2026-08-11 cutover)      #
# ------------------------------------------------------------------ #

def test_derive_coach_note_takes_first_non_empty_line():
    """The note is the review's opening line, sanitized and clamped.

    Regression guard for the cutover to Claude Routines, which left `daily_note`
    with no writer at all: config/self_state kept an 8-day-old daily_note_date,
    the /api/today date gate returned None every day, and the Hub showed its
    placeholder permanently.
    """
    from core.hub.today import derive_coach_note

    review = (
        "\n"
        "   \n"
        "## **Morning, Sir.** Wednesday's split stands untouched.\n"
        "Recovery: 6.5h sleep, HRV at baseline.\n"
    )

    assert derive_coach_note(review) == (
        "Morning, Sir. Wednesday's split stands untouched."
    )


def test_derive_coach_note_returns_empty_when_nothing_usable():
    """No usable line → "" so callers skip the write instead of storing a blank."""
    from core.hub.today import derive_coach_note

    assert derive_coach_note("") == ""
    assert derive_coach_note("\n\n   \n") == ""
    assert derive_coach_note(None) == ""
    # A line that sanitizes away to nothing must not become the note.
    assert derive_coach_note("###\n**Real line**") == "Real line"


def test_coach_note_and_timestamp_are_gated_on_today():
    """A note from a previous day is not served, and neither is its timestamp.

    Both reads share the same date gate — a stale timestamp must never outlive
    the note it describes.
    """
    from core.hub import today as hub_today

    state = {
        "daily_note": "Morning, Sir.",
        "daily_note_date": "2026-08-11",
        "daily_note_at": "2026-08-11T04:40:00+00:00",
    }
    with patch.object(hub_today, "_read_self_state", return_value=state):
        assert hub_today._today_coach_note("2026-08-19") is None
        assert hub_today._today_coach_note_at("2026-08-19") is None

        assert hub_today._today_coach_note("2026-08-11") == "Morning, Sir."
        assert hub_today._today_coach_note_at("2026-08-11") == "2026-08-11T04:40:00+00:00"


def test_coach_note_timestamp_absent_when_never_stamped():
    """A note written before daily_note_at existed still renders, unstamped."""
    from core.hub import today as hub_today

    state = {"daily_note": "Morning, Sir.", "daily_note_date": "2026-08-19"}
    with patch.object(hub_today, "_read_self_state", return_value=state):
        assert hub_today._today_coach_note("2026-08-19") == "Morning, Sir."
        assert hub_today._today_coach_note_at("2026-08-19") is None


# ------------------------------------------------------------------ #
# Garmin write-through + stored fallback                             #
# ------------------------------------------------------------------ #

def test_today_garmin_falls_back_to_stored_biometrics():
    """A failed live Garmin read serves the stored row instead of blanking.

    Without this the Hub shows "Sleep stats syncing…" all day on a rate limit,
    even though the 05:30 cron already has the numbers.
    """
    from core.hub import today as hub_today

    stored_row = {
        "date": "2026-08-19",
        "resting_hr": 48,
        "hrv_overnight": 107,
        "sleep_duration": 6.5,
        "body_battery_max": 63,
    }
    with patch.dict(sys.modules, {"mcp_tools.garmin_tool": MagicMock()}):
        sys.modules["mcp_tools.garmin_tool"].fetch_garmin_today.side_effect = (
            RuntimeError("garmin rate limited")
        )
        with patch(
            "core.health_reads.fetch_biometric_range", return_value=[stored_row]
        ):
            out = hub_today._today_garmin()

    assert out is not None
    assert out["sleep"] == 6.5
    assert out["hrv"] == 107
    assert out["resting_hr"] == 48
    # body_battery_max is the day's peak, not the morning read — flagged so the
    # client can say the numbers are stored rather than live.
    assert out["body_battery"] == 63
    assert out["stored"] is True


def test_today_garmin_returns_none_when_neither_source_has_data():
    """Live failure + empty stored row still yields the D-06 placeholder."""
    from core.hub import today as hub_today

    with patch.dict(sys.modules, {"mcp_tools.garmin_tool": MagicMock()}):
        sys.modules["mcp_tools.garmin_tool"].fetch_garmin_today.side_effect = (
            RuntimeError("garmin down")
        )
        with patch("core.health_reads.fetch_biometric_range", return_value=[]):
            assert hub_today._today_garmin() is None


def test_persist_garmin_snapshot_writes_once_per_interval():
    """The write-through is bounded so it cannot fire once per request.

    /api/today runs on every Hub refresh AND every ten-minute alert tick; an
    ungated write would open a Postgres connection each time.
    """
    from core.hub import today as hub_today

    data = {"date": "2026-08-19", "sleep_hours": 6.5, "hrv_overnight": 107,
            "resting_hr": 48, "body_battery_morning": 63}

    writer = MagicMock()
    hub_today._biometric_write_through_seen.clear()
    with patch.dict(sys.modules, {"mcp_tools.garmin_tool": MagicMock()}):
        sys.modules["mcp_tools.garmin_tool"].write_biometrics_to_postgres = writer
        hub_today._persist_garmin_snapshot(data)
        hub_today._persist_garmin_snapshot(data)
        hub_today._persist_garmin_snapshot(data)
    hub_today._biometric_write_through_seen.clear()

    assert writer.call_count == 1
    # The FULL dict is persisted — the narrowed four Hub fields would drop
    # sleep_score, hrv_baseline, training_readiness and vo2_max.
    assert writer.call_args[0][0] is data


def test_persist_garmin_snapshot_skips_an_empty_day():
    """A watch-off day writes nothing — an all-NULL row would mask the gap."""
    from core.hub import today as hub_today

    writer = MagicMock()
    hub_today._biometric_write_through_seen.clear()
    with patch.dict(sys.modules, {"mcp_tools.garmin_tool": MagicMock()}):
        sys.modules["mcp_tools.garmin_tool"].write_biometrics_to_postgres = writer
        hub_today._persist_garmin_snapshot({
            "date": "2026-08-19", "sleep_hours": None, "hrv_overnight": None,
            "resting_hr": None, "body_battery_morning": None,
        })
        hub_today._persist_garmin_snapshot({"sleep_hours": 6.5})  # no date
    hub_today._biometric_write_through_seen.clear()

    assert writer.call_count == 0


# ------------------------------------------------------------------ #
# Weather last-good fallback                                         #
# ------------------------------------------------------------------ #

def test_today_weather_serves_last_good_reading_on_failure():
    """wttr.in fails several times an hour; a stale line beats a bare "—"."""
    from core.hub import today as hub_today

    payload = {
        "current": {"condition": "Sunny", "temp_c": 30},
        "today": {"max_c": 32, "min_c": 24, "rain_chance": 0},
    }
    hub_today._weather_last_good = None
    with patch.dict(sys.modules, {"mcp_tools.weather_tool": MagicMock()}):
        weather = sys.modules["mcp_tools.weather_tool"]
        weather.fetch_weather.return_value = payload
        first = hub_today._today_weather()

        weather.fetch_weather.side_effect = RuntimeError("wttr.in read timed out")
        second = hub_today._today_weather()
    hub_today._weather_last_good = None

    assert first == "Sunny, 30°C, H 32°/L 24°"
    assert second == first


def test_today_weather_returns_none_with_no_cached_reading():
    """A failure with nothing cached still degrades to None (client shows "—")."""
    from core.hub import today as hub_today

    hub_today._weather_last_good = None
    with patch.dict(sys.modules, {"mcp_tools.weather_tool": MagicMock()}):
        sys.modules["mcp_tools.weather_tool"].fetch_weather.side_effect = (
            RuntimeError("wttr.in 500")
        )
        assert hub_today._today_weather() is None


def test_derive_coach_note_trims_on_a_sentence_boundary():
    """A long opening paragraph is cut at a sentence end, not mid-word.

    The Claude Routines morning review opens with a full paragraph rather than
    the one-liner the retired cascade produced, so a bare 280-char slice ended
    real notes like "Nothing overnight changed t".
    """
    from core.hub.today import _COACH_NOTE_MAX_LEN, derive_coach_note

    note = derive_coach_note(
        "Morning, Sir. Wednesday's split stands untouched — Track Workout at "
        "08:15, and Heavy Lower Body Gym at 17:00, both still carrying their "
        "Get Ready and travel buffers. " + "Filler that runs past the limit. " * 8
    )

    assert len(note) <= _COACH_NOTE_MAX_LEN
    assert note.endswith(".")
    assert "…" not in note


def test_derive_coach_note_falls_back_to_a_word_boundary():
    """With no sentence end in range, cut at a whole word and mark it elided."""
    from core.hub.today import _COACH_NOTE_MAX_LEN, derive_coach_note

    note = derive_coach_note("alpha bravo charlie delta " * 40)

    assert len(note) <= _COACH_NOTE_MAX_LEN + 1  # the ellipsis
    assert note.endswith("…")
    # Never a partial word before the ellipsis.
    assert note[:-1].split()[-1] in {"alpha", "bravo", "charlie", "delta"}


def test_short_notes_are_left_exactly_as_written():
    """The common case — a note under the limit — is untouched."""
    from core.hub.today import derive_coach_note

    assert derive_coach_note("Morning, Sir. Easy day.") == "Morning, Sir. Easy day."
