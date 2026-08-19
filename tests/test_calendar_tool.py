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


def test_list_writable_calendars_is_cached_between_calls():
    """The calendarList read is served from a TTL cache.

    list_all_events calls this on every GET /api/today, so an uncached read added
    a Google round trip to every Hub refresh and every ten-minute alert tick — for
    a calendar set that changes about once a year.
    """
    m = _mgr()
    service = MagicMock()
    page = {"items": [
        {"id": "primary", "summary": "Amit", "primary": True, "accessRole": "owner"},
    ]}
    service.calendarList.return_value.list.side_effect = [_chain(page)]

    with patch.object(m, "_get_service", return_value=service):
        first = m.list_writable_calendars()
        second = m.list_writable_calendars()

    assert first == second
    assert service.calendarList.return_value.list.call_count == 1


def test_list_writable_calendars_does_not_cache_a_failure():
    """A transient calendarList error must self-heal on the next call.

    Caching the [] would blind every downstream read — including the Hub's
    calendar and the deterministic leave-by alerts — until the TTL expired.
    """
    m = _mgr()
    service = MagicMock()
    good = {"items": [
        {"id": "primary", "summary": "Amit", "primary": True, "accessRole": "owner"},
    ]}
    service.calendarList.return_value.list.side_effect = [
        RuntimeError("calendarList 503"),
        _chain(good),
    ]

    with patch.object(m, "_get_service", return_value=service):
        assert m.list_writable_calendars() == []
        assert [c["id"] for c in m.list_writable_calendars()] == ["primary"]


def test_cached_calendar_list_cannot_be_mutated_by_a_caller():
    """Callers get their own copies — a mutation must not poison the cache."""
    m = _mgr()
    service = MagicMock()
    page = {"items": [
        {"id": "primary", "summary": "Amit", "primary": True, "accessRole": "owner"},
    ]}
    service.calendarList.return_value.list.side_effect = [_chain(page)]

    with patch.object(m, "_get_service", return_value=service):
        first = m.list_writable_calendars()
        first[0]["id"] = "tampered"
        second = m.list_writable_calendars()

    assert second[0]["id"] == "primary"
