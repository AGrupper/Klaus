# Architecture Research

**Domain:** Klaus Hub (v5.0) — Web PWA integration with existing Klaus Cloud Run service
**Researched:** 2026-06-13
**Confidence:** HIGH (all integration points verified from direct code reading of all affected files)

---

## System Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    FastAPI  (interfaces/web_server.py)                      │
│                                                                             │
│  ┌───────────────┐   ┌──────────────────┐   ┌────────────────────────┐    │
│  │ /telegram-    │   │ /api/*           │   │ /cron/*                │    │
│  │ webhook       │   │ (new: hub)       │   │ /internal/*            │    │
│  │ /internal/    │   │ Google Sign-In   │   │ /trigger/*             │    │
│  │ process-      │   │ session cookie   │   │ OIDC / shared-secret   │    │
│  │ update        │   │ auth (new)       │   │ auth  (UNCHANGED)      │    │
│  └──────┬────────┘   └────────┬─────────┘   └──────────────────────-─┘   │
│         │                     │                                            │
│         │   StaticFiles at /  (frontend/dist/ — mounted LAST, after all    │
│         │   route definitions so existing routes always win)               │
└─────────┼─────────────────────┼─────────────────────────────────────────-─┘
          │                     │
          ▼                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│              Cloud Tasks queue  (me-central1)                               │
│                                                                             │
│  enqueue_update(payload)       → POST /internal/process-update              │
│  enqueue_hub_message(payload)  → POST /internal/process-hub-message  (new) │
│                                                                             │
│  Both tasks carry OIDC token from CLOUD_SCHEDULER_SA_EMAIL.                │
│  Both targets run with full Cloud Run CPU (request is in-flight).          │
└────────────────────────────────────────────────────────────────────────────┘
          │                     │
          ▼                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│              core/   (orchestration — mostly unchanged)                     │
│                                                                             │
│  AgentOrchestrator._run_smart_loop (brain)  ← unchanged singleton          │
│  MessageRouter.handle_update        (Telegram)                              │
│  MessageRouter.handle_hub_message   (hub, new)                             │
│                                                                             │
│  scheduled_message.send_and_inject  ← gains hub_push + telegram_mirror     │
│  autonomous.gather_situation        ← gains _gather_habits_state() source  │
│  tools.py  TOOL_SCHEMAS             ← native task/habit tools; drop TickTick│
└────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────────────────────────┐
│              Firestore  (database: "klaus-firestore")                       │
│                                                                             │
│  conversations/         (unchanged — shared by Telegram + hub)             │
│  tasks/                 (new — TaskStore)                                   │
│  habits/                (new — HabitStore, with completions sub-collection) │
│  push_subscriptions/    (new — PushSubscriptionStore)                       │
│  outreach_log/          (unchanged — D-10 gating unmodified)               │
└────────────────────────────────────────────────────────────────────────────┘
          ▲
          │  serves built assets
┌─────────┴───────────────────────────────────────────────────────────────── ┐
│              frontend/dist/   (React + TypeScript PWA)                      │
│                                                                             │
│  Installed on iPhone home screen and opened as window on PC.               │
│  Polls  GET /api/messages/since?after=<cursor>  while tab is open.         │
│  Receives  Web Push  when closed  (Phase 4).                               │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

| Component | Responsibility | Status |
|-----------|---------------|--------|
| `interfaces/web_server.py` | Route mounting, all auth surfaces, lifespan | Modify: add `include_router` + StaticFiles mount at end |
| `interfaces/hub_api.py` | All `/api/*` handlers, session dependency | New file |
| `frontend/` | React + TypeScript + Vite PWA source | New directory |
| `core/task_dispatch.py` | Cloud Tasks enqueue for full-CPU turns | Modify: add `enqueue_hub_message()` |
| `interfaces/_router.py` | Telegram message routing | Modify: add `handle_hub_message()` method |
| `core/scheduled_message.py` | Proactive message delivery | Modify: add `hub_push` + `telegram_mirror` kwargs |
| `core/autonomous.py` | Layer-0 gather, triage, compose | Modify: add `_gather_habits_state()` source; rename TickTick gather |
| `core/tools.py` | Tool schemas + dispatch | Modify: add task/habit tools to `SMART_AGENT_DIRECT_TOOLS`; retire TickTick schemas |
| `memory/firestore_db.py` | All Firestore stores | Modify: add TaskStore, HabitStore, PushSubscriptionStore |
| `mcp_tools/ticktick_tool.py` | TickTick task sync | Retire after one-time import (Phase 2) |
| `scripts/import_ticktick.py` | One-time migration TickTick → TaskStore | New script |

---

## Recommended Project Structure

```
Klaus/
├── frontend/                        # new — React + TypeScript PWA
│   ├── src/
│   │   ├── components/              # shared UI components
│   │   ├── pages/
│   │   │   ├── Today.tsx            # Today timeline (home)
│   │   │   ├── Tasks.tsx
│   │   │   ├── Habits.tsx
│   │   │   ├── Health.tsx
│   │   │   └── Chat.tsx             # center tab on phone
│   │   ├── api/                     # typed fetch wrappers for /api/*
│   │   └── sw.ts                    # service worker: Web Push + installability
│   ├── public/manifest.json         # PWA manifest (name, icons, display: standalone)
│   ├── vite.config.ts               # PWA plugin, build output → dist/
│   └── package.json
├── interfaces/
│   ├── web_server.py                # modified: add include_router + StaticFiles
│   ├── hub_api.py                   # new: /api/* router + session dependency
│   └── _router.py                   # modified: add handle_hub_message()
├── core/
│   ├── task_dispatch.py             # modified: enqueue_hub_message()
│   ├── scheduled_message.py         # modified: hub_push + telegram_mirror
│   ├── autonomous.py                # modified: _gather_habits_state()
│   └── tools.py                     # modified: task/habit tools, drop TickTick
├── memory/
│   └── firestore_db.py              # modified: TaskStore, HabitStore, PushSubscriptionStore
└── scripts/
    └── import_ticktick.py           # new: one-time TickTick → TaskStore migration
```

### Structure Rationale

- **frontend/ is a peer to interfaces/ and core/,** not nested inside any Python package. Vite tooling runs independently; `npm run build` outputs to `frontend/dist/` which FastAPI mounts.
- **interfaces/hub_api.py** is separate from `web_server.py` because `web_server.py` already contains four distinct auth patterns (Telegram HMAC, OIDC cron, iOS shared-secret ×2). Adding session cookie auth inline would make it a god file and obscure which auth path applies to each route.
- **scripts/import_ticktick.py** lives in `scripts/` — the convention for one-time operational tools — so it can never be accidentally invoked by any cron or import path.

---

## Integration Point 1: SPA Mount and Auth Middleware in `web_server.py`

### The mounting rule

FastAPI resolves routes in registration order. A `StaticFiles` mount at `/` with `html=True` will serve `index.html` for any unmatched path — if registered before any other routes, it captures everything. The invariant is:

**`StaticFiles` mount must be the last statement in `web_server.py` after all `@app.post`/`@app.get` decorators and `include_router()` calls.**

```python
# interfaces/web_server.py — additions at the BOTTOM of the file

from interfaces.hub_api import router as hub_router

# /api/* routes (session-authed, defined in hub_api.py)
app.include_router(hub_router, prefix="/api")

# SPA catch-all — MUST be last.
# Serves frontend/dist/. html=True makes any unresolved path return index.html
# so the React client-side router handles /tasks, /habits, /chat, etc.
# /api/*, /cron/*, /telegram-webhook, /internal/* are resolved BEFORE this mount.
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="spa",
    )
```

The `if _FRONTEND_DIST.exists()` guard means tests and local dev without a built frontend do not fail.

### Session auth as a FastAPI dependency, not global middleware

Global `@app.middleware("http")` fires on every request — including Telegram webhook HMAC validation and OIDC cron verification. Injecting session-cookie logic there would either break those paths or require duplicating their detection logic inside the middleware. The correct pattern is a per-route `Depends()`:

```python
# interfaces/hub_api.py
from fastapi import APIRouter, Depends, Request, HTTPException, Response
import os, hashlib, hmac, time, json

router = APIRouter()

_SESSIONS: dict[str, dict] = {}   # in-process; acceptable for single user


async def require_hub_session(request: Request) -> str:
    """Validate session cookie. Returns Amit's email on success; raises 401 on failure."""
    token = request.cookies.get("hub_session", "")
    session = _SESSIONS.get(token)
    if not session or session.get("expires_at", 0) < time.time():
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session["email"]

@router.get("/auth/me")
async def auth_me(user: str = Depends(require_hub_session)):
    return {"email": user}

@router.post("/chat")
async def hub_chat(request: Request, user: str = Depends(require_hub_session)):
    ...
```

Existing routes in `web_server.py` — `/telegram-webhook`, `/internal/process-update`, all `/cron/*`, all `/trigger/*` — are completely unaffected because they do not use `Depends(require_hub_session)`.

### Google Sign-In flow

```
GET /api/auth/google
    → redirect to Google OAuth2 authorize URL
    → (user approves in browser)
GET /api/auth/callback?code=...&state=...
    → exchange code for ID token
    → verify email == os.environ["AMIT_EMAIL"]
    → generate session token (secrets.token_hex(32))
    → store {email, expires_at} in _SESSIONS dict
    → set "hub_session" cookie (HttpOnly, Secure, SameSite=Lax)
    → redirect to "/"
```

`google-auth` and `google-auth-oauthlib` are already in the dependency graph (used by `core/auth_google.py` and `mcp_tools/` tools). No new packages required for the OAuth2 exchange.

The allowlist check (`email == os.environ["AMIT_EMAIL"]`) is a single string comparison — single-user system, no ACL store needed.

---

## Integration Point 2: Hub Chat Through Cloud Tasks (Shared Conversation)

### Why a new Cloud Tasks path (not reusing `/internal/process-update`)

`/internal/process-update` calls `Update.de_json(data=request_json, bot=_application.bot)` — it expects Telegram wire-format JSON. The bot object is required for some nested `Update` objects' helper methods. Injecting a hub message as a fake Telegram `Update` is brittle and leaks the Telegram abstraction into the hub. The correct design is a parallel but structurally identical Cloud Tasks path.

### `enqueue_hub_message()` in `core/task_dispatch.py`

```python
def enqueue_hub_message(payload: dict) -> bool:
    """Enqueue one hub chat message for full-CPU processing.

    payload shape:
        {"text": str, "user_id": int, "source": "hub", "request_id": str}
    request_id is an ISO timestamp the client sent; the poll endpoint uses it
    as a cursor to find the reply.

    Returns True on success, False on any failure (never raises).
    Falls back to direct in-process handling is NOT provided — the hub API
    handler returns 202 immediately and the client polls; there is no
    Starlette BackgroundTask fallback here because the hub does not have the
    Telegram instant-ACK requirement.
    """
    queue = os.getenv("CLOUD_TASKS_QUEUE", "")
    if not queue:
        return False
    # ... identical Cloud Tasks construction to enqueue_update() ...
    # url: f"{base_url}/internal/process-hub-message"
```

This reuses the same queue (`CLOUD_TASKS_QUEUE`), the same OIDC service account, and the same `_DISPATCH_DEADLINE_SECONDS` as the Telegram path. No new infrastructure.

### `/internal/process-hub-message` endpoint in `web_server.py`

```python
@app.post("/internal/process-hub-message")
async def internal_process_hub_message(request: Request) -> JSONResponse:
    """Cloud Tasks target: process one hub chat message with full CPU.

    Verified via the same _verify_cron_request() as /internal/process-update.
    Payload: {"text": str, "user_id": int, "source": "hub", "request_id": str}
    """
    await _verify_cron_request(request)
    if _router is None:
        raise HTTPException(status_code=500, detail={"error": "Not initialised"})
    payload = await request.json()
    await _router.handle_hub_message(payload)
    return JSONResponse(content={"ok": True})
```

`_verify_cron_request` already validates the OIDC bearer token from `CLOUD_SCHEDULER_SA_EMAIL`. Cloud Tasks uses that same service account. No new auth logic needed.

### `handle_hub_message()` on `MessageRouter` in `interfaces/_router.py`

```python
async def handle_hub_message(self, payload: dict) -> None:
    """Process a hub chat message: inject into conversation, then run agent turn."""
    user_id = payload["user_id"]
    text = payload["text"]
    # 1. Append user message into shared conversation (same store Telegram uses)
    self._conversation_store.append(user_id, "user", text, source="hub")
    # 2. Run the brain — same orchestrator, same smart loop
    reply = await self._orchestrator.handle_message(user_id, text)
    # 3. Append assistant reply
    self._conversation_store.append(user_id, "assistant", reply, source="hub")
    # Note: no Telegram send here. Delivery is via polling or Web Push.
```

### Channel tagging in `FirestoreConversationStore`

The existing message schema is `{"role": "user"|"assistant", "content": str}`. Adding an optional `source` field (`"telegram"` | `"hub"` | `"cron"`) enables the polling endpoint to return hub-visible messages and suppresses cron injections from appearing in the chat UI.

Change in `_txn_append` signature:

```python
def _txn_append(
    transaction, doc_ref, role: str, content: str,
    max_messages: int, timeout_hours: int,
    source: str | None = None,     # new, optional
) -> None:
    ...
    messages.append({"role": role, "content": content, **({"source": source} if source else {})})
```

All existing callers pass no `source` — the kwarg defaults to `None` and the field is absent from the stored dict (backward compatible). The hub path passes `source="hub"`. Cron injections via `scheduled_message.send_and_inject` pass `source="cron"`.

### Polling endpoint

```python
@router.get("/messages/since")
async def messages_since(
    after: str,   # ISO timestamp — last seen message time
    user: str = Depends(require_hub_session),
):
    """Return assistant messages newer than `after`. Used for chat polling."""
    messages = conversation_store.get(AMIT_USER_ID)
    # Filter: role == "assistant", source != "cron", timestamp > after
    # Timestamp approximation: conversation doc updated_at is doc-level only;
    # use message list position relative to a known-sent request_id as the
    # cursor if per-message timestamps are not added. Simplest v1: return all
    # assistant messages in the last 20 entries of the conversation.
    ...
```

The simplest viable v1 cursor: the client tracks the index of the last message it displayed; the poll endpoint returns `messages[last_index:]`. This avoids per-message timestamps in Firestore (a schema change with transaction implications). SSE is a clean fast-follow that makes this endpoint obsolete.

---

## Integration Point 3: `send_and_inject` Hub Push + Telegram Mirror (D-10 Gating Preserved)

### D-10 invariant

`OutreachLogStore.append` is called by the autonomous tick **only after** `send_and_inject` returns without raising. This invariant is documented in `CLAUDE.md` and enforced by the call sites in `core/autonomous.py`. The signature change must not alter the success/failure semantics that D-10 callers depend on.

### Modified signature

```python
# core/scheduled_message.py
async def send_and_inject(
    bot: Bot,
    text: str,
    *,
    inject_into_conversation: bool = False,
    reply_markup=None,                    # existing — unchanged
    hub_push: bool = True,               # new: attempt Web Push delivery
    telegram_mirror: bool = True,        # new: env-overridable for hybrid transition
) -> "telegram.Message | None":
    """
    Delivery behavior:
      1. If telegram_mirror=True (default): bot.send_message() as before.
         If this raises, the exception propagates to the caller — D-10 gating
         is preserved: OutreachLogStore.append is never called on a failed send.
      2. If hub_push=True: _send_hub_push(text) — best-effort, NEVER raises,
         NEVER affects the return value. Web Push failure is swallowed + logged
         at WARNING. A stale push subscription must not prevent a Telegram
         outreach from being logged.
      3. inject_into_conversation: same as before.

    telegram_mirror is read from env at call time:
      actual_mirror = telegram_mirror and (
          os.getenv("TELEGRAM_MIRROR", "true").lower() == "true"
      )
    When TELEGRAM_MIRROR=false is deployed, the function skips Telegram send
    and returns None. Callers that use the returned telegram.Message only for
    reply-to detection (training_checkin.py) must guard for None.
    """
```

The `TELEGRAM_MIRROR` env var (default `"true"`) is the Telegram retirement switch. It can be flipped without a redeploy via Cloud Run environment variable update. Until it is flipped, every proactive message goes to both Telegram and Web Push with no behavior change for existing callers.

### `_send_hub_push()` helper

```python
# core/scheduled_message.py
async def _send_hub_push(text: str) -> None:
    """Send Web Push to all registered VAPID subscriptions. Best-effort — never raises."""
    try:
        from memory.firestore_db import PushSubscriptionStore
        from pywebpush import webpush, WebPushException
        store = PushSubscriptionStore(
            project_id=os.environ["GCP_PROJECT_ID"],
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
        subs = store.list_all()
        vapid_private = os.environ.get("VAPID_PRIVATE_KEY", "")
        vapid_claims = {"sub": f"mailto:{os.environ.get('AMIT_EMAIL', '')}"}
        for sub in subs:
            try:
                webpush(
                    subscription_info=sub,
                    data=text,
                    vapid_private_key=vapid_private,
                    vapid_claims=vapid_claims,
                )
            except WebPushException as e:
                if e.response and e.response.status_code == 410:
                    # Subscription expired — remove it
                    store.delete(sub.get("endpoint", ""))
                else:
                    logger.warning("Web Push failed for one subscription: %s", e)
    except Exception:
        logger.warning("_send_hub_push failed entirely", exc_info=True)
```

---

## Integration Point 4: New Firestore Stores in `firestore_db.py`

All three new stores follow the established discipline exactly:
- Constructor: `(project_id: str, database: str = "(default)")` calling `_make_firestore_client()`
- Reads: never raise, return `[]` / `None` / `{}` on any error
- Writes: re-raise after `logger.error(...)` so API handlers can return 500
- Timestamps: `updated_at: firestore.SERVER_TIMESTAMP` on every write; `created_at` as static ISO string
- JSON safety: `_jsonsafe_doc()` applied to all reads before returning

### TaskStore

```
Collection: tasks
Document ID: uuid4 hex

Fields:
  id:           str    — doc id (also stored in payload for query)
  title:        str    — required
  notes:        str    — optional
  due:          str    — YYYY-MM-DD or None
  priority:     int    — 0=none 1=low 2=medium 3=high
  list:         str    — "Inbox" | "Work" | "Personal" | custom
  recurrence:   str    — "daily" | "weekly" | "monthly" | None
  completed_at: str    — ISO datetime or None
  status:       str    — "pending" | "completed" | "cancelled"
  created_at:   str    — ISO UTC datetime (static — NOT SERVER_TIMESTAMP)
  updated_at:   SERVER_TIMESTAMP
```

Methods:
- `create(payload: dict) -> dict` — generates uuid4, writes, returns `{"id": id}`; re-raises
- `get(task_id: str) -> dict | None` — never raises
- `list_pending() -> list[dict]` — `status == "pending"`, newest-first; never raises
- `list_due_today(date_str: str) -> list[dict]` — `status == "pending"` AND `due <= date_str`; never raises (requires composite index on `status` + `due`)
- `list_by_list(list_name: str) -> list[dict]` — filtered by list; never raises
- `update(task_id: str, patch: dict) -> None` — merge patch + `updated_at`; re-raises
- `complete(task_id: str) -> None` — sets `status="completed"`, `completed_at=now_iso`; re-raises
- `delete(task_id: str) -> None` — hard delete (TickTick allows hard deletes); re-raises

### HabitStore

```
Collection: habits
Document ID: uuid4 hex

Definition doc fields:
  id:             str    — doc id
  name:           str    — habit/supplement name
  type:           str    — "habit" | "supplement"
  dose:           str    — optional, e.g. "5g creatine" — Klaus reads this field
  schedule_days:  list   — ["mon","tue","wed","thu","fri","sat","sun"] subset
  slot:           str    — "morning" | "afternoon" | "evening" | "anytime"
  active:         bool
  created_at:     str    — static ISO UTC
  updated_at:     SERVER_TIMESTAMP

Sub-collection: habits/{habit_id}/completions/{YYYY-MM-DD}
  date:           str    — YYYY-MM-DD
  completed:      bool
  completed_at:   str    — ISO datetime or None
  note:           str    — optional
  updated_at:     SERVER_TIMESTAMP
```

Methods:
- `create(payload: dict) -> dict` — re-raises
- `get(habit_id: str) -> dict | None` — never raises
- `list_active() -> list[dict]` — all `active=True` habits; never raises
- `get_today_state(date_str: str) -> list[dict]` — all active habits with their completion doc for `date_str` merged in; used by `_gather_habits_state()` and `GET /api/today`; never raises
- `log_completion(habit_id: str, date_str: str, completed: bool, note: str) -> None` — writes to sub-collection; re-raises
- `list_completions(habit_id: str, days: int) -> list[dict]` — last N days of completions; never raises
- `compute_streak(completions: list[dict]) -> int` — pure function, no Firestore I/O

`get_today_state` is the core read path. Implementation:

```python
def get_today_state(self, date_str: str) -> list[dict]:
    """Return active habits with today's completion status merged in. Never raises."""
    try:
        habits = self.list_active()
        result = []
        for h in habits:
            comp_snap = (
                self._col.document(h["id"])
                .collection("completions")
                .document(date_str)
                .get()
            )
            comp = _jsonsafe_doc(comp_snap.to_dict() or {}) if comp_snap.exists else {}
            result.append({**h, "today": comp})
        return result
    except Exception:
        logger.warning("HabitStore.get_today_state(%r) failed", date_str, exc_info=True)
        return []
```

### PushSubscriptionStore

```
Collection: push_subscriptions
Document ID: SHA-256 hex of endpoint URL (stable, collision-resistant, avoids URL chars in doc IDs)

Fields:
  endpoint:     str    — Web Push subscription endpoint URL
  p256dh:       str    — ECDH public key (base64url)
  auth:         str    — auth secret (base64url)
  created_at:   str    — static ISO UTC
  updated_at:   SERVER_TIMESTAMP
```

Methods:
- `upsert(subscription: dict) -> None` — called on every `pushManager.subscribe`; idempotent; re-raises
- `list_all() -> list[dict]` — returns all subscriptions for push fan-out; never raises
- `delete(endpoint: str) -> None` — called on HTTP 410 Gone from push service; re-raises

---

## Integration Point 5: Native Task Tools in `core/tools.py`

### Why brain-direct (not worker-delegated)

Task management is identity-critical — it is the hub's core replacement for TickTick. Worker tools are for structured data execution (JSON parsing, API calls). Task create/complete/update require judgment (which list? what priority? does this conflict with calendar?). Brain-direct tools are the correct pattern for tools requiring orchestration reasoning, matching the existing convention for `get_plan`, `log_benchmark`, `update_plan`.

### New entries in `SMART_AGENT_DIRECT_TOOLS`

```python
# core/tools.py — added to SMART_AGENT_DIRECT_TOOLS frozenset
"create_task",
"get_tasks",
"complete_task",
"update_task",
"delete_task",
"get_habits",
"log_habit_completion",
"create_habit",
"update_habit",
```

Each gets a schema in `TOOL_SCHEMAS` and a handler in `_HANDLERS` dispatching to `TaskStore` / `HabitStore` via the same lazy-singleton pattern used by every other store-backed tool.

### TickTick retirement sequence

1. Run `scripts/import_ticktick.py` → verify all tasks are in `TaskStore`
2. Remove `ticktick_tool` schema entries from `TOOL_SCHEMAS`
3. Remove `ticktick_tool` handlers from `_HANDLERS`
4. Remove `_gather_ticktick_overdue()` from `core/autonomous.py`, add `_gather_tasks_overdue()`
5. Update `prompts/autonomous_triage.md`: rename `ticktick_overdue` key to `tasks_overdue` in the triage prompt context block
6. `mcp_tools/ticktick_tool.py` and `mcp_tools/ticktick_auth.py` can be removed (or archived) after confirming no other imports

---

## Integration Point 6: Layer-0 Gather Extension in `core/autonomous.py`

### Adding `_gather_habits_state()`

The autonomous tick should be aware of today's supplement adherence so tick-brain can judge a nudge. This is a new source `(l)` alongside the existing 11 sources.

```python
def _gather_habits_state(now: datetime, project_id: str, database: str) -> list:
    """(l) Today's habit/supplement completion state for autonomous tick awareness."""
    try:
        from memory.firestore_db import HabitStore
        hs = HabitStore(project_id=project_id, database=database)
        today_iso = now.astimezone(_TZ).date().isoformat()
        return hs.get_today_state(today_iso) or []
    except Exception:
        logger.warning("autonomous: habits gather failed", exc_info=True)
        return []
```

In `gather_situation()`, add to the `jobs` dict:

```python
"habits_state": lambda: _gather_habits_state(now, project_id, database),
```

And add to `_is_empty_signals()`: incomplete supplements at a scheduled slot can act as a proactive trigger (same pattern as `meals_since_last_tick`). This is a Phase 3 addition — implement when HabitStore exists.

### Replacing `_gather_ticktick_overdue()` with `_gather_tasks_overdue()`

```python
def _gather_tasks_overdue(now: datetime, project_id: str, database: str) -> list:
    """(b) Tasks overdue as of today — reads native TaskStore (Phase 2 replacement for TickTick)."""
    try:
        from memory.firestore_db import TaskStore
        ts = TaskStore(project_id=project_id, database=database)
        today_iso = now.astimezone(_TZ).date().isoformat()
        return ts.list_due_today(today_iso) or []
    except Exception:
        logger.warning("autonomous: tasks gather failed", exc_info=True)
        return []
```

The `jobs` dict key changes from `"ticktick_overdue"` to `"tasks_overdue"`. The triage prompt template must be updated in sync — the key name appears in `prompts/autonomous_triage.md`.

---

## Integration Point 7: `/api/today` Composition Endpoint

Mirrors the `gather_situation()` fan-out pattern: each data source has its own `try/except`, failures produce `null` sections in the response rather than a 500.

```python
@router.get("/today")
async def get_today(
    date: str | None = None,
    user: str = Depends(require_hub_session),
):
    """Compose Today timeline server-side from all sources concurrently.

    Sources (fanned out in thread pool, mirrors autonomous.gather_situation):
      - Calendar events (GoogleCalendarManager.list_events)
      - Meals (MealStore.get_day_aggregate) — display-only, slot-time caveat applies
      - Habits due today (HabitStore.get_today_state)
      - Tasks due today (TaskStore.list_due_today)
      - Garmin morning stats (GarminTool — sleep, HRV, body battery)
      - Weather (WeatherTool.get_weather)
      - Leave-by times for calendar events with location (RoutesTool — best-effort)

    Returns structured JSON. Missing sources produce null sections.
    """
    from concurrent.futures import ThreadPoolExecutor
    today_iso = date or datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            "calendar": pool.submit(_fetch_today_calendar, today_iso),
            "meals": pool.submit(_fetch_today_meals, today_iso),
            "habits": pool.submit(_fetch_today_habits, today_iso),
            "tasks": pool.submit(_fetch_today_tasks, today_iso),
            "garmin": pool.submit(_fetch_garmin_morning),
            "weather": pool.submit(_fetch_weather),
        }
        result = {k: _safe_result(f) for k, f in futures.items()}

    return JSONResponse(content={"date": today_iso, **result})
```

Meal timestamp caveat (from `CLAUDE.md`): `MealStore` timestamps are canonical slot times (08:00/12:00/20:00), NOT actual eating times. The Today endpoint must not infer eating time from them or display them as "eaten at 08:00". Display label: "Breakfast" not "Eaten at 08:00".

---

## Data Flow

### Hub Chat Flow (Phase 1)

```
User types in hub chat → POST /api/chat {text, request_id}  (session cookie auth)
    ↓
hub_api.py: store request_id + enqueue_hub_message({text, user_id, source:"hub", request_id})
    ↓  (returns HTTP 202 immediately)
Cloud Tasks: POST /internal/process-hub-message  (OIDC auth, full CPU)
    ↓
_router.handle_hub_message(payload)
    ↓
FirestoreConversationStore.append(user_id, "user", text, source="hub")
    ↓
AgentOrchestrator.handle_message(user_id, text)  — same brain, same tool loop
    ↓
reply text produced
    ↓
FirestoreConversationStore.append(user_id, "assistant", reply, source="hub")

Meanwhile, client polls every 2s:
GET /api/messages/since?after=<cursor>
    → FirestoreConversationStore.get(user_id)
    → return messages[cursor:] where role=="assistant" and source!="cron"
```

### Proactive Message Flow with Web Push (Phase 4)

```
autonomous tick / morning briefing / nightly review
    ↓
send_and_inject(bot, text, hub_push=True, telegram_mirror=<TELEGRAM_MIRROR env>)
    ↓
if telegram_mirror:
    bot.send_message(telegram_user_id, text)  ← existing path
    (if this raises, exception propagates — D-10 gating preserved)
if hub_push:
    _send_hub_push(text)  ← best-effort, never raises
        → PushSubscriptionStore.list_all()
        → for each sub: webpush(sub, text, vapid_claims)
        → on HTTP 410: PushSubscriptionStore.delete(endpoint)
inject into FirestoreConversationStore (source="cron")
    ↓
caller: OutreachLogStore.append(...)  ← D-10: called only after return, unchanged
```

### TickTick → TaskStore Migration (Phase 2, one-time)

```
scripts/import_ticktick.py (manual operator run)
    ↓
ticktick_tool.get_all_tasks()  (all lists + completed)
    ↓
for each task: TaskStore.create(normalize_ticktick(task))
    ↓
print summary {total, imported, errors}
    ↓  [Amit verifies in hub UI]
Operator: cancel TickTick subscription
Operator: remove ticktick schemas from tools.py + autonomous.py
```

---

## New `/api/*` Endpoints

| Endpoint | Auth | Purpose | Phase |
|----------|------|---------|-------|
| `GET /api/auth/google` | None | Initiate Google OAuth2 | 1 |
| `GET /api/auth/callback` | None | OAuth2 callback, set session cookie | 1 |
| `GET /api/auth/me` | Session | Return authenticated email | 1 |
| `POST /api/auth/logout` | Session | Clear session cookie | 1 |
| `GET /api/today` | Session | Compose Today timeline | 1 |
| `POST /api/chat` | Session | Enqueue hub chat → Cloud Tasks | 1 |
| `GET /api/messages/since` | Session | Poll for new assistant messages | 1 |
| `GET /api/vapid-public-key` | None | Serve VAPID public key for service worker | 1 |
| `GET /api/tasks` | Session | List tasks (filtered) | 2 |
| `POST /api/tasks` | Session | Create task | 2 |
| `PATCH /api/tasks/{id}` | Session | Update task | 2 |
| `POST /api/tasks/{id}/complete` | Session | Complete task | 2 |
| `DELETE /api/tasks/{id}` | Session | Delete task | 2 |
| `GET /api/habits` | Session | List habits with today's completion state | 3 |
| `POST /api/habits/{id}/complete` | Session | Log habit/supplement completion | 3 |
| `POST /api/push/subscribe` | Session | Register Web Push subscription | 4 |
| `DELETE /api/push/subscribe` | Session | Remove push subscription | 4 |
| `GET /api/health/training` | Session | Training history (Hevy + Garmin) | 5 |
| `GET /api/health/nutrition` | Session | Nutrition detail (MealStore range) | 5 |
| `GET /api/health/sleep` | Session | Sleep trends (Garmin) | 5 |

---

## Dockerfile Change (Multi-Stage Build)

```dockerfile
# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime (existing, extended)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Copy built frontend assets from stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist
CMD ["uvicorn", "interfaces.web_server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

The Python runtime image contains only compiled static files — no Node.js, no `node_modules`. Cold start is not materially affected.

---

## Anti-Patterns

### Anti-Pattern 1: Global Auth Middleware for Hub Routes

**What people do:** Add `@app.middleware("http")` that validates a session cookie for all requests.

**Why it's wrong:** `web_server.py` has four distinct auth surfaces (Telegram HMAC, OIDC, iOS shared-secret ×2). A global middleware fires before all of them. The OIDC `_verify_cron_request` and the `hmac.compare_digest` webhook check run inside their route handlers — global middleware would need to detect which auth pattern applies per-path, duplicating routing logic and creating a maintenance hazard.

**Do this instead:** Per-route `Depends(require_hub_session)` in `hub_api.py`. The hub routes are fully isolated from the existing auth surfaces.

### Anti-Pattern 2: Reusing `/internal/process-update` for Hub Messages

**What people do:** Serialize the hub chat message as a fake Telegram `Update` JSON and POST it to the existing endpoint.

**Why it's wrong:** The endpoint calls `Update.de_json(data=request_json, bot=_application.bot)`, which deserializes into python-telegram-bot's typed `Update` object. Hub messages are not Telegram updates and should not pretend to be. A fake `Update` breaks type safety, makes debugging harder, and ties hub chat to Telegram's wire format forever.

**Do this instead:** `enqueue_hub_message()` + `/internal/process-hub-message` — a parallel path with ~50 lines of code sharing the same auth, queue, and full-CPU invariant.

### Anti-Pattern 3: Calling `OutreachLogStore.append` Before Both Deliveries Succeed

**What people do:** Log the outreach after both Telegram send and Web Push succeed, making the log conditional on two network calls.

**Why it's wrong:** Web Push is inherently unreliable (subscriptions expire, devices go offline). Making D-10 gating conditional on push delivery means a sleeping phone can prevent the outreach log from being written, allowing the autonomous tick to re-send the same message repeatedly.

**Do this instead:** Web Push is best-effort — the `_send_hub_push()` helper never raises, and the outreach log is written after Telegram send succeeds (or after any send path succeeds when TELEGRAM_MIRROR=false). Web Push failure is logged but has no effect on D-10 gating.

### Anti-Pattern 4: Inserting `firestore.SERVER_TIMESTAMP` Inside Outreach Log Entries

**What people do:** Add a `"push_sent_at": firestore.SERVER_TIMESTAMP` field to the entry dict passed to `OutreachLogStore.append`.

**Why it's wrong:** `OutreachLogStore.append` uses `firestore.ArrayUnion([entry])` for atomic duplicate-free appends. `ArrayUnion` uses deep equality comparison; each `SERVER_TIMESTAMP` sentinel is a freshly allocated object, so two identical entries with sentinel timestamps would not de-duplicate. The existing `OutreachLogStore` docstring (NOTE 2) explicitly warns against this.

**Do this instead:** `"push_sent_at": datetime.now(timezone.utc).isoformat()` — a static ISO string that round-trips through deep equality correctly.

### Anti-Pattern 5: Computing Habit Streaks in Firestore

**What people do:** Use Firestore `count()` aggregations on the completions sub-collection to compute streaks.

**Why it's wrong:** Firestore has no server-side window functions. `count()` returns the total number of completions, not the current unbroken streak. Streak computation requires knowing which consecutive days have completions — this is sequential logic that must run in Python.

**Do this instead:** `list_completions(habit_id, days=30)` returns raw documents; `compute_streak(completions)` is a pure Python function. Thirty days is sufficient for any meaningful streak display.

### Anti-Pattern 6: Building the Frontend at Container Runtime

**What people do:** Include `node` in the Python image and run `npm run build` during container startup.

**Why it's wrong:** Adds Node.js and hundreds of MB of `node_modules` to the runtime image. Increases cold start time. Makes npm vulnerabilities a runtime security surface.

**Do this instead:** Multi-stage Dockerfile (documented above). The final image contains only static files.

---

## Scaling Considerations

This is a single-user system. Scaling is not a concern. The `--workers 1` uvicorn constraint (required by `AgentOrchestrator` singleton and `ConversationManager`) already handles all traffic on a single instance. Cloud Run scales instances horizontally when the single worker is busy, but one user generates insufficient load for that to matter.

The in-process TTL read cache for `self_state` and `journal` (10-minute TTL, existing) extends naturally to `TaskStore` and `HabitStore` reads in the Today endpoint — tasks and habits change slowly during the day. A 30-60 second in-process cache for `get_today_state()` reduces Firestore read costs during rapid client polling without meaningful staleness risk.

---

## Sources

- Direct code reading (verified line numbers):
  - `interfaces/web_server.py` — route registration order, auth surfaces, lifespan, singleton guards
  - `core/task_dispatch.py` — `enqueue_update()` implementation, Cloud Tasks payload shape
  - `core/scheduled_message.py` — `send_and_inject()` signature, D-10 gating relationship
  - `core/autonomous.py` — `gather_situation()` fan-out, `_gather_*()` function patterns, `_is_empty_signals()` gate
  - `core/tools.py` — `SMART_AGENT_DIRECT_TOOLS`, `TOOL_SCHEMAS`, `_HANDLERS` dispatch pattern
  - `memory/firestore_db.py` — `OutreachLogStore` (D-10, NOTE 2 invariant), `TrainingLogStore` (store discipline pattern), `FollowupStore` (sub-collection-free alternative pattern)
  - `memory/firestore_conversation.py` — `_txn_append`, message schema, `get_last_user_timestamp`
- Design spec: `docs/superpowers/specs/2026-06-13-klaus-hub-design.md`
- Project context: `.planning/PROJECT.md`
- CLAUDE.md invariants verified: Cloud Tasks full-CPU turns, OutreachLog D-10 gating, lowercase GCP resource names, `load_dotenv(override=True)`, single-worker constraint

---
*Architecture research for: Klaus Hub v5.0 — Web PWA integration with existing Klaus Cloud Run service*
*Researched: 2026-06-13*
