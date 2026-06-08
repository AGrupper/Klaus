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


def test_unset_is_workout_defaults_to_non_workout():
    """Training blocks are no longer keyword-detected: an unset is_workout defaults
    to non-workout, so even a 'Gym session' title stays on primary with no lookup
    and no Get Ready block."""
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)), \
         patch.object(m, "get_calendar_id_by_name") as gcbn:
        m.create_event("Gym session", start, end)  # no is_workout passed

    assert len(calls) == 1, "no Get Ready block should be created for a non-workout"
    assert calls[0]["calendarId"] == "primary", calls
    gcbn.assert_not_called()


def test_explicit_workout_creates_get_ready_block():
    """An explicit is_workout=True still creates a Get Ready prep block (regardless
    of the title), routed to the Training calendar."""
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)), \
         patch.object(m, "get_calendar_id_by_name", return_value="training_cal_id"):
        result = m.create_event("Leg Day", start, end, is_workout=True)

    # Main event + Get Ready block.
    assert len(calls) == 2, calls
    assert {c["summary"] for c in calls} == {"Leg Day", "Get Ready: Leg Day"}
    assert "get_ready_event_id" in result


def test_get_ready_summary_never_treated_as_workout():
    """The Get Ready guard holds even if a caller passes is_workout=True for a
    'Get Ready:' event — it stays on primary with no nested prep block."""
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)), \
         patch.object(m, "get_calendar_id_by_name") as gcbn:
        m.create_event("Get Ready: Run", start, end, is_workout=True)

    assert len(calls) == 1, "no nested Get Ready block"
    assert calls[0]["calendarId"] == "primary", calls
    gcbn.assert_not_called()
