# Phase 20: Accountability Crons & Recovery Briefing — Research

**Researched:** 2026-05-31
**Domain:** Telegram inline keyboards + Firestore state persistence + Google Calendar calendarList + Cloud Scheduler + Recovery heuristics
**Confidence:** HIGH

---

## Summary

Phase 20 is a largely additive phase: it introduces the first interactive Telegram inline-keyboard flow Klaus has ever sent (net-new infrastructure), folds training check-in logic into the existing proactive-alerts cron (no new cron trigger required for check-in), adds a new weekly-review cron, and wires recovery data into two existing prompts. The most technically novel territory is the callback_query dispatch path and the pending-prompt state store — nothing analogous exists anywhere in the codebase today.

The existing patterns for cron routes (`_verify_cron_request`, `_log_cron_run`, lazy module import, `_application` guard), Firestore stores (`UserProfileStore`, `JournalStore`, `MealStore` as templates), tool registration (SMART_AGENT_DIRECT_TOOLS frozenset + TOOL_SCHEMAS + WORKER_TOOL_SCHEMAS exclusion + _HANDLERS lambda), and brain-composition crons (`core/reflection.py`) are all mature and directly reusable for Phase 20.

The webhook currently registers `allowed_updates=["message"]` (DEPLOYMENT.md line 489). This MUST be extended to include `"callback_query"` before any inline-keyboard button press reaches the server — without this change the Telegram Bot API silently swallows all button-tap events. The `_router.handle_update` line 65 (`if update.message is None: return`) MUST be patched to dispatch `callback_query` events before any check-in can work end-to-end.

**Primary recommendation:** Implement in this order: (1) `TrainingLogStore` + `PendingPromptStore` in `memory/firestore_db.py`, (2) `send_and_inject` extension for `reply_markup`, (3) router extension for `callback_query` + reply-to detection, (4) training-calendar read path in `calendar_tool.py`, (5) `core/training_checkin.py` module, (6) fold into `proactive_alerts.py`, (7) recovery flag in `morning_briefing.py`, (8) weekly-review cron, (9) bootstrap script + DEPLOYMENT.md.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Training calendar resolved by NAME ("Training") via calendarList lookup — not hardcoded ID
- D-02: Buffer events filtered by title prefix "Get Ready:" (and defensively "Travel:"); all other calendar events are trackable workouts
- D-03: Five Fingers (Wed/Sun) tracked as workout — watch-off/RPE branch
- D-04: Training calendar created but empty at discussion time — forward-only, no backfill
- D-05: Notes step "open until you reply" — native reply-to attaches note; `/skip` dismisses; brain decides from injected context if user sends free text without reply-to
- D-06: One training_log entry per session, keyed by calendar event ID / start time (not just date)
- D-07: Time-gate — at 21:30 only prompt about planned workouts whose scheduled start has already passed
- D-08: Watch-off branch: "Did it — watch was off" → ask RPE; "Skipped" → skip-reason buttons
- D-08b: Skip-reason buttons: Rest/recovery, Sick/injured, Too busy, Other→free text
- D-09 (DEVIATION): Separate 21:00 /cron/training-checkin and klaus-training-checkin job are REPLACED by folding check-in into existing 21:30 proactive-alerts cron. CHECKIN-01/06 and CRON-01 wording must be reconciled.
- D-10: Garmin covers planned event when activity start falls within event window (± buffer) AND type loosely matches. "RPE present" = perceived_exertion (from directWorkoutRpe) is non-null
- D-11: One entry per session; Garmin owns objective fields; manual reply fills gaps; Garmin wins on direct conflict
- D-12: Severity levels mild/strong (not bare boolean); RECOVERY_THRESHOLDS dict
- D-13: Tone shift + qualitative metric-anchored prescription; no invented numeric targets; empty profile → no fabrication
- D-14: Intensity classified by event-title keyword (heavy, long run, intervals, type defaults); unknown → moderate
- D-15: Consecutive-low-sleep rule: 2 nights sleep_score < 70 + intense session today
- D-16: recovery_concern surfaced in BOTH morning_briefing.md and proactive_alert.md equally
- D-17: Weekly review brain-composed (gemini-3.5-flash); trivial cost
- D-18: Format = emoji/bullet scorecard; no monospace tables
- D-19: Depth = richer coaching narrative + scorecard
- D-20: One suggestion grounded in actual data, JARVIS voice, no invented targets
- D-21: Nutrition source = raw MealStore 7-day totals; no MealAuditStore built; REVIEW-02 "meal_audits" resolves to live MealStore aggregates + meal_audit.md guidance
- D-22: Trend window = week-over-week (~14 days); this week vs last week
- D-23: Week boundary = previous Sun–Sat (last Sun 00:00 → Sat 23:59)
- D-24: Weekly review always sends even when sparse (intentional departure from morning-recap silent-omit)
- D-25: bootstrap_shifu_crons.sh re-runnable (describe-or-create/update); creates only `klaus-weekly-training-review`
- D-26: RPE inline keyboard = two rows of 5 (1–5 / 6–10)

### Claude's Discretion
- Where callback/pending-prompt state is persisted (Firestore collection shape, TTL)
- How the webhook router is extended to dispatch callback_query (today interfaces/_router.py:65 drops any update with no .message)
- How send_and_inject (core/scheduled_message.py) is extended to accept reply_markup for inline keyboards
- Module layout (core/training_checkin.py vs inline in proactive_alerts.py; TrainingLogStore placement in memory/firestore_db.py)
- Exact buffer-window minutes for D-10 time-overlap matching and the type-synonym map
- Logging/structured-log style (follow existing conventions)
- TDD RED→GREEN commit discipline per project convention

### Deferred Ideas (OUT OF SCOPE)
- Recurring "daily review" skill (carry-over of unanswered prompts)
- MealAuditStore (persisted per-meal critiques)
- Personalized recovery/intensity thresholds
- Personalized prescriptions (specific weights/HR zones/paces)
- Apple Watch / HealthKit workout source
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LOG-01 | TrainingLogStore.log_session(...) writes training_log/{date}_{slot} with date, type, planned, completed, skipped_reason, rpe, feel, notes, source, garmin_activity_id | Firestore store patterns: MealStore, JournalStore, UserProfileStore in memory/firestore_db.py |
| LOG-02 | TrainingLogStore.get_recent(days) and get_by_date(date) return entries for queries | Mirror JournalStore.get_recent / MealStore.get_day pattern |
| LOG-03 | log_training tool registered brain-direct | SMART_AGENT_DIRECT_TOOLS frozenset pattern at tools.py:39; requires 5-site registration |
| LOG-04 | get_training_history tool registered as worker-delegated | WORKER_TOOL_SCHEMAS pattern; excluded from SMART_AGENT_DIRECT_TOOLS |
| CHECKIN-01 | (RECONCILED per D-09) No separate /cron/training-checkin endpoint; logic folds into proactive-alerts handler | Existing /cron/proactive-alerts at web_server.py:350 is the trigger |
| CHECKIN-02 | Cron first silent-syncs Garmin activities with perceived_exertion to training_log | fetch_garmin_activities at garmin_tool.py:286; perceived_exertion at :332 |
| CHECKIN-03 | Sends Telegram only for unlogged planned Calendar workouts; branches into RPE prompt or watch-off | calendar calendarList API for "Training" calendar lookup |
| CHECKIN-04 | RPE prompt uses inline keyboard 1–10 buttons (two rows per D-26) | InlineKeyboardMarkup / InlineKeyboardButton from python-telegram-bot 22.7 |
| CHECKIN-05 | Fully silent when all planned workouts covered | Existing silent-return pattern in proactive_alerts.py |
| CHECKIN-06 | (RECONCILED per D-09) Timing = 21:30 within proactive-alerts, not separate 21:00 cron | No new scheduler job |
| REVIEW-01 | /cron/weekly-training-review endpoint with OIDC auth | Mirror /cron/autonomous-tick at web_server.py:398 |
| REVIEW-02 | (RECONCILED per D-21) Composes from training_log, activities, daily_biometrics, LIVE MealStore 7-day totals + meal_audit.md guidance | MealStore.get_day_aggregate + existing meal_audit.md |
| REVIEW-03 | prompts/weekly_training_review.md exists | New file; brain-composed using LLMClient with SMART_AGENT_* env vars |
| REVIEW-04 | Cron runs at 0 10 * * 0 Asia/Jerusalem | Cloud Scheduler + OIDC pattern from DEPLOYMENT.md §14e |
| RECOVERY-01 | _gather_data() computes recovery_concern from ACWR, HRV, sleep, today's planned intensity | morning_briefing.py:174 _gather_data; compute_acwr_from_db from garmin_tool.py:396 |
| RECOVERY-02 | RECOVERY_THRESHOLDS dict with v0 heuristics and docstring | D-12 severity levels; ACWR>1.5+high-intensity; HRV+sleep rules; consecutive low-sleep |
| RECOVERY-03 | prompts/morning_briefing.md and prompts/proactive_alert.md read recovery_concern | Extend both prompts; D-16 both paths equal weight |
| CRON-01 | (RECONCILED per D-09) bootstrap_shifu_crons.sh creates ONLY klaus-weekly-training-review | Not two jobs — D-09 eliminates training-checkin job |
| CRON-02 | DEPLOYMENT.md gains Phase Shifu section; one new job in inventory table | Mirror §14d/§14e gcloud blocks in DEPLOYMENT.md |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Inline keyboard rendering | Telegram Bot API / Client | — | Telegram renders InlineKeyboardMarkup server-side; Klaus only provides the structure |
| callback_query dispatch | Backend (FastAPI webhook) | — | Telegram POSTs callback_query updates to the same webhook; router must branch on update.callback_query |
| Pending-prompt state (which session a button tap belongs to) | Backend / Firestore | — | State must survive across two HTTP requests (cron that sent keyboard, user button-tap); in-memory won't work on Cloud Run |
| Training check-in logic | Backend (core/training_checkin.py) | proactive_alerts.py orchestrates | Folded into 21:30 cron trigger; own module for testability |
| Garmin silent sync | Backend (training_checkin.py) | Postgres (ACWR source) | fetch_garmin_activities already in garmin_tool.py:286 |
| Training calendar lookup | Backend (calendar_tool.py) | — | calendarList API; new method on GoogleCalendarManager |
| TrainingLogStore | Backend / Firestore | — | Per-session log; mirrors MealStore/JournalStore shape |
| recovery_concern computation | Backend (morning_briefing.py) | garmin_tool.py (ACWR) | Natural home in _gather_data(); ACWR+HRV+sleep all already fetched there |
| Weekly review composition | Backend (LLM / brain) | — | D-17: brain-composed; mirrors reflection.py pattern |
| prompts/weekly_training_review.md | Backend (prompts/) | — | New file; read by weekly review handler; injected as system prompt |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-telegram-bot | 22.7 [VERIFIED: `python3 -c "import telegram; print(telegram.__version__)"`] | InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Bot.send_message(reply_markup=), Bot.answer_callback_query() | Existing dependency; all inline-keyboard classes already importable |
| google-cloud-firestore | >=2.18 (requirements.txt) | TrainingLogStore, PendingPromptStore | All existing Firestore store patterns |
| google-api-python-client | >=2.140 (requirements.txt) | service.calendarList().list() for Training calendar name lookup | Already used in calendar_tool.py for events().list() |
| google-auth | >=2.30 (requirements.txt) | OIDC verification for weekly-review cron | Existing _verify_cron_request uses verify_oauth2_token |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| garminconnect | >=0.2 (requirements.txt) | fetch_garmin_activities, perceived_exertion, compute_acwr_from_db | Recovery flag + silent Garmin sync in check-in |
| psycopg2-binary | >=2.9 (requirements.txt) | compute_acwr_from_db reads Postgres | ACWR for recovery_concern; already used |
| zoneinfo / tzdata | stdlib / >=2024.1 | Asia/Jerusalem timezone for time-gating (D-07) and week boundary (D-23) | All schedule comparisons |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Firestore PendingPromptStore | Redis / in-memory | Cloud Run is stateless; Firestore is the project's single state backend; Redis adds infra complexity with no benefit |
| New /cron/training-checkin (21:00) | Fold into existing /cron/proactive-alerts (21:30) | D-09 decision: fewer jobs, no contention risk, simpler ops |

---

## Architecture Patterns

### System Architecture Diagram

```
21:30 Cloud Scheduler → POST /cron/proactive-alerts
  └─ _verify_cron_request (OIDC)
  └─ core.proactive_alerts.run_proactive_alerts(bot, tomorrow)
       ├─ [existing] weather / overload / travel alerts
       └─ [NEW] core.training_checkin.run_training_checkin(bot, today)
            ├─ GARMIN silent sync → TrainingLogStore (source="garmin")   ← no Telegram
            ├─ calendar_tool.list_training_events(today)                  ← calendarList lookup
            └─ for each unlogged workout (start < now):
                 ├─ RPE present → silent log → done
                 ├─ Garmin record but no RPE → send RPE keyboard
                 │    └─ PendingPromptStore.set(session_key, state="awaiting_rpe")
                 └─ No Garmin record → send watch-off keyboard
                      └─ PendingPromptStore.set(session_key, state="awaiting_watchoff")

Telegram button tap → POST /telegram-webhook
  └─ Update.de_json
  └─ _router.handle_update(update)        ← EXTENDED: no longer returns on callback_query=None
       └─ [new branch] update.callback_query is not None
            └─ await bot.answer_callback_query(callback_query.id)
            └─ PendingPromptStore.get(session_key from callback_data)
            └─ dispatch: rpe:{key}:{val} / watchoff:{key}:{done|skipped} / skipreason:{key}:{reason}
            └─ TrainingLogStore.log_session(...)
            └─ send notes follow-up OR done

Free-text reply → POST /telegram-webhook
  └─ update.message.reply_to_message is not None (native reply)
       └─ check PendingPromptStore for matching message_id → attach note
  └─ OR: update.message.reply_to_message is None + PendingPromptStore has open note
       └─ inject pending-note context → brain decides

Morning briefing tick → POST /cron/morning-briefing-tick
  └─ morning_briefing._gather_data(today)
       └─ [NEW] compute_recovery_concern(garmin, ACWR, today_training_events)
            └─ returns {"level": "mild"|"strong"|None, ...}
       └─ data["recovery_concern"] = result

Sunday 10:00 Cloud Scheduler → POST /cron/weekly-training-review
  └─ _verify_cron_request (OIDC)
  └─ _application guard
  └─ core.weekly_training_review.run_weekly_review(bot, sunday_date)
       ├─ TrainingLogStore.get_recent(7) — this week's log
       ├─ fetch_garmin_activities(14) — trend data (this + last week)
       ├─ MealStore 7-day totals — nutrition for review (D-21)
       ├─ UserProfileStore.load() — goals (if non-empty)
       └─ LLMClient(SMART_AGENT_*) compose with prompts/weekly_training_review.md
       └─ send_and_inject(bot, text, inject_into_conversation=True)
       └─ _log_cron_run("weekly-training-review", ok=True/False)
```

### Recommended Project Structure

```
core/
├── training_checkin.py     # new — check-in logic (training calendar + Garmin sync + keyboard dispatch)
├── weekly_training_review.py  # new — weekly review composition + send
├── proactive_alerts.py     # extend — call run_training_checkin at end of run_proactive_alerts
├── morning_briefing.py     # extend — add recovery_concern computation in _gather_data
├── heartbeat.py            # extend — add 'weekly-training-review': 170 staleness key
memory/
├── firestore_db.py         # extend — add TrainingLogStore, PendingPromptStore
interfaces/
├── _router.py              # extend — dispatch callback_query; reply-to detection
├── web_server.py           # extend — add /cron/weekly-training-review route; update setWebhook docs
core/
├── scheduled_message.py    # extend — add reply_markup optional param
mcp_tools/
├── calendar_tool.py        # extend — add list_training_events() using calendarList
core/
├── tools.py                # extend — register log_training (brain-direct) + get_training_history (worker)
prompts/
├── weekly_training_review.md  # new
├── morning_briefing.md     # extend — recovery_concern section
├── proactive_alert.md      # extend — recovery_concern framing
scripts/
├── bootstrap_shifu_crons.sh   # new — re-runnable; creates only klaus-weekly-training-review
docs/
├── DEPLOYMENT.md           # extend — §Phase Shifu section + updated job inventory
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Inline keyboard construction | Custom JSON builder | `InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=...), ...], ...])` | python-telegram-bot 22.7 provides typed classes; already importable [VERIFIED] |
| Answering a button tap | Manual Telegram API call | `await bot.answer_callback_query(callback_query.id)` | Required to dismiss the loading spinner; built-in method |
| Calendar ID lookup for "Training" | Hardcode a calendar ID | `service.calendarList().list()` — iterate items, match on `item["summary"] == calendar_name` | Calendar IDs are user-account specific and change on re-auth; name lookup is stable |
| OIDC verification | Custom JWT decode | `_verify_cron_request(request)` at web_server.py:232 — already implemented | Reuse existing helper; same SA email + Cloud Run URL |
| Cron liveness ledger | Custom Firestore write | `_log_cron_run(job_id, ok=True/False)` at web_server.py:338 | Existing best-effort helper; heartbeat already monitors it |
| ACWR computation | Re-implement rolling average | `compute_acwr_from_db()` at garmin_tool.py:396 | Already Postgres-backed; swallows all exceptions; returns sentinel on insufficient baseline |
| Nutrition 7-day totals | New aggregation logic | `MealStore.get_day_aggregate(date_str)` per day for 7 days; sum totals | Aggregate method already implemented; fiber included |

**Key insight:** The inline-keyboard infrastructure is net-new but python-telegram-bot already ships all the needed classes. The callback_query dispatch gap in `_router.py` is a one-line guard removal + a new branch — not a framework gap.

---

## Detailed Implementation Findings

### Finding 1: python-telegram-bot 22.7 Inline Keyboard API [VERIFIED: live import]

```python
# Source: live python3 -c verification + python-telegram-bot 22.7
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

# RPE picker — two rows of 5 per D-26
rpe_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton(str(i), callback_data=f"rpe:{session_key}:{i}") for i in range(1, 6)],
    [InlineKeyboardButton(str(i), callback_data=f"rpe:{session_key}:{i}") for i in range(6, 11)],
])

# Watch-off branch
watchoff_keyboard = InlineKeyboardMarkup([[
    InlineKeyboardButton("Did it — watch was off", callback_data=f"watchoff:{session_key}:done"),
    InlineKeyboardButton("Skipped", callback_data=f"watchoff:{session_key}:skipped"),
]])

# Skip-reason buttons (D-08b)
skipreason_keyboard = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("Rest / recovery", callback_data=f"skipreason:{session_key}:rest_recovery"),
        InlineKeyboardButton("Sick / injured",  callback_data=f"skipreason:{session_key}:sick_injured"),
    ],
    [
        InlineKeyboardButton("Too busy", callback_data=f"skipreason:{session_key}:too_busy"),
        InlineKeyboardButton("Other — tell me", callback_data=f"skipreason:{session_key}:other"),
    ],
])
```

`InlineKeyboardButton` constructor: `InlineKeyboardButton(text: str, callback_data: str | None = None, ...)` [VERIFIED: live introspection]

`CallbackQuery` fields: `id`, `from_user`, `chat_instance`, `message`, `data`, `inline_message_id` [VERIFIED: live introspection]

Answering a callback query (dismisses spinner): `await bot.answer_callback_query(callback_query_id=cq.id)` [VERIFIED: Bot.answer_callback_query signature]

### Finding 2: send_and_inject Extension

Current signature (`core/scheduled_message.py:22`):
```python
async def send_and_inject(bot: Bot, text: str, *, inject_into_conversation: bool = False) -> None:
    await bot.send_message(chat_id=user_id, text=text)
```

`Bot.send_message` already has `reply_markup` parameter [VERIFIED: live signature check]. Extension:
```python
async def send_and_inject(
    bot: Bot,
    text: str,
    *,
    inject_into_conversation: bool = False,
    reply_markup=None,          # InlineKeyboardMarkup | None — for check-in keyboards
) -> telegram.Message:          # CHANGE: return Message so caller can record message_id for reply-to detection
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
    # ... existing inject logic unchanged ...
    return msg
```

All existing callers pass only `(bot, text, inject_into_conversation=...)` — adding `reply_markup=None` as a keyword-only default is backward-compatible. Returning `Message` is a new addition; existing callers ignore the return value, so this is also safe.

The returned `Message.message_id` is needed by the notes follow-up step to record which message the user must reply-to.

### Finding 3: Router Extension for callback_query

The blocking guard at `_router.py:65`:
```python
if update.message is None:
    return     # ← drops ALL callback_query, channel_post, edited_message, etc.
```

Extension pattern:
```python
async def handle_update(self, update: Update) -> None:
    # NEW: dispatch callback_query before the message guard
    if update.callback_query is not None:
        await self._handle_callback_query(update)
        return

    # Existing guard: ignore non-message updates (edits, channel posts, etc.)
    if update.message is None:
        return

    # ... rest of existing logic unchanged ...
```

The `_handle_callback_query` method must:
1. Check `effective_user.id` in `self.allowed_user_ids` (same guard as text messages)
2. Extract `callback_data` from `update.callback_query.data`
3. Answer the callback query immediately: `await update.callback_query.answer()` (or `bot.answer_callback_query(id)`)
4. Parse the callback_data prefix (`rpe:`, `watchoff:`, `skipreason:`) and dispatch

`update.callback_query.answer()` is a shorthand on the `CallbackQuery` object that calls `bot.answer_callback_query(self.id)` — both available in v22.7 [ASSUMED based on v21+ API; standard in all recent versions].

### Finding 4: Webhook allowed_updates Must Include callback_query

DEPLOYMENT.md line 489 shows:
```bash
-d "allowed_updates=[\"message\"]"
```

Phase 20 requires updating to:
```bash
-d "allowed_updates=[\"message\",\"callback_query\"]"
```

This `setWebhook` call must be re-run after deployment. Without this change, Telegram will only deliver `message` updates and silently drop all button-tap events. The re-registration is a one-time operator step documented in DEPLOYMENT.md.

### Finding 5: Pending-Prompt State (Claude's Discretion — Recommendation)

**Recommended shape — new `PendingPromptStore` in `memory/firestore_db.py`:**

Firestore path: `pending_prompts/{session_key}`

```python
# Document fields:
{
    "session_key":   str,   # "2026-06-01_evt_abc123" — calendar event date + event id fragment
    "user_id":       int,   # Telegram user ID
    "state":         str,   # "awaiting_rpe" | "awaiting_watchoff" | "awaiting_notes" | "awaiting_skipreason_other"
    "message_id":    int,   # Telegram message_id of the keyboard/notes prompt (for reply-to detection)
    "event_summary": str,   # Calendar event name — for user-facing copy
    "event_date":    str,   # YYYY-MM-DD
    "rpe":           int | None,  # filled after RPE tap, before notes
    "created_at":    str,   # ISO-8601 UTC
    "expires_at":    str,   # ISO-8601 UTC — TTL marker (no Firestore TTL enforcement; soft expiry)
}
```

**TTL recommendation:** Set `expires_at = created_at + 20 hours`. At morning briefing time (6–10 am) the check-in prompts from 21:30 the prior evening will have expired. The router check-in handler should skip stale sessions (created more than 20 hours ago). Phase 20 ships ask-once only (no carry-over per deferred section) — expired = silently gone.

**Why not Firestore TTL policy:** Firestore native TTL policies require a field named with a TTL config applied at collection level (Firebase console or gcloud). For a single-user project with at most 3-4 documents per day, soft expiry in Python is simpler and avoids infra config drift.

**Store methods:**
```python
class PendingPromptStore:
    _COLLECTION = "pending_prompts"

    def set(self, session_key: str, payload: dict) -> None: ...     # merge=True (upsert)
    def get(self, session_key: str) -> dict | None: ...             # returns None if expired
    def delete(self, session_key: str) -> None: ...                  # cleanup on resolution
    def get_open_note_session(self, user_id: int) -> dict | None:   # find any awaiting_notes session for user
        ...
```

**Reply-to detection:** When user sends a message, `update.message.reply_to_message` is not None and has `.message_id` [VERIFIED: live Message introspection]. The router should check if `reply_to_message.message_id` matches any `pending_prompts.message_id`. The `PendingPromptStore.get_open_note_session(user_id)` fallback handles the D-05 "brain decides" path when there is no reply-to but an open notes session.

### Finding 6: Training Calendar Read Path

`GoogleCalendarManager.list_events` at `mcp_tools/calendar_tool.py:71` hardcodes `calendarId="primary"` [VERIFIED: file read]. The `service.calendarList().list()` endpoint is the standard Google Calendar API v3 method to enumerate a user's calendars by name.

**New method to add to `GoogleCalendarManager`:**
```python
def get_calendar_id_by_name(self, name: str) -> str | None:
    """Return the calendarId for the calendar with the given display name.

    Calls calendarList().list() and matches on item["summary"].
    Returns None if no calendar with that name is found.
    Never raises — returns None on API error.
    """
    try:
        service = self._get_service()
        result = service.calendarList().list().execute()
        for item in result.get("items", []):
            if item.get("summary", "") == name:
                return item.get("id")
        return None
    except HttpError as exc:
        logger.error("Calendar API error in get_calendar_id_by_name(%r): %s", name, exc)
        return None

def list_training_events(
    self,
    time_min_iso: str,
    time_max_iso: str,
    calendar_name: str = "Training",
    max_results: int = 20,
) -> list[dict]:
    """List events from the named training calendar, filtering buffer blocks."""
    cal_id = self.get_calendar_id_by_name(calendar_name)
    if cal_id is None:
        logger.warning("Training calendar %r not found", calendar_name)
        return []
    # ... same as list_events but with calendarId=cal_id ...
    # Filter: skip events whose summary starts with "Get Ready:" or "Travel:"
```

The `calendarList` response items have fields: `id` (the calendarId to use in events calls), `summary` (display name), `primary` (True for the primary calendar), `accessRole`. [ASSUMED: standard Calendar API v3 response shape — consistent with Google docs knowledge]

**Buffer-window minutes for D-10 (Claude's Discretion — Recommendation):** 30 minutes before/after event window. Rationale: a Garmin activity that starts up to 30 min before the calendar event start or up to 30 min after covers warm-up, commute variations, and tracking quirks. This is a v0 heuristic — matches the scale of the 15-min travel buffer already used in create_event.

**Type-synonym map for D-10 (Claude's Discretion — Recommendation):**
```python
_ACTIVITY_TYPE_MAP = {
    # calendar keyword → set of Garmin activity type keys
    "run":           {"running", "trail_running", "treadmill_running", "indoor_track"},
    "gym":           {"strength_training", "fitness_equipment", "indoor_cycling"},
    "basketball":    {"basketball", "court_sports", "other"},
    "bike":          {"cycling", "mountain_biking", "indoor_cycling", "road_biking"},
    "five fingers":  None,  # watch-off by definition — always goes to watch-off branch
}
# Unknown calendar event type → treat as moderate intensity, no type-match needed
# (D-14: unknown → moderate)
```

### Finding 7: TrainingLogStore Shape

Mirror `MealStore` and `JournalStore` patterns from `memory/firestore_db.py`. Recommended:

Firestore path: `training_log/{date}_{slot}` where `slot` = calendar event ID (or truncated start time when event ID unavailable).

```python
class TrainingLogStore:
    _COLLECTION = "training_log"

    def log_session(
        self,
        date: str,             # YYYY-MM-DD
        slot: str,             # calendar event id or startTime truncated to YYYYMMDDHHmm
        session_type: str,     # e.g. "gym", "run", "five fingers"
        planned: bool,
        completed: bool,
        skipped_reason: str | None = None,  # "rest_recovery" | "sick_injured" | "too_busy" | "other"
        rpe: int | None = None,             # 1–10
        feel: int | None = None,            # Garmin feel value (preserved verbatim from Garmin)
        notes: str | None = None,
        source: str = "telegram",           # "garmin" | "telegram" | "manual_chat"
        garmin_activity_id: str | None = None,
    ) -> None:
        doc_id = f"{date}_{slot}"
        # merge=True for idempotency — Garmin silent sync may run before user reply
        ...

    def get_recent(self, days: int) -> list[dict]: ...  # last N days, sorted desc
    def get_by_date(self, date_str: str) -> list[dict]: ...  # entries for one date
    def get_range(self, start_date: str, end_date: str) -> list[dict]: ...  # for weekly review
```

**LOG-01 key alignment:** REQUIREMENTS.md says `{date}_{slot}` but D-06 clarifies slot = per-session key (calendar event id / start time). The document ID `f"{date}_{slot}"` satisfies both.

### Finding 8: /cron/weekly-training-review Route

Mirror `/cron/autonomous-tick` at `web_server.py:398` exactly:

```python
@app.post("/cron/weekly-training-review")
async def cron_weekly_training_review(request: Request) -> JSONResponse:
    """Weekly training review — Sunday 10:00 Asia/Jerusalem.

    Phase 20 — REVIEW-01.
    """
    await _verify_cron_request(request)
    if _application is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    import core.weekly_training_review as _review
    try:
        today = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        await _review.run_weekly_review(_application.bot, today)
        _log_cron_run("weekly-training-review", ok=True)
    except Exception:
        _log_cron_run("weekly-training-review", ok=False)
        raise
    return JSONResponse(content={"ok": True})
```

### Finding 9: Heartbeat Staleness Key

Mirror `'healthkit-sync': 48` pattern at `core/heartbeat.py:116`:

```python
_CRON_MAX_STALENESS_HOURS = {
    ...
    "healthkit-sync": 48,
    "weekly-training-review": 170,  # Phase 20 — Sunday 10:00; 170h = one week + 2h slack
}
```

170 hours = 7 days + 2 hours. The weekly-review fires once per week; one missed Sunday plus 2h tolerance prevents spurious alerts while still catching a broken job within the second weekly window.

### Finding 10: recovery_concern Computation in _gather_data

`core/morning_briefing.py:174` `_gather_data(today_iso)` already fetches `garmin` data and writes biometrics to Postgres. The `recovery_concern` block should be added after the Garmin + Postgres writeback block, before the TickTick tasks block, as a best-effort Pattern-C:

```python
# PHASE 20 — RECOVERY-01: compute recovery_concern from ACWR + HRV + sleep + today's intensity
try:
    from core.training_checkin import compute_recovery_concern
    rc = compute_recovery_concern(
        garmin_data=data.get("garmin"),        # already fetched
        today_training_events=_get_today_training_events(today_iso),  # Training calendar
        acwr=None,                              # filled lazily inside if garmin data present
    )
    if rc:
        data["recovery_concern"] = rc
except Exception:
    logger.warning("morning_briefing: recovery_concern computation failed", exc_info=True)
    # silent omit — no "all clear" placeholder per D-13 guardrail
```

`RECOVERY_THRESHOLDS` dict (RECOVERY-02):
```python
RECOVERY_THRESHOLDS = {
    # v0 heuristics — tune after 2 weeks of journaled training_log + biometrics data.
    # Keys map to severity levels ("mild" or "strong").
    "acwr_mild":   1.5,   # ACWR >= 1.5 + any high-intensity session today → mild
    "acwr_strong": 1.8,   # ACWR >= 1.8 + high-intensity → strong
    "sleep_low":   70,    # Garmin sleep score < 70 (D-15)
    "consecutive_low_sleep_nights": 2,   # 2 consecutive nights below sleep_low (D-15)
    "intensity_keywords_high": ("heavy", "intervals", "speed", "long run", "hiit"),
    "intensity_keywords_moderate": ("gym", "run", "bike", "five fingers"),
    # HRV: Garmin provides hrv_status as string; flag unbalanced/low
    "hrv_flag_values": ("unbalanced", "low"),  # Garmin HRV status strings
}
```

Severity level determination (D-12):
- **Strong:** (ACWR >= acwr_strong + high-intensity) OR (HRV flagged + sleep_score < sleep_low + heavy lifting)
- **Mild:** (ACWR >= acwr_mild + high-intensity) OR (2 consecutive nights sleep < 70 + intense today)
- **None:** none of the above

### Finding 11: Tool Registration Pattern for log_training and get_training_history

Following Phase 19 Plan 02 pattern [VERIFIED: core/tools.py:39-55, 756-775, 1340-1354]:

**log_training — brain-direct (LOG-03):**
1. Add to `SMART_AGENT_DIRECT_TOOLS` frozenset (tools.py:39)
2. Add schema to `TOOL_SCHEMAS` list
3. Add to exclusion set in `WORKER_TOOL_SCHEMAS` comprehension (tools.py:758-775)
4. Add `_handle_log_training` function
5. Add lambda to `_HANDLERS` dict (tools.py:1319)

**get_training_history — worker-delegated (LOG-04):**
1. Add schema to `TOOL_SCHEMAS` list (NOT to SMART_AGENT_DIRECT_TOOLS)
2. No exclusion needed (worker-delegated is the default)
3. Add `_handle_get_training_history` function
4. Add lambda to `_HANDLERS` dict

### Finding 12: Weekly Review Composition (D-17, mirrors reflection.py)

`core/reflection.py` uses `LLMClient(SMART_AGENT_BACKEND, SMART_AGENT_MODEL, SMART_AGENT_API_KEY)` for brain composition [VERIFIED: reflection.py:229]. The weekly review should follow the same pattern:

```python
# core/weekly_training_review.py
async def run_weekly_review(bot: Bot, today_iso: str) -> None:
    week_data = _gather_week_data(today_iso)
    message = _compose_review(week_data, today_iso)
    from core.scheduled_message import send_and_inject
    await send_and_inject(bot, message, inject_into_conversation=True)
    _log_cron_run("weekly-training-review", ok=True)  # caller handles this
```

`_compose_review` loads `prompts/weekly_training_review.md`, appends `prompts/meal_audit.md` for nutrition critique (mirrors morning_briefing.py:283), calls LLMClient with SMART_AGENT_* env vars. Always sends (D-24) — no silent-omit.

### Finding 13: bootstrap_shifu_crons.sh — Re-runnable Pattern

Existing DEPLOYMENT.md §14e uses a simple `gcloud scheduler jobs create` block. Per D-25 the script must be re-runnable. Pattern:

```bash
# describe-or-create/update pattern (re-runnable)
if gcloud scheduler jobs describe "klaus-weekly-training-review" \
     --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud scheduler jobs update http "klaus-weekly-training-review" \
    --schedule="0 10 * * 0" \
    --time-zone="Asia/Jerusalem" \
    --uri="${SERVICE_URL}/cron/weekly-training-review" \
    ...
else
  gcloud scheduler jobs create http "klaus-weekly-training-review" \
    --schedule="0 10 * * 0" \
    --time-zone="Asia/Jerusalem" \
    --uri="${SERVICE_URL}/cron/weekly-training-review" \
    --http-method=POST \
    --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
    --oidc-token-audience="${SERVICE_URL}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
fi
```

Uses existing `CLOUD_SCHEDULER_SA_EMAIL` OIDC SA (per CRON-01, D-25) [VERIFIED: DEPLOYMENT.md §14d/§14e use the same SA].

### Finding 14: self_manifest.py Coverage

`core/self_manifest.py` generates `docs/SELF.md` by grepping `core/tools.py` for `"name":` patterns and `interfaces/web_server.py` for `/cron/` routes [VERIFIED: self_manifest.py:66-76]. Adding `log_training` and `get_training_history` to TOOL_SCHEMAS + `_HANDLERS`, and `/cron/weekly-training-review` to web_server.py, will automatically appear in SELF.md on the next regeneration run (`python core/self_manifest.py`).

---

## Common Pitfalls

### Pitfall 1: Telegram silently drops callback_query without allowed_updates update
**What goes wrong:** Inline keyboard buttons tap generates a `callback_query` update type. The existing `setWebhook` call in DEPLOYMENT.md registers `allowed_updates=["message"]` only. After deploying Phase 20, button taps produce no server-side events whatsoever — no error, just silence.
**Why it happens:** Telegram filters updates server-side per the `allowed_updates` list.
**How to avoid:** Update DEPLOYMENT.md with a re-registration step: `allowed_updates=["message","callback_query"]`. Document this as a required operator step in the Phase 20 bootstrap sequence.
**Warning signs:** User taps button, no Firestore write, no log entry, no follow-up message sent.

### Pitfall 2: Router returns early before callback_query dispatch
**What goes wrong:** `_router.py:65` has `if update.message is None: return`. A `callback_query` update has `update.message = None` (the message is nested inside `update.callback_query.message`). The router drops it silently.
**How to avoid:** Add callback_query branch BEFORE the `update.message is None` guard [VERIFIED: confirmed by reading _router.py source].

### Pitfall 3: PendingPromptStore document not deleted after resolution
**What goes wrong:** A session that's been handled stays in `pending_prompts`, causing the "open note" detector to fire on the wrong session the next day.
**How to avoid:** `PendingPromptStore.delete(session_key)` on all terminal transitions: RPE-only logged (if user skips notes), notes attached, skip-reason recorded.

### Pitfall 4: Garmin silent sync runs twice (idempotency)
**What goes wrong:** The check-in folds into proactive-alerts. If `_already_sent` passes (dedup check on `proactive_alerts/{date}`) but the check-in already wrote `training_log` on an earlier partial run, a second run writes a duplicate log entry with `source="garmin"`.
**How to avoid:** `TrainingLogStore.log_session` uses `merge=True` (idempotent on `{date}_{slot}` doc ID). Garmin sync always writes by doc ID = same key → safe to re-run.

### Pitfall 5: proactive_alerts `_already_sent` blocks check-in on retry
**What goes wrong:** The existing `_already_sent` dedup at `proactive_alerts.py:98` marks the date as processed after the first run. If the check-in fails partway through, a retry the same evening will be blocked.
**How to avoid:** The check-in logic should have its own lightweight dedup (or no dedup — the training log is idempotent). The `_already_sent` gate at proactive-alerts level should mark only the alert-sending portion, not the check-in. Alternatively: run training check-in BEFORE the `_already_sent` check so it can be retried.

### Pitfall 6: calendar calendarList not paginated
**What goes wrong:** `calendarList().list()` may be paginated for users with many calendars. With only a few calendars (personal use), this is unlikely to matter, but a nextPageToken check prevents a production edge case.
**How to avoid:** Implement a simple pagination loop or use `maxResults=100` (the API default maximum). For this single-user project, one page is virtually guaranteed sufficient [ASSUMED: standard Google Calendar API pagination behaviour].

### Pitfall 7: RPE values from Garmin in steps-of-10 encoding
**What goes wrong:** `garmin_tool.py:332` reads `perceived_exertion` from `directWorkoutRpe`. Per STATE.md Phase 19-01 research, Garmin stores workoutRpe in steps of 10 (10..100 for scale 1..10). The Phase 19 parser captures the raw value. If the check-in compares `perceived_exertion is not None` this is fine (any non-null RPE = "covered") but if the value is displayed or compared as 1–10, it must be divided by 10.
**How to avoid:** In `TrainingLogStore.log_session` normalise: `rpe = perceived_exertion // 10 if perceived_exertion is not None else None`.

### Pitfall 8: Weekly review date boundary DST edge case
**What goes wrong:** D-23 says week boundary = "previous Sun 00:00 → Sat 23:59 in Asia/Jerusalem". Israel transitions between Standard (+2) and Daylight (+3) time. Using Python's `ZoneInfo("Asia/Jerusalem")` correctly handles DST — but `date.fromisoformat` produces naive dates.
**How to avoid:** Always construct the boundary as `datetime(..., tzinfo=ZoneInfo("Asia/Jerusalem"))` and convert to UTC for Firestore queries.

### Pitfall 9: Anti-pattern — inline-keyboard in the conversation injection
**What goes wrong:** The notes prompt message is injected into the conversation store via `inject_into_conversation=True`. Injecting the raw text "Reply to this message or /skip" without the keyboard context is fine. But if the bot later renders history, the keyboard is gone (keyboards cannot be retrieved from Telegram history).
**How to avoid:** For check-in messages, pass `inject_into_conversation=False`. Only the weekly-review full narrative and recovery framing should be injected (mirrors proactive-alerts which sets `inject_into_conversation=False`).

---

## Code Examples

### send_and_inject with reply_markup

```python
# core/scheduled_message.py — extended signature
async def send_and_inject(
    bot: Bot,
    text: str,
    *,
    inject_into_conversation: bool = False,
    reply_markup=None,
) -> "telegram.Message":
    # Source: Bot.send_message signature verified live; reply_markup param confirmed present
    user_id = _telegram_user_id()
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
    if inject_into_conversation:
        # ... existing injection logic unchanged ...
    return msg
```

### Callback query dispatch (router extension)

```python
# interfaces/_router.py — new branch before existing guard
async def handle_update(self, update: Update) -> None:
    if update.callback_query is not None:
        if update.effective_user.id not in self.allowed_user_ids:
            return
        await self._handle_callback_query(update)
        return

    if update.message is None:
        return
    # ... existing code unchanged from here ...

async def _handle_callback_query(self, update: Update) -> None:
    cq = update.callback_query
    await cq.answer()  # dismiss spinner
    data = cq.data or ""
    # Dispatch by prefix
    if data.startswith("rpe:"):
        await self._dispatch_to_checkin_handler("rpe", data)
    elif data.startswith("watchoff:"):
        await self._dispatch_to_checkin_handler("watchoff", data)
    elif data.startswith("skipreason:"):
        await self._dispatch_to_checkin_handler("skipreason", data)
    else:
        logger.warning("Unknown callback_data: %r", data)
```

### Google Calendar calendarList lookup

```python
# mcp_tools/calendar_tool.py — new method on GoogleCalendarManager
def get_calendar_id_by_name(self, name: str) -> str | None:
    # Source: Google Calendar API v3 calendarList.list — standard endpoint
    try:
        service = self._get_service()
        result = service.calendarList().list().execute()
        for item in result.get("items", []):
            if item.get("summary", "").strip() == name:
                return item.get("id")
        return None
    except HttpError as exc:
        logger.error("Calendar calendarList error looking up %r: %s", name, exc)
        return None
```

### Firestore store read pattern (never-raises read)

```python
# Mirrors UserProfileStore.load() and MealStore.get_day()
def get_recent(self, days: int) -> list[dict]:
    try:
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        # Stream the collection; filter + sort in Python (same as JournalStore.get_recent)
        snaps = list(self._col.stream())
        results = []
        for snap in snaps:
            d = snap.to_dict() or {}
            d["doc_id"] = snap.id
            if d.get("date", "") >= cutoff:
                results.append(d)
        results.sort(key=lambda d: d.get("date", ""), reverse=True)
        return results
    except Exception:
        logger.warning("TrainingLogStore.get_recent failed", exc_info=True)
        return []
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `allowed_updates=["message"]` (DEPLOYMENT.md line 489) | Must add `"callback_query"` | Phase 20 | Buttons silently dropped until re-registered |
| `_router.py` drops all non-message updates | Must branch on `callback_query` | Phase 20 | Check-in flow completely broken without this |
| `send_and_inject` returns None | Should return `telegram.Message` | Phase 20 | Notes prompt needs `message_id` for reply-to detection |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `update.callback_query.answer()` is available as a shorthand method on CallbackQuery in v22.7 (in addition to `bot.answer_callback_query`) | Finding 3 | Use `bot.answer_callback_query(cq.id)` instead — equivalent outcome |
| A2 | Google Calendar calendarList().list() response items have `id` and `summary` fields matching the display name | Finding 6 | Use `items[*]["summary"]` vs actual API field name; if wrong, lookup fails silently and returns None |
| A3 | calendarList().list() returns all user calendars in one page for a typical personal account (< 20 calendars) | Pitfall 6 | Add pagination loop if user has many shared/subscribed calendars |
| A4 | Garmin HRV status string values are "unbalanced" and "low" (for RECOVERY_THRESHOLDS) | Finding 10 | If Garmin returns different strings, HRV flag check never fires; degrade gracefully |
| A5 | `_already_sent` dedup in proactive_alerts.py will not block training check-in from running (i.e., check-in runs before the dedup mark) | Pitfall 5 | Restructure to run training check-in before `_already_sent` check |

---

## Open Questions (RESOLVED)

> All three questions were resolved during planning and folded into Phase 20 plan actions:
> Q1 → Plan 20-04 Task 3 (run check-in BEFORE the `_already_sent`/`_mark_processed` gate);
> Q2 → Plan 20-01 Task 1 (RPE normalisation guard, `% 10 == 0` encoding detection);
> Q3 → Plan 20-05 Task 1 (`_recent_sleep_scores` Postgres read of `daily_biometrics`).

1. **[RESOLVED — Plan 20-04 Task 3]** proactive_alerts dedup interaction with check-in
   - What we know: `run_proactive_alerts` at `proactive_alerts.py:98` marks the date as processed and returns early on subsequent calls
   - What's unclear: If proactive alerts already ran (no issues) and we fold check-in in, does the `_already_sent` gate block a retry of the check-in on the same evening?
   - Recommendation: Run training check-in BEFORE the `_already_sent` / `_mark_processed` gate, or give the check-in its own separate dedup key in `pending_prompts` or `training_checkin/{date}`.

2. **[RESOLVED — Plan 20-01 Task 1]** Garmin RPE encoding normalisation
   - What we know: STATE.md Phase 19-01 notes "Garmin stores workoutRpe in steps of 10 (10..100 for 1..10)"
   - What's unclear: Does the live `fetch_garmin_activities` response already normalise RPE to 1–10, or does it return raw 10–100?
   - Recommendation: Add a normalisation step in TrainingLogStore.log_session or in the silent-sync step; guard with `% 10 == 0` check to detect the encoding.

3. **[RESOLVED — Plan 20-05 Task 1]** How to surface Garmin sleep from multiple nights for the consecutive-low-sleep rule (D-15)
   - What we know: `fetch_garmin_today` provides today's sleep; `morning_briefing._gather_data` fetches today's garmin data; `daily_biometrics` Postgres table has sleep data
   - What's unclear: Is yesterday's sleep_score easily accessible without a separate Garmin API call or Postgres query?
   - Recommendation: Use `compute_acwr_from_db`-style Postgres read for sleep: `SELECT date, sleep_score FROM daily_biometrics WHERE date >= (today - 2) ORDER BY date DESC LIMIT 2`. This avoids a second Garmin API call and uses data already written by `write_today_biometrics_to_postgres`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| python-telegram-bot | InlineKeyboardMarkup, CallbackQuery dispatch | ✓ | 22.7 [VERIFIED] | — |
| google-cloud-firestore | TrainingLogStore, PendingPromptStore | ✓ | >=2.18 (requirements.txt) | — |
| google-api-python-client | calendarList().list() | ✓ | >=2.140 (requirements.txt) | — |
| garminconnect | fetch_garmin_activities, compute_acwr_from_db | ✓ | >=0.2 (requirements.txt) | Silent omit on GarminUnavailableError |
| psycopg2-binary | daily_biometrics sleep history query | ✓ | >=2.9 (requirements.txt) | Silent omit; ACWR sentinel |
| Cloud Scheduler (ops) | weekly-training-review cron job | ✓ (existing 7 jobs deployed) | — | Not applicable (operator step) |

**Missing dependencies with no fallback:** None — all required libraries are already in requirements.txt.

**Missing dependencies with fallback:** garminconnect / psycopg2 failures are already handled with sentinel returns; the check-in degrades gracefully to "all unverified — prompt watch-off for each".

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0 |
| Config file | none (direct pytest invocation) |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LOG-01 | TrainingLogStore.log_session writes to correct Firestore path with all fields | unit | `pytest tests/test_training_log_store.py -x` | Wave 0 |
| LOG-02 | get_recent + get_by_date return correct entries | unit | `pytest tests/test_training_log_store.py -x` | Wave 0 |
| LOG-03 | log_training registered brain-direct (in SMART_AGENT_DIRECT_TOOLS, in TOOL_SCHEMAS, NOT in WORKER_TOOL_SCHEMAS) | unit | `pytest tests/test_tool_registration_phase20.py -x` | Wave 0 |
| LOG-04 | get_training_history registered worker-delegated | unit | `pytest tests/test_tool_registration_phase20.py -x` | Wave 0 |
| CHECKIN-02 | Silent Garmin sync writes to TrainingLogStore with source="garmin" | unit | `pytest tests/test_training_checkin.py::test_silent_garmin_sync -x` | Wave 0 |
| CHECKIN-03 | Only prompts for unlogged, past-start workouts; silent when all covered | unit | `pytest tests/test_training_checkin.py::test_silent_when_all_covered -x` | Wave 0 |
| CHECKIN-04 | RPE keyboard sent with correct callback_data format rpe:{key}:{val}; two rows of 5 | unit | `pytest tests/test_training_checkin.py::test_rpe_keyboard_layout -x` | Wave 0 |
| CHECKIN-05 | Cron fully silent when no unlogged workouts | unit | `pytest tests/test_training_checkin.py::test_silent_when_all_covered -x` | Wave 0 |
| REVIEW-01 | /cron/weekly-training-review: 200 on dev-bypass + app present; 500 on app absent; 401 on bad token | unit | `pytest tests/test_web_server.py::TestCronWeeklyTrainingReview -x` | Wave 0 |
| REVIEW-03 | prompts/weekly_training_review.md exists and contains required placeholders | smoke | `pytest tests/test_docs.py::test_weekly_training_review_prompt_exists -x` | Wave 0 |
| REVIEW-04 | _log_cron_run called on success AND exception in weekly-review route | unit | `pytest tests/test_web_server.py::TestCronWeeklyTrainingReview -x` | Wave 0 |
| RECOVERY-01 | compute_recovery_concern returns None on no-trigger inputs; severity=mild/strong on threshold crossings | unit | `pytest tests/test_recovery_concern.py -x` | Wave 0 |
| RECOVERY-02 | RECOVERY_THRESHOLDS dict exists in module with all required keys | unit | `pytest tests/test_recovery_concern.py::test_thresholds_dict_shape -x` | Wave 0 |
| CRON-01 | bootstrap_shifu_crons.sh creates only one job (not two) | smoke/manual | N/A — script; verify via `gcloud scheduler jobs list` | Manual |
| callback_query dispatch | Router dispatches callback_query updates; existing message path unaffected | unit | `pytest tests/test_router_callback_query.py -x` | Wave 0 |
| PendingPromptStore | set/get/delete/get_open_note_session behave correctly; TTL soft-expiry | unit | `pytest tests/test_pending_prompt_store.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q` (full suite, fail-fast)
- **Per wave merge:** `pytest tests/ -q` (full suite, no fail-fast)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps (new test files needed)
- [ ] `tests/test_training_log_store.py` — covers LOG-01, LOG-02
- [ ] `tests/test_tool_registration_phase20.py` — covers LOG-03, LOG-04 (mirror `tests/test_tools.py` or `TestPhase19ToolRegistration` pattern)
- [ ] `tests/test_training_checkin.py` — covers CHECKIN-02..CHECKIN-05
- [ ] `tests/test_pending_prompt_store.py` — covers PendingPromptStore CRUD + expiry
- [ ] `tests/test_recovery_concern.py` — covers RECOVERY-01, RECOVERY-02
- [ ] `tests/test_router_callback_query.py` — covers callback_query dispatch in _router.py
- [ ] `tests/test_web_server.py` extended with `TestCronWeeklyTrainingReview` — covers REVIEW-01, REVIEW-04
- [ ] `tests/test_docs.py` extended with `test_weekly_training_review_prompt_exists` — covers REVIEW-03

Existing: `tests/test_heartbeat.py` must be extended with `test_weekly_training_review_staleness_threshold` (mirrors `test_autonomous_tick_staleness_threshold_is_one_hour` for 170h).

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (internal Telegram + OIDC — no new auth surfaces) | — |
| V3 Session Management | yes (PendingPromptStore: callback session state) | Soft TTL (20h) + session_key scoped to user; no sensitive data in callback_data |
| V4 Access Control | yes (callback_query user allow-list) | Extend existing `allowed_user_ids` check to the new `_handle_callback_query` branch |
| V5 Input Validation | yes (callback_data parsing) | Parse with prefix check + split; unknown prefixes logged and discarded |
| V6 Cryptography | no | — |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Foreign user taps inline button (if callback_data leaks) | Elevation of privilege | Check `effective_user.id` in `allowed_user_ids` before processing callback_query (mirrors existing text-message guard) |
| callback_data forgery (attacker constructs fake rpe:key:val URL) | Tampering | Validate session_key exists in PendingPromptStore before accepting; unknown session → "couldn't match" message (per UI-SPEC error copy) |
| Stale session replay (old button tap arrives hours later) | Tampering | Soft TTL check in `PendingPromptStore.get()`: reject sessions older than 20h |

---

## Sources

### Primary (HIGH confidence)
- `interfaces/_router.py` (full file read) — `handle_update` structure; line 65 guard confirmed
- `core/scheduled_message.py` (full file read) — `send_and_inject` signature confirmed; no `reply_markup`; no return value
- `interfaces/web_server.py:220-500` (read) — cron route pattern, `_verify_cron_request`, `_log_cron_run`, `_already_sent` interaction
- `memory/firestore_db.py:1-800` (read) — `UserProfileStore`, `JournalStore`, `MealStore`, `SelfStateStore` patterns
- `core/proactive_alerts.py` (full file read) — `run_proactive_alerts` structure; `_already_sent` gate
- `core/morning_briefing.py:140-300` (read) — `_gather_data` pattern; recovery injection point
- `mcp_tools/garmin_tool.py:280-400` (read) — `fetch_garmin_activities`; `perceived_exertion` at line 332; `compute_acwr` at :339; `compute_acwr_from_db` at :396
- `mcp_tools/calendar_tool.py:1-420` (read) — `list_events` hardcodes `calendarId="primary"`; no `calendarList` usage exists
- `core/tools.py:39-55, 680-780, 1250-1420` (read) — SMART_AGENT_DIRECT_TOOLS; WORKER_TOOL_SCHEMAS exclusion; _HANDLERS pattern
- `core/reflection.py:1-300` (read) — brain-composition cron pattern; LLMClient usage
- `core/heartbeat.py:100-135` (read) — `_CRON_MAX_STALENESS_HOURS` dict; `healthkit-sync: 48` staleness key pattern
- `core/self_manifest.py:49-80` (read) — SHA hash computed from tool names + cron route names; auto-includes new additions
- `docs/DEPLOYMENT.md:700-1200` (read) — job inventory table; §14d/§14e gcloud blocks; `allowed_updates=["message"]` at line 489
- `tests/test_meal_store.py` (full file read) — Firestore mock pattern (sys.modules stub at module level)
- `tests/test_web_server.py:1-90` (read) — `_stub_web_server_imports` helper; TestCronAutonomousTick pattern
- python-telegram-bot 22.7 [VERIFIED: live import check]: `InlineKeyboardMarkup`, `InlineKeyboardButton`, `CallbackQuery`, `Bot.send_message(reply_markup=)`, `Bot.answer_callback_query(callback_query_id)` all confirmed importable and working
- requirements.txt (full read) — `python-telegram-bot>=21.0` confirmed; all other dependencies confirmed present

### Secondary (MEDIUM confidence)
- `20-CONTEXT.md` (full read) — 26 locked decisions; all canonical file:line references cross-checked against live source reads
- `20-UI-SPEC.md` (full read) — approved keyboard layouts; callback_data formats; copy strings
- `.planning/REQUIREMENTS.md` (full read) — requirement texts + deviations identified (D-09 vs CHECKIN-01/06, D-21 vs REVIEW-02)

### Tertiary (LOW confidence)
- Google Calendar API calendarList response field names (`id`, `summary`) — consistent with training knowledge but not verified against live API call in this session [A2]

---

## Metadata

**Confidence breakdown:**
- Standard stack / library APIs: HIGH — python-telegram-bot 22.7 verified live; all other dependencies in requirements.txt
- Architecture / Firestore patterns: HIGH — read from live source files
- Pitfalls: HIGH — most from direct code reading; allowed_updates gap confirmed from DEPLOYMENT.md
- calendarList API field names: MEDIUM — standard well-known API; not verified live

**Research date:** 2026-05-31
**Valid until:** 2026-07-01 (stable stack; all dependencies pinned in requirements.txt)
