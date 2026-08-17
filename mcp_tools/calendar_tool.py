"""Read-only Google Calendar client for the Hub's day view.

Klaus no longer writes to the calendar. Claude does that through its own Google
Calendar connector, which is attached to the Project and to each routine, and
which reaches more of the calendar than this ever did.

What is left is the one read Claude cannot supply: `core.hub.today` builds
`GET /api/today` from `list_all_events`, and that snapshot also feeds
`get_life_snapshot` and the deterministic alert evaluator — a path with no model
in it, so nothing else can raise a conflict push.

`list_all_events` reads EVERY writable calendar, not just primary. Reading only
primary made the Hub and the alert evaluator blind to the Training calendar,
where every session actually lives (fixed 2026-08-16).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError

from core.auth.google import GoogleAuthManager

logger = logging.getLogger(__name__)

# WHY (HttpError, OSError): a stalled/reset Google API socket read raises
# TimeoutError, ssl.SSLError, or ConnectionError — none of which are an
# HttpError (that only covers responses the server actually sent). All three
# subclass OSError, so this tuple catches "the call didn't come back" the
# same way HttpError catches "the call came back with an error status".
# Every read method below is documented to return an empty/error sentinel on
# API failure — this keeps that contract true for a network-level timeout too
# (observed recurring in production 2026-08-01..03, GOOGLE_API_TIMEOUT_SECONDS
# now bounds it to a fast failure instead of a long hang; core/auth_google.py).
_TRANSIENT_ERRORS = (HttpError, OSError)

# WHY num_retries=1 on read-only calls only: googleapiclient's own retry
# machinery (used when num_retries > 0) already treats socket/timeout errors
# as retryable with a short backoff. One bounded retry absorbs a single
# transient blip without turning a stalled call into an unbounded wait —
# GOOGLE_API_TIMEOUT_SECONDS still caps each individual attempt. Deliberately
# NOT applied to insert/patch/delete calls: retrying a write whose response
# was merely lost (not the request) risks a duplicate side effect.
_READ_NUM_RETRIES = 1

_CALENDAR_TIMEZONE = "Asia/Jerusalem"


class GoogleCalendarManager:
    """Authenticated wrapper around the Google Calendar v3 API.

    Provides the merged multi-calendar read used to build the Hub day view.
    The service resource is built lazily on first use so that construction is
    cheap and the class can be instantiated before any network I/O is needed.
    """

    def __init__(self, auth_manager: GoogleAuthManager) -> None:
        """Store the auth manager; defer building the service until first call.

        Args:
            auth_manager: A `GoogleAuthManager` instance whose
                `calendar_service()` method returns an authenticated
                Calendar v3 resource.
        """
        self._auth_manager = auth_manager
        # Lazily populated on first call to _get_service().
        self._service: Any | None = None
        # Store the local timezone for display convenience and future use.
        self._tz = ZoneInfo("Asia/Jerusalem")

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_service(self) -> Any:
        """Return the Calendar v3 service, building it if not yet initialised.

        Returns:
            An authenticated `googleapiclient.discovery.Resource` for the
            Calendar v3 API.
        """
        # WHY lazy init: GoogleAuthManager.calendar_service() may trigger a
        # token refresh (network call).  We delay that until we actually need
        # the service so that constructing this class is always free of I/O.
        if self._service is None:
            self._service = self._auth_manager.calendar_service()
        return self._service

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def _list_primary_events(
        self,
        time_min_iso: str,
        time_max_iso: str,
        max_results: int = 20,
    ) -> list[dict]:
        """Return a list of events that fall within the given time window.

        Calls `events().list` with `singleEvents=True` so recurring events are
        expanded into individual instances, and `orderBy="startTime"` so the
        result is chronologically sorted.

        Args:
            time_min_iso: RFC 3339 / ISO 8601 string for the window start
                (e.g. "2026-05-04T08:00:00+03:00").
            time_max_iso: RFC 3339 / ISO 8601 string for the window end.
            max_results: Maximum number of events to return (default 20).

        Returns:
            A list of dicts, each containing:
                - "id"          (str)  — Calendar event ID.
                - "summary"     (str)  — Event title.
                - "start"       (str)  — Prefers dateTime over date.
                - "end"         (str)  — Prefers dateTime over date.
                - "description" (str)  — Event body; empty string if absent.
            Returns an empty list on API error.
        """
        try:
            service = self._get_service()

            # WHY singleEvents=True: without this, recurring events appear as
            # a single master entry with recurrence rules — useless for
            # time-window comparisons.  Expanding them lets us see each
            # occurrence individually.
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min_iso,
                    timeMax=time_max_iso,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=max_results,
                )
                .execute(num_retries=_READ_NUM_RETRIES)
            )

            events: list[dict] = []
            for item in result.get("items", []):
                start_field = item.get("start", {})
                end_field = item.get("end", {})

                # WHY prefer dateTime over date: all-day events only have
                # "date"; timed events have "dateTime".  We normalise so
                # callers always get a string regardless of event type.
                start = start_field.get("dateTime") or start_field.get("date", "")
                end = end_field.get("dateTime") or end_field.get("date", "")

                events.append(
                    {
                        "id": item.get("id", ""),
                        "summary": item.get("summary", ""),
                        "start": start,
                        "end": end,
                        "description": item.get("description", ""),
                        "location": item.get("location", ""),
                    }
                )

            return events

        except _TRANSIENT_ERRORS as exc:
            logger.error(
                "Calendar API error in list_events(%s, %s): %s",
                time_min_iso,
                time_max_iso,
                exc,
            )
            return []

    # Calendars the user can write to (owner/writer). Read-only subscribed
    # calendars (holidays, birthdays, week-numbers) are excluded so the Hub's
    # day view is not flooded with them. Klaus no longer writes anywhere, but
    # this is still the right filter: these are the calendars that carry Amit's
    # own commitments rather than a feed he subscribed to.
    _WRITABLE_ACCESS_ROLES: frozenset[str] = frozenset({"owner", "writer"})

    def list_writable_calendars(self) -> list[dict]:
        """Return the user's calendars that allow writes (owner/writer access).

        Paginates ``calendarList().list()`` (Pitfall 6) and filters out read-only
        subscribed calendars. Used by the generic list/edit/delete paths so Klaus
        can act on any calendar he controls — not just primary + Training.

        Returns:
            A list of dicts, each with ``"id"``, ``"summary"``, ``"primary"``
            (bool), and ``"access_role"``. Returns ``[]`` on any API error;
            never raises.
        """
        try:
            service = self._get_service()
            calendars: list[dict] = []
            page_token = None
            while True:
                kwargs: dict = {}
                if page_token:
                    kwargs["pageToken"] = page_token
                result = service.calendarList().list(**kwargs).execute(
                    num_retries=_READ_NUM_RETRIES
                )
                for item in result.get("items", []):
                    access_role = item.get("accessRole", "")
                    if access_role not in self._WRITABLE_ACCESS_ROLES:
                        continue
                    calendars.append(
                        {
                            "id": item.get("id", ""),
                            "summary": item.get("summary", ""),
                            "primary": bool(item.get("primary", False)),
                            "access_role": access_role,
                        }
                    )
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            return calendars
        except Exception:
            logger.error("Calendar calendarList error in list_writable_calendars", exc_info=True)
            return []

    def list_all_events(
        self,
        time_min_iso: str,
        time_max_iso: str,
        max_results: int = 20,
    ) -> list[dict]:
        """List events across ALL of the user's writable calendars, merged.

        Unlike the primary-only fallback this enumerates every calendar
        the user can write to and tags each event with both its calendar display
        name (``"calendar"``) and the real ``"calendar_id"`` — the latter is what
        the edit/delete tools need to act on an event in its own calendar.

        Buffer blocks (``Get Ready:`` / ``Travel:``) are intentionally NOT
        stripped here so Klaus can see and manage a workout's prep block himself.

        Args:
            time_min_iso: RFC 3339 / ISO 8601 window start.
            time_max_iso: RFC 3339 / ISO 8601 window end.
            max_results:  Maximum events to return per calendar (default 20).

        Returns:
            A chronologically sorted list of event dicts, each with ``"id"``,
            ``"summary"``, ``"start"``, ``"end"``, ``"description"``,
            ``"location"``, ``"calendar"``, and ``"calendar_id"``. Returns ``[]``
            on error; never raises.
        """
        calendars = self.list_writable_calendars()
        if not calendars:
            # Fall back to the primary-only view so we degrade gracefully rather
            # than returning nothing if calendarList is unavailable.
            events = self._list_primary_events(time_min_iso, time_max_iso, max_results)
            for ev in events:
                ev.setdefault("calendar", "primary")
                ev.setdefault("calendar_id", "primary")
            return events

        try:
            service = self._get_service()
            merged: list[dict] = []
            for cal in calendars:
                cal_id = cal["id"]
                cal_name = cal["summary"]
                result = (
                    service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=time_min_iso,
                        timeMax=time_max_iso,
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=max_results,
                    )
                    .execute(num_retries=_READ_NUM_RETRIES)
                )
                for item in result.get("items", []):
                    start_field = item.get("start", {})
                    end_field = item.get("end", {})
                    start = start_field.get("dateTime") or start_field.get("date", "")
                    end = end_field.get("dateTime") or end_field.get("date", "")
                    merged.append(
                        {
                            "id": item.get("id", ""),
                            "summary": item.get("summary", ""),
                            "start": start,
                            "end": end,
                            "description": item.get("description", ""),
                            "location": item.get("location", ""),
                            "calendar": cal_name,
                            "calendar_id": cal_id,
                        }
                    )
            merged.sort(key=lambda e: e.get("start") or "")
            return merged
        except _TRANSIENT_ERRORS as exc:
            logger.error(
                "Calendar API error in list_all_events(%s, %s): %s",
                time_min_iso,
                time_max_iso,
                exc,
            )
            return []
