# Phase 26: Hub Shell - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 27 (7 backend new/modified + 20 frontend greenfield)
**Analogs found:** 7 / 7 backend files have strong in-repo analogs; 20 frontend files are greenfield (no in-repo analog)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `interfaces/hub_auth.py` | middleware/auth | request-response | `interfaces/web_server.py` (`_verify_cron_request`, `_verify_healthkit_request`) | role-match (auth verify pattern exact; different credential type) |
| `interfaces/web_server.py` (modified) | controller | request-response | self (existing routes — `/cron/*`, `/internal/process-update`) | exact (new routes follow same pattern) |
| `core/task_dispatch.py` (modified) | service | request-response | self (`enqueue_update`) | exact (new function mirrors existing) |
| `memory/firestore_db.py` (modified) | model/store | CRUD | self (`SelfStateStore.set`, `UserProfileStore.update`) | exact (field additions to existing stores) |
| `core/morning_briefing.py` (modified) | service | event-driven | `core/reflection.py`, `core/autonomous.py` | role-match (writes to SelfStateStore after compose) |
| `Dockerfile` (modified) | config | batch/build | self (existing single-stage Dockerfile) | exact (gains Node build stage prepended) |
| `tests/test_hub_auth.py` | test | request-response | `tests/test_task_dispatch.py`, `tests/test_web_server.py` | exact |
| `tests/test_api_today.py` | test | request-response | `tests/test_web_server.py` | exact |
| `tests/test_hub_chat.py` | test | CRUD | `tests/test_task_dispatch.py` | role-match |
| `frontend/vite.config.ts` | config | — | **GREENFIELD** — RESEARCH.md Pattern 4 | no analog |
| `frontend/tailwind.config.ts` | config | — | **GREENFIELD** — RESEARCH.md Standard Stack | no analog |
| `frontend/src/main.tsx` | config/bootstrap | — | **GREENFIELD** — RESEARCH.md Pattern 5 | no analog |
| `frontend/src/App.tsx` | component | request-response | **GREENFIELD** — RESEARCH.md + UI-SPEC.md AppShell | no analog |
| `frontend/src/api/client.ts` | utility | request-response | **GREENFIELD** — RESEARCH.md Code Examples | no analog |
| `frontend/src/api/auth.ts` | utility | request-response | **GREENFIELD** — RESEARCH.md Pattern 2 | no analog |
| `frontend/src/api/today.ts` | utility | request-response | **GREENFIELD** — RESEARCH.md Pattern 3 | no analog |
| `frontend/src/api/chat.ts` | utility | request-response | **GREENFIELD** — RESEARCH.md Pattern 5 | no analog |
| `frontend/src/store/auth.ts` | store | event-driven | **GREENFIELD** — RESEARCH.md Standard Stack (zustand) | no analog |
| `frontend/src/hooks/useToday.ts` | hook | request-response | **GREENFIELD** — RESEARCH.md Pattern 3 | no analog |
| `frontend/src/hooks/useChat.ts` | hook | request-response | **GREENFIELD** — RESEARCH.md Pattern 5 | no analog |
| `frontend/src/hooks/useUnread.ts` | hook | event-driven | **GREENFIELD** — RESEARCH.md Pattern 7 | no analog |
| `frontend/src/components/layout/AppShell.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Layout Components | no analog |
| `frontend/src/components/layout/Sidebar.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Layout Components | no analog |
| `frontend/src/components/layout/BottomTabs.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Layout Components | no analog |
| `frontend/src/components/layout/GlanceRail.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Layout Components | no analog |
| `frontend/src/components/layout/DockChat.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Layout Components | no analog |
| `frontend/src/components/timeline/TimelineDay.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Timeline Components | no analog |
| `frontend/src/components/timeline/TimelineItem.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Timeline Components | no analog |
| `frontend/src/components/timeline/NowLine.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Timeline Components | no analog |
| `frontend/src/components/timeline/TimelineHeader.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Timeline Components | no analog |
| `frontend/src/components/timeline/PlaceholderCard.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Timeline Components | no analog |
| `frontend/src/components/chat/ChatWindow.tsx` | component | request-response | **GREENFIELD** — UI-SPEC.md Chat Components | no analog |
| `frontend/src/components/chat/MessageBubble.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Chat Components | no analog |
| `frontend/src/components/chat/TypingIndicator.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Chat Components | no analog |
| `frontend/src/components/chat/ChatInput.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Chat Components | no analog |
| `frontend/src/components/shared/Skeleton.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Shared Components | no analog |
| `frontend/src/components/shared/OfflineIndicator.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Shared Components | no analog |
| `frontend/src/components/shared/InstallBanner.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Shared Components + RESEARCH.md Pattern 4 | no analog |
| `frontend/src/components/shared/UnreadBadge.tsx` | component | — | **GREENFIELD** — UI-SPEC.md Shared Components | no analog |
| `frontend/src/components/auth/SignInPage.tsx` | component | request-response | **GREENFIELD** — RESEARCH.md Pattern 2 (GIS button) | no analog |

---

## Pattern Assignments — Backend (Concrete Excerpts)

### `interfaces/hub_auth.py` (new file — middleware/auth, request-response)

**Analog:** `interfaces/web_server.py` — `_verify_healthkit_request` (lines 371–428) and `_verify_cron_request` (lines 325–368)

**Imports pattern** (from `interfaces/web_server.py` lines 20–36):
```python
import hmac
import os

from fastapi import HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
```

**Auth verify pattern — constant-time compare + redacted logging** (from `interfaces/web_server.py` lines 416–428):
```python
# From _verify_healthkit_request — MANDATORY: use hmac.compare_digest, never ==
# Never log the full secret value — redact to prefix only
if not hmac.compare_digest(received.encode(), expected.encode()):
    client = request.client.host if request.client else "?"
    redacted = (
        received[:4] + "..." + received[-4:] if len(received) >= 8 else "***"
    )
    logger.warning(
        "healthkit auth failed from %s (token_prefix=%s)", client, redacted,
    )
    raise HTTPException(
        status_code=403,
        detail={"error": "Invalid token"},
    )
```

**CRON_DEV_BYPASS bypass pattern** (from `interfaces/web_server.py` lines 337–339):
```python
if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
    logger.info("CRON_DEV_BYPASS=true — skipping OIDC verification")
    return
```

**GIS ID token verify pattern** (from `interfaces/web_server.py` lines 351–368, also referenced in RESEARCH.md Pattern 2):
```python
# Same verify_oauth2_token used in _verify_cron_request — already in google-auth
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.id_token import verify_oauth2_token

payload = verify_oauth2_token(token, GoogleRequest(), audience=cloud_run_url)
```

**Refuse-all on unset env** (from `interfaces/web_server.py` lines 401–412):
```python
expected = os.environ.get("HEALTHKIT_WEBHOOK_TOKEN", "")
if not expected:
    # WHY: refuse-all on unset env var prevents a fail-open when the
    # Secret Manager mount silently fails.
    logger.error(
        "HEALTHKIT_WEBHOOK_TOKEN env unset — refusing all HealthKit auth"
    )
    raise HTTPException(
        status_code=500,
        detail={"error": "Server misconfigured"},
    )
```

**Key difference from analogs:** `hub_auth.py` issues and verifies a signed `itsdangerous.TimestampSigner` cookie rather than checking a bearer token. The GIS verify is a one-time call at sign-in; subsequent requests use `require_hub_session` as a FastAPI `Depends` that reads `request.cookies.get("hub_session")`. The full `hub_auth.py` skeleton is in RESEARCH.md Pattern 2 (lines 306–367 of RESEARCH.md).

---

### `interfaces/web_server.py` — new routes (modified file, controller, request-response)

**Analog:** existing routes in `interfaces/web_server.py` — especially `/internal/process-update` (lines 285–318) and `/cron/strength-sync` (lines 807–833)

**New route registration pattern** — OIDC-gated `/internal/*` route (lines 285–318):
```python
@app.post("/internal/process-update")
async def internal_process_update(request: Request) -> JSONResponse:
    await _verify_cron_request(request)

    if _application is None or _router is None:
        logger.error("/internal/process-update before singletons initialised")
        raise HTTPException(
            status_code=500,
            detail={"error": "Server is still initialising; please retry."},
        )

    request_json: dict = await request.json()
    update = Update.de_json(data=request_json, bot=_application.bot)
    await _router.handle_update(update)
    return JSONResponse(content={"ok": True})
```

**Sync-in-async pattern with run_in_executor** (from `/cron/strength-sync` lines 807–833):
```python
@app.post("/cron/strength-sync")
async def cron_strength_sync(request: Request) -> JSONResponse:
    await _verify_cron_request(request)
    import asyncio as _asyncio
    import core.strength_ingest as _strength
    try:
        loop = _asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _strength.run_one_batch)
        _log_cron_run("strength-sync", ok=bool(result.get("ok")), backlog_done=result.get("done"))
        return JSONResponse(content=result)
    except Exception:
        _log_cron_run("strength-sync", ok=False)
        raise
```

**Mount ordering CRITICAL** — from RESEARCH.md Pattern 1. The `SPAStaticFiles` mount MUST be the very last statement in the file. The existing pattern of all routes being registered before `yield` in `lifespan` or before the bottom of the file shows the ordering discipline:
```python
# MUST be absolutely last in web_server.py — any route after this is unreachable
_DIST_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_DIST_PATH):
    app.mount("/", SPAStaticFiles(directory=_DIST_PATH, html=True), name="spa")
else:
    logger.warning("Frontend dist/ not found — SPA will not be served (dev mode?)")
```

**`_jsonsafe_doc` in every `/api/*` JSON response** — mandatory because `MealStore.get_day()`, `SelfStateStore.get()`, and `UserProfileStore.load()` all have `SERVER_TIMESTAMP` fields (see RESEARCH.md Pitfall 4, CONTEXT.md line 109):
```python
# From RESEARCH.md Code Examples — the /api/today handler pattern
from memory.firestore_db import _jsonsafe_doc  # existing helper at line 882

return JSONResponse(content=_jsonsafe_doc({
    "today": today_iso,
    "calendar": calendar_with_leave_by,
    # ... all Firestore-derived data wrapped here
}))
```

---

### `core/task_dispatch.py` — `enqueue_hub_message` (modified file, service, request-response)

**Analog:** `enqueue_update` in `core/task_dispatch.py` lines 54–103

**Full function structure to copy** (lines 54–103):
```python
def enqueue_update(payload: dict) -> bool:
    """..."""
    queue = os.getenv("CLOUD_TASKS_QUEUE", "")
    if not queue:
        return False
    try:
        project = os.environ["GCP_PROJECT_ID"]
        location = os.getenv("CLOUD_TASKS_LOCATION", "me-central1")
        base_url = os.environ["CLOUD_RUN_URL"]
        sa_email = os.environ["CLOUD_SCHEDULER_SA_EMAIL"]

        client = _get_client()
        parent = client.queue_path(project, location, queue)
        task = {
            "dispatch_deadline": {"seconds": _DISPATCH_DEADLINE_SECONDS},
            "http_request": {
                "http_method": "POST",
                "url": f"{base_url}/internal/process-update",  # CHANGE: /internal/process-hub-message
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode("utf-8"),
                "oidc_token": {
                    "service_account_email": sa_email,
                    "audience": base_url,
                },
            },
        }
        client.create_task(request={"parent": parent, "task": task})
        return True
    except Exception:
        logger.exception(
            "Cloud Tasks enqueue failed for update_id=%s — falling back to "
            "in-process handling",
            payload.get("update_id"),
        )
        return False
```

**For `enqueue_hub_message`:** Copy this exactly. Change the URL to `/internal/process-hub-message`. Change the payload to `{"content": content, "user_id": user_id}`. Change the exception log message to reference hub message. Signature: `def enqueue_hub_message(content: str, user_id: int) -> bool`. The lazy `_client` singleton and `_DISPATCH_DEADLINE_SECONDS = 540` are already module-level — no changes needed there.

---

### `memory/firestore_db.py` — field additions to `SelfStateStore` and `UserProfileStore` (modified file, model, CRUD)

**Analog:** existing field additions in same file — `UserProfileStore._SCAFFOLD` (lines 204–220) and `SelfStateStore.set` (lines 523–539)

**Adding fields to SelfStateStore** — mirror `set()` pattern (lines 523–539):
```python
def set(self, patch: dict) -> None:
    """Merge patch into the self_state document. Raises on failure (caller decides)."""
    try:
        self._doc_ref.set(
            {**patch, "updated_at": firestore.SERVER_TIMESTAMP},
            merge=True,
        )
    except Exception:
        logger.error("SelfStateStore.set() failed", exc_info=True)
        raise
    cache_key = getattr(self, "_cache_key", None)
    if cache_key is not None:
        _cache_invalidate_prefix(cache_key)
```

**New fields for Phase 26 (TIME-07 coach note, open question resolved):**
- `SelfStateStore` gains `daily_note: str | None` and `daily_note_date: str | None`
- `UserProfileStore._SCAFFOLD` gains `telegram_user_id: int | None` (to bridge hub identity to Firestore conversation key — RESEARCH.md Open Question 2)
- `UserProfileStore._SCAFFOLD` gains `session_version: int` (for sign-out-everywhere — D-02; initialized to 0)

**Adding `session_version` field to `UserProfileStore._SCAFFOLD`** — mirror scaffold pattern (lines 204–220):
```python
_SCAFFOLD = {
    # ... existing fields ...
    "session_version": 0,        # bumped by /api/auth/revoke-all (D-02)
    "telegram_user_id": None,    # Amit's Telegram user_id; hub uses this to key FirestoreConversationStore
}
```

**`_jsonsafe_doc` helper** (lines 882–910 — read-only reference, do not modify):
```python
def _jsonsafe_doc(d: dict) -> dict:
    return {k: _jsonsafe_value(v) for k, v in d.items()}

def _jsonsafe_value(v):
    if isinstance(v, dict):
        return {k: _jsonsafe_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonsafe_value(x) for x in v]
    iso = getattr(v, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return str(v)
    return v
```

**MealStore.get_day** (lines 774–816 — called by `/api/today`, read-only reference):
```python
def get_day(self, date_str: str) -> list[dict]:
    """Return all meals for a date, sorted by timestamp ascending. Never raises."""
    try:
        snaps = self._col.document(date_str).collection("timestamps").stream()
        # ... dedup logic ...
        return sorted(meals, key=lambda d: d.get("timestamp", ""))
    except Exception:
        logger.warning("MealStore.get_day(%r) failed", date_str, exc_info=True)
        return []
```

---

### `core/morning_briefing.py` — write `daily_note` to `SelfStateStore` (modified file, service, event-driven)

**Analog:** `core/reflection.py` or `core/autonomous.py` — pattern of writing to `SelfStateStore.set()` after a compose step.

The exact line in `morning_briefing.py` to add a `SelfStateStore.set({"daily_note": note, "daily_note_date": today})` call. Mirror the write pattern from `SelfStateStore.set()`:
```python
# After composing the morning briefing message (existing compose step)
# Add this write:
self_state_store.set({
    "daily_note": coach_note_one_line,  # the one-liner extracted from the briefing
    "daily_note_date": today_iso,       # guards against serving yesterday's note
})
```

This write is "best-effort" — if it fails, the briefing should still send. Wrap in `try/except Exception` and log at WARNING.

---

### `Dockerfile` (modified — config, build)

**Analog:** existing `Dockerfile` lines 1–31 (the current single-stage Python image)

**Existing single-stage structure** (lines 1–31):
```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --no-create-home --uid 1000 --shell /bin/false klaus
USER klaus

EXPOSE 8080

CMD ["sh", "-c", "uvicorn interfaces.web_server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
```

**New multi-stage structure** (RESEARCH.md Multi-Stage Dockerfile pattern) — prepend Node build stage, keep Python stage identical:
```dockerfile
# Stage 1: Build frontend (new)
FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# Output: /frontend/dist/

# Stage 2: Python runtime (existing — keep all existing lines identical)
FROM python:3.11-slim
# ... all existing ENV, WORKDIR, COPY, RUN, USER, EXPOSE, CMD unchanged ...

# Insert before CMD:
COPY --from=frontend-builder /frontend/dist ./frontend/dist
```

**Invariant preserved:** `--workers 1` in CMD is unchanged (ConversationManager in-process singleton requirement from CLAUDE.md §6).

---

### `tests/test_hub_auth.py` (new file — test, request-response)

**Analog:** `tests/test_task_dispatch.py` (lines 1–101) and `tests/test_web_server.py` (lines 1–80)

**Test file structure pattern** (from `tests/test_task_dispatch.py` lines 1–30):
```python
"""Tests for interfaces/hub_auth.py — session cookie + GIS verify + allowlist.

WHY this module exists: ...
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

_ENV = {
    "HUB_SESSION_SECRET": "test-secret-32-bytes-long-enough!",
    "HUB_ALLOWED_EMAIL": "amit.grupper@gmail.com",
    "GOOGLE_OAUTH_CLIENT_ID": "fake-client-id.apps.googleusercontent.com",
    "CRON_DEV_BYPASS": "true",
}
```

**Fixture pattern for lazy-import stubbing** (from `tests/test_task_dispatch.py` lines 33–47):
```python
@pytest.fixture()
def fake_tasks_v2():
    """Stub google.cloud.tasks_v2 in sys.modules and reset the client singleton."""
    fake = MagicMock(name="tasks_v2")
    # ...
    with patch.dict(sys.modules, {"google.cloud.tasks_v2": fake}):
        import core.task_dispatch as td
        td._client = None  # reset lazy singleton between tests
        yield fake, fake_client
        td._client = None
```

**Web server test pattern for env + stubs** (from `tests/test_web_server.py` lines 43–62):
```python
def _stub_web_server_imports() -> dict:
    stubs = {
        "telegram": sys.modules.get("telegram", MagicMock(name="telegram")),
        "core.auth_google": MagicMock(name="core.auth_google"),
        "core.main": MagicMock(name="core.main"),
        "interfaces._router": MagicMock(name="interfaces._router"),
    }
    for key in list(sys.modules.keys()):
        if key == "interfaces.web_server" or key.startswith("interfaces.web_server."):
            del sys.modules[key]
    return stubs
```

**Test class pattern with `CRON_DEV_BYPASS`** (from `tests/test_web_server.py` lines 70–80):
```python
class TestCronAutonomousTick:
    def test_returns_200_with_dev_bypass_and_app_present(self, monkeypatch):
        stubs = _stub_web_server_imports()
        with patch.dict(sys.modules, stubs):
            import interfaces.web_server as ws
            from fastapi.testclient import TestClient
            # ... setup + assert
```

**Required test cases for `tests/test_hub_auth.py`** (from RESEARCH.md Validation Architecture):
- `test_valid_gis_token_issues_cookie` — `create_session_cookie` + `verify_session_cookie` round-trip
- `test_allowlist_rejects_other_email` — non-Amit email → 403
- `test_no_cookie_401` — `require_hub_session` with no cookie → 401
- `test_revoked_session` — bumped `session_version` invalidates old cookie

---

### `tests/test_api_today.py` (new file — test, request-response)

**Analog:** `tests/test_web_server.py` — same web server import-stubbing pattern

Required test cases (from RESEARCH.md Validation Architecture):
- `test_today_returns_expected_keys` — mocked tools; response has `calendar`, `garmin`, `weather`, `meals`, `training`, `coach_note`
- `test_no_datetimewithnanoseconds_leak` — all Firestore mocks return `DatetimeWithNanoseconds`; JSON serialization succeeds
- `test_meal_slot_time_not_eating_time` — slot timestamps `08:00/12:00/20:00` are never described as eating times in the response shape (TIME-03 / slot-time caveat from CLAUDE.md §6)
- `test_unauthenticated_returns_401` — no session cookie → 401

---

### `tests/test_hub_chat.py` (new file — test, CRUD)

**Analog:** `tests/test_task_dispatch.py` — same mock pattern for Cloud Tasks

Required test cases (from RESEARCH.md Validation Architecture):
- `test_post_chat_appends_to_firestore` — mocked `FirestoreConversationStore.append`; verifies call
- `test_post_chat_enqueues_hub_message` — mocked `enqueue_hub_message`; verifies URL target `/internal/process-hub-message`
- `test_get_messages_returns_window` — mocked `FirestoreConversationStore.get`; returns list
- `test_internal_process_hub_message_oidc_gated` — missing OIDC token → 401 (mirrors `tests/test_web_server.py` OIDC test)

---

## Shared Patterns (Cross-Cutting)

### 1. `load_dotenv(override=True)` — mandatory project invariant

**Source:** `interfaces/web_server.py` line 45
**Apply to:** any new Python module that calls `load_dotenv`
```python
# WHY: override=True ensures .env values win even when the shell has already
# exported the variable — the default behaviour silently ignores .env in that
# case, which causes confusing "wrong token" failures in local dev.
load_dotenv(override=True)
```

### 2. `_jsonsafe_doc()` before every `json.dumps` / `JSONResponse`

**Source:** `memory/firestore_db.py` lines 882–910
**Apply to:** every `/api/*` route that returns Firestore-derived data
```python
from memory.firestore_db import _jsonsafe_doc
# Wrap ALL Firestore read results before JSONResponse:
return JSONResponse(content=_jsonsafe_doc({...}))
```
**Warning:** `MealStore.get_day()`, `SelfStateStore.get()`, `UserProfileStore.load()` all have `SERVER_TIMESTAMP` fields. Missing this wrapper causes a `TypeError` on the first real request.

### 3. `hmac.compare_digest` for all auth token comparisons

**Source:** `interfaces/web_server.py` lines 228, 417, 468
**Apply to:** `interfaces/hub_auth.py` — any bearer token or session value comparison
```python
import hmac
# Always use this, never ==:
if not hmac.compare_digest(received.encode(), expected.encode()):
    raise HTTPException(status_code=403, detail={"error": "Invalid token"})
```

### 4. `run_in_executor` + `asyncio.gather` for sync tool calls in async routes

**Source:** `interfaces/web_server.py` lines 769–772 (ingest-chats), 826–828 (strength-sync), 856–858 (run-sync)
**Apply to:** `/api/today` route — all tool calls (`calendar_tool`, `garmin_tool`, `weather_tool`, `routes_tool`, `MealStore.get_day`, `UserProfileStore.load`, `SelfStateStore.get`) are synchronous
```python
@app.get("/api/today")
async def api_today(_email: str = Depends(require_hub_session)) -> JSONResponse:
    loop = asyncio.get_running_loop()
    calendar_data, garmin_data, weather_data = await asyncio.gather(
        loop.run_in_executor(None, _fetch_calendar, today_iso),
        loop.run_in_executor(None, _fetch_garmin),
        loop.run_in_executor(None, _fetch_weather),
    )
```

### 5. Lazy import pattern inside route handlers

**Source:** `interfaces/web_server.py` lines 619–620, 655–656, 700–702
**Apply to:** new `/api/*` and `/internal/process-hub-message` handlers
```python
# WHY: lazy import — same convention as every other /cron/* route.
# Keeps /health cold-start fast.
import core.morning_briefing as _morning  # inside the handler, not at module top
```

### 6. Singleton guard before route execution

**Source:** `interfaces/web_server.py` lines 302–307
**Apply to:** `/internal/process-hub-message` (needs `_orchestrator`)
```python
if _orchestrator is None:
    logger.error("/internal/process-hub-message before orchestrator initialised")
    raise HTTPException(
        status_code=500,
        detail={"error": "Server is still initialising; please retry."},
    )
```

### 7. Refuse-all on unset critical env var

**Source:** `interfaces/web_server.py` lines 401–412 (`_verify_healthkit_request`)
**Apply to:** `hub_auth.py` for `HUB_SESSION_SECRET` (cannot sign cookies without it)
```python
secret = os.environ.get("HUB_SESSION_SECRET", "")
if not secret:
    logger.error("HUB_SESSION_SECRET env unset — refusing all hub auth")
    raise HTTPException(status_code=500, detail={"error": "Server misconfigured"})
```

### 8. `CRON_DEV_BYPASS` skip pattern for local dev

**Source:** `interfaces/web_server.py` lines 337–339, 388–390, 447–449
**Apply to:** `require_hub_session` dependency (allow bypass in local dev without a real Google cookie)
```python
if os.getenv("CRON_DEV_BYPASS", "false").lower() == "true":
    return "amit.grupper@gmail.com"  # bypass returns the allowed email
```

---

## Frontend Pattern Assignments (Greenfield — No In-Repo Analog)

All frontend files have no analog in this Python-only codebase. The source of truth for each is RESEARCH.md + UI-SPEC.md. Summary of which RESEARCH.md pattern governs each file:

| Frontend File Group | RESEARCH.md Pattern | Key Constraints from UI-SPEC.md |
|---------------------|--------------------|---------------------------------|
| `vite.config.ts` | Pattern 4 (vite-plugin-pwa) | `registerType: 'autoUpdate'`, `generateSW`, network-first for `document`, cache-first for `/assets/` |
| `src/main.tsx` | Pattern 5 (polling + query client) | `QueryClientProvider` wraps `RouterProvider`; `zustand` auth store initialized here |
| `src/App.tsx` + `AppShell.tsx` | UI-SPEC.md Responsive Layout Contract | `md:` breakpoint = desktop (sidebar + timeline + glance + chat); `<md` = bottom tabs |
| `src/api/client.ts` | RESEARCH.md Code Examples ("fetch with credentials") | `credentials: 'include'` on all fetch calls; redirect to `/?signin=required` on 401 |
| `src/api/chat.ts` | Pattern 5 (optimistic send + polling) | `POST /api/chat` + `GET /api/chat/messages?before=<seq>` |
| `src/hooks/useChat.ts` | Pattern 5 | `refetchInterval: 2500` only when `ChatWindow` mounted; `useMutation` with `onMutate`/`onError`/`onSettled` |
| `src/hooks/useUnread.ts` | Pattern 7 | `localStorage.last_seen_seq`; badge = `messages.length - last_seen_seq`; clear on IntersectionObserver on last message |
| `src/components/auth/SignInPage.tsx` | Pattern 2 (GIS button) | Dark background `#0A0A0A`; heading "Klaus" at Display size (28px/600); subheading "Your personal agent" |
| `src/components/shared/InstallBanner.tsx` | Pattern 4 iOS banner | `isIOS && !isStandalone && !localStorage.getItem('install-banner-dismissed')`; fixed bottom; accent CTA button |
| `src/components/timeline/NowLine.tsx` | UI-SPEC.md Interaction Contracts | Accent `#6366F1` horizontal rule; `scrollIntoView({ behavior: 'smooth', block: 'center' })` on mount |
| `src/components/timeline/PlaceholderCard.tsx` | UI-SPEC.md D-06 + Copywriting Contract | No shimmer (not a skeleton); fixed text strings from Copywriting Contract |
| `src/components/chat/ChatWindow.tsx` | Pattern 5 + Pattern 7 | Load 50 messages; scroll-to-bottom on new Klaus message if already at bottom; IntersectionObserver on last message for unread clear |
| All layout components | UI-SPEC.md Layout Components | Dark theme `#0A0A0A` dominant / `#1A1A1A` cards; `#6366F1` accent for active states only; `lucide-react` icons; `sr-only` spans on desktop sidebar icons |

**Color constants (UI-SPEC.md Color section) — define in a shared `src/tokens.ts` or Tailwind config:**
- Dominant: `#0A0A0A`
- Secondary: `#1A1A1A`
- Accent: `#6366F1` (indigo-500) — ONLY for: unread badge, active tab/sidebar icon, chat send button, now-line, install banner CTA
- Text primary: `#F9FAFB`
- Text secondary: `#9CA3AF`
- Destructive: `#EF4444`
- Success: `#22C55E`
- Surface border: `#2A2A2A`
- Offline: `#F59E0B` (amber-500) — top border strip only

**Typography constants (UI-SPEC.md Typography section):**
- Body: 16px / weight 400 / line-height 1.5
- Label: 13px / weight 400 / line-height 1.4
- Heading: 20px / weight 600 / line-height 1.2
- Display: 28px / weight 600 / line-height 1.15
- Exactly 2 weights: 400 (regular) and 600 (semibold). No 500.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| All `frontend/src/**` files (20 files) | component/hook/store/utility | — | No React/TypeScript/Vite project exists in this Python repo. Use RESEARCH.md + UI-SPEC.md as the sole source of truth. |

---

## Critical Anti-Patterns (Codebase-Verified)

These are explicitly forbidden by existing code discipline or CLAUDE.md §6 invariants:

1. **`app.mount` before API routes** — `SPAStaticFiles` mount must be the absolute last statement in `web_server.py`. Checked: no existing `app.mount` call exists yet in the file (safe to append).

2. **Agent turns in Starlette BackgroundTask** — `/internal/process-hub-message` MUST use Cloud Tasks (same as `/internal/process-update`). From CLAUDE.md §6 invariant: "Agent turns must run INSIDE a tracked request (Cloud Tasks → `/internal/process-update`), never in a Starlette BackgroundTask."

3. **`json.dumps` on raw Firestore docs** — always go through `_jsonsafe_doc()`. Multiple existing usages at lines 1022, 1047, 1072, 1157, 1176, 1203, 1295, 1309, 1328 in `firestore_db.py` confirm this is the universal convention.

4. **`load_dotenv()` without `override=True`** — from CLAUDE.md §6: "load_dotenv always with override=True". From `web_server.py` line 45.

5. **`--workers` > 1** — `ConversationManager` is in-process singleton. Dockerfile CMD preserves `--workers 1`.

6. **Uppercase in GCP/Pinecone resource names** — from CLAUDE.md §6: "All GCP/Pinecone resource names lowercase `klaus-`". New Firestore fields/documents follow existing lowercase convention (`session_version`, `daily_note`, `telegram_user_id`).

---

## Metadata

**Analog search scope:** `interfaces/`, `core/`, `memory/`, `tests/`, root `Dockerfile`
**Files read:** `interfaces/web_server.py` (886 lines), `core/task_dispatch.py` (104 lines), `memory/firestore_conversation.py` (191 lines), `core/auth_google.py` (424 lines), `memory/firestore_db.py` (selected ranges: lines 159–271, 479–565, 708–880, 882–911), `Dockerfile` (31 lines), `tests/test_task_dispatch.py` (101 lines), `tests/test_web_server.py` (80 lines, header + TestCronAutonomousTick start)
**Pattern extraction date:** 2026-06-13
