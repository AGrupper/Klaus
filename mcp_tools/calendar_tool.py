"""Google Calendar MCP tool — Phase 3 implementation.

Exposes calendar reads/writes to the agent: availability lookup, free/busy
queries, and event creation with automatic travel buffers and workout prep
blocks (per `docs/USER.md` personal routines).  All higher-level scheduling
policy lives in the Smart agent layer; this module only enforces the
mechanical rules documented in the spec.
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

# Scheduling rules from docs/USER.md ("scheduling-rules"). They live here as
# named constants rather than inline numbers because they are Amit's routine,
# not arbitrary defaults: a workout is bracketed by travel, and a "Get Ready"
# block precedes the whole thing.
_DEFAULT_WORKOUT_TRAVEL_MINUTES = 15
_GET_READY_MINUTES = 45

_KLAUS_EVENT_MARKER = {"klaus_owned": "true", "klaus_version": "7"}
_CALENDAR_TIMEZONE = "Asia/Jerusalem"


class GoogleCalendarManager:
    """Authenticated wrapper around the Google Calendar v3 API.

    Provides list, free/busy, and create operations used by the Klaus agent.
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

    # Phase 20 — D-01/D-02: training-calendar read path
    _TRAINING_CALENDAR_NAME: str = "Training"   # D-01: configurable via constant

    def get_calendar_id_by_name(self, name: str) -> str | None:
        """Return the calendarId for the calendar with the given display name.

        Iterates through the user's calendarList with pagination (Pitfall 6)
        and matches on ``item["summary"]``.

        Args:
            name: Calendar display name to search for (e.g. ``"Training"``).

        Returns:
            The calendar ID string, or ``None`` if not found or on any API error.
            Never raises.
        """
        try:
            service = self._get_service()
            page_token = None
            while True:
                kwargs: dict = {}
                if page_token:
                    kwargs["pageToken"] = page_token
                result = service.calendarList().list(**kwargs).execute(
                    num_retries=_READ_NUM_RETRIES
                )
                for item in result.get("items", []):
                    if item.get("summary", "").strip() == name:
                        return item.get("id")
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
            return None
        except Exception as exc:
            logger.error(
                "Calendar calendarList error looking up %r: %s", name, exc
            )
            return None

    # Calendars the user can write to (owner/writer). Read-only subscribed
    # calendars (holidays, birthdays, week-numbers) are excluded so listings and
    # briefings aren't flooded — and so Klaus never tries to edit/delete an event
    # on a calendar where the API would reject the write anyway.
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

    def is_klaus_owned(self, event_id: str, calendar_id: str | None = None) -> bool:
        """Return true only for events created by Klaus's action engine.

        Routines use this marker as a hard server-side gate before moving or
        deleting an event. Missing/unreadable metadata fails closed.
        """
        target_cal = calendar_id or "primary"
        try:
            service = self._get_service()
            try:
                event = service.events().get(
                    calendarId=target_cal, eventId=event_id
                ).execute(num_retries=_READ_NUM_RETRIES)
            except HttpError as exc:
                if exc.resp.status != 404:
                    raise
                found = self._find_calendar_for_event(event_id)
                if not found:
                    return False
                event = service.events().get(
                    calendarId=found, eventId=event_id
                ).execute(num_retries=_READ_NUM_RETRIES)
            private = (event.get("extendedProperties") or {}).get("private") or {}
            return private.get("klaus_owned") == "true"
        except _TRANSIENT_ERRORS:
            logger.warning("Could not verify Klaus ownership for event %s", event_id)
            return False

    def is_free(self, start_iso: str, end_iso: str) -> dict:
        """Check whether ALL writable calendars are free in the given window.

        Uses the `freebusy().query` endpoint, which is cheaper than listing
        events and is specifically designed for availability checks.  It queries
        every calendar the user can write to (primary, Training, etc.) so a
        workout in the Training calendar correctly registers as busy.  If the
        slot is busy, a follow-up `list_all_events` call identifies the first
        conflicting event so the agent can report it to the user.

        Args:
            start_iso: RFC 3339 / ISO 8601 start of the window to check.
            end_iso:   RFC 3339 / ISO 8601 end of the window to check.

        Returns:
            A dict with:
                - "is_free"           (bool) — True if no events overlap the window.
                - "conflicting_event" (str | None) — Summary of the first
                  overlapping event, or None if the slot is free.
            On API error the dict also includes:
                - "error" (str) — The exception message.
        """
        try:
            service = self._get_service()

            # Check every calendar the user can write to, not just primary —
            # otherwise a Training-calendar workout never registers as busy.
            # Fall back to primary-only if calendarList is unavailable.
            writable = self.list_writable_calendars()
            items = (
                [{"id": cal["id"]} for cal in writable]
                if writable
                else [{"id": "primary"}]
            )

            # WHY freebusy instead of events().list: freebusy is a single
            # query optimised for availability — it returns only busy intervals,
            # not full event objects, so it's lighter on quota and latency.
            result = (
                service.freebusy()
                .query(
                    body={
                        "timeMin": start_iso,
                        "timeMax": end_iso,
                        # "items" tells the API which calendars to check.
                        "items": items,
                    }
                )
                .execute(num_retries=_READ_NUM_RETRIES)
            )

            # Busy if ANY queried calendar reports a busy interval.
            calendars = result.get("calendars", {})
            any_busy = any(
                cal.get("busy") for cal in calendars.values()
            )

            if not any_busy:
                # No busy intervals on any calendar — the slot is completely free.
                return {"is_free": True, "conflicting_event": None}

            # Slot is busy — identify the first conflicting event title so the
            # agent can give the user a meaningful explanation.
            conflicting_events = self.list_all_events(start_iso, end_iso, max_results=1)
            conflicting_title: str | None = None
            if conflicting_events:
                conflicting_title = conflicting_events[0].get("summary") or None

            return {"is_free": False, "conflicting_event": conflicting_title}

        except _TRANSIENT_ERRORS as exc:
            logger.error(
                "Calendar API error in is_free(%s, %s): %s",
                start_iso,
                end_iso,
                exc,
            )
            return {"is_free": False, "conflicting_event": None, "error": str(exc)}

    def create_event(
        self,
        summary: str,
        start_iso: str,
        end_iso: str,
        description: str = "",
        travel_minutes_each_way: int | None = None,
        is_workout: bool | None = None,
        calendar_id: str | None = None,
    ) -> dict:
        """Create a calendar event, automatically applying travel buffers and
        workout prep blocks per the user's personal routines.

        Workflow
        --------
        1. Treat the event as a workout iff is_workout is True (defaults to False
           when unset — training blocks are defined by the caller's judgment /
           Training-calendar membership, not by title keywords).
        2. Determine travel time: use the explicit argument if supplied,
           otherwise default to 15 min for workouts and 0 for everything else.
        3. Expand the event window by `travel` minutes on each side.
        4. Insert the main event (with the buffered window).
        5. For workouts, insert a 45-minute "Get Ready" block immediately
           before the buffered start.

        Args:
            summary:                  Event title.
            start_iso:                Desired start time (RFC 3339 / ISO 8601,
                                      timezone-aware).
            end_iso:                  Desired end time (RFC 3339 / ISO 8601,
                                      timezone-aware).
            description:              Optional event body text.
            travel_minutes_each_way:  Minutes to pad before start and after end.
                                      Pass 0 to suppress buffering even for
                                      workouts.  If None, defaults to 15 for
                                      workouts and 0 otherwise.
            is_workout:               Whether the event is a workout. Defaults to
                                      False when None. When True, the event is
                                      routed to the Training calendar and gets a
                                      travel buffer + Get Ready prep block.
            calendar_id:              Optional explicit target calendar ID. When
                                      set it overrides the primary/Training
                                      routing, so callers can create an event in
                                      any writable calendar.

        Returns:
            A dict containing:
                - "event_id"                (str)  — Created event ID.
                - "summary"                 (str)  — Event title.
                - "start"                   (str)  — Buffered start ISO string.
                - "end"                     (str)  — Buffered end ISO string.
                - "travel_minutes_each_way" (int)  — Travel buffer used.
                - "calendar_id"             (str)  — Calendar it landed in.
                - "buffers"                 (list) — Buffer blocks applied, each
                  ``{"kind", "start", "end"}``. Claude turns this into prose.
                - "get_ready_event_id"      (str)  — (Workout only) ID of the
                  prep block event.
            On API error:
                - "error"   (str) — Exception message.
                - "summary" (str) — The requested event title.

        Raises:
            ValueError: If `travel_minutes_each_way` is negative.
        """
        is_workout = self._is_workout_event(summary, is_workout)
        travel = self._resolve_travel_minutes(travel_minutes_each_way, is_workout)
        plan = self._plan_buffer_blocks(summary, start_iso, end_iso, travel, is_workout)

        if travel > 0:
            # WHY prepend: keeps the buffer notice at the top so it's visible
            # in the calendar event preview without scrolling.
            description = (
                f"[Includes {travel}-min travel buffer before and after]\n\n"
                + description
            )

        try:
            service = self._get_service()
            target_cal = self._target_calendar(is_workout, calendar_id)

            created_event: dict = (
                service.events()
                .insert(
                    calendarId=target_cal,
                    body=self._klaus_event_body(
                        summary, description, plan["start"], plan["end"]
                    ),
                )
                .execute()
            )

            result: dict = {
                "event_id": created_event.get("id", ""),
                "summary": summary,
                "start": plan["start"].isoformat(),
                "end": plan["end"].isoformat(),
                "travel_minutes_each_way": travel,
                "calendar_id": target_cal,
                "buffers": plan["buffers"],
            }

            get_ready = plan["get_ready"]
            if get_ready is not None:
                get_ready_event: dict = (
                    service.events()
                    .insert(
                        calendarId=target_cal,
                        body=self._klaus_event_body(
                            get_ready["summary"],
                            "Pre-workout prep block (per personal routine).",
                            get_ready["start"],
                            get_ready["end"],
                        ),
                    )
                    .execute()
                )
                result["get_ready_event_id"] = get_ready_event.get("id", "")

            return result

        except _TRANSIENT_ERRORS as exc:
            logger.error(
                "Calendar API error in create_event('%s', %s, %s): %s",
                summary,
                start_iso,
                end_iso,
                exc,
            )
            return {"error": str(exc), "summary": summary}

    @staticmethod
    def _is_workout_event(summary: str, is_workout: bool | None) -> bool:
        """Decide whether an event is a training block.

        A training block is defined by the caller's judgement and by Training-
        calendar membership, never by title keywords — so an unset flag means
        "not a workout" rather than triggering a guess.

        The one override: a "Get Ready" block is itself a buffer. Letting one be
        flagged as a workout would generate buffers for the buffer, which is the
        infinite recursion this guard exists to prevent.
        """
        if not is_workout:
            return False
        return not summary.lower().startswith("get ready")

    @staticmethod
    def _resolve_travel_minutes(travel_minutes_each_way: int | None, is_workout: bool) -> int:
        """Return the travel buffer to apply on each side of an event.

        Args:
            travel_minutes_each_way: Explicit caller value; 0 suppresses buffering.
            is_workout: Whether the event is a training block.

        Returns:
            int: Explicit value when given, otherwise Amit's standard workout
            travel buffer for workouts and 0 for everything else.

        Raises:
            ValueError: If the explicit value is negative.
        """
        if travel_minutes_each_way is None:
            return _DEFAULT_WORKOUT_TRAVEL_MINUTES if is_workout else 0
        if travel_minutes_each_way < 0:
            raise ValueError(
                f"travel_minutes_each_way must be >= 0, got {travel_minutes_each_way}"
            )
        return travel_minutes_each_way

    @staticmethod
    def _plan_buffer_blocks(
        summary: str,
        start_iso: str,
        end_iso: str,
        travel: int,
        is_workout: bool,
    ) -> dict:
        """Work out the real footprint of an event before anything is written.

        Pure: no network, no clock. This is the whole of Amit's scheduling rule
        from docs/USER.md, in one testable place — the buffered window plus the
        "Get Ready" block that precedes a workout.

        Args:
            summary:    Event title, used to name the prep block.
            start_iso:  Requested start (RFC 3339 / ISO 8601, timezone-aware).
            end_iso:    Requested end (RFC 3339 / ISO 8601, timezone-aware).
            travel:     Travel minutes to add on each side.
            is_workout: Whether to add the pre-workout prep block.

        Returns:
            dict: ``start`` and ``end`` datetimes for the buffered event,
            ``get_ready`` (a ``{"summary", "start", "end"}`` spec or None), and
            ``buffers`` — a JSON-safe description of what was applied, for the
            caller to report.
        """
        # WHY fromisoformat: stdlib, and it handles the RFC 3339 strings Google
        # Calendar returns (3.11+ accepts a "Z" suffix; older callers should
        # normalise to "+00:00").
        parsed_start = datetime.fromisoformat(start_iso)
        parsed_end = datetime.fromisoformat(end_iso)

        buffered_start = parsed_start - timedelta(minutes=travel)
        buffered_end = parsed_end + timedelta(minutes=travel)

        buffers: list[dict] = []
        if travel > 0:
            buffers.append(
                {
                    "kind": "travel",
                    "minutes": travel,
                    "start": buffered_start.isoformat(),
                    "end": parsed_start.isoformat(),
                }
            )
            buffers.append(
                {
                    "kind": "travel",
                    "minutes": travel,
                    "start": parsed_end.isoformat(),
                    "end": buffered_end.isoformat(),
                }
            )

        get_ready = None
        if is_workout:
            # The prep block ends exactly when the buffered event begins, so
            # travel and preparation never overlap.
            get_ready_start = buffered_start - timedelta(minutes=_GET_READY_MINUTES)
            get_ready = {
                "summary": f"Get Ready: {summary}",
                "start": get_ready_start,
                "end": buffered_start,
            }
            buffers.append(
                {
                    "kind": "get_ready",
                    "minutes": _GET_READY_MINUTES,
                    "start": get_ready_start.isoformat(),
                    "end": buffered_start.isoformat(),
                }
            )

        return {
            "start": buffered_start,
            "end": buffered_end,
            "get_ready": get_ready,
            "buffers": buffers,
        }

    def _target_calendar(self, is_workout: bool, calendar_id: str | None) -> str:
        """Choose the calendar an event should be created in.

        An explicit ``calendar_id`` always wins. Otherwise workouts route to the
        dedicated Training calendar (D-01) — which is what makes them training
        blocks — falling back to primary when no such calendar exists.
        """
        if calendar_id:
            return calendar_id
        if is_workout:
            training_cal_id = self.get_calendar_id_by_name(self._TRAINING_CALENDAR_NAME)
            if training_cal_id:
                return training_cal_id
        return "primary"

    @staticmethod
    def _klaus_event_body(
        summary: str, description: str, start: datetime, end: datetime
    ) -> dict:
        """Build a Google Calendar event body marked as Klaus-owned.

        The ``klaus_owned`` marker is what lets routines move or delete an event
        autonomously; anything without it is treated as user-created and is never
        touched. Every event Klaus creates goes through here so the marker cannot
        be forgotten on one path.
        """
        return {
            "summary": summary,
            "description": description,
            "extendedProperties": {"private": dict(_KLAUS_EVENT_MARKER)},
            "start": {
                # WHY an explicit timeZone even though dateTime is already
                # tz-aware: Google Calendar uses this field when rendering the
                # event in the user's UI.
                "dateTime": start.isoformat(),
                "timeZone": _CALENDAR_TIMEZONE,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": _CALENDAR_TIMEZONE,
            },
        }

    def _find_calendar_for_event(self, event_id: str) -> str | None:
        """Return the ID of the writable calendar that contains ``event_id``.

        Used as a fallback by delete/update when the caller didn't pass the right
        ``calendar_id`` — Klaus's listing now hands back ``calendar_id`` per event,
        but this keeps mutations robust if it's ever omitted or stale. Probes each
        writable calendar with a cheap ``events().get`` until one succeeds.

        Returns:
            The matching calendar ID, or ``None`` if no writable calendar holds it.
        """
        service = self._get_service()
        for cal in self.list_writable_calendars():
            cal_id = cal["id"]
            try:
                service.events().get(calendarId=cal_id, eventId=event_id).execute(
                    num_retries=_READ_NUM_RETRIES
                )
                return cal_id
            except _TRANSIENT_ERRORS:
                continue
        return None

    def delete_event(self, event_id: str, calendar_id: str | None = None) -> dict:
        """Delete an event from any calendar by ID.

        Args:
            event_id:    The Calendar event ID (returned by list_calendar_events).
            calendar_id: The calendar the event lives on (returned alongside each
                event by the listing). Defaults to ``"primary"``. If the event
                isn't found there, falls back to searching the user's writable
                calendars so the delete still lands on the right calendar.

        Returns:
            A dict with:
                - "ok"        (bool) — True on success or 410 Gone (already deleted).
                - "event_id"  (str)  — The requested event ID.
                - "confirmation" (str) — Human-readable result (success only).
            On error:
                - "ok"       (bool) — False.
                - "event_id" (str)  — The requested event ID.
                - "error"    (str)  — Exception message.
        """
        target_cal = calendar_id or "primary"
        try:
            service = self._get_service()
            try:
                service.events().delete(calendarId=target_cal, eventId=event_id).execute()
            except HttpError as exc:
                # 404 → the event isn't on the assumed calendar. Find its real
                # home among the writable calendars and retry once before failing.
                if exc.resp.status == 404:
                    found = self._find_calendar_for_event(event_id)
                    if found and found != target_cal:
                        target_cal = found
                        service.events().delete(
                            calendarId=target_cal, eventId=event_id
                        ).execute()
                    else:
                        raise
                else:
                    raise
            logger.info("Deleted calendar event %s from %s", event_id, target_cal)
            return {
                "ok": True,
                "event_id": event_id,
                "confirmation": f"Event {event_id} deleted.",
            }
        except _TRANSIENT_ERRORS as exc:
            # WHY: 410 Gone means the event is already absent — treat as success.
            # Only an HttpError carries a `.resp` — a socket/timeout error
            # (OSError) has no HTTP response to inspect, so it always falls
            # through to the generic failure branch below.
            if isinstance(exc, HttpError) and exc.resp.status == 410:
                logger.info("Calendar event already deleted (410): %s", event_id)
                return {
                    "ok": True,
                    "event_id": event_id,
                    "confirmation": f"Event {event_id} was already deleted.",
                }
            logger.error("Calendar API error in delete_event('%s'): %s", event_id, exc)
            return {"ok": False, "event_id": event_id, "error": str(exc)}

    def update_event(
        self,
        event_id: str,
        calendar_id: str | None = None,
        summary: str | None = None,
        start_iso: str | None = None,
        end_iso: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Edit an existing event in place (partial update via PATCH).

        Only the fields you pass are changed; everything else is left as-is. This
        is what lets Klaus modify an event Amit asked to change instead of
        creating a duplicate.

        Args:
            event_id:    The Calendar event ID (returned by list_calendar_events).
            calendar_id: The calendar the event lives on (returned alongside each
                event by the listing). Defaults to ``"primary"``; if the event
                isn't found there, falls back to searching writable calendars.
            summary:     New title, if changing.
            start_iso:   New start datetime (RFC 3339 / ISO 8601), if changing.
            end_iso:     New end datetime (RFC 3339 / ISO 8601), if changing.
            description: New description, if changing.

        Returns:
            A dict with ``"ok"``, ``"event_id"``, and ``"confirmation"`` on
            success, or ``"ok": False`` + ``"error"`` on failure.
        """
        # Build the patch body from supplied fields only — PATCH leaves the rest.
        body: dict = {}
        if summary is not None:
            body["summary"] = summary
        if description is not None:
            body["description"] = description
        if start_iso is not None:
            body["start"] = {"dateTime": start_iso, "timeZone": "Asia/Jerusalem"}
        if end_iso is not None:
            body["end"] = {"dateTime": end_iso, "timeZone": "Asia/Jerusalem"}

        if not body:
            return {
                "ok": False,
                "event_id": event_id,
                "error": "No fields to update were provided.",
            }

        target_cal = calendar_id or "primary"
        try:
            service = self._get_service()
            try:
                service.events().patch(
                    calendarId=target_cal, eventId=event_id, body=body
                ).execute()
            except HttpError as exc:
                if exc.resp.status == 404:
                    found = self._find_calendar_for_event(event_id)
                    if found and found != target_cal:
                        target_cal = found
                        service.events().patch(
                            calendarId=target_cal, eventId=event_id, body=body
                        ).execute()
                    else:
                        raise
                else:
                    raise
            logger.info("Updated calendar event %s on %s (%s)", event_id, target_cal, list(body))
            return {
                "ok": True,
                "event_id": event_id,
                "confirmation": f"Event {event_id} updated.",
            }
        except _TRANSIENT_ERRORS as exc:
            logger.error("Calendar API error in update_event('%s'): %s", event_id, exc)
            return {"ok": False, "event_id": event_id, "error": str(exc)}
