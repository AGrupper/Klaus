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

from googleapiclient.errors import HttpError

import mcp_tools.calendar_tool as cal


def _mgr():
    return cal.GoogleCalendarManager(MagicMock())


def _http_error(status: int) -> HttpError:
    """Build an HttpError carrying the given HTTP status."""
    resp = MagicMock()
    resp.status = status
    return HttpError(resp=resp, content=b"{}")


def _chain(result):
    """Return a mock request object whose .execute() yields result (or raises)."""
    c = MagicMock()
    if isinstance(result, Exception):
        c.execute.side_effect = result
    else:
        c.execute.return_value = result
    return c


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


# --------------------------------------------------------------------------- #
# list_writable_calendars                                                      #
# --------------------------------------------------------------------------- #

def test_list_writable_calendars_filters_by_access_role():
    """Only owner/writer calendars are returned; reader/freeBusyReader excluded.
    Verifies pagination is followed across pages."""
    m = _mgr()
    service = MagicMock()
    page1 = {
        "items": [
            {"id": "primary", "summary": "Amit", "primary": True, "accessRole": "owner"},
            {"id": "holidays", "summary": "Holidays", "accessRole": "reader"},
        ],
        "nextPageToken": "tok",
    }
    page2 = {
        "items": [
            {"id": "training_cal_id", "summary": "Training", "accessRole": "writer"},
            {"id": "shared_ro", "summary": "Shared RO", "accessRole": "freeBusyReader"},
        ],
    }
    service.calendarList.return_value.list.side_effect = [_chain(page1), _chain(page2)]

    with patch.object(m, "_get_service", return_value=service):
        cals = m.list_writable_calendars()

    ids = [c["id"] for c in cals]
    assert ids == ["primary", "training_cal_id"], cals
    assert cals[0]["primary"] is True
    assert cals[1]["access_role"] == "writer"


# --------------------------------------------------------------------------- #
# list_all_events                                                              #
# --------------------------------------------------------------------------- #

def test_list_all_events_merges_and_tags_calendar_id():
    """Events from every writable calendar are merged, sorted by start, and each
    tagged with its calendar name and real calendar_id."""
    m = _mgr()
    service = MagicMock()

    def _list(calendarId=None, **kwargs):
        if calendarId == "primary":
            return _chain({"items": [
                {"id": "p1", "summary": "Standup", "start": {"dateTime": "2026-07-01T09:00:00+03:00"}, "end": {}},
            ]})
        if calendarId == "training_cal_id":
            return _chain({"items": [
                {"id": "t1", "summary": "Leg Day", "start": {"dateTime": "2026-07-01T07:00:00+03:00"}, "end": {}},
            ]})
        return _chain({"items": []})

    service.events.return_value.list.side_effect = _list

    writable = [
        {"id": "primary", "summary": "Amit", "primary": True, "access_role": "owner"},
        {"id": "training_cal_id", "summary": "Training", "primary": False, "access_role": "writer"},
    ]
    with patch.object(m, "_get_service", return_value=service), \
         patch.object(m, "list_writable_calendars", return_value=writable):
        events = m.list_all_events("2026-07-01T00:00:00+03:00", "2026-07-02T00:00:00+03:00")

    # Sorted by start → training (07:00) before standup (09:00).
    assert [e["id"] for e in events] == ["t1", "p1"], events
    assert events[0]["calendar"] == "Training"
    assert events[0]["calendar_id"] == "training_cal_id"
    assert events[1]["calendar_id"] == "primary"


# --------------------------------------------------------------------------- #
# delete_event                                                                 #
# --------------------------------------------------------------------------- #

def test_delete_event_uses_given_calendar_id():
    m = _mgr()
    service = MagicMock()
    seen: dict = {}

    def _delete(calendarId=None, eventId=None):
        seen["calendarId"] = calendarId
        return _chain({})

    service.events.return_value.delete.side_effect = _delete
    with patch.object(m, "_get_service", return_value=service):
        result = m.delete_event("evt1", calendar_id="training_cal_id")

    assert result["ok"] is True
    assert seen["calendarId"] == "training_cal_id"


def test_delete_event_falls_back_to_search_on_404():
    """When the assumed calendar 404s, delete searches writable calendars and
    retries on the one that actually holds the event."""
    m = _mgr()
    service = MagicMock()
    delete_calls: list = []

    def _delete(calendarId=None, eventId=None):
        delete_calls.append(calendarId)
        if calendarId == "primary":
            return _chain(_http_error(404))
        return _chain({})

    def _get(calendarId=None, eventId=None):
        if calendarId == "training_cal_id":
            return _chain({"id": eventId})
        return _chain(_http_error(404))

    service.events.return_value.delete.side_effect = _delete
    service.events.return_value.get.side_effect = _get

    writable = [
        {"id": "primary", "summary": "Amit", "primary": True, "access_role": "owner"},
        {"id": "training_cal_id", "summary": "Training", "primary": False, "access_role": "writer"},
    ]
    with patch.object(m, "_get_service", return_value=service), \
         patch.object(m, "list_writable_calendars", return_value=writable):
        result = m.delete_event("evt1")  # no calendar_id → defaults to primary

    assert result["ok"] is True, result
    assert delete_calls == ["primary", "training_cal_id"], delete_calls


def test_delete_event_410_is_success():
    m = _mgr()
    service = MagicMock()
    service.events.return_value.delete.side_effect = lambda calendarId=None, eventId=None: _chain(_http_error(410))
    with patch.object(m, "_get_service", return_value=service):
        result = m.delete_event("evt1", calendar_id="primary")
    assert result["ok"] is True
    assert "already deleted" in result["confirmation"]


# --------------------------------------------------------------------------- #
# update_event                                                                 #
# --------------------------------------------------------------------------- #

def test_update_event_patches_only_given_fields():
    m = _mgr()
    service = MagicMock()
    seen: dict = {}

    def _patch(calendarId=None, eventId=None, body=None):
        seen["calendarId"] = calendarId
        seen["body"] = body
        return _chain({"id": eventId})

    service.events.return_value.patch.side_effect = _patch
    with patch.object(m, "_get_service", return_value=service):
        result = m.update_event(
            "evt1",
            calendar_id="training_cal_id",
            start_iso="2026-07-01T08:00:00+03:00",
            end_iso="2026-07-01T09:00:00+03:00",
        )

    assert result["ok"] is True
    assert seen["calendarId"] == "training_cal_id"
    # Only start/end were sent — no summary/description keys.
    assert set(seen["body"]) == {"start", "end"}, seen["body"]
    assert seen["body"]["start"]["dateTime"] == "2026-07-01T08:00:00+03:00"


def test_update_event_no_fields_is_rejected():
    m = _mgr()
    with patch.object(m, "_get_service", return_value=MagicMock()):
        result = m.update_event("evt1", calendar_id="primary")
    assert result["ok"] is False
    assert "No fields" in result["error"]


def test_update_event_falls_back_on_404():
    m = _mgr()
    service = MagicMock()
    patch_calls: list = []

    def _patch(calendarId=None, eventId=None, body=None):
        patch_calls.append(calendarId)
        if calendarId == "primary":
            return _chain(_http_error(404))
        return _chain({"id": eventId})

    def _get(calendarId=None, eventId=None):
        if calendarId == "training_cal_id":
            return _chain({"id": eventId})
        return _chain(_http_error(404))

    service.events.return_value.patch.side_effect = _patch
    service.events.return_value.get.side_effect = _get
    writable = [
        {"id": "primary", "summary": "Amit", "primary": True, "access_role": "owner"},
        {"id": "training_cal_id", "summary": "Training", "primary": False, "access_role": "writer"},
    ]
    with patch.object(m, "_get_service", return_value=service), \
         patch.object(m, "list_writable_calendars", return_value=writable):
        result = m.update_event("evt1", summary="New title")

    assert result["ok"] is True, result
    assert patch_calls == ["primary", "training_cal_id"], patch_calls


# --------------------------------------------------------------------------- #
# is_free across all writable calendars                                        #
# --------------------------------------------------------------------------- #

def test_is_free_busy_if_any_calendar_busy():
    """A workout on the Training calendar makes the slot busy even though primary
    is free."""
    m = _mgr()
    service = MagicMock()
    fb_body: dict = {}

    def _query(body=None):
        fb_body.update(body or {})
        return _chain({"calendars": {
            "primary": {"busy": []},
            "training_cal_id": {"busy": [{"start": "x", "end": "y"}]},
        }})

    service.freebusy.return_value.query.side_effect = _query
    writable = [
        {"id": "primary", "summary": "Amit", "primary": True, "access_role": "owner"},
        {"id": "training_cal_id", "summary": "Training", "primary": False, "access_role": "writer"},
    ]
    with patch.object(m, "_get_service", return_value=service), \
         patch.object(m, "list_writable_calendars", return_value=writable), \
         patch.object(m, "list_all_events", return_value=[{"summary": "Leg Day"}]):
        result = m.is_free("2026-07-01T07:00:00+03:00", "2026-07-01T08:00:00+03:00")

    assert result["is_free"] is False
    assert result["conflicting_event"] == "Leg Day"
    # Both calendars were queried.
    assert {i["id"] for i in fb_body["items"]} == {"primary", "training_cal_id"}
