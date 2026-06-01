# tests/test_calendar_tool.py
"""Tests for GoogleCalendarManager.create_event calendar routing.

Workout events must be created on the dedicated Training calendar (so the evening
training check-in, which reads only that calendar, can see them), falling back to
the primary calendar when no Training calendar exists. Non-workout events stay on
primary.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import mcp_tools.calendar_tool as cal


def _mgr():
    return cal.GoogleCalendarManager(MagicMock())


def _fake_service(calls):
    """Return a mock Calendar service whose events().insert() records the
    calendarId it was called with."""
    service = MagicMock()

    def _insert(calendarId=None, body=None):
        calls.append({"calendarId": calendarId, "summary": (body or {}).get("summary")})
        chain = MagicMock()
        chain.execute.return_value = {"id": f"evt_{len(calls)}"}
        return chain

    service.events.return_value.insert.side_effect = _insert
    return service


def _window():
    start = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    return start, end


def test_workout_routes_to_training_calendar():
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)), \
         patch.object(m, "get_calendar_id_by_name", return_value="training_cal_id") as gcbn:
        m.create_event("Gym session", start, end, is_workout=True)

    gcbn.assert_called_once_with(m._TRAINING_CALENDAR_NAME)
    # Main event + Get Ready block both land on the Training calendar.
    assert calls, "expected at least the main event insert"
    assert all(c["calendarId"] == "training_cal_id" for c in calls), calls


def test_workout_falls_back_to_primary_without_training_calendar():
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)), \
         patch.object(m, "get_calendar_id_by_name", return_value=None):
        m.create_event("Gym session", start, end, is_workout=True)

    assert calls[0]["calendarId"] == "primary", calls


def test_non_workout_stays_on_primary_and_skips_lookup():
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)), \
         patch.object(m, "get_calendar_id_by_name") as gcbn:
        m.create_event("Team meeting", start, end, is_workout=False)

    assert calls[0]["calendarId"] == "primary", calls
    gcbn.assert_not_called()


def test_bare_practice_detected_as_workout_and_routed():
    """A bare 'Practice' event (auto-detected) routes to the Training calendar."""
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)), \
         patch.object(m, "get_calendar_id_by_name", return_value="training_cal_id"):
        m.create_event("Practice", start, end)  # is_workout auto-detected

    assert calls[0]["calendarId"] == "training_cal_id", calls


def test_practice_substring_does_not_false_positive():
    """'practice' is whole-word matched — 'Practice presentation' is NOT a workout."""
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)), \
         patch.object(m, "get_calendar_id_by_name") as gcbn:
        m.create_event("Practice presentation for work", start, end)

    assert calls[0]["calendarId"] == "primary", calls
    gcbn.assert_not_called()
