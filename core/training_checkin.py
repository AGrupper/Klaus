"""Training check-in — evidence-first daily session logging.

Called from core/proactive_alerts.run_proactive_alerts (D-09) before the
_already_sent gate so a same-evening retry is not blocked (Pitfall 5).

Flow:
  1. Silent Garmin sync — write training_log entries for today's Garmin
     activities that have a perceived_exertion (source="garmin", no Telegram).
  2. Fetch Training calendar events for today via GoogleCalendarManager.
  3. Time-gate per D-07: only events whose start has passed.
  4. For each unlogged event, branch:
       - Log entry exists with rpe or source="garmin" → covered, silent.
       - Garmin activity covers event (D-10 ±30-min window + type match)
         but no RPE → send RPE keyboard (state "awaiting_rpe").
       - No Garmin record → send watch-off keyboard (state "awaiting_watchoff").
  5. Send a check-in intro message only when at least one prompt is needed.

Callback handlers (dispatched by interfaces/_router.py):
  - handle_rpe_callback  — button tap on the RPE picker
  - handle_watchoff_callback — button tap on watch-off branch
  - handle_skipreason_callback — button tap on skip-reason picker
  - attach_note — called when user replies to a notes prompt
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# compute_acwr_from_db imported at module level so tests can patch it
# (garmin_tool is heavy; the actual Garmin client is only built on first call)
from mcp_tools.garmin_tool import compute_acwr_from_db  # noqa: F401 (used in compute_recovery_concern)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Constants (D-10, RESEARCH Finding 6)                               #
# ------------------------------------------------------------------ #

_TZ = ZoneInfo("Asia/Jerusalem")

_MATCH_BUFFER_MINUTES = 30   # D-10: Garmin activity within ±30 min of event window

_ACTIVITY_TYPE_MAP: dict[str, set[str] | None] = {
    "run":           {"running", "trail_running", "treadmill_running", "indoor_track"},
    "gym":           {"strength_training", "fitness_equipment", "indoor_cycling"},
    "basketball":    {"basketball", "court_sports", "other"},
    "bike":          {"cycling", "mountain_biking", "indoor_cycling", "road_biking"},
    "five fingers":  None,   # D-03: watch-off by definition → always watch-off branch
}

# Error copy from UI-SPEC line 258 (T-20-08/T-20-09 stale-session rejection)
_SESSION_NOT_FOUND_COPY = (
    "I couldn't match that button to an open session, sir. "
    "The log entry may have already been closed. "
    "Reply with your RPE and I'll update the log."
)


# ------------------------------------------------------------------ #
# Recovery concern thresholds (RECOVERY-02, Phase 20 Plan 05)        #
# ------------------------------------------------------------------ #

RECOVERY_THRESHOLDS = {
    # v0 heuristics — tune after ~2 weeks of journaled training_log + biometrics data.
    # Keys map to severity levels ("mild" or "strong"). RECOVERY-02.
    "acwr_mild":   1.5,   # ACWR >= 1.5 + any high-intensity session today → mild
    "acwr_strong": 1.8,   # ACWR >= 1.8 + high-intensity → strong
    "sleep_low":   70,    # Garmin sleep score < 70 (D-15)
    "consecutive_low_sleep_nights": 2,        # 2 consecutive nights below sleep_low (D-15)
    "intensity_keywords_high": ("heavy", "intervals", "speed", "long run", "hiit"),
    "intensity_keywords_moderate": ("gym", "run", "bike", "five fingers"),
    "hrv_flag_values": ("unbalanced", "low"),  # Garmin HRV status strings (A4 assumption)
}


def _recent_sleep_scores(today_iso: str, n: int = 2) -> list[int | None]:
    """Read the last n nights' sleep scores from Postgres daily_biometrics.

    Open Question 3 (RESEARCH): use Postgres, NOT a second Garmin call.
    Returns a list of sleep scores (may be None per row) or [] on any failure.
    Mirrors compute_acwr_from_db lazy psycopg2 import + never-raises sentinel.

    Args:
        today_iso: YYYY-MM-DD reference date (today; reads nights ending on or before today).
        n: number of nights to fetch (default 2 for consecutive-sleep check).
    """
    try:
        import psycopg2
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("PG_CONNECTION_STRING")
        if not dsn:
            return []
        from datetime import date, timedelta
        today = date.fromisoformat(today_iso)
        cutoff = (today - timedelta(days=n)).isoformat()
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date, sleep_score FROM daily_biometrics "
                    "WHERE date >= %s ORDER BY date DESC LIMIT %s",
                    (cutoff, n),
                )
                rows = cur.fetchall()
        return [r[1] for r in rows]  # list of sleep_score values (may include None)
    except Exception:
        logger.warning("_recent_sleep_scores failed", exc_info=True)
        return []


def _classify_intensity(events: list[dict]) -> str:
    """Classify today's planned intensity from event titles (D-14).

    Returns "high", "moderate", or "none".
    - Empty events list → "none" (no workout planned; no concern triggered).
    - Event with no matching keyword → "moderate" (unknown → moderate per D-14).

    Args:
        events: list of Training calendar event dicts with "summary" key.
    """
    if not events:
        return "none"   # no Training events today → no workout, no concern

    titles = " ".join(
        (e.get("summary") or "").lower() for e in events
    )
    for keyword in RECOVERY_THRESHOLDS["intensity_keywords_high"]:
        if keyword.lower() in titles:
            return "high"
    for keyword in RECOVERY_THRESHOLDS["intensity_keywords_moderate"]:
        if keyword.lower() in titles:
            return "moderate"
    return "moderate"  # D-14: unknown title → moderate


def compute_recovery_concern(
    garmin_data: dict | None,
    today_iso: str,
) -> dict | None:
    """Compute a recovery concern flag from ACWR, HRV, sleep, and today's training intensity.

    Implements D-12 mild/strong severity logic (RECOVERY-01):
      - Calls compute_acwr_from_db() for ACWR ratio (lazy, never-raises sentinel).
      - Reads HRV status + sleep score from garmin_data (already fetched by caller).
      - Reads consecutive nights' sleep from Postgres via _recent_sleep_scores
        (Open Q3: no second Garmin call, uses daily_biometrics table).
      - Classifies today's planned intensity from Training calendar events (D-14).

    Severity rules (D-12):
      strong: (ACWR >= acwr_strong AND intensity == "high")
              OR (HRV flagged AND sleep_score < sleep_low AND intensity == "high")
      mild:   (ACWR >= acwr_mild AND intensity in {"high", "moderate"})
              OR (>= consecutive_low_sleep_nights nights below sleep_low
                  AND intensity in {"high", "moderate"})
      None:   none of the above

    Returns:
        None when no trigger is found (D-13 silent omit — the prompt relies on
        the key being absent when there is no concern).
        dict with keys: level, acwr, hrv_status, sleep_score, intensity
        when a concern is triggered. No prescriptive numeric targets (D-13).

    Args:
        garmin_data: dict from fetch_garmin_today (may be None or have state=2).
        today_iso:   YYYY-MM-DD reference date.
    """
    thresholds = RECOVERY_THRESHOLDS

    # 1. Classify today's planned intensity (D-14); best-effort on calendar failure.
    try:
        today_events = _get_todays_training_events(today_iso)
    except Exception:
        logger.warning("compute_recovery_concern: calendar fetch failed", exc_info=True)
        today_events = []
    intensity = _classify_intensity(today_events)

    # 2. ACWR ratio (module-level import, never-raises sentinel).
    acwr_result = compute_acwr_from_db()
    ratio = acwr_result.get("ratio")  # None when insufficient baseline

    # 3. HRV status + sleep score from garmin_data (already fetched by caller).
    garmin = garmin_data or {}
    hrv_status = (garmin.get("hrv_status") or "").lower()
    sleep_score = garmin.get("sleep_score")  # int or None

    # 4. Consecutive-sleep Postgres read (Open Q3 — no 2nd Garmin call).
    recent_scores = _recent_sleep_scores(today_iso, n=thresholds["consecutive_low_sleep_nights"])

    # 5. Determine severity (D-12).
    hrv_flagged = hrv_status in thresholds["hrv_flag_values"]
    sleep_low = thresholds["sleep_low"]
    acwr_mild = thresholds["acwr_mild"]
    acwr_strong = thresholds["acwr_strong"]
    consec_nights = thresholds["consecutive_low_sleep_nights"]

    # Count consecutive low-sleep nights (recent_scores is ordered DESC by date).
    low_sleep_nights = sum(
        1 for s in recent_scores
        if s is not None and s < sleep_low
    )
    has_consecutive_low_sleep = low_sleep_nights >= consec_nights

    level: str | None = None

    # No concern when no training events today (rest day).
    if intensity == "none":
        return None

    # Strong trigger.
    if intensity == "high":
        if (ratio is not None and ratio >= acwr_strong):
            level = "strong"
        elif (hrv_flagged and sleep_score is not None and sleep_score < sleep_low):
            level = "strong"

    # Mild trigger (only if not already strong).
    if level is None and intensity in ("high", "moderate"):
        if (ratio is not None and ratio >= acwr_mild):
            level = "mild"
        elif has_consecutive_low_sleep:
            level = "mild"

    if level is None:
        return None

    return {
        "level": level,
        "acwr": ratio,
        "hrv_status": garmin.get("hrv_status"),
        "sleep_score": sleep_score,
        "intensity": intensity,
    }


# ------------------------------------------------------------------ #
# Helpers — Firestore stores                                         #
# ------------------------------------------------------------------ #

def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _mfc(project_id, database)


def TrainingLogStore():  # noqa: N802  (factory, intentionally named like a class for test-patchability)
    from memory.firestore_db import TrainingLogStore as _TLS
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _TLS(project_id, database)


def PendingPromptStore():  # noqa: N802
    from memory.firestore_db import PendingPromptStore as _PPS
    from memory.firestore_db import _pending_expiry
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _PPS(project_id, database)


def _pending_expiry(hours: int = 20):
    """Return (created_at_iso, expires_at_iso) for a new pending session.

    Mirrors memory.firestore_db._pending_expiry but importable without a
    live Firestore client (so run_training_checkin can be called from tests
    that stub at the module level without triggering google.api_core imports).
    """
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    return now.isoformat(), (now + timedelta(hours=hours)).isoformat()


# ------------------------------------------------------------------ #
# Helpers — send_and_inject                                          #
# ------------------------------------------------------------------ #

async def send_and_inject(bot, text, *, inject_into_conversation=False, reply_markup=None):
    from core.scheduled_message import send_and_inject as _sai
    return await _sai(bot, text, inject_into_conversation=inject_into_conversation, reply_markup=reply_markup)


# ------------------------------------------------------------------ #
# Helpers — GoogleCalendarManager                                    #
# ------------------------------------------------------------------ #

def GoogleCalendarManager():  # noqa: N802 (factory function)
    from core.tools import _get_calendar_tool
    return _get_calendar_tool()


# ------------------------------------------------------------------ #
# Helpers — fetch_garmin_activities                                  #
# ------------------------------------------------------------------ #

def fetch_garmin_activities(days: int = 1):
    from mcp_tools.garmin_tool import fetch_garmin_activities as _fga
    return _fga(days)


# ------------------------------------------------------------------ #
# Inline keyboard builders (UI-SPEC + RESEARCH Finding 1)            #
# ------------------------------------------------------------------ #

def _rpe_keyboard(session_key: str):
    """Two rows of 5 RPE buttons (D-26).

    Row 1: 1–5, Row 2: 6–10.
    Callback data: rpe:{session_key}:{value}
    """
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"rpe:{session_key}:{i}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"rpe:{session_key}:{i}") for i in range(6, 11)],
    ])


def _watchoff_keyboard(session_key: str):
    """Watch-off branch: did-it or skipped (D-08).

    Callback data: watchoff:{session_key}:done / watchoff:{session_key}:skipped
    """
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Did it — watch was off", callback_data=f"watchoff:{session_key}:done"),
        InlineKeyboardButton("Skipped", callback_data=f"watchoff:{session_key}:skipped"),
    ]])


def _skipreason_keyboard(session_key: str):
    """Skip-reason picker: 4 structured reason buttons (D-08b).

    Callback data: skipreason:{session_key}:{reason_key}
    """
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Rest / recovery", callback_data=f"skipreason:{session_key}:rest_recovery"),
            InlineKeyboardButton("Sick / injured",  callback_data=f"skipreason:{session_key}:sick_injured"),
        ],
        [
            InlineKeyboardButton("Too busy", callback_data=f"skipreason:{session_key}:too_busy"),
            InlineKeyboardButton("Other — tell me", callback_data=f"skipreason:{session_key}:other"),
        ],
    ])


# ------------------------------------------------------------------ #
# D-10: Garmin activity coverage check                               #
# ------------------------------------------------------------------ #

def _activity_type_matches_event(garmin_type: str, event_summary: str) -> bool:
    """Return True if a Garmin activity type loosely matches the event summary.

    Matches by checking whether any keyword from _ACTIVITY_TYPE_MAP appears
    in the event summary (case-insensitive).  If the matched keyword maps to
    None (five fingers), returns False — five fingers is always watch-off.

    Unknown event summaries (no keyword match) → True (treat as covered).
    This implements D-14: unknown → moderate (we assume the activity covers it).
    """
    summary_lower = event_summary.lower()
    for keyword, garmin_types in _ACTIVITY_TYPE_MAP.items():
        if keyword in summary_lower:
            if garmin_types is None:
                return False   # five fingers → watch-off by definition (D-03)
            return garmin_type.lower() in garmin_types
    # Unknown event type (D-14: no keyword matched) → treat as covered
    return True


def _garmin_covers(event: dict, activities: list[dict]) -> dict | None:
    """Return the first Garmin activity that covers this event (D-10), or None.

    Coverage: activity start within (event_start - buffer, event_end + buffer)
    AND type loosely matches (via _ACTIVITY_TYPE_MAP).

    Args:
        event:      Training calendar event dict (id, summary, start, end).
        activities: List of today's Garmin activity dicts.

    Returns:
        The matching activity dict, or None if no match.
    """
    from datetime import timedelta
    buffer = _MATCH_BUFFER_MINUTES * 60  # seconds

    try:
        event_start = datetime.fromisoformat(event["start"])
        event_end = datetime.fromisoformat(event["end"])
    except (KeyError, ValueError):
        return None

    # Make timezone-aware if naive
    if event_start.tzinfo is None:
        event_start = event_start.replace(tzinfo=_TZ)
    if event_end.tzinfo is None:
        event_end = event_end.replace(tzinfo=_TZ)

    window_start = event_start - timedelta(seconds=buffer)
    window_end = event_end + timedelta(seconds=buffer)

    for act in activities:
        act_date_str = act.get("date") or ""
        try:
            act_dt = datetime.fromisoformat(act_date_str)
        except ValueError:
            continue
        if act_dt.tzinfo is None:
            act_dt = act_dt.replace(tzinfo=_TZ)

        if not (window_start <= act_dt <= window_end):
            continue

        garmin_type = act.get("type", "unknown")
        event_summary = event.get("summary", "")
        if _activity_type_matches_event(garmin_type, event_summary):
            return act

    return None


# ------------------------------------------------------------------ #
# Session key helper                                                 #
# ------------------------------------------------------------------ #

def _slot_for(event: dict) -> str:
    """Return a stable slot identifier for the training event.

    Preference order: event["id"] (Google Calendar event ID),
    fallback: start truncated to YYYYMMDDHHmm.
    """
    event_id = event.get("id", "")
    if event_id:
        return event_id
    start = event.get("start", "")
    try:
        dt = datetime.fromisoformat(start)
        return dt.strftime("%Y%m%d%H%M")
    except ValueError:
        return start[:16].replace("-", "").replace("T", "").replace(":", "")


# ------------------------------------------------------------------ #
# Silent Garmin sync (Pattern-C best-effort)                         #
# ------------------------------------------------------------------ #

def _silent_garmin_sync(today_iso: str) -> None:
    """Silently sync today's Garmin activities with RPE to training_log.

    Best-effort: swallows all exceptions.  No Telegram messages sent.
    Source is always "garmin" (CHECKIN-02).

    RPE normalisation (Pitfall 7) is handled inside TrainingLogStore.log_session.

    Args:
        today_iso: YYYY-MM-DD for today's date.
    """
    try:
        activities = fetch_garmin_activities(1)
        store = TrainingLogStore()
        for act in activities:
            perceived_exertion = act.get("perceived_exertion")
            if perceived_exertion is None:
                continue
            act_date_str = (act.get("date") or "")[:10]  # keep only YYYY-MM-DD
            if act_date_str != today_iso:
                continue
            activity_id = str(act.get("activity_id", ""))
            store.log_session(
                date=today_iso,
                slot=activity_id,
                session_type=act.get("type"),
                planned=False,
                completed=True,
                rpe=perceived_exertion,
                feel=act.get("feel"),
                source="garmin",
                garmin_activity_id=activity_id,
            )
    except Exception:
        logger.warning("training_checkin: silent Garmin sync failed", exc_info=True)


# ------------------------------------------------------------------ #
# Calendar helper                                                    #
# ------------------------------------------------------------------ #

def _get_todays_training_events(today_iso: str) -> list[dict]:
    """Fetch today's Training calendar events (filtered of buffer blocks by calendar_tool).

    Returns [] on any error.
    """
    try:
        mgr = GoogleCalendarManager()
        time_min = f"{today_iso}T00:00:00+03:00"
        time_max = f"{today_iso}T23:59:59+03:00"
        return mgr.list_training_events(time_min, time_max)
    except Exception:
        logger.warning("training_checkin: calendar fetch failed", exc_info=True)
        return []


# ------------------------------------------------------------------ #
# Public entry point                                                 #
# ------------------------------------------------------------------ #

async def run_training_checkin(bot, today_iso: str) -> None:
    """Sync Garmin, scan Training calendar, prompt for unlogged workouts.

    Called from core/proactive_alerts.run_proactive_alerts after its own
    data gathering, BEFORE the _already_sent gate (Pitfall 5 / D-09).
    Idempotent via TrainingLogStore merge=True (Pitfall 4).

    Args:
        bot:       Telegram Bot instance.
        today_iso: YYYY-MM-DD for today (passed from proactive_alerts so both
                   use the same date reference).
    """
    # Step 1: Silent Garmin sync (best-effort, no Telegram)
    _silent_garmin_sync(today_iso)

    # Step 2: Fetch Training calendar events for today
    events = _get_todays_training_events(today_iso)
    if not events:
        logger.info("training_checkin: no training events for %s — silent", today_iso)
        return

    # Step 3: Read existing log entries for today, keyed by slot
    store = TrainingLogStore()
    logged_entries = store.get_by_date(today_iso)
    logged_by_slot: dict[str, dict] = {}
    for entry in logged_entries:
        slot = entry.get("slot") or entry.get("doc_id", "").split("_", 1)[-1]
        logged_by_slot[slot] = entry

    # Step 4: Fetch today's Garmin activities for D-10 matching
    try:
        garmin_activities = fetch_garmin_activities(1)
    except Exception:
        logger.warning("training_checkin: Garmin activities fetch failed for matching", exc_info=True)
        garmin_activities = []

    # D-07: time-gate — only prompt about past-start workouts
    now = datetime.now(_TZ)

    pending_store = PendingPromptStore()
    user_id_str = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "0").split(",")[0].strip()
    try:
        user_id = int(user_id_str)
    except ValueError:
        user_id = 0

    prompts_to_send: list[dict] = []   # collect what needs prompting

    for event in events:
        slot = _slot_for(event)
        session_key = f"{today_iso}_{slot}"

        # D-07: skip if event has not started yet
        try:
            event_start = datetime.fromisoformat(event["start"])
        except (KeyError, ValueError):
            continue
        if event_start.tzinfo is None:
            event_start = event_start.replace(tzinfo=_TZ)
        if event_start > now:
            logger.debug("training_checkin: skipping future event %s", event.get("summary"))
            continue

        # Check if already covered (existing log entry with rpe, or garmin source)
        existing = logged_by_slot.get(slot)
        if existing:
            if existing.get("rpe") is not None or existing.get("source") == "garmin":
                logger.debug("training_checkin: %s covered by existing log", slot)
                continue

        # D-10: check if a Garmin activity covers this event
        covering_activity = _garmin_covers(event, garmin_activities)

        if covering_activity:
            # Garmin covers; check RPE
            if covering_activity.get("perceived_exertion") is not None:
                # RPE present → already handled by silent sync — covered
                logger.debug("training_checkin: %s covered by Garmin RPE", slot)
                continue
            else:
                # Garmin record but no RPE → prompt for RPE
                prompts_to_send.append({
                    "type": "rpe",
                    "event": event,
                    "slot": slot,
                    "session_key": session_key,
                })
        else:
            # No Garmin record → watch-off branch
            prompts_to_send.append({
                "type": "watchoff",
                "event": event,
                "slot": slot,
                "session_key": session_key,
            })

    if not prompts_to_send:
        logger.info("training_checkin: all workouts covered for %s — silent", today_iso)
        return

    # Step 5: Send check-in intro + keyboards (CHECKIN-05: only when needed)
    count = len(prompts_to_send)
    if count == 1:
        intro = "Good evening, sir. One item to close out the training log."
    else:
        intro = f"Good evening, sir. A couple of items to log before the day closes."

    await send_and_inject(bot, intro, inject_into_conversation=False)

    for prompt in prompts_to_send:
        event = prompt["event"]
        session_key = prompt["session_key"]
        slot = prompt["slot"]
        workout_name = event.get("summary", "your workout")

        created_at, expires_at = _pending_expiry()
        base_payload = {
            "user_id": user_id,
            "event_summary": workout_name,
            "event_date": today_iso,
            "created_at": created_at,
            "expires_at": expires_at,
        }

        if prompt["type"] == "rpe":
            kb = _rpe_keyboard(session_key)
            text = (
                f"How did {workout_name} feel? "
                "Rate your effort: 1 = easy · 10 = max effort"
            )
            msg = await send_and_inject(
                bot, text, inject_into_conversation=False, reply_markup=kb
            )
            msg_id = msg.message_id if msg else None
            pending_store.set(session_key, {
                **base_payload,
                "state": "awaiting_rpe",
                "message_id": msg_id,
            })
        else:  # watchoff
            kb = _watchoff_keyboard(session_key)
            text = f"No Garmin record for {workout_name}. What happened?"
            msg = await send_and_inject(
                bot, text, inject_into_conversation=False, reply_markup=kb
            )
            msg_id = msg.message_id if msg else None
            pending_store.set(session_key, {
                **base_payload,
                "state": "awaiting_watchoff",
                "message_id": msg_id,
            })


# ------------------------------------------------------------------ #
# Callback handlers (dispatched by interfaces/_router.py)            #
# ------------------------------------------------------------------ #

async def handle_rpe_callback(orchestrator, user_id: int, cq, data: str) -> None:
    """Handle an RPE button tap from the inline keyboard.

    Parses rpe:{session_key}:{value}, validates the session via PendingPromptStore,
    logs the RPE, then sends the notes follow-up prompt.

    T-20-08/T-20-09: if session is None (expired or forged) → send error copy,
    no log write.

    Args:
        orchestrator: AgentOrchestrator (provides bot access).
        user_id:      Telegram user ID (allow-list already enforced by router).
        cq:           CallbackQuery (for bot access via cq.message).
        data:         Raw callback_data string "rpe:{session_key}:{value}".
    """
    try:
        parts = data.split(":", 2)
        if len(parts) < 3:
            return
        _, session_key, value_str = parts

        # T-20-08: validate session before any write
        pps = PendingPromptStore()
        session = pps.get(session_key)
        if session is None:
            bot = _bot_from_orchestrator_or_cq(orchestrator, cq)
            await send_and_inject(bot, _SESSION_NOT_FOUND_COPY, inject_into_conversation=False)
            return

        rpe_value = int(value_str)
        event_date = session.get("event_date", session_key.split("_")[0])

        # Write RPE to training_log (source=telegram)
        tls = TrainingLogStore()
        tls.log_session(
            date=event_date,
            slot=session_key.split("_", 1)[1] if "_" in session_key else session_key,
            session_type=session.get("session_type"),
            planned=True,
            completed=True,
            rpe=rpe_value,
            source="telegram",
        )

        # Send notes follow-up prompt (D-05)
        bot = _bot_from_orchestrator_or_cq(orchestrator, cq)
        notes_text = (
            f"Logged — RPE {rpe_value}. "
            "Anything to note about that session? "
            "Reply to this message, or /skip."
        )
        msg = await send_and_inject(bot, notes_text, inject_into_conversation=False)
        msg_id = msg.message_id if msg else None

        # Transition state → awaiting_notes
        pps.set(session_key, {
            **session,
            "state": "awaiting_notes",
            "message_id": msg_id,
            "rpe": rpe_value,
        })

    except Exception:
        logger.warning("handle_rpe_callback: unexpected error", exc_info=True)


async def handle_watchoff_callback(orchestrator, user_id: int, cq, data: str) -> None:
    """Handle a watch-off button tap.

    "done" → send RPE keyboard (state awaiting_rpe).
    "skipped" → send skip-reason keyboard (state awaiting_skipreason).

    T-20-08: if session is None → send error copy, no action.

    Args:
        orchestrator: AgentOrchestrator.
        user_id:      Telegram user ID.
        cq:           CallbackQuery.
        data:         "watchoff:{session_key}:done" or "watchoff:{session_key}:skipped".
    """
    try:
        parts = data.split(":", 2)
        if len(parts) < 3:
            return
        _, session_key, value = parts

        pps = PendingPromptStore()
        session = pps.get(session_key)
        if session is None:
            bot = _bot_from_orchestrator_or_cq(orchestrator, cq)
            await send_and_inject(bot, _SESSION_NOT_FOUND_COPY, inject_into_conversation=False)
            return

        bot = _bot_from_orchestrator_or_cq(orchestrator, cq)
        workout_name = session.get("event_summary", "your workout")

        if value == "done":
            # Watch was off but workout done → ask for RPE
            kb = _rpe_keyboard(session_key)
            text = (
                f"Got it — {workout_name} done. "
                "Rate your effort: 1 = easy · 10 = max effort"
            )
            msg = await send_and_inject(bot, text, inject_into_conversation=False, reply_markup=kb)
            msg_id = msg.message_id if msg else None
            pps.set(session_key, {**session, "state": "awaiting_rpe", "message_id": msg_id})

        elif value == "skipped":
            # Skipped → ask for reason
            kb = _skipreason_keyboard(session_key)
            text = "Got it. What was the reason?"
            msg = await send_and_inject(bot, text, inject_into_conversation=False, reply_markup=kb)
            msg_id = msg.message_id if msg else None
            pps.set(session_key, {**session, "state": "awaiting_skipreason", "message_id": msg_id})

    except Exception:
        logger.warning("handle_watchoff_callback: unexpected error", exc_info=True)


async def handle_skipreason_callback(orchestrator, user_id: int, cq, data: str) -> None:
    """Handle a skip-reason button tap.

    Structured reasons (rest_recovery / sick_injured / too_busy):
      → log completed=False + skipped_reason → PendingPromptStore.delete (Pitfall 3 terminal).

    "other":
      → send free-text request → set state awaiting_skipreason_other (not terminal yet).

    T-20-08: if session is None → send error copy, no write.

    Args:
        orchestrator: AgentOrchestrator.
        user_id:      Telegram user ID.
        cq:           CallbackQuery.
        data:         "skipreason:{session_key}:{reason_key}".
    """
    try:
        parts = data.split(":", 2)
        if len(parts) < 3:
            return
        _, session_key, reason_key = parts

        pps = PendingPromptStore()
        session = pps.get(session_key)
        if session is None:
            bot = _bot_from_orchestrator_or_cq(orchestrator, cq)
            await send_and_inject(bot, _SESSION_NOT_FOUND_COPY, inject_into_conversation=False)
            return

        bot = _bot_from_orchestrator_or_cq(orchestrator, cq)
        event_date = session.get("event_date", session_key.split("_")[0])

        _STRUCTURED_REASONS = {"rest_recovery", "sick_injured", "too_busy"}
        if reason_key in _STRUCTURED_REASONS:
            # Terminal: log + delete (Pitfall 3)
            tls = TrainingLogStore()
            tls.log_session(
                date=event_date,
                slot=session_key.split("_", 1)[1] if "_" in session_key else session_key,
                session_type=session.get("session_type"),
                planned=True,
                completed=False,
                skipped_reason=reason_key,
                source="telegram",
            )
            pps.delete(session_key)

        elif reason_key == "other":
            # Non-terminal: ask for free-text, transition state
            msg = await send_and_inject(
                bot,
                "No problem. What got in the way? Reply with a note.",
                inject_into_conversation=False,
            )
            msg_id = msg.message_id if msg else None
            pps.set(session_key, {
                **session,
                "state": "awaiting_skipreason_other",
                "message_id": msg_id,
            })

    except Exception:
        logger.warning("handle_skipreason_callback: unexpected error", exc_info=True)


async def attach_note(orchestrator, user_id: int, session: dict, note_text: str) -> None:
    """Attach a user's note text to the training log entry.

    Called by the router when the user replies to a notes prompt (D-05 reply-to path).
    Writes the note via log_session (merge=True preserves RPE/other fields — D-11),
    then deletes the pending session (Pitfall 3 terminal transition).

    Args:
        orchestrator: AgentOrchestrator.
        user_id:      Telegram user ID.
        session:      The pending_prompts document dict (may be empty/malformed).
        note_text:    The user's reply text.
    """
    try:
        session_key = session.get("session_key", "")
        if not session_key:
            logger.warning("attach_note: session missing session_key — skipping")
            return

        event_date = session.get("event_date", session_key.split("_")[0])

        tls = TrainingLogStore()
        tls.log_session(
            date=event_date,
            slot=session_key.split("_", 1)[1] if "_" in session_key else session_key,
            session_type=session.get("session_type"),
            planned=True,
            completed=True,
            notes=note_text,
            source="telegram",
        )

        # Terminal: delete pending session (Pitfall 3)
        pps = PendingPromptStore()
        pps.delete(session_key)

    except Exception:
        logger.warning("attach_note: unexpected error", exc_info=True)


# ------------------------------------------------------------------ #
# D-05: /skip command path                                           #
# ------------------------------------------------------------------ #

async def handle_skip_note(bot, session_key: str) -> None:
    """Handle /skip when user wants to dismiss the notes follow-up.

    Deletes the pending session, leaving the RPE-only entry valid.
    Called inline when the brain or router detects /skip while an
    awaiting_notes session is open.

    Args:
        bot:         Telegram Bot instance.
        session_key: The pending_prompts document ID.
    """
    try:
        pps = PendingPromptStore()
        pps.delete(session_key)
        logger.info("training_checkin: notes skipped for %s", session_key)
    except Exception:
        logger.warning("handle_skip_note: unexpected error", exc_info=True)


# ------------------------------------------------------------------ #
# Utility: bot extraction from orchestrator or cq                    #
# ------------------------------------------------------------------ #

def _bot_from_orchestrator_or_cq(orchestrator, cq):
    """Return the Bot instance from orchestrator or callback query.

    Tries orchestrator.bot first (process singleton), falls back to
    cq.message.get_bot() or cq.get_bot() if available.
    """
    bot = getattr(orchestrator, "bot", None)
    if bot is not None:
        return bot
    # Fallback: extract from callback query message
    try:
        return cq.message.get_bot()
    except Exception:
        pass
    try:
        return cq.get_bot()
    except Exception:
        pass
    return orchestrator  # last resort — caller will surface the error
