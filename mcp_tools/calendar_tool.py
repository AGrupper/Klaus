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

from core.auth_google import GoogleAuthManager

logger = logging.getLogger(__name__)

# Keywords that identify a workout event.  Matched case-insensitively against
# the event summary so we know when to add a travel buffer and a Get Ready block.
WORKOUT_KEYWORDS: tuple[str, ...] = ("run", "bike", "basketball", "gym", "five fingers")


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

    def list_events(
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
                .execute()
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

        except HttpError as exc:
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
                result = service.calendarList().list(**kwargs).execute()
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

    def list_training_events(
        self,
        time_min_iso: str,
        time_max_iso: str,
        calendar_name: str = "Training",
        max_results: int = 20,
    ) -> list[dict]:
        """List events from the named training calendar, filtering buffer blocks.

        Resolves the calendar by display name (D-01) rather than a hardcoded ID,
        then returns events excluding ``Get Ready:`` and ``Travel:`` buffer blocks
        created by the automatic workout-prep logic (D-02).

        Args:
            time_min_iso:   RFC 3339 / ISO 8601 window start.
            time_max_iso:   RFC 3339 / ISO 8601 window end.
            calendar_name:  Display name of the training calendar.  Defaults to
                            ``_TRAINING_CALENDAR_NAME`` (``"Training"``).
            max_results:    Maximum events to return (default 20).

        Returns:
            A list of dicts, each containing ``"id"``, ``"summary"``, ``"start"``,
            ``"end"``, ``"description"``.  Returns ``[]`` if the calendar is not
            found or on any API error.  Never raises.
        """
        cal_id = self.get_calendar_id_by_name(calendar_name)
        if cal_id is None:
            logger.warning("Training calendar %r not found", calendar_name)
            return []
        try:
            service = self._get_service()
            result = (
                service.events()
                .list(
                    calendarId=cal_id,          # NOT "primary" — resolved by name
                    timeMin=time_min_iso,
                    timeMax=time_max_iso,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=max_results,
                )
                .execute()
            )
            events: list[dict] = []
            for item in result.get("items", []):
                summary = item.get("summary", "") or ""
                # D-02: skip buffer blocks added by create_event workout logic
                if summary.startswith("Get Ready:") or summary.startswith("Travel:"):
                    continue
                start_field = item.get("start", {})
                end_field = item.get("end", {})
                # WHY prefer dateTime over date: same normalisation as list_events
                start = start_field.get("dateTime") or start_field.get("date", "")
                end = end_field.get("dateTime") or end_field.get("date", "")
                events.append(
                    {
                        "id": item.get("id", ""),
                        "summary": summary,
                        "start": start,
                        "end": end,
                        "description": item.get("description", ""),
                    }
                )
            return events
        except Exception:
            logger.warning(
                "list_training_events(%r, %r) failed",
                time_min_iso,
                time_max_iso,
                exc_info=True,
            )
            return []

    def is_free(self, start_iso: str, end_iso: str) -> dict:
        """Check whether the primary calendar has no events in the given window.

        Uses the `freebusy().query` endpoint, which is cheaper than listing
        events and is specifically designed for availability checks.  If the
        slot is busy, a follow-up `list_events` call identifies the first
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
                        # "primary" is the user's default calendar.
                        "items": [{"id": "primary"}],
                    }
                )
                .execute()
            )

            busy_slots: list[dict] = result["calendars"]["primary"]["busy"]

            if not busy_slots:
                # No busy intervals — the slot is completely free.
                return {"is_free": True, "conflicting_event": None}

            # Slot is busy — identify the first conflicting event title so the
            # agent can give the user a meaningful explanation.
            conflicting_events = self.list_events(start_iso, end_iso, max_results=1)
            conflicting_title: str | None = None
            if conflicting_events:
                conflicting_title = conflicting_events[0].get("summary") or None

            return {"is_free": False, "conflicting_event": conflicting_title}

        except HttpError as exc:
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
    ) -> dict:
        """Create a calendar event, automatically applying travel buffers and
        workout prep blocks per the user's personal routines.

        Workflow
        --------
        1. Detect whether the event is a workout via WORKOUT_KEYWORDS (if is_workout is None).
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
            is_workout:               Whether the event is a workout. If None,
                                      dynamic keyword matching is used.

        Returns:
            A dict containing:
                - "event_id"                (str)  — Created event ID.
                - "summary"                 (str)  — Event title.
                - "start"                   (str)  — Buffered start ISO string.
                - "end"                     (str)  — Buffered end ISO string.
                - "travel_minutes_each_way" (int)  — Travel buffer used.
                - "confirmation"            (str)  — Human-readable summary.
                - "get_ready_event_id"      (str)  — (Workout only) ID of the
                  prep block event.
            On API error:
                - "error"   (str) — Exception message.
                - "summary" (str) — The requested event title.

        Raises:
            ValueError: If `travel_minutes_each_way` is negative.
        """
        # -------------------------------------------------------------- #
        # Step 1 — Determine whether this is a workout and set travel.   #
        # -------------------------------------------------------------- #
        if is_workout is None:
            summary_lc = summary.lower()
            is_workout = any(kw in summary_lc for kw in WORKOUT_KEYWORDS)
            # A bare "Practice" event (the user's basketball session) is a workout.
            # Matched as the exact title only — NOT a substring — so unrelated events
            # like "Practice presentation" are never misclassified. ("Basketball
            # practice" etc. are already caught by the keyword list above.)
            if not is_workout and summary_lc.strip() == "practice":
                is_workout = True
        if is_workout and summary.lower().startswith("get ready"):
            is_workout = False

        if travel_minutes_each_way is not None:
            travel = travel_minutes_each_way
        else:
            # WHY default 15 for workouts: user's personal routine requires
            # travel to/from any workout venue (per docs/USER.md).
            travel = 15 if is_workout else 0

        if travel < 0:
            raise ValueError(
                f"travel_minutes_each_way must be >= 0, got {travel}"
            )

        # -------------------------------------------------------------- #
        # Step 2 — Compute buffered start and end times.                 #
        # -------------------------------------------------------------- #
        # WHY fromisoformat: stdlib approach, handles the RFC 3339 strings
        # that Google Calendar returns (Python 3.11+ handles "Z" suffix too;
        # earlier versions need "+00:00" form — callers should normalise).
        parsed_start: datetime = datetime.fromisoformat(start_iso)
        parsed_end: datetime = datetime.fromisoformat(end_iso)

        buffered_start: datetime = parsed_start - timedelta(minutes=travel)
        buffered_end: datetime = parsed_end + timedelta(minutes=travel)

        # -------------------------------------------------------------- #
        # Step 3 — Build description, prepending the travel note if needed.
        # -------------------------------------------------------------- #
        if travel > 0:
            # WHY prepend: keeps the buffer notice at the top so it's visible
            # in the calendar event preview without scrolling.
            description = (
                f"[Includes {travel}-min travel buffer before and after]\n\n"
                + description
            )

        # -------------------------------------------------------------- #
        # Step 4 — Insert the main event.                                #
        # -------------------------------------------------------------- #
        try:
            service = self._get_service()

            # Workouts go to the dedicated Training calendar (D-01) so the evening
            # training check-in — which reads ONLY the Training calendar — can see
            # them. Fall back to the primary calendar if no Training calendar exists.
            target_cal = "primary"
            if is_workout:
                training_cal_id = self.get_calendar_id_by_name(self._TRAINING_CALENDAR_NAME)
                if training_cal_id:
                    target_cal = training_cal_id

            event_body: dict = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": buffered_start.isoformat(),
                    # WHY explicit timeZone: even though the dateTime string is
                    # already tz-aware, Google Calendar uses this field when
                    # rendering the event in the user's calendar UI.
                    "timeZone": "Asia/Jerusalem",
                },
                "end": {
                    "dateTime": buffered_end.isoformat(),
                    "timeZone": "Asia/Jerusalem",
                },
            }

            created_event: dict = (
                service.events()
                .insert(calendarId=target_cal, body=event_body)
                .execute()
            )

            event_id: str = created_event.get("id", "")

            # -------------------------------------------------------------- #
            # Step 5 — For workouts, create the "Get Ready" prep block.      #
            # -------------------------------------------------------------- #
            get_ready_event_id: str | None = None

            if is_workout:
                # WHY 45 minutes: user's personal pre-workout routine takes
                # ~45 min (per docs/USER.md), so we block it out automatically
                # rather than relying on manual entry.
                get_ready_start: datetime = buffered_start - timedelta(minutes=45)
                get_ready_end: datetime = buffered_start  # ends when workout starts

                get_ready_body: dict = {
                    "summary": f"Get Ready: {summary}",
                    "description": "Pre-workout prep block (per personal routine).",
                    "start": {
                        "dateTime": get_ready_start.isoformat(),
                        "timeZone": "Asia/Jerusalem",
                    },
                    "end": {
                        "dateTime": get_ready_end.isoformat(),
                        "timeZone": "Asia/Jerusalem",
                    },
                }

                get_ready_event: dict = (
                    service.events()
                    .insert(calendarId=target_cal, body=get_ready_body)
                    .execute()
                )
                get_ready_event_id = get_ready_event.get("id", "")

            # -------------------------------------------------------------- #
            # Step 6 — Build human-readable confirmation string and return.  #
            # -------------------------------------------------------------- #
            # Format times as HH:MM for readability in the confirmation message.
            start_display = buffered_start.strftime("%H:%M")
            end_display = buffered_end.strftime("%H:%M")

            if is_workout:
                get_ready_display = (buffered_start - timedelta(minutes=45)).strftime(
                    "%H:%M"
                )
                if travel > 0:
                    confirmation = (
                        f"'{summary}' scheduled for {start_display}–{end_display} "
                        f"(includes {travel}-min travel buffer). "
                        f"Get Ready block created at {get_ready_display}."
                    )
                else:
                    confirmation = (
                        f"'{summary}' scheduled for {start_display}–{end_display}. "
                        f"Get Ready block created at {get_ready_display}."
                    )
            else:
                if travel > 0:
                    confirmation = (
                        f"'{summary}' scheduled for {start_display}–{end_display} "
                        f"(includes {travel}-min travel buffer)."
                    )
                else:
                    confirmation = (
                        f"'{summary}' scheduled for {start_display}–{end_display}."
                    )

            result: dict = {
                "event_id": event_id,
                "summary": summary,
                "start": buffered_start.isoformat(),
                "end": buffered_end.isoformat(),
                "travel_minutes_each_way": travel,
                "confirmation": confirmation,
            }

            if is_workout and get_ready_event_id is not None:
                result["get_ready_event_id"] = get_ready_event_id

            return result

        except HttpError as exc:
            logger.error(
                "Calendar API error in create_event('%s', %s, %s): %s",
                summary,
                start_iso,
                end_iso,
                exc,
            )
            return {"error": str(exc), "summary": summary}

    def delete_event(self, event_id: str) -> dict:
        """Delete an event from the primary calendar by ID.

        Args:
            event_id: The Calendar event ID (returned by list_events).

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
        try:
            service = self._get_service()
            service.events().delete(calendarId="primary", eventId=event_id).execute()
            logger.info("Deleted calendar event: %s", event_id)
            return {
                "ok": True,
                "event_id": event_id,
                "confirmation": f"Event {event_id} deleted.",
            }
        except HttpError as exc:
            # WHY: 410 Gone means the event is already absent — treat as success.
            if exc.resp.status == 410:
                logger.info("Calendar event already deleted (410): %s", event_id)
                return {
                    "ok": True,
                    "event_id": event_id,
                    "confirmation": f"Event {event_id} was already deleted.",
                }
            logger.error("Calendar API error in delete_event('%s'): %s", event_id, exc)
            return {"ok": False, "event_id": event_id, "error": str(exc)}
