# Phase 20: Accountability Crons & Recovery Briefing — Pattern Map

**Mapped:** 2026-05-31
**Files analyzed:** 14 new/modified files
**Analogs found:** 12 / 14 (2 genuinely net-new with no analog)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `memory/firestore_db.py` :: `TrainingLogStore` | store | CRUD | `memory/firestore_db.py` :: `JournalStore` (multi-doc collection) + `MealStore` (merge=True idempotency) | exact |
| `memory/firestore_db.py` :: `PendingPromptStore` | store | CRUD + TTL | `memory/firestore_db.py` :: `SelfStateStore` (merge=True upsert) + `JournalStore` (stream+filter read) | role-match |
| `core/training_checkin.py` | service | event-driven + CRUD | `core/proactive_alerts.py` (21:30 cron module, gather → branch → send) | exact |
| `core/weekly_training_review.py` | service | request-response | `core/reflection.py` (brain-composed cron, LLMClient + send_and_inject) | exact |
| `interfaces/_router.py` :: `_handle_callback_query` | middleware | event-driven | No analog — net-new callback_query dispatch; closest structural reference is the existing `handle_update` method and `_handle_text_message` guard pattern | no-analog |
| `interfaces/web_server.py` :: `/cron/weekly-training-review` | route | request-response | `interfaces/web_server.py` :: `@app.post("/cron/autonomous-tick")` (lines 398–435) | exact |
| `core/scheduled_message.py` :: `send_and_inject` extension | utility | request-response | Self (current `send_and_inject` signature — additive keyword arg) | self-extend |
| `core/proactive_alerts.py` (fold check-in) | service | event-driven | Self — `run_proactive_alerts` pattern; check-in appended at end before `_mark_processed` | self-extend |
| `core/morning_briefing.py` :: `_gather_data` (recovery_concern) | service | CRUD | Self — `_gather_data` Pattern-C best-effort blocks (lines 174–) | self-extend |
| `core/heartbeat.py` :: `_CRON_MAX_STALENESS_HOURS` | config | — | Self — `"healthkit-sync": 48` line 115 | self-extend |
| `core/tools.py` :: `log_training` + `get_training_history` | utility | CRUD | `core/tools.py` — Phase 19 `get_training_profile` (brain-direct) and `fetch_recent_activities` (worker-delegated), lines 649–774, 1207–1229, 1340–1345 | exact |
| `mcp_tools/calendar_tool.py` :: `list_training_events` | service | request-response | `mcp_tools/calendar_tool.py` :: `list_events` (lines 71–139) | role-match |
| `prompts/weekly_training_review.md` | config | — | `prompts/reflection.md` (brain-composed narrative with placeholders) | role-match |
| `scripts/bootstrap_shifu_crons.sh` | config | — | `docs/DEPLOYMENT.md` §14d/§14e `gcloud scheduler jobs create` blocks (lines 1082–1109) | role-match |

---

## Pattern Assignments

### `memory/firestore_db.py` :: `TrainingLogStore` (store, CRUD)

**Primary analog:** `memory/firestore_db.py` :: `JournalStore` (multi-doc collection, stream+sort read) and `MealStore` (merge=True idempotency, date-keyed doc IDs).

**Class/collection pattern** (`JournalStore` lines 447–537, `MealStore` lines 540–633):
```python
class TrainingLogStore:
    _COLLECTION = "training_log"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)
```

**Write pattern — idempotent merge** (mirror `MealStore.upsert` + `SelfStateStore.set`, lines 570–603, 410–422):
```python
def log_session(self, date: str, slot: str, ...) -> None:
    doc_id = f"{date}_{slot}"
    try:
        self._col.document(doc_id).set(
            {**payload, "updated_at": firestore.SERVER_TIMESTAMP},
            merge=True,          # idempotent — Garmin silent sync safe to re-run
        )
    except Exception:
        logger.error("TrainingLogStore.log_session(%r) failed", doc_id, exc_info=True)
        raise
```
Note: `JournalStore.set` uses `set()` WITHOUT `merge=True` (full overwrite per D-12 idempotency there). `TrainingLogStore` needs `merge=True` because Garmin sync may write before the user replies — mirrors `MealStore.upsert`.

**Read pattern — stream + Python sort** (mirror `JournalStore.get_recent` lines 512–537):
```python
def get_recent(self, days: int) -> list[dict]:
    try:
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=days)).isoformat()
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

**Single-date read** (mirror `JournalStore.get` lines 469–488):
```python
def get_by_date(self, date_str: str) -> list[dict]:
    try:
        snaps = list(self._col.stream())
        return [
            {**snap.to_dict(), "doc_id": snap.id}
            for snap in snaps
            if snap.id.startswith(date_str)
        ]
    except Exception:
        logger.warning("TrainingLogStore.get_by_date(%r) failed", date_str, exc_info=True)
        return []
```

---

### `memory/firestore_db.py` :: `PendingPromptStore` (store, CRUD + soft TTL)

**Primary analog:** `memory/firestore_db.py` :: `SelfStateStore` (merge=True upsert, singleton document pattern) + `JournalStore.get_recent` (stream + Python filter). No exact match; PendingPromptStore is multi-doc (one per session), not a singleton.

**Class skeleton** (mirror `SelfStateStore` constructor pattern lines 377–394):
```python
class PendingPromptStore:
    _COLLECTION = "pending_prompts"

    def __init__(self, project_id: str, database: str = "(default)") -> None:
        self._client = _make_firestore_client(project_id, database)
        self._col = self._client.collection(self._COLLECTION)
```

**Upsert pattern** (mirror `SelfStateStore.set` lines 410–422):
```python
def set(self, session_key: str, payload: dict) -> None:
    try:
        self._col.document(session_key).set(
            {**payload, "session_key": session_key},
            merge=True,
        )
    except Exception:
        logger.warning("PendingPromptStore.set(%r) failed", session_key, exc_info=True)
```
Note: writes NEVER raise (unlike `SelfStateStore.set`) — a failed pending-prompt write is logged and silent-skipped; the check-in degrades to no follow-up, not a crash.

**Read with soft TTL** (mirror `UserProfileStore.load` lines 126–135 never-raises pattern):
```python
def get(self, session_key: str) -> dict | None:
    try:
        from datetime import datetime, timezone
        snap = self._col.document(session_key).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        expires_at = data.get("expires_at")
        if expires_at:
            if isinstance(expires_at, str):
                from datetime import datetime
                exp = datetime.fromisoformat(expires_at)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
            else:
                exp = expires_at
            if datetime.now(timezone.utc) > exp:
                return None   # soft TTL expired — silently return None
        return data
    except Exception:
        logger.warning("PendingPromptStore.get(%r) failed", session_key, exc_info=True)
        return None
```

**Delete** (mirror `IncidentStore` doc reference pattern lines 248–274):
```python
def delete(self, session_key: str) -> None:
    try:
        self._col.document(session_key).delete()
    except Exception:
        logger.warning("PendingPromptStore.delete(%r) failed", session_key, exc_info=True)
```

---

### `core/training_checkin.py` (service, event-driven + CRUD)

**Primary analog:** `core/proactive_alerts.py` (full file) — same module-level entry function pattern, same best-effort try/except per data source, same send_and_inject call, same dedup/guard discipline.

**Module entry point pattern** (mirror `proactive_alerts.run_proactive_alerts` lines 91–140):
```python
async def run_training_checkin(bot: Bot, today_iso: str) -> None:
    """Sync Garmin, scan Training calendar, prompt for unlogged workouts.

    Called from core/proactive_alerts.run_proactive_alerts after its own
    alert composition. Runs regardless of the _already_sent gate (own idempotency
    via TrainingLogStore merge=True).
    """
    # 1. Silent Garmin sync
    _silent_garmin_sync(today_iso)

    # 2. Fetch Training calendar events for today (time-gated per D-07)
    training_events = _get_todays_training_events(today_iso)
    if not training_events:
        logger.info("training_checkin: no training events for %s", today_iso)
        return

    # 3. For each unlogged event whose start < now, branch and prompt
    from core.scheduled_message import send_and_inject
    for event in training_events:
        ...
```

**LLM composition pattern** (mirror `proactive_alerts._compose_alert` lines 334–366):
```python
def _compose_recovery_concern(garmin_data: dict, ...) -> dict | None:
    try:
        from core.llm_client import LLMClient
        client = LLMClient(
            backend=os.environ["SMART_AGENT_BACKEND"],
            model=os.environ["SMART_AGENT_MODEL"],
            api_key=os.environ["SMART_AGENT_API_KEY"],
        )
        ...
    except Exception:
        logger.warning("training_checkin: LLM call failed", exc_info=True)
```

**Dedup/guard pattern** (mirror `proactive_alerts._already_sent` / `_mark_processed` lines 147–168):
```python
def _make_firestore_client():
    from memory.firestore_db import _make_firestore_client as _mfc
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _mfc(project_id, database)
```

**Inline keyboard construction** — no codebase analog; use python-telegram-bot 22.7 verified API directly per RESEARCH.md Finding 1:
```python
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

rpe_keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton(str(i), callback_data=f"rpe:{session_key}:{i}") for i in range(1, 6)],
    [InlineKeyboardButton(str(i), callback_data=f"rpe:{session_key}:{i}") for i in range(6, 11)],
])
```

---

### `core/weekly_training_review.py` (service, request-response)

**Primary analog:** `core/reflection.py` (brain-composed cron, SMART_AGENT_* LLMClient, send_and_inject, prompt file loading).

**LLM brain call pattern** (`reflection.py` lines 288–322):
```python
from pathlib import Path
from core.llm_client import LLMClient

prompt_path = Path(__file__).parent.parent / "prompts" / "weekly_training_review.md"
system_prompt = prompt_path.read_text(encoding="utf-8").replace("{today_date}", today_str)

client = LLMClient(
    backend=os.environ["SMART_AGENT_BACKEND"],
    model=os.environ["SMART_AGENT_MODEL"],
    api_key=os.environ["SMART_AGENT_API_KEY"],
)
response = client.chat(
    messages=[{"role": "user", "content": user_message}],
    system=system_prompt,
    purpose="weekly_review",
)
text = (response.get("text") or "").strip()
```
Note: D-17 uses brain, not tick-brain. `reflection.py:305` uses `SMART_AGENT_BACKEND/MODEL/API_KEY` — copy exactly.

**send_and_inject call** (mirror `proactive_alerts.py` line 138 and `morning_briefing.py` line 140):
```python
from core.scheduled_message import send_and_inject
await send_and_inject(bot, message, inject_into_conversation=True)
```
D-24 says always send — no silent-omit guard (unlike `morning_briefing.py` which early-returns when data absent).

**Data gather pattern** — mirror `morning_briefing._gather_data` best-effort try/except blocks (lines 174–):
```python
def _gather_week_data(today_iso: str) -> dict:
    data: dict = {"today_date": today_iso}
    try:
        ...
    except Exception:
        logger.warning("weekly_review: <source> fetch failed", exc_info=True)
        data["<source>"] = None
    return data
```

---

### `interfaces/_router.py` :: `_handle_callback_query` (middleware, event-driven)

**No analog exists.** The current `handle_update` (full file, line 65) drops all non-message updates with `if update.message is None: return`. There is no callback_query dispatch anywhere in the codebase.

**Closest structural reference — existing `handle_update` guard and allow-list check** (`_router.py` lines 51–77):
```python
async def handle_update(self, update: Update) -> None:
    # Guard: ignore updates that carry no message (e.g. channel posts, edits).
    if update.message is None:
        return

    telegram_user_id = update.effective_user.id
    if telegram_user_id not in self.allowed_user_ids:
        logger.warning(
            "Unauthorised update from user_id=%d — silently ignored.",
            telegram_user_id,
        )
        return
```

**Extension point — insert BEFORE line 65 guard** (new branch, no codebase analog):
```python
async def handle_update(self, update: Update) -> None:
    # NEW (Phase 20): dispatch inline-keyboard button taps
    if update.callback_query is not None:
        if update.effective_user.id not in self.allowed_user_ids:
            return
        await self._handle_callback_query(update)
        return

    # Existing guard unchanged — leave line 65 in place
    if update.message is None:
        return
    ...
```

**`_handle_callback_query` dispatch skeleton** — no analog; see RESEARCH.md Finding 3:
```python
async def _handle_callback_query(self, update: Update) -> None:
    cq = update.callback_query
    await cq.answer()   # dismiss Telegram spinner — must be called immediately
    data = cq.data or ""
    if data.startswith("rpe:"):
        await self._dispatch_to_checkin_handler("rpe", data)
    elif data.startswith("watchoff:"):
        await self._dispatch_to_checkin_handler("watchoff", data)
    elif data.startswith("skipreason:"):
        await self._dispatch_to_checkin_handler("skipreason", data)
    else:
        logger.warning("training_checkin: unknown callback_data=%r", data)
```

**Reply-to detection for notes step** — `update.message.reply_to_message.message_id` (verified live in RESEARCH.md Finding 5); no codebase analog but is plain attribute access on the `Update` object already imported:
```python
# In handle_update text-message path — add before _handle_text_message call
if update.message.reply_to_message is not None:
    await self._check_pending_note_reply(update)
    return  # or fall through if not a pending note
```

---

### `interfaces/web_server.py` :: `/cron/weekly-training-review` (route, request-response)

**Primary analog:** `interfaces/web_server.py` :: `@app.post("/cron/autonomous-tick")` lines 398–435.

**Full route pattern** (lines 398–435 — copy verbatim, substituting names):
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
Key invariants (from analog): `_verify_cron_request` called first; `_application is None` guard; lazy module import inside handler; `_log_cron_run` on both success AND exception path; `raise` re-raises on exception so Cloud Run logs the 500.

---

### `core/scheduled_message.py` :: `send_and_inject` extension (utility, request-response)

**Self-extension** — current signature is at lines 22–57:
```python
async def send_and_inject(
    bot: Bot,
    text: str,
    *,
    inject_into_conversation: bool = False,
) -> None:
    user_id = _telegram_user_id()
    await bot.send_message(chat_id=user_id, text=text)
    if not inject_into_conversation:
        return
    try:
        ...store.append(user_id, "assistant", text)
    except Exception:
        logger.warning("...", exc_info=True)
```

**Extension adds two things** (backward-compatible):
1. `reply_markup=None` keyword-only argument (passed through to `bot.send_message`)
2. Return `telegram.Message` so callers can read `msg.message_id` for reply-to detection

```python
async def send_and_inject(
    bot: Bot,
    text: str,
    *,
    inject_into_conversation: bool = False,
    reply_markup=None,          # InlineKeyboardMarkup | None
) -> "telegram.Message":        # was None; now returns Message for message_id
    user_id = _telegram_user_id()
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
    if not inject_into_conversation:
        return msg
    try:
        ...store.append(user_id, "assistant", text)
        ...
    except Exception:
        logger.warning("...", exc_info=True)
    return msg
```
All existing callers pass only `(bot, text)` or `(bot, text, inject_into_conversation=True)` — adding `reply_markup=None` as a keyword-only default is backward-compatible. Returning `msg` is also safe (existing callers ignore the return value).

---

### `core/proactive_alerts.py` (extend — fold check-in)

**Self-extension** — call `run_training_checkin` at end of `run_proactive_alerts`, BEFORE `_mark_processed`. Key constraint from Pitfall 5 (RESEARCH.md): check-in must run before the `_already_sent` / `_mark_processed` gate so it can be retried independently.

**Fold-in pattern** (after line 139, before `_mark_processed`):
```python
# Phase 20 — D-09: training check-in folded into the 21:30 proactive-alerts cron
try:
    from core.training_checkin import run_training_checkin
    today = datetime.now(_TZ).date().isoformat()
    await run_training_checkin(bot, today)
except Exception:
    logger.warning("proactive_alerts: training check-in failed", exc_info=True)
    # Non-fatal — proactive alerts already sent; check-in failure logged only
```
Placement: after the `send_and_inject` call for the existing alert (line 138) but before `_mark_processed(target_date, alert_sent=True)` — and also call check-in from the `no issues found` early-return path (line 126) to ensure it runs even on quiet evenings.

---

### `core/morning_briefing.py` :: `_gather_data` (extend — recovery_concern)

**Self-extension** — inject a new best-effort block inside `_gather_data` (lines 174–) following the existing Pattern-C discipline:
```python
# Pattern-C: each source in its own try/except; failure silent-omits the key
try:
    from mcp_tools.garmin_tool import fetch_garmin_today
    garmin = fetch_garmin_today()
    if garmin and garmin.get("date") == today_iso:
        data["garmin"] = {"state": 1, **garmin}
    else:
        data["garmin"] = {"state": 2}
except Exception:
    logger.warning("morning_briefing: Garmin data fetch failed", exc_info=True)
```

**New block to add after Garmin + Postgres writeback** (mirror same Pattern-C shape):
```python
# Phase 20 — RECOVERY-01: compute recovery concern from ACWR + HRV + sleep + today's intensity
try:
    from core.training_checkin import compute_recovery_concern
    rc = compute_recovery_concern(
        garmin_data=data.get("garmin"),
        today_iso=today_iso,
    )
    if rc:
        data["recovery_concern"] = rc
except Exception:
    logger.warning("morning_briefing: recovery_concern computation failed", exc_info=True)
    # silent omit — no "all clear" placeholder (D-13 guardrail)
```

---

### `core/heartbeat.py` :: `_CRON_MAX_STALENESS_HOURS` (extend — new key)

**Self-extension** — add one key to the dict at lines 108–116:
```python
_CRON_MAX_STALENESS_HOURS = {
    "morning-briefing": 26,
    "proactive-alerts": 26,
    "ingest-chats": 26,
    "ingest-chat-exports": 26,
    "reflect": 26,
    "autonomous-tick": 1,
    "healthkit-sync": 48,          # Phase 19.1 — iPhone Shortcut push bridge
    "weekly-training-review": 170, # Phase 20 — Sunday 10:00; 170h = 7d + 2h slack
}
```
The `healthkit-sync: 48` line is the direct pattern precedent (Phase 19.1). Rationale for 170: weekly job; one missed Sunday plus 2h tolerance prevents spurious heartbeat alerts during the second week.

---

### `core/tools.py` :: `log_training` + `get_training_history` (extend — tool registration)

**Primary analog:** Phase 19 `get_training_profile` (brain-direct, 5-site registration) and `fetch_recent_activities` (worker-delegated).

**Site 1 — `SMART_AGENT_DIRECT_TOOLS` frozenset** (lines 39–55 — brain-direct tools only):
```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    ...
    # Phase 20 — brain-direct training log (LOG-03)
    "log_training",
    # NOTE: get_training_history is worker-delegated — NOT added here
})
```

**Site 2 — `TOOL_SCHEMAS` list** (add after Phase 19 block at line 649):
```python
{
    "name": "log_training",
    "description": (
        "Log a completed or skipped training session. Brain-direct. "
        "Call when Sir reports a workout done, skipped, or RPE. "
        "Parameters: date (YYYY-MM-DD), session_type (gym/run/etc), "
        "completed (bool), rpe (1–10 optional), notes (optional), "
        "skipped_reason (optional)."
    ),
    "input_schema": { ... },
},
{
    "name": "get_training_history",
    "description": (
        "Return recent training log entries from Firestore. "
        "Worker-delegated. Use days param (default 7) for recent history."
    ),
    "input_schema": { ... },
},
```

**Site 3 — `WORKER_TOOL_SCHEMAS` exclusion** (lines 760–775 — add `log_training` to exclusion set):
```python
WORKER_TOOL_SCHEMAS = [
    s for s in TOOL_SCHEMAS
    if s["name"] not in {
        ...
        "get_training_profile",
        "update_training_profile",
        "log_training",           # Phase 20 — brain-direct only
    }
]
```

**Site 4 — handler functions** (mirror `_handle_get_training_profile` lines 1207–1214):
```python
def _handle_log_training(**kwargs) -> str:
    """LOG-03 brain-direct: write one training session to TrainingLogStore."""
    from memory.firestore_db import TrainingLogStore
    store = TrainingLogStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    try:
        store.log_session(**kwargs)
        return json.dumps({"ok": True})
    except Exception as exc:
        return json.dumps({"error": str(exc)})

def _handle_get_training_history(days: int = 7) -> str:
    """LOG-04 worker-delegated: return recent training log entries."""
    from memory.firestore_db import TrainingLogStore
    store = TrainingLogStore(
        project_id=os.environ["GCP_PROJECT_ID"],
        database=os.environ.get("FIRESTORE_DATABASE", "(default)"),
    )
    return json.dumps(store.get_recent(days))
```

**Site 5 — `_HANDLERS` dict** (lines 1319–1354):
```python
_HANDLERS: dict[str, object] = {
    ...
    # Phase 20 — training log tools
    "log_training":         lambda args: _handle_log_training(**args),
    "get_training_history": lambda args: _handle_get_training_history(**args),
}
```

---

### `mcp_tools/calendar_tool.py` :: `list_training_events` (extend, request-response)

**Primary analog:** `mcp_tools/calendar_tool.py` :: `list_events` (lines 71–139) — same `GoogleCalendarManager` class, same `_get_service()` pattern, same `events().list()` call shape.

**New method skeleton** — add to `GoogleCalendarManager` after `list_events`:
```python
def get_calendar_id_by_name(self, name: str) -> str | None:
    """Return the calendarId for the calendar with the given display name.

    Calls calendarList().list() and matches on item["summary"].
    Returns None if not found or on API error — never raises.
    """
    try:
        service = self._get_service()     # same lazy-init pattern as list_events line 99
        result = service.calendarList().list().execute()
        for item in result.get("items", []):
            if item.get("summary", "").strip() == name:
                return item.get("id")
        return None
    except Exception as exc:            # same HttpError catch as list_events
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
    """List events from the named training calendar, filtering buffer blocks."""
    cal_id = self.get_calendar_id_by_name(calendar_name)
    if cal_id is None:
        logger.warning("Training calendar %r not found", calendar_name)
        return []
    try:
        service = self._get_service()
        result = (
            service.events()
            .list(
                calendarId=cal_id,         # NOT "primary" — resolved by name
                timeMin=time_min_iso,
                timeMax=time_max_iso,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )
        events = []
        for item in result.get("items", []):
            summary = item.get("summary", "") or ""
            # D-02: filter buffer blocks
            if summary.startswith("Get Ready:") or summary.startswith("Travel:"):
                continue
            start_field = item.get("start", {})
            end_field = item.get("end", {})
            start = start_field.get("dateTime") or start_field.get("date", "")
            end = end_field.get("dateTime") or end_field.get("date", "")
            events.append({
                "id": item.get("id", ""),
                "summary": summary,
                "start": start,
                "end": end,
                "description": item.get("description", ""),
            })
        return events
    except Exception:
        logger.warning("list_training_events failed", exc_info=True)
        return []
```
The `list_events` response-shaping block (lines 118–138) is the direct template for the inner loop.

---

### `prompts/weekly_training_review.md` (config, new file)

**Primary analog:** `prompts/reflection.md` and `prompts/proactive_alert.md` — both use `{today_date}` placeholder substitution, JARVIS voice directives, and a structured data JSON block as the user message.

**Template pattern** (from `proactive_alerts._compose_alert` lines 337–347):
- `prompt_path.read_text(encoding="utf-8").replace("{today_date}", today_str)` — same substitution convention
- System prompt = the `.md` file content; user message = `json.dumps(week_data, ensure_ascii=False, indent=2)`

**Required placeholders (per D-18..D-23):**
- `{today_date}` — standard substitution
- The review prompt must instruct the brain to: emit emoji/bullet scorecard (✅/❌/⚠️), add richer coaching narrative, close with one JARVIS-voiced suggestion grounded in the week's data, and apply `meal_audit.md` nutrition guidance to MealStore totals (D-21)

---

### `scripts/bootstrap_shifu_crons.sh` (config, new file)

**Primary analog:** `docs/DEPLOYMENT.md` §14e `gcloud scheduler jobs create http` block (lines 1100–1109).

**Re-runnable describe-or-create pattern** (D-25, no existing script analog — pattern from RESEARCH.md Finding 13):
```bash
#!/usr/bin/env bash
# bootstrap_shifu_crons.sh — Phase 20 (Shifu)
# Re-runnable: describe → update if exists, create if absent.
# Creates: klaus-weekly-training-review
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-me-west1}"
SERVICE_URL="${SERVICE_URL:?set SERVICE_URL}"
CLOUD_SCHEDULER_SA_EMAIL="${CLOUD_SCHEDULER_SA_EMAIL:?set CLOUD_SCHEDULER_SA_EMAIL}"

if gcloud scheduler jobs describe "klaus-weekly-training-review" \
     --location="${REGION}" --project="${PROJECT_ID}" &>/dev/null; then
  gcloud scheduler jobs update http "klaus-weekly-training-review" \
    --schedule="0 10 * * 0" \
    --time-zone="Asia/Jerusalem" \
    --uri="${SERVICE_URL}/cron/weekly-training-review" \
    --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
    --oidc-token-audience="${SERVICE_URL}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}"
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
echo "Done."
```
Compare to DEPLOYMENT.md §14e (lines 1100–1109): that is a plain `create` block; this adds `describe || create` idempotency per D-25.

---

## Shared Patterns

### OIDC Cron Verification
**Source:** `interfaces/web_server.py` lines 232–275, `_verify_cron_request`
**Apply to:** `/cron/weekly-training-review` route (REVIEW-01), `bootstrap_shifu_crons.sh` (uses same SA email)
```python
await _verify_cron_request(request)
# OR bypass in local dev:
# CRON_DEV_BYPASS=true skips the check (line 244)
```

### Cron Liveness Ledger
**Source:** `interfaces/web_server.py` lines 338–344, `_log_cron_run`
**Apply to:** `/cron/weekly-training-review`, `proactive_alerts.py` (check-in fold)
```python
def _log_cron_run(job_id: str, ok: bool, ...) -> None:
    """Best-effort liveness ledger write for a cron endpoint. Never raises."""
    try:
        from memory.firestore_db import record_cron_run
        record_cron_run(job_id, ok, ...)
    except Exception:
        logger.warning("Failed to record cron run for %s", job_id, exc_info=True)
```
Pattern: called on BOTH success and exception paths; exception path always re-raises after logging.

### Firestore Client Instantiation
**Source:** `memory/firestore_db.py` lines 22–38, `_make_firestore_client`
**Apply to:** `TrainingLogStore`, `PendingPromptStore`
```python
def __init__(self, project_id: str, database: str = "(default)") -> None:
    self._client = _make_firestore_client(project_id, database)
    self._col = self._client.collection(self._COLLECTION)
```
Callers always pass `project_id=os.environ["GCP_PROJECT_ID"], database=os.environ.get("FIRESTORE_DATABASE", "(default)")`.

### Error Handling — Never-Raises Reads
**Source:** `memory/firestore_db.py` `UserProfileStore.load()` lines 126–135, `JournalStore.get_recent` lines 512–537
**Apply to:** `TrainingLogStore.get_recent`, `TrainingLogStore.get_by_date`, `PendingPromptStore.get`
```python
try:
    # ... Firestore read ...
    return result
except Exception:
    logger.warning("<StoreName>.<method>(%r) failed", key, exc_info=True)
    return []   # or None or {}
```

### Error Handling — Re-Raising Writes
**Source:** `memory/firestore_db.py` `UserProfileStore.update()` lines 137–146, `MealStore.upsert` lines 570–603
**Apply to:** `TrainingLogStore.log_session` (re-raises on write failure so callers know the sync failed)
```python
try:
    self._col.document(doc_id).set({...}, merge=True)
except Exception:
    logger.error("<StoreName>.<method>(%r) failed", doc_id, exc_info=True)
    raise
```

### Pattern-C Best-Effort Block (gather functions)
**Source:** `core/morning_briefing.py` `_gather_data` lines 174– (each source in its own try/except)
**Apply to:** `core/training_checkin.py` `_silent_garmin_sync`, `compute_recovery_concern`; `core/weekly_training_review.py` `_gather_week_data`
```python
try:
    from mcp_tools.garmin_tool import fetch_garmin_today
    data["garmin"] = fetch_garmin_today()
except Exception:
    logger.warning("<module>: <source> fetch failed", exc_info=True)
    data["garmin"] = None
```

### Brain LLM Call (Smart Agent backend)
**Source:** `core/reflection.py` lines 301–322, `core/proactive_alerts.py` lines 349–356
**Apply to:** `core/weekly_training_review.py` (`_compose_review`), `core/training_checkin.py` (recovery concern if LLM-composed)
```python
from core.llm_client import LLMClient
client = LLMClient(
    backend=os.environ["SMART_AGENT_BACKEND"],
    model=os.environ["SMART_AGENT_MODEL"],
    api_key=os.environ["SMART_AGENT_API_KEY"],
)
response = client.chat(
    messages=[{"role": "user", "content": user_message}],
    system=system_prompt,
    purpose="weekly_review",   # change purpose string per use
)
text = (response.get("text") or "").strip()
```

### Lazy Module Import in Cron Routes
**Source:** `interfaces/web_server.py` lines 363, 385, 425
**Apply to:** `/cron/weekly-training-review` route
```python
import core.weekly_training_review as _review   # inside the route handler
```
WHY (from line 424 comment): keeps heavy module out of web_server import-time so `/health` cold-start stays fast.

### Tool Handler Return Convention
**Source:** `core/tools.py` `_handle_get_training_profile` lines 1207–1214, `_handle_update_training_profile` lines 1217–1228
**Apply to:** `_handle_log_training`, `_handle_get_training_history`
```python
return json.dumps({"ok": True})      # success
return json.dumps({"error": str(exc)})  # failure (never raises from handler)
```

### Telegram Allow-List Guard
**Source:** `interfaces/_router.py` lines 68–77
**Apply to:** `_handle_callback_query` (must check before processing button data)
```python
if update.effective_user.id not in self.allowed_user_ids:
    logger.warning(
        "Unauthorised update from user_id=%d — silently ignored.",
        telegram_user_id,
    )
    return
```

### Test — Firestore Mock (sys.modules stub)
**Source:** `tests/test_meal_store.py` lines 19–60 (`_install_firestore_mock`)
**Apply to:** `tests/test_training_log_store.py`, `tests/test_pending_prompt_store.py`
Pattern: install `google.cloud.firestore` mock at `sys.modules` level before importing `memory.firestore_db`; use `MagicMock` for the Firestore client; `SERVER_TIMESTAMP = object()` as a distinguishable sentinel.

### Test — Web Server Cron Route (stub imports + TestClient)
**Source:** `tests/test_web_server.py` lines 43–90 (`_stub_web_server_imports`, `TestCronAutonomousTick`)
**Apply to:** `TestCronWeeklyTrainingReview` extension of `tests/test_web_server.py`
```python
stubs = _stub_web_server_imports()
with patch.dict(sys.modules, stubs):
    import interfaces.web_server as ws
    from fastapi.testclient import TestClient
    with patch.dict(os.environ, _BASE_ENV):
        ws._application = fake_app
        async_mock = AsyncMock(return_value=None)
        with patch("core.weekly_training_review.run_weekly_review", async_mock):
            client = TestClient(ws.app)
            resp = client.post("/cron/weekly-training-review")
            assert resp.status_code == 200
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `interfaces/_router.py` :: `_handle_callback_query` + reply-to detection | middleware | event-driven | No inline-keyboard or `callback_query` dispatch exists anywhere in the codebase today. `_router.py:65` actively drops all non-message updates. The closest reference is the existing `handle_update` allow-list guard and the `_handle_text_message` dispatcher shape — use those as structural templates for the new branch. |
| `scripts/bootstrap_shifu_crons.sh` (re-runnable describe-or-create) | config | — | No existing `.sh` bootstrap script with `describe || create` idempotency in `scripts/`. All prior scheduler jobs are documented as one-shot `gcloud scheduler jobs create` commands in `docs/DEPLOYMENT.md` — no shell script exists as a template. DEPLOYMENT.md §14e `create` block is the closest analog for the `gcloud` flag set. |

---

## Critical Pitfalls for Planner (from RESEARCH.md)

These are code-level traps the planner should encode as explicit task guards:

1. **`allowed_updates` must include `"callback_query"`** — DEPLOYMENT.md line 489 currently has `allowed_updates=["message"]`. Without updating the `setWebhook` call to include `"callback_query"`, all button taps are silently swallowed by Telegram before reaching the server. Document as a required operator step after deploy.

2. **Router `callback_query` branch BEFORE line 65 guard** — `_router.py:65` `if update.message is None: return` drops callback_query updates because `update.message` is `None` on a callback_query. New branch must be inserted before line 65.

3. **`PendingPromptStore.delete` on all terminal transitions** — expired/resolved sessions must be deleted to prevent stale `awaiting_notes` state triggering on the wrong session next day (Pitfall 3).

4. **`TrainingLogStore.log_session` uses `merge=True`** — Garmin silent sync may write before user button tap; idempotent merge on `{date}_{slot}` key prevents duplicate rows (Pitfall 4).

5. **Training check-in runs BEFORE `_already_sent` gate** — check-in must run before `_mark_processed(target_date)` in `proactive_alerts.py` so a partial-failure retry is not blocked (Pitfall 5).

6. **Garmin RPE normalisation** — `perceived_exertion` from `garmin_tool.py:332` is stored raw (10–100 scale). Normalise to 1–10 in `TrainingLogStore.log_session`: `rpe = perceived_exertion // 10 if perceived_exertion is not None else None` (Pitfall 7).

7. **Weekly review DST boundary** — always construct Sun/Sat boundaries as `datetime(..., tzinfo=ZoneInfo("Asia/Jerusalem"))`, not naive `date` objects, when querying Firestore (Pitfall 8).

---

## Metadata

**Analog search scope:** `core/`, `memory/`, `interfaces/`, `mcp_tools/`, `tests/`, `scripts/`, `docs/DEPLOYMENT.md`
**Files scanned:** 16 source files read directly
**Pattern extraction date:** 2026-05-31
