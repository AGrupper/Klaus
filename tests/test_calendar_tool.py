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
        calls.append({
            "calendarId": calendarId,
            "summary": (body or {}).get("summary"),
            "body": body or {},
        })
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


def test_created_events_are_marked_as_klaus_owned():
    calls: list = []
    m = _mgr()
    start, end = _window()
    with patch.object(m, "_get_service", return_value=_fake_service(calls)):
        m.create_event("Deep work", start, end)

    assert calls[0]["body"]["extendedProperties"]["private"]["klaus_owned"] == "true"


def test_is_klaus_owned_reads_private_extended_property():
    m = _mgr()
    service = MagicMock()
    service.events.return_value.get.return_value = _chain({
        "id": "evt1",
        "extendedProperties": {"private": {"klaus_owned": "true"}},
    })
    with patch.object(m, "_get_service", return_value=service):
        assert m.is_klaus_owned("evt1", "primary") is True


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


# ---------------------------------------------------------------------------
# Timeout degradation — production fix for recurring
# `TimeoutError: The read operation timed out` calendar-gather failures
# (2026-08-01..03). Every read/write method must degrade to its documented
# error sentinel rather than let the raw socket-level exception propagate.
# ---------------------------------------------------------------------------

def test_list_primary_events_degrades_gracefully_on_timeout_error():
    """A raw TimeoutError (not an HttpError — the socket read itself stalled)
    must be caught and degrade to [] like any other API error, not propagate
    up and crash the caller (core/autonomous.py's gather layer, or a direct
    brain tool call)."""
    m = _mgr()
    service = MagicMock()
    service.events.return_value.list.return_value = _chain(TimeoutError("The read operation timed out"))
    with patch.object(m, "_get_service", return_value=service):
        result = m._list_primary_events("2026-07-01T00:00:00+03:00", "2026-07-02T00:00:00+03:00")
    assert result == []


def test_list_primary_events_passes_bounded_num_retries():
    """A single bounded retry (not unbounded) is requested on the read call."""
    m = _mgr()
    service = MagicMock()
    chain = _chain({"items": []})
    service.events.return_value.list.return_value = chain
    with patch.object(m, "_get_service", return_value=service):
        m._list_primary_events("2026-07-01T00:00:00+03:00", "2026-07-02T00:00:00+03:00")
    chain.execute.assert_called_once_with(num_retries=1)


def test_is_free_degrades_gracefully_on_ssl_timeout():
    """ssl.SSLError (a socket-level failure, subclass of OSError) must also
    be caught — not just the base TimeoutError."""
    import ssl

    m = _mgr()
    service = MagicMock()
    service.freebusy.return_value.query.return_value = _chain(
        ssl.SSLError("record layer failure")
    )
    with patch.object(m, "_get_service", return_value=service), \
         patch.object(m, "list_writable_calendars", return_value=[]):
        result = m.is_free("2026-07-01T07:00:00+03:00", "2026-07-01T08:00:00+03:00")
    assert result["is_free"] is False
    assert "error" in result


def test_delete_event_degrades_gracefully_on_timeout_error():
    """A write path (delete) must also fail soft on a socket timeout —
    returning {"ok": False, ...} rather than raising."""
    m = _mgr()
    service = MagicMock()
    service.events.return_value.delete.return_value = _chain(
        TimeoutError("The read operation timed out")
    )
    with patch.object(m, "_get_service", return_value=service):
        result = m.delete_event("evt_1", calendar_id="primary")
    assert result["ok"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# Buffer planning — Amit's scheduling rule (docs/USER.md "scheduling-rules")
# as a pure function. Before this was extracted from create_event, the only way
# to check the rule was to mock the whole Google service and read the event
# bodies back out, so the arithmetic itself was never asserted directly.
# ---------------------------------------------------------------------------

class TestPlanBufferBlocks:
    """No network, no clock — just the rule."""

    START = "2026-08-20T14:00:00+03:00"
    END = "2026-08-20T15:15:00+03:00"

    def _plan(self, travel: int, is_workout: bool):
        return cal.GoogleCalendarManager._plan_buffer_blocks(
            "Leg Day", self.START, self.END, travel, is_workout
        )

    def test_plain_event_with_no_travel_is_left_alone(self):
        plan = self._plan(travel=0, is_workout=False)

        assert plan["start"] == datetime.fromisoformat(self.START)
        assert plan["end"] == datetime.fromisoformat(self.END)
        assert plan["get_ready"] is None
        assert plan["buffers"] == []

    def test_travel_extends_the_window_on_both_sides(self):
        plan = self._plan(travel=15, is_workout=False)

        assert plan["start"] == datetime.fromisoformat("2026-08-20T13:45:00+03:00")
        assert plan["end"] == datetime.fromisoformat("2026-08-20T15:30:00+03:00")
        # One block before, one after — 30 minutes of buffer in total.
        kinds = [b["kind"] for b in plan["buffers"]]
        assert kinds == ["travel", "travel"]
        assert all(b["minutes"] == 15 for b in plan["buffers"])

    def test_workout_gets_a_get_ready_block_before_the_travel(self):
        """USER.md: Get Ready at T-60, travel at T-15, session at T-0."""
        plan = self._plan(travel=15, is_workout=True)

        get_ready = plan["get_ready"]
        assert get_ready is not None
        assert get_ready["summary"] == "Get Ready: Leg Day"
        # 45 min of prep ending where the 15 min of travel begins: 60 before the
        # session itself, exactly as the rule states.
        assert get_ready["start"] == datetime.fromisoformat("2026-08-20T13:00:00+03:00")
        assert get_ready["end"] == datetime.fromisoformat("2026-08-20T13:45:00+03:00")
        assert get_ready["end"] == plan["start"], "prep must not overlap travel"

    def test_get_ready_and_travel_never_overlap_without_travel(self):
        plan = self._plan(travel=0, is_workout=True)

        assert plan["get_ready"]["end"] == datetime.fromisoformat(self.START)
        assert [b["kind"] for b in plan["buffers"]] == ["get_ready"]

    def test_buffers_are_json_safe_for_the_tool_payload(self):
        """Claude phrases the confirmation, so the blocks ship as data."""
        import json

        plan = self._plan(travel=15, is_workout=True)
        assert json.loads(json.dumps(plan["buffers"])) == plan["buffers"]


class TestWorkoutClassification:
    """A Get Ready block must never be treated as a workout (recursion guard)."""

    def test_unset_flag_never_guesses_from_the_title(self):
        assert cal.GoogleCalendarManager._is_workout_event("Gym session", None) is False

    def test_get_ready_block_is_not_itself_a_workout(self):
        assert cal.GoogleCalendarManager._is_workout_event("Get Ready: Leg Day", True) is False

    def test_explicit_workout_is_honoured(self):
        assert cal.GoogleCalendarManager._is_workout_event("Leg Day", True) is True


class TestResolveTravelMinutes:
    def test_workouts_default_to_the_standard_travel_buffer(self):
        assert cal.GoogleCalendarManager._resolve_travel_minutes(None, True) == 15

    def test_other_events_default_to_no_buffer(self):
        assert cal.GoogleCalendarManager._resolve_travel_minutes(None, False) == 0

    def test_explicit_zero_suppresses_buffering_for_a_workout(self):
        assert cal.GoogleCalendarManager._resolve_travel_minutes(0, True) == 0

    def test_negative_travel_is_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            cal.GoogleCalendarManager._resolve_travel_minutes(-5, True)
