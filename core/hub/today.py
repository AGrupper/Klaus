"""Today's state, assembled from every source Klaus reads.

Backs `GET /api/today` for the Hub and the `today` block of the life snapshot
Claude receives. Every loader is fail-open: one unavailable source degrades its
own key rather than emptying the whole day, because a dashboard missing its
weather is useful and a dashboard missing everything is not.

Extracted from interfaces/web_server.py, where these helpers made up a third of
the module and forced core/life_snapshot.py to import the HTTP layer.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _today_calendar(today_iso: str) -> dict:
    """Fetch today's calendar events — all-day pinned + timed sorted chronologically.

    TIME-01: all-day events are pinned at top; timed events sorted by start ascending.
    Returns {"all_day": [...], "timed": [...]} or {"all_day": [], "timed": []} on error.

    Each event dict carries: id, title, start, end, calendar, location (if present).

    Reads EVERY writable calendar, not just primary. This used to call
    ``list_events`` (primary only), which made the whole no-model side of Klaus
    blind to the Training calendar — where every session actually lives. The Hub
    showed an empty day and, worse, ``core.routines.alerts`` reads this same
    snapshot, so conflict and leave-by pushes could never fire for a workout. It
    stayed hidden because Claude reaches the calendar through ``list_all_events``
    and compensated; only the deterministic paths were affected.
    """
    try:
        # WHY shared: the singleton retains Google's short-lived access token
        # in process memory. Rebuilding authentication for every ten-minute
        # snapshot would repeatedly exchange the same static refresh grant.
        from core.tools import _get_calendar_tool  # lazy import — Shared Pattern 5
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI

        tz = _ZI("Asia/Jerusalem")
        day_start = _dt.fromisoformat(today_iso).replace(
            hour=0, minute=0, second=0, tzinfo=tz
        )
        day_end = _dt.fromisoformat(today_iso).replace(
            hour=23, minute=59, second=59, tzinfo=tz
        )

        cal = _get_calendar_tool()
        # max_results is per calendar here, and list_all_events already merges
        # chronologically and falls back to primary if calendarList is unreadable.
        raw_events = cal.list_all_events(
            day_start.isoformat(),
            day_end.isoformat(),
            max_results=50,
        )

        all_day = []
        timed = []
        for ev in raw_events:
            start_str = ev.get("start", "")
            location = ev.get("location", "")
            calendar_name = ev.get("calendar", "")
            entry = {
                "id": ev.get("id", ""),
                "title": ev.get("summary", ""),
                "start": start_str,
                "end": ev.get("end", ""),
            }
            if location:
                entry["location"] = location
            if calendar_name:
                entry["calendar"] = calendar_name
            # All-day events have a date-only "start" (YYYY-MM-DD, length 10 with no 'T').
            if "T" not in start_str and len(start_str) == 10:
                # All-day events surface as title strings to match the frontend
                # contract (TodayData.calendar.all_day: string[]).
                all_day.append(entry["title"])
            else:
                timed.append(entry)

        # All-day events are pinned as-is; timed events are already sorted by startTime.
        return {"all_day": all_day, "timed": timed}
    except Exception:
        logger.warning("_today_calendar() failed", exc_info=True)
        return {"all_day": [], "timed": []}


# Minimum gap between write-throughs of the same day's biometrics. Every Hub
# refresh and every ten-minute alert tick fetches these numbers, so an ungated
# write would open a Postgres connection per request — and a Postgres outage
# would add its five-second connect timeout to every one of them.
_BIOMETRIC_WRITE_THROUGH_INTERVAL_SECONDS = 900  # 15 minutes

# date -> monotonic timestamp of the last write-through attempt (success or not).
_biometric_write_through_seen: dict[str, float] = {}


def _persist_garmin_snapshot(data: dict) -> None:
    """Write a live Garmin read through to the daily_biometrics table.

    The Hub fetches exactly the columns the 05:30 biometric cron backfills, dozens
    of times a day, and used to discard every one. Persisting them here closes the
    gap where a late Garmin sync leaves the row missing until the next day's cron
    re-pull — at no extra Garmin cost, since the data is already in hand.

    Bounded by an interval guard per date so the alert cadence cannot turn into a
    write per request. The underlying writer upserts and swallows its own errors;
    this never raises, because a history write must not break the day view.
    """
    import time as _time

    date_iso = str(data.get("date") or "")
    if not date_iso:
        return
    # Nothing to persist on a watch-off day — writing all-NULLs would mask the gap.
    if all(
        data.get(k) is None
        for k in ("sleep_hours", "hrv_overnight", "resting_hr", "body_battery_morning")
    ):
        return

    now = _time.monotonic()
    last = _biometric_write_through_seen.get(date_iso)
    if last is not None and now - last < _BIOMETRIC_WRITE_THROUGH_INTERVAL_SECONDS:
        return
    # Stamped before the attempt: a hung or failing write must not be retried on
    # the very next request.
    _biometric_write_through_seen[date_iso] = now

    try:
        from mcp_tools.garmin_tool import write_biometrics_to_postgres  # lazy import
        write_biometrics_to_postgres(data)
    except Exception:
        logger.warning("_persist_garmin_snapshot(%r) failed", date_iso, exc_info=True)


def _stored_garmin(today_iso: str) -> dict | None:
    """Fall back to the biometrics already stored for today, or None.

    Reached when the live Garmin call fails — rate limit, expired token, Garmin
    outage. Without this the Hub shows "Sleep stats syncing…" all day even though
    the 05:30 cron has the numbers, which reads as missing data rather than as a
    transient upstream failure.

    `stored: True` marks the payload so the client can say the numbers are the
    stored ones. That flag also carries a real caveat: `body_battery_max` is the
    day's peak, not the live read's `body_battery_morning`, so the two are close
    but not the same measurement.
    """
    try:
        from core.health_reads import fetch_biometric_range  # lazy import
        rows = fetch_biometric_range(today_iso, today_iso)
        if not rows:
            return None
        row = rows[-1]
        stats = {
            "sleep": row.get("sleep_duration"),
            "hrv": row.get("hrv_overnight"),
            "body_battery": row.get("body_battery_max"),
            "resting_hr": row.get("resting_hr"),
        }
        if all(v is None for v in stats.values()):
            return None
        return {**stats, "stored": True}
    except Exception:
        logger.warning("_stored_garmin(%r) failed", today_iso, exc_info=True)
        return None


def _today_garmin() -> dict | None:
    """Fetch today's Garmin morning stats — sleep, HRV, body battery, resting HR.

    TIME-02 stats half. Falls back to the stored daily_biometrics row when the
    live call fails, and returns None only when neither source has anything (D-06:
    client shows "Sleep stats syncing…").
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI

    today_iso = _dt.now(_ZI("Asia/Jerusalem")).date().isoformat()
    try:
        from mcp_tools.garmin_tool import fetch_garmin_today  # lazy import
        data = fetch_garmin_today()
        # Persist the FULL dict — the narrowed four fields below drop sleep_score,
        # hrv_baseline, training_readiness and vo2_max, which the table wants.
        _persist_garmin_snapshot(data)
        # Field names match the frontend GarminStats contract
        # (frontend/src/api/today.ts): sleep (hours), hrv (ms), body_battery, resting_hr.
        return {
            "sleep": data.get("sleep_hours"),
            "hrv": data.get("hrv_overnight"),
            "body_battery": data.get("body_battery_morning"),
            "resting_hr": data.get("resting_hr"),
        }
    except Exception:
        logger.warning("_today_garmin() failed — falling back to stored biometrics", exc_info=True)
        return _stored_garmin(today_iso)


# Last successful weather line, with the monotonic time it was fetched. wttr.in is
# a free service that fails several times an hour, and its failures used to render
# as a bare "—" with no way to tell an outage from a quiet sky.
_WEATHER_CACHE_TTL_SECONDS = 3600  # an hour-old reading still beats nothing
_weather_last_good: tuple[float, str] | None = None


def _today_weather() -> str | None:
    """Fetch a one-line weather summary string for Tel Aviv.

    TIME-02 weather half. Falls back to the last successful reading (up to an hour
    old) when wttr.in fails, and returns None only when there is nothing cached —
    client can show "—".
    """
    global _weather_last_good
    import time as _time

    try:
        from mcp_tools.weather_tool import fetch_weather  # lazy import
        data = fetch_weather("Tel Aviv")
        current = data.get("current", {})
        today = data.get("today", {})
        cond = current.get("condition", "")
        temp = current.get("temp_c")
        high = today.get("max_c")
        low = today.get("min_c")
        rain = today.get("rain_chance")
        parts = []
        if cond:
            parts.append(cond)
        if temp is not None:
            parts.append(f"{temp}°C")
        if high is not None and low is not None:
            parts.append(f"H {high}°/L {low}°")
        if rain:
            parts.append(f"{rain}% rain")
        summary = ", ".join(parts) if parts else None
        if summary:
            _weather_last_good = (_time.monotonic(), summary)
        return summary
    except Exception:
        logger.warning("_today_weather() failed — trying last good reading", exc_info=True)
        if _weather_last_good is not None:
            cached_at, cached_summary = _weather_last_good
            if _time.monotonic() - cached_at < _WEATHER_CACHE_TTL_SECONDS:
                return cached_summary
        return None


_SLOT_LABELS: dict[str, str] = {
    "08:00": "Breakfast",
    "12:00": "Lunch",
    "20:00": "Dinner",
}


def _today_meals(today_iso: str) -> list[dict]:
    """Fetch today's meals as slot-label entries with macros.

    TIME-03: meals are rendered as canonical slot LABELS (Breakfast/Lunch/Dinner)
    derived from the canonical slot timestamps (08:00/12:00/20:00). Per CLAUDE.md §6
    invariant: these timestamps are NOT actual eating times — they are canonical
    slot identifiers written by the HealthKit/Lifesum pipeline. The returned dicts
    MUST NOT include any field named or framed as eaten_at or eating_time.
    """
    try:
        from memory.firestore_db import MealStore  # lazy import
        store = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        raw_meals = store.get_day(today_iso)
        result = []
        for meal in raw_meals:
            ts = meal.get("timestamp", "")
            # Derive the slot label from the HH:MM portion of the canonical timestamp.
            time_part = ""
            try:
                time_part = ts[11:16] if len(ts) >= 16 else ts[:5]
            except (IndexError, TypeError):
                pass
            slot_label = _SLOT_LABELS.get(time_part, "Meal")
            result.append({
                "slot_label": slot_label,         # canonical display label (TIME-03)
                # NOTE: deliberately no `slot_time` field on the wire — the client
                # contract (MealItem in today.ts) only declares slot_label + macros,
                # and per CLAUDE.md §6 the HH:MM slot identifier must never be
                # surfaced as (or risk being rendered as) an eating time.
                "macros": {
                    "kcal": meal.get("calories"),
                    "protein_g": meal.get("protein_g"),
                    "carbs_g": meal.get("carbs_g"),
                    "fat_g": meal.get("fat_g"),
                    "fiber_g": meal.get("fiber_g"),
                },
            })
        return result
    except Exception:
        logger.warning("_today_meals(%r) failed", today_iso, exc_info=True)
        return []


def _today_training(today_iso: str) -> dict | None:
    """Fetch today's training plan item + "Week N of 16 — {split name}" block context.

    TIME-04: uses BlockStore.get_current() (date-range resolution) mirroring the
    morning briefing block-fetch path (core/morning_briefing.py lines 399–420).
    Returns None when no block is active (pre/post-cycle) so the client can show
    the D-06 "no training block" placeholder.
    """
    try:
        from datetime import date as _date
        from memory.firestore_db import BlockStore, UserProfileStore  # lazy import

        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")

        block = None
        if project_id:
            bs = BlockStore(project_id=project_id, database=database)
            block = bs.get_current(today_iso)

        split_name = None
        if project_id:
            profile = UserProfileStore(project_id=project_id, database=database).load()
            # weekly_split is keyed by day name e.g. "Monday"
            try:
                from datetime import date as _d
                day_name = _d.fromisoformat(today_iso).strftime("%A")
                split_today = profile.get("weekly_split", {}).get(day_name) or {}
                am_slot = split_today.get("am") or {}
                split_name = am_slot.get("label")
            except Exception:
                pass

        if not block:
            return None

        # Derive week number the same way morning_briefing does — from plan_start_date 2026-06-21.
        try:
            plan_start = _date.fromisoformat("2026-06-21")
            today_date = _date.fromisoformat(today_iso)
            week_num = max(1, (today_date - plan_start).days // 7 + 1)
        except Exception:
            week_num = None

        block_context = None
        if week_num is not None:
            label = block.get("label") or "Training"
            if split_name:
                block_context = f"Week {week_num} of 16 — {split_name}"
            else:
                block_context = f"Week {week_num} of 16 — {label}"

        return {
            # "item" matches the frontend TrainingItem contract — the day's
            # workout name (split label, falling back to the block label).
            "item": split_name or block.get("label"),
            "block_context": block_context,
            "block_label": block.get("label"),
            "week_num": week_num,
            "split_name": split_name,
            "benchmark_due": block.get("benchmark_due", False),
        }
    except Exception:
        logger.warning("_today_training(%r) failed", today_iso, exc_info=True)
        return None


_COACH_NOTE_MAX_LEN = 280


def _strip_note_markup(note: str) -> str:
    """Strip control/format chars + inline Markdown markers. No length limit.

    The coach note is the morning briefing's first line — first-party text, but
    it can carry Markdown (``#`` headers, ``**bold**``) or stray bidi/format
    control chars (LRM/RLM) that render oddly as a one-line plain-text note.
    React escapes HTML, so this is hardening, not XSS defense (CR-04).
    """
    import unicodedata
    cleaned = "".join(
        ch for ch in str(note)
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )
    return cleaned.replace("**", "").replace("*", "").lstrip("#").strip()


def _sanitize_coach_note(note: str) -> str:
    """Strip markup and hard-clamp to the note length limit."""
    return _strip_note_markup(note)[:_COACH_NOTE_MAX_LEN]


def _trim_to_note_length(note: str) -> str:
    """Shorten a note to the length limit without cutting mid-word.

    The morning review opens with a full paragraph, not the one-liner the retired
    cascade produced, so a bare slice ended notes like "Nothing overnight changed
    t". Prefer the last sentence that fits; fall back to the last whole word plus
    an ellipsis, so the note always reads as a finished thought or an obvious
    continuation — never as a typo.
    """
    if len(note) <= _COACH_NOTE_MAX_LEN:
        return note

    window = note[:_COACH_NOTE_MAX_LEN]
    # Sentence end nearest the limit, provided it leaves a substantial note.
    sentence_end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_end >= _COACH_NOTE_MAX_LEN // 2:
        return window[: sentence_end + 1].strip()

    word_end = window.rfind(" ")
    if word_end <= 0:
        return window.rstrip()
    return window[:word_end].rstrip(" ,;:—-") + "…"


def derive_coach_note(review_text: str) -> str:
    """Reduce a published morning review to its one-line coach note.

    The note the Hub renders is the review's opening line — the same rule the
    retired Python morning cascade used before the Claude Routines cutover
    (v6.0 Phase 33: "first non-empty line of final_text"). Restoring the
    derivation here rather than in the skill keeps it a backend contract, so it
    cannot drift with an un-uploaded skill version.

    Returns "" when the text has no usable line, which callers treat as
    "nothing to persist" rather than writing an empty note.
    """
    for line in str(review_text or "").splitlines():
        cleaned = _strip_note_markup(line)
        if cleaned:
            return _trim_to_note_length(cleaned)
    return ""


def _read_self_state() -> dict:
    """Return the self_state doc, JSON-safe. ``{}`` on any error — never raises.

    Shared by both coach-note reads so a single ``/api/today`` costs one
    Firestore round trip (SelfStateStore.get() is TTL-cached between writes).
    """
    try:
        from memory.firestore_db import SelfStateStore, _jsonsafe_doc as _jsd  # lazy import
        project_id = os.environ.get("GCP_PROJECT_ID", "")
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        if not project_id:
            return {}
        return _jsd(SelfStateStore(project_id=project_id, database=database).get())
    except Exception:
        logger.warning("_read_self_state() failed", exc_info=True)
        return {}


def _today_coach_note(today_iso: str) -> str | None:
    """Read the coach note written by the morning briefing from SelfStateStore.

    TIME-07 / D-06: returns `daily_note` ONLY when `daily_note_date` equals today's
    Asia/Jerusalem date. Returns None when the note is absent or stale — the client
    shows "Coach note coming after your morning briefing" per D-06.
    """
    try:
        state = _read_self_state()
        note = state.get("daily_note")
        note_date = state.get("daily_note_date")
        if note and note_date == today_iso:
            return _sanitize_coach_note(note)
        return None
    except Exception:
        logger.warning("_today_coach_note() failed", exc_info=True)
        return None


def _today_coach_note_at(today_iso: str) -> str | None:
    """Return when today's coach note was written, as an ISO timestamp.

    The Hub renders this beside the note so it reads as what Klaus said at a
    particular hour rather than as live advice — the note is a byproduct of the
    morning review and is never recomposed later in the day.

    Gated on the same `daily_note_date == today` check as the note itself, so a
    stale timestamp can never outlive the note it describes.
    """
    try:
        state = _read_self_state()
        if not state.get("daily_note") or state.get("daily_note_date") != today_iso:
            return None
        written_at = state.get("daily_note_at")
        return str(written_at) if written_at else None
    except Exception:
        logger.warning("_today_coach_note_at() failed", exc_info=True)
        return None


# Get Ready block before leaving (USER.md: 45 min prep before departure).
_GET_READY_MINUTES = 45


# One-way travel time for a located event, in minutes. Amit's commute is a
# fixed ~15 minutes each way (USER.md gym template), so a constant produces the
# same departure window a traffic lookup did for the trips he actually makes.
_DEFAULT_TRAVEL_MINUTES = 15


def _configured_travel_minutes() -> int:
    """Return the configured one-way travel time, falling back to the default.

    Kept permissive on purpose: a malformed or negative override must not strip
    leave_by from the whole day, because that is the field the deterministic
    departure alert fires on.
    """
    raw = os.environ.get("KLAUS_TRAVEL_MINUTES_DEFAULT", "").strip()
    if not raw:
        return _DEFAULT_TRAVEL_MINUTES
    try:
        minutes = int(raw)
    except ValueError:
        logger.warning(
            "KLAUS_TRAVEL_MINUTES_DEFAULT=%r is not an integer; using %d",
            raw, _DEFAULT_TRAVEL_MINUTES,
        )
        return _DEFAULT_TRAVEL_MINUTES
    if minutes < 0:
        logger.warning(
            "KLAUS_TRAVEL_MINUTES_DEFAULT=%d is negative; using %d",
            minutes, _DEFAULT_TRAVEL_MINUTES,
        )
        return _DEFAULT_TRAVEL_MINUTES
    return minutes


def _today_departure_windows(calendar: dict) -> dict:
    """Attach leave_by + get_ready_at to timed events that have a location.

    TIME-05. This used to call the Google Routes API per located event, behind a
    persisted cache and a 25/day cost breaker. That was a lot of moving parts to
    produce one number for a fixed commute, so travel time is now configuration.

    The output contract is deliberately unchanged: the Hub renders these two
    fields, and `core.routines.alerts` raises the "leave now" push off
    leave_by. That alert has no LLM in the loop, so nothing else can produce it.

    Returns the same calendar dict, mutated in place. Per-event errors are
    swallowed — one unparseable start time must not prevent the rest of the
    calendar from rendering.
    """
    from datetime import datetime as _dt, timedelta as _td

    travel_minutes = _configured_travel_minutes()
    try:
        for ev in calendar.get("timed", []):
            if not ev.get("location"):
                continue
            start_iso = ev.get("start", "")
            if not start_iso:
                continue
            try:
                start_dt = _dt.fromisoformat(start_iso)
            except ValueError:
                logger.warning(
                    "_today_departure_windows: unparseable start %r for event %s",
                    start_iso, ev.get("id", ""),
                )
                continue
            leave_by_dt = start_dt - _td(minutes=travel_minutes)
            ev["leave_by"] = leave_by_dt.isoformat()
            ev["get_ready_at"] = (
                leave_by_dt - _td(minutes=_GET_READY_MINUTES)
            ).isoformat()
        return calendar
    except Exception:
        logger.warning("_today_departure_windows() failed", exc_info=True)
        return calendar


def _today_nutrition_totals(today_iso: str) -> dict:
    """Fetch today's nutrition running totals for the glance rail.

    TIME-08: uses MealStore.get_day_aggregate() to get server-computed totals.
    Returns {kcal, protein_g, carbs_g, fat_g, fiber_g} or {} when no meals logged.
    """
    try:
        from memory.firestore_db import MealStore  # lazy import
        store = MealStore(
            project_id=os.environ.get("GCP_PROJECT_ID", ""),
            database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
        )
        agg = store.get_day_aggregate(today_iso)
        totals = agg.get("totals", {}) if agg else {}
        # Always return all five keys as numbers (default 0). A missing key or a
        # None value crashes the hub's NutritionStrip (.toFixed on undefined),
        # which blanks the whole SPA on a fresh day before any meal is logged.
        return {
            "kcal": totals.get("calories") or 0,
            "protein_g": totals.get("protein_g") or 0,
            "carbs_g": totals.get("carbs_g") or 0,
            "fat_g": totals.get("fat_g") or 0,
            "fiber_g": totals.get("fiber_g") or 0,
        }
    except Exception:
        logger.warning("_today_nutrition_totals(%r) failed", today_iso, exc_info=True)
        return {"kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": 0}
