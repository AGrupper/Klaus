# Phase 26: Hub Shell - Research

**Researched:** 2026-06-13
**Domain:** React + TypeScript + Vite PWA served by FastAPI (Cloud Run) — auth, SPA routing, chat polling, Today aggregation
**Confidence:** HIGH (core patterns verified via official docs and authoritative sources)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Auth model = Google Sign-In allowlisted to Amit's account only + effectively-permanent session. Sign in once per device, long-lived cookie silently refreshed on each visit.
- **D-02:** Sign-out + sign-out-everywhere. "Revoke all" via a bumpable session-version counter (small Firestore doc or `UserProfileStore` field). In-process sessions acceptable for v5.0.
- **D-03:** Timeline covers strict today, midnight–midnight (not rolling-24h).
- **D-04:** Now-line marker + past items dimmed, auto-scroll to now-line on open.
- **D-05:** Refresh `/api/today` on open and on focus; pull-to-refresh on phone. No constant timer polling.
- **D-06:** Empty/not-yet-generated data → quiet "not ready yet" placeholder (distinct from in-flight skeleton). Coach note before morning briefing: "coming after your morning briefing". Garmin before sync: "Sleep stats syncing…".
- **D-07:** One continuous conversation stream. Not multi-thread. Matches Telegram shared history invariant.
- **D-08:** On open, load a recent window (~30–50 messages) for fast first paint, with scroll-up to page in older history from shared Firestore conversation.
- **D-09:** Hub chat processed via dedicated `/internal/process-hub-message` endpoint (Cloud Tasks full-CPU path). Not a Starlette BackgroundTask. Not reusing `/internal/process-update` directly.
- **D-10:** Unread badge clears when user scrolls to bottom of chat (newest message actually viewed).
- **D-11:** Badge counts all unseen Klaus messages — direct replies AND proactive/autonomous-tick outreach AND anything that arrived via Telegram since last-seen.
- **D-12:** One-time dismissible iOS install banner (manual instruction: Share → Add to Home Screen). iOS has no `beforeinstallprompt`. Dismiss once → stays gone (localStorage).

### Claude's Discretion
- Service-worker caching strategy for HUB-03 (network-first for `index.html`; cache-first for hashed/immutable assets).
- Session cookie mechanics (signing, `httpOnly`/`Secure`/`SameSite`, refresh-on-visit), Google Sign-In flow details (GIS button, popup vs redirect), session-version storage location.
- Frontend project structure, component breakdown, routing, state/data-fetching library choices.
- Optimistic-send + 2–3s polling implementation details for chat (behavior locked; mechanics are Claude's).
- `/api/today` composition internals and caching of expensive sub-calls (routes/Garmin).

### Deferred Ideas (OUT OF SCOPE)
- ChatGPT/Claude-style multi-conversation threads (breaks Telegram shared history).
- Tasks on glance rail / Today timeline (TASK-07) — Phase 27.
- Habits/supplements on timeline (TIME-06) — Phase 28.
- Web Push + Telegram-mirror flag + unread-count app-icon badge (PUSH-01..04) — Phase 29.
- Periodic auto-refresh/SSE for timeline and chat (HUBX-01) — only if polling proves insufficient.
- Firestore-backed sessions surviving cold starts (HUBX-02) — v5.0 in-process acceptable.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HUB-01 | Google Sign-In allowlisted to Amit's account; `/api/*` rejects unauthenticated requests | GIS + `verify_oauth2_token` (google-auth, already in requirements.txt); `itsdangerous.TimestampSigner` cookie; FastAPI dependency injection |
| HUB-02 | Hub installs as PWA on iPhone (manifest, icons, service worker) with explicit Add-to-Home-Screen onboarding | vite-plugin-pwa 1.3.0; iOS no `beforeinstallprompt` → manual banner; `apple-touch-icon` 180×180 |
| HUB-03 | App shell loads on bad connection; API data degrades to skeletons + offline indicator; new deploys not blocked by stale `index.html` | vite-plugin-pwa `generateSW` + Workbox; network-first `index.html`, cache-first hashed assets |
| HUB-04 | Frontend served from `klaus-agent` Cloud Run without breaking existing routes | Multi-stage Dockerfile; `SPAStaticFiles` catch-all mounted LAST after all `/api/*`, `/cron/*`, `/internal/*`, `/trigger/*`, `/telegram-webhook`, `/health` |
| HUB-05 | Desktop = sidebar + timeline + glance rail + collapsible chat; phone = bottom tabs with Klaus center tab | Tailwind responsive breakpoints; component layout (UI phase handles pixel design) |
| CHAT-01 | Chat uses same Firestore conversation history as Telegram | `FirestoreConversationStore.get()` + `append()` (existing); hub reads same `conversations/{telegram_user_id}` doc |
| CHAT-02 | Hub messages via Cloud Tasks full-CPU path (`/internal/process-hub-message`) | `enqueue_update()` pattern from `core/task_dispatch.py`; adapt target URL to new endpoint |
| CHAT-03 | Optimistic send + 2–3s polling; "Klaus is thinking…" indicator | `@tanstack/react-query` `useMutation` (optimistic) + `useQuery` with `refetchInterval: 2500` |
| CHAT-04 | Klaus tab unread badge counting messages since last-seen | `last_seen_seq` stored in `localStorage`; compare against loaded message count |
| TIME-01 | Today calendar events chronologically; all-day events pinned at top | `mcp_tools/calendar_tool.py`; `/api/today` aggregation |
| TIME-02 | Garmin morning stats + one-line weather summary in timeline header | `mcp_tools/garmin_tool.py` + `mcp_tools/weather_tool.py`; `/api/today` |
| TIME-03 | Today meals as slot labels with macros (display-only; never present slot timestamps as eating times) | `MealStore.get_day()` from `memory/firestore_db.py`; slot-time caveat enforced server-side |
| TIME-04 | Today training plan item + block context ("Week N of 16") | `UserProfileStore.load()` from `memory/firestore_db.py` |
| TIME-05 | Events with location show leave-by / Get Ready times (traffic-aware) | `mcp_tools/routes_tool.py.get_travel_time()`; cached per event in `/api/today` |
| TIME-07 | One-line coach note for the day (sourced from morning briefing) | `SelfStateStore.get()` or a new `daily_note` field; see Coach Note Source section |
| TIME-08 | Glance rail: day's nutrition running totals (kcal + macros) from MealStore | `MealStore.get_day_aggregate()` from `memory/firestore_db.py` |
</phase_requirements>

---

## Summary

Phase 26 is the first phase of v5.0 — it adds the entire frontend layer to a backend-only Python service. The codebase has never had a frontend. The core engineering challenge is not "how to build a React app" but six specific integration problems at the seam between existing Python code and new TypeScript/Vite code: SPA static serving without breaking existing routes, multi-stage Dockerfile, Google session auth, PWA install on iOS, chat-via-Cloud-Tasks, and the `/api/today` aggregator.

All six integration problems have well-established solutions. The Starlette `SPAStaticFiles` catch-all pattern is well-documented. The multi-stage Dockerfile for Node→Python is straightforward and mirrors patterns used at scale. Google Identity Services + `verify_oauth2_token` (already in `google-auth`, which is in `requirements.txt`) is the right auth path. `vite-plugin-pwa` handles Workbox/service-worker complexity. `@tanstack/react-query` handles optimistic mutations and polling idiomatically. The `/api/today` aggregator reuses existing tool functions already in the codebase.

The biggest landmines are ordering-related: (1) `app.mount("/", SPAStaticFiles(...))` MUST be the very last statement in `web_server.py` — any route registered after it is unreachable; (2) Firestore `SERVER_TIMESTAMP` reads back as `DatetimeWithNanoseconds` and MUST go through `_jsonsafe_doc()` before `json.dumps` in every `/api/*` handler; (3) the synchronous Firestore/tool calls in `/api/today` MUST run in `run_in_executor` (same pattern as existing `/cron/*` routes) because the async event loop blocks on sync calls; (4) iOS is Israel's target platform and Safari has no `beforeinstallprompt` — the install banner must be a pure instructional UI, not a programmatic trigger.

**Primary recommendation:** Use `vite-plugin-pwa` (not hand-rolled Workbox), `@tanstack/react-query` (not hand-rolled polling), `itsdangerous.TimestampSigner` (not JWT, not `SessionMiddleware`), and the `SPAStaticFiles(lookup_path)` override pattern (not `html=True` alone). Mount static files absolutely last.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Auth / session verification | API / Backend (FastAPI) | — | Session cookie is httpOnly; JS never sees it; server verifies on every `/api/*` call |
| Google ID token verification | API / Backend (FastAPI) | — | `verify_oauth2_token` is a server-side operation; never done in the browser |
| Today timeline data composition | API / Backend (`/api/today`) | — | Aggregates Firestore + external tools; heavy; cached server-side |
| Calendar / weather / Garmin / routes calls | API / Backend | — | All existing tool files are Python; keep them there |
| Chat message send | Browser / Client → Cloud Tasks | API / Backend | Client POSTs to `/api/chat`; server enqueues to Cloud Tasks; agent turn runs in `/internal/process-hub-message` |
| Chat message receive (polling) | Browser / Client | API / Backend | Client polls `/api/chat/messages`; server reads Firestore window |
| Unread badge count | Browser / Client | — | Computed client-side from `last_seen_seq` (localStorage) vs loaded messages |
| PWA manifest / service worker | Browser / Client (build-time) | — | Generated by vite-plugin-pwa at build; served as static assets |
| iOS install banner | Browser / Client | — | Pure instructional UI; no browser API involvement |
| SPA static serving | API / Backend (FastAPI) | — | `SPAStaticFiles` mounted last; catches everything not matched by API routes |
| Firestore conversation history | Database / Storage | — | Shared with Telegram; read/write via `FirestoreConversationStore` |
| Nutrition totals, meals, training plan | Database / Storage | API / Backend | Firestore reads through existing store classes |

---

## Standard Stack

### Frontend Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react | 19.2.7 | UI component model | Latest stable; concurrent features available |
| typescript | 6.0.3 | Type safety | Project standard; required for maintainability |
| vite | 8.0.16 | Build tool | Fastest HMR; native ESM; ecosystem standard |
| tailwindcss | 4.3.1 | Utility-first CSS | Locked in design spec; fast responsive layout |
| @vitejs/plugin-react | 6.0.2 | React JSX transform via Babel | Standard Vite+React plugin |
| vite-plugin-pwa | 1.3.0 | Service worker, manifest, Workbox integration | Replaces ~500 lines of hand-rolled Workbox config |

### Frontend Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @tanstack/react-query | 5.101.0 | Server state: fetch, cache, poll, optimistic updates | All API data fetching (`/api/today`, `/api/chat/messages`) |
| zustand | 5.0.14 | Client-only UI state | Auth state, unread count, chat send status (not server-derived data) |
| react-router-dom | 7.17.0 | Client-side routing | Tab navigation; route guards for unauthenticated users |
| lucide-react | 1.18.0 | Icon set | Consistent with Tailwind; tree-shaken |
| clsx | 2.1.1 | Conditional className utility | Cleaner than template literals for Tailwind |

### Backend New Dependencies
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| itsdangerous | 2.2.0 | HMAC-signed session cookie (TimestampSigner) | In Python stdlib lineage; used by Flask/Starlette internally; no JWT overhead for session data that is just "email + session_version" |

**Note on `python-jose`:** `python-jose` 3.5.0 is on PyPI. It is NOT needed here because we are not issuing JWTs — we are issuing signed opaque cookies via `itsdangerous`. `python-jose` is tagged `[ASSUMED]` to be unnecessary and is excluded from the stack.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| vite-plugin-pwa | Hand-rolled Workbox | Hand-rolled requires ~500 lines of workbox config; plugin handles precache manifest injection at build time |
| @tanstack/react-query | SWR | TanStack is more featureful (optimistic mutations, background refetch, polling control); SWR is simpler but polling + optimistic is harder |
| itsdangerous | python-jose JWT | JWT adds ~80 bytes overhead per request for session data; itsdangerous `TimestampSigner` is simpler for a session that carries only email + version |
| zustand | React Context | Context re-renders every subscriber; zustand is selective subscription |

**Installation — Frontend:**
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install tailwindcss @tailwindcss/vite
npm install vite-plugin-pwa
npm install @tanstack/react-query
npm install zustand
npm install react-router-dom
npm install lucide-react clsx
```

**Installation — Backend:**
```bash
pip install itsdangerous
# Add to requirements.txt: itsdangerous>=2.2
```

**Version verification (run before finalizing):**
```bash
npm view react version              # 19.2.7 confirmed
npm view vite-plugin-pwa version    # 1.3.0 confirmed
npm view @tanstack/react-query version  # 5.101.0 confirmed
npm view tailwindcss version        # 4.3.1 confirmed
pip3 index versions itsdangerous    # 2.2.0 confirmed
```

---

## Package Legitimacy Audit

slopcheck was not available in this environment (install permission denied). All packages below are tagged `[ASSUMED]` based on registry verification only. The planner must add `checkpoint:human-verify` before each install.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| react | npm | ~12 yrs | >50M/wk | github.com/facebook/react | [ASSUMED] | Approved — canonical React |
| vite | npm | ~5 yrs | >25M/wk | github.com/vitejs/vite | [ASSUMED] | Approved — canonical Vite |
| typescript | npm | ~12 yrs | >60M/wk | github.com/microsoft/TypeScript | [ASSUMED] | Approved |
| tailwindcss | npm | ~7 yrs | >15M/wk | github.com/tailwindlabs/tailwindcss | [ASSUMED] | Approved |
| @vitejs/plugin-react | npm | ~4 yrs | >20M/wk | github.com/vitejs/vite/tree/main/packages/plugin-react | [ASSUMED] | Approved |
| vite-plugin-pwa | npm | ~4 yrs | >1.5M/wk | github.com/vite-pwa/vite-plugin-pwa | [ASSUMED] | Approved — widely used |
| @tanstack/react-query | npm | ~5 yrs | >8M/wk | github.com/TanStack/query | [ASSUMED] | Approved — canonical |
| zustand | npm | ~5 yrs | >5M/wk | github.com/pmndrs/zustand | [ASSUMED] | Approved |
| react-router-dom | npm | ~9 yrs | >15M/wk | github.com/remix-run/react-router | [ASSUMED] | Approved |
| lucide-react | npm | ~4 yrs | >3M/wk | github.com/lucide-icons/lucide | [ASSUMED] | Approved |
| clsx | npm | ~6 yrs | >20M/wk | github.com/lukeed/clsx | [ASSUMED] | Approved |
| itsdangerous | PyPI | ~12 yrs | >15M/wk | github.com/pallets/itsdangerous | [ASSUMED] | Approved — Pallets project (Flask ecosystem) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck was unavailable at research time; all packages above are tagged `[ASSUMED]` and the planner must gate each install behind a `checkpoint:human-verify` task.*

---

## Architecture Patterns

### System Architecture Diagram

```
Browser (React SPA)
  │
  ├── GET /                → SPAStaticFiles (dist/) → index.html (SPA bootstrap)
  ├── GET /assets/*.js     → SPAStaticFiles (dist/assets/) → hashed file (cache-first)
  │
  ├── POST /api/auth/google-signin  → FastAPI: verify GIS ID token → set signed cookie
  ├── POST /api/auth/signout        → FastAPI: clear cookie
  ├── POST /api/auth/revoke-all     → FastAPI: bump session_version in Firestore
  │
  ├── GET  /api/today               → FastAPI (session guard)
  │                                    → asyncio.gather([calendar, garmin, weather, meals,
  │                                                       training_plan, routes, coach_note])
  │                                    → _jsonsafe_doc() each result → JSON response
  │
  ├── GET  /api/chat/messages?before=<seq>  → FastAPI (session guard)
  │                                           → FirestoreConversationStore.get()
  │                                           → slice window (D-08) → JSON
  │
  └── POST /api/chat                → FastAPI (session guard)
        │  append user msg to FirestoreConversationStore
        └─ enqueue_hub_message() → Cloud Tasks queue
                                      → POST /internal/process-hub-message (OIDC)
                                            → _router.handle_hub_message(content, user_id)
                                                → AgentOrchestrator._run_smart_loop()
                                                → FirestoreConversationStore.append(assistant)
                                                (Telegram delivery skipped — hub source)

Service Worker (vite-plugin-pwa)
  ├── index.html              → NetworkFirst (never serve stale shell)
  ├── /assets/*.{js,css}      → CacheFirst, 365d (content-hashed filenames)
  └── App Shell precache      → Workbox generateSW precache manifest
```

### Recommended Project Structure
```
frontend/                    # All frontend code (gitignored node_modules)
├── index.html               # Vite entry; <link rel="apple-touch-icon">
├── vite.config.ts           # VitePWA plugin config; alias @/ → src/
├── tailwind.config.ts       # Tailwind v4 config
├── tsconfig.json
├── public/
│   ├── manifest.json        # Generated by vite-plugin-pwa or hand-crafted
│   ├── icon-192.png
│   ├── icon-512.png
│   ├── icon-512-maskable.png
│   └── apple-touch-icon.png  # 180×180
└── src/
    ├── main.tsx             # React root, QueryClientProvider, Router
    ├── App.tsx              # Route layout: auth guard → desktop/phone layout
    ├── api/
    │   ├── client.ts        # fetch wrapper (credentials: 'include' for cookies)
    │   ├── auth.ts          # /api/auth/* calls
    │   ├── today.ts         # /api/today fetch + TanStack query key
    │   └── chat.ts          # /api/chat POST + /api/chat/messages GET
    ├── components/
    │   ├── layout/          # Sidebar, BottomTabs, GlanceRail, DockChat
    │   ├── timeline/        # TimelineDay, TimelineItem, NowLine
    │   ├── chat/            # ChatWindow, MessageBubble, TypingIndicator
    │   └── shared/          # Skeleton, OfflineIndicator, InstallBanner
    ├── hooks/
    │   ├── useToday.ts      # useQuery wrapper for /api/today
    │   ├── useChat.ts       # polling + optimistic send
    │   └── useUnread.ts     # localStorage last_seen_seq + badge count
    └── store/
        └── auth.ts          # Zustand: { email, signedIn, signOut }
```

### Pattern 1: SPAStaticFiles — SPA catch-all without shadowing API routes

**What:** Override `StaticFiles.lookup_path` to fall back to `index.html` for unknown paths. Mount LAST in `web_server.py`.

**When to use:** Any FastAPI app serving a React SPA with client-side routing.

```python
# interfaces/web_server.py  — APPEND after all existing routes

from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

class SPAStaticFiles(StaticFiles):
    """Serve a Vite SPA build; fall back to index.html for client-side routes.

    WHY lookup_path override (not get_response override): lookup_path is called
    before the response is built, so a 404 fallback via lookup_path avoids
    constructing a 404 response that we then discard. The get_response override
    pattern catches the exception AFTER, which is slightly less efficient.
    """
    async def lookup_path(self, path: str):
        full_path, stat_result = await super().lookup_path(path)
        if stat_result is None:
            # Unknown path → let the React router handle it
            return await super().lookup_path("index.html")
        return full_path, stat_result

# IMPORTANT: this must be the VERY LAST statement that registers routes.
# Any route registered AFTER app.mount is unreachable.
_DIST_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_DIST_PATH):
    app.mount("/", SPAStaticFiles(directory=_DIST_PATH, html=True), name="spa")
else:
    logger.warning("Frontend dist/ not found — SPA will not be served (dev mode?)")
```

**Source:** Pattern confirmed via [Starlette SPA serving guide](https://www.crccheck.com/blog/serving-spas-from-starlette/) [CITED] and [FastAPI static files docs](https://fastapi.tiangolo.com/tutorial/static-files/) [CITED: fastapi.tiangolo.com].

### Pattern 2: Session Auth — GIS → server verify → signed cookie

**What:** Frontend uses Google Identity Services button (one-tap or popup) to obtain an `id_token`. Posts it to `/api/auth/google-signin`. Backend calls `verify_oauth2_token`, checks email against allowlist, issues an `itsdangerous.TimestampSigner`-signed `session` cookie.

**When to use:** Every visit to `/api/*`. The FastAPI dependency reads the cookie and validates it.

```python
# interfaces/hub_auth.py  — new file

import hmac
import os
from datetime import timedelta

from fastapi import Cookie, HTTPException, Request, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

_ALLOWED_EMAIL = os.environ.get("HUB_ALLOWED_EMAIL", "amit.grupper@gmail.com")
_SESSION_SECRET = os.environ["HUB_SESSION_SECRET"]  # 32-byte random, stored in Secret Manager
_SESSION_MAX_AGE_DAYS = 365  # "effectively permanent" per D-01
_SIGNER = TimestampSigner(_SESSION_SECRET)


def create_session_cookie(email: str, session_version: int) -> str:
    """Sign 'email:session_version' with a timestamp; returns URL-safe string."""
    payload = f"{email}:{session_version}"
    return _SIGNER.sign(payload).decode("utf-8")


def verify_session_cookie(cookie_value: str, current_version: int) -> str:
    """Return email if cookie is valid and session_version matches current.

    Raises HTTPException 401 on any failure.
    """
    try:
        payload_bytes = _SIGNER.unsign(
            cookie_value,
            max_age=int(timedelta(days=_SESSION_MAX_AGE_DAYS).total_seconds()),
        )
        payload = payload_bytes.decode("utf-8")
        email, stored_version = payload.rsplit(":", 1)
    except (SignatureExpired, BadSignature, ValueError):
        raise HTTPException(status_code=401, detail={"error": "Session expired or invalid"})

    if int(stored_version) != current_version:
        raise HTTPException(status_code=401, detail={"error": "Session revoked"})
    if email != _ALLOWED_EMAIL:
        raise HTTPException(status_code=403, detail={"error": "Forbidden"})
    return email


async def require_hub_session(request: Request) -> str:
    """FastAPI dependency: verify session cookie, return email. Use on all /api/* routes."""
    cookie_value = request.cookies.get("hub_session")
    if not cookie_value:
        raise HTTPException(status_code=401, detail={"error": "Not authenticated"})
    # Load current session_version from UserProfileStore (or dedicated Firestore doc)
    current_version = _get_session_version()
    return verify_session_cookie(cookie_value, current_version)


# In the signin handler:
# response.set_cookie(
#     "hub_session", token,
#     max_age=_SESSION_MAX_AGE_DAYS * 86400,
#     httponly=True, secure=True, samesite="strict"
# )
```

**Google ID token verification (backend):**
```python
# Source: https://developers.google.com/identity/gsi/web/guides/verify-google-id-token [CITED]
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

idinfo = id_token.verify_oauth2_token(
    token,
    google_requests.Request(),
    os.environ["GOOGLE_OAUTH_CLIENT_ID"],
)
email = idinfo.get("email")
if not idinfo.get("email_verified"):
    raise HTTPException(status_code=401, detail={"error": "Email not verified"})
if email != _ALLOWED_EMAIL:
    raise HTTPException(status_code=403, detail={"error": "Not authorized"})
```

**Note:** `google-auth` is already in `requirements.txt`. `verify_oauth2_token` is the same function used by `core/auth_google.py` (different flow — here we verify an ID token, not an OAuth access token, but same library). [VERIFIED: already in requirements.txt]

**Session version storage:** The `UserProfileStore` already has a Firestore doc at `config/user_profile`. Add `session_version: int` field there. `bump_session_version()` increments it. `get_session_version()` reads it (cached in the 10-min `_READ_CACHE` alongside `SelfStateStore`). This avoids adding a new Firestore collection. [ASSUMED — confirm this field doesn't conflict with existing UserProfileStore schema]

### Pattern 3: Sync-in-async tool calls inside `/api/today`

**What:** All existing tool functions (`calendar_tool`, `garmin_tool`, `weather_tool`, `routes_tool`, `MealStore.get_day`) are **synchronous**. FastAPI routes are async. Calling sync code directly from an async route blocks the event loop (measured as stalled requests on Cloud Run).

**Pattern:** Use `loop.run_in_executor(None, sync_fn)` exactly as existing cron routes do (e.g., `/cron/strength-sync`). For concurrency, `asyncio.gather`.

```python
# Source: mirrors existing pattern in interfaces/web_server.py /cron/* routes [VERIFIED: codebase]

@app.get("/api/today")
async def api_today(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    loop = asyncio.get_running_loop()
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()

    # Run all independent sync calls concurrently in the executor pool
    calendar_data, garmin_data, weather_data, meal_data, training_data = await asyncio.gather(
        loop.run_in_executor(None, _fetch_calendar, today_iso),
        loop.run_in_executor(None, _fetch_garmin),
        loop.run_in_executor(None, _fetch_weather),
        loop.run_in_executor(None, _fetch_meals, today_iso),
        loop.run_in_executor(None, _fetch_training_plan),
    )
    # Routes tool is expensive — run separately and per-event only for events with location
    # Cache routes results in process memory with a short TTL (30 min)

    return JSONResponse(content=_jsonsafe_doc({
        "today": today_iso,
        "calendar": calendar_data,
        "garmin": garmin_data,
        "weather": weather_data,
        "meals": meal_data,
        "training": training_data,
        "coach_note": _fetch_coach_note(),
    }))
```

**Coach note source:** TIME-07 requires a "one-line coach note for the day sourced from the morning briefing." No existing Firestore field stores this. Two options:
1. Add a `daily_note` field to `SelfStateStore` (written by `core/morning_briefing.py` at compose time) — **recommended** because it follows the existing self_state pattern and is read via the TTL cache.
2. Read the last journal entry from `JournalStore` — less reliable (journal may not yet exist today).
The planner should decide; this is identified as an open question.

### Pattern 4: vite-plugin-pwa Configuration (network-first index.html + iOS banner)

**What:** `vite-plugin-pwa` generates the service worker via Workbox's `generateSW` strategy. Configure `runtimeCaching` to use `NetworkFirst` for `index.html` (so new deploys are never blocked) and `CacheFirst` for hashed static assets.

```typescript
// frontend/vite.config.ts
// Source: https://vite-pwa-org.netlify.app/workbox/generate-sw [CITED]
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',   // Service worker updates itself silently
      strategies: 'generateSW',
      workbox: {
        // Precache all build outputs (hashed JS/CSS) — these are cache-first by default
        globPatterns: ['**/*.{js,css,html,ico,png,svg,webmanifest}'],
        // index.html: network-first so a new deploy is never blocked by stale cache
        runtimeCaching: [
          {
            urlPattern: ({ request }) => request.destination === 'document',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'html-cache',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 5, maxAgeSeconds: 60 * 60 * 24 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          // Hashed assets (JS/CSS bundles) — cache-first, long TTL
          {
            urlPattern: /\/assets\/.+\.(js|css)$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'assets-cache',
              expiration: { maxEntries: 50, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      manifest: {
        name: 'Klaus',
        short_name: 'Klaus',
        description: 'Your personal AI agent',
        theme_color: '#000000',
        background_color: '#000000',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      // iOS apple-touch-icon is in index.html head, not in manifest
    }),
  ],
})
```

**iOS install banner (D-12):** iOS has no `beforeinstallprompt` event. [CITED: developer.apple.com/forums/thread/807603] Detection logic:
```typescript
// src/hooks/useInstallBanner.ts
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent)
const isInStandaloneMode = window.matchMedia('(display-mode: standalone)').matches
const dismissed = localStorage.getItem('install-banner-dismissed') === '1'
const showBanner = isIOS && !isInStandaloneMode && !dismissed
```

### Pattern 5: Chat — Optimistic Send + 2–3s Polling

**What:** `useMutation` sends optimistically; `useQuery` with `refetchInterval: 2500` polls while user is on the chat tab; polling pauses when tab loses focus (default TanStack behavior).

```typescript
// Source: https://tanstack.com/query/latest/docs/framework/react/guides/polling [CITED]
// and https://tanstack.com/query/v4/docs/framework/react/guides/optimistic-updates [CITED]

const { data: messages } = useQuery({
  queryKey: ['chat', 'messages'],
  queryFn: () => fetchMessages({ limit: 50 }),
  refetchInterval: isOnChatTab ? 2500 : false,  // only poll when chat is visible
  // refetchIntervalInBackground: false (default) — pause when tab loses focus
})

const sendMessage = useMutation({
  mutationFn: (content: string) => postChatMessage(content),
  onMutate: async (content) => {
    // 1. Cancel in-flight refetch to avoid race
    await queryClient.cancelQueries({ queryKey: ['chat', 'messages'] })
    // 2. Snapshot current messages
    const previous = queryClient.getQueryData(['chat', 'messages'])
    // 3. Optimistically append the message with status: 'sending'
    queryClient.setQueryData(['chat', 'messages'], (old: Message[]) => [
      ...old,
      { id: `optimistic-${Date.now()}`, role: 'user', content, status: 'sending' },
    ])
    return { previous }
  },
  onError: (_err, _content, context) => {
    // Roll back to previous state on error
    queryClient.setQueryData(['chat', 'messages'], context?.previous)
  },
  onSettled: () => {
    // Invalidate to sync with server (removes optimistic entry, gets real one)
    queryClient.invalidateQueries({ queryKey: ['chat', 'messages'] })
  },
})
```

**"Klaus is thinking…" indicator:** After a user message is sent (status transitions from `sending` to `sent`), the polling will eventually return Klaus's reply. While waiting, check if the last message in the conversation is from `role: 'user'` and show a `TypingIndicator` component. Clear it when the next `role: 'assistant'` message arrives.

### Pattern 6: Hub Message Dispatch (`/internal/process-hub-message`)

**What:** Mirror `enqueue_update()` in `core/task_dispatch.py` exactly, but target `/internal/process-hub-message`. The new endpoint calls into the orchestrator similarly to `/internal/process-update`, but the input is a simple JSON `{ "content": "...", "user_id": 123456 }` rather than a Telegram `Update` object.

```python
# core/task_dispatch.py — add alongside enqueue_update()

def enqueue_hub_message(content: str, user_id: int) -> bool:
    """Enqueue a hub chat message for full-CPU agent processing.

    Same queue, same OIDC token, different URL target.
    Returns True on success, False on any failure (never raises).
    """
    queue = os.getenv("CLOUD_TASKS_QUEUE", "")
    if not queue:
        return False
    try:
        # ... same boilerplate as enqueue_update ...
        task = {
            "dispatch_deadline": {"seconds": _DISPATCH_DEADLINE_SECONDS},
            "http_request": {
                "http_method": "POST",
                "url": f"{base_url}/internal/process-hub-message",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"content": content, "user_id": user_id}).encode(),
                "oidc_token": {
                    "service_account_email": sa_email,
                    "audience": base_url,
                },
            },
        }
        client.create_task(request={"parent": parent, "task": task})
        return True
    except Exception:
        logger.exception("Hub message enqueue failed — falling back")
        return False
```

**`/internal/process-hub-message` handler:**
- Verified by `_verify_cron_request(request)` (same OIDC path — same service account already has `run.invoker` on the service).
- Reads `{"content": str, "user_id": int}` from body.
- Appends user message to `FirestoreConversationStore`.
- Calls `_orchestrator.run_smart_loop(user_id=user_id, user_message=content)` (same orchestrator, same conversation — one Klaus).
- Does NOT call `send_and_inject()` / Telegram delivery (hub source; the reply goes into Firestore where the client polls it).

### Pattern 7: Firestore Conversation Window for Hub Chat

**What:** `FirestoreConversationStore.get(user_id)` returns the entire stored message list (up to `max_messages=100`). For the hub, we need a `before` cursor for scroll-up pagination (D-08).

The existing store does NOT support cursor-based pagination — it returns the whole window. For Phase 26, this is sufficient: 100 messages is a small payload (~15–20KB). Pagination for older history requires a new method or a rethink of the store schema (messages stored individually, not as an array in one document).

**Recommended approach for Phase 26:** Return the full window from `GET /api/chat/messages`. Frontend slices the most recent 50 for initial display; scroll-up to bottom shows older messages from the already-loaded window. Calling the API again with `before` query param is out of scope for this array-in-doc schema. Full cursor pagination is a `HUBX-02` concern if the window ever overflows.

**Unread badge (D-10/D-11):** Store `last_seen_message_index` (an integer = length of messages array at the time the user last saw the bottom) in `localStorage`. Badge count = `messages.length - last_seen_message_index`. Clear on scroll-to-bottom event.

### Multi-Stage Dockerfile

**What:** Node.js build stage produces `frontend/dist/`. Python stage copies it in. Single uvicorn worker maintained.

```dockerfile
# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
# Output: /frontend/dist/

# Stage 2: Python runtime (keep existing base)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy built frontend assets
COPY --from=frontend-builder /frontend/dist ./frontend/dist

RUN useradd --no-create-home --uid 1000 --shell /bin/false klaus
USER klaus

EXPOSE 8080

# Single worker REQUIRED: ConversationManager is in-process
CMD ["sh", "-c", "uvicorn interfaces.web_server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
```

**Key points:**
- Node 20-slim (LTS) for the build stage — [ASSUMED: latest LTS; verify `node:20-slim` is available on Docker Hub]
- `npm ci` (not `npm install`) in Dockerfile for reproducible builds
- `COPY --from=frontend-builder` references the named stage, not a path on the host
- `SPAStaticFiles` in `web_server.py` checks `os.path.isdir("frontend/dist")` and mounts conditionally — so local dev without a build still starts cleanly

### Anti-Patterns to Avoid
- **`app.mount` before API routes:** Any route registered after `app.mount("/", SPAStaticFiles(...))` is unreachable. Always mount LAST.
- **`json.dumps` on raw Firestore docs:** `DatetimeWithNanoseconds` breaks `json.dumps`. Always use `_jsonsafe_doc()` from `memory/firestore_db.py`.
- **Calling sync tools directly from async route:** Blocks event loop. Use `loop.run_in_executor(None, sync_fn)`.
- **`SESSION_MIDDLEWARE` with `secret_key`:** Starlette's `SessionMiddleware` puts session data in the cookie value unencrypted (only signed). For a single-user app this is tolerable, but `itsdangerous.TimestampSigner` is more minimal and avoids importing a cookie-based session store (which would conflict with the existing in-process ConversationManager).
- **httponly=False on the session cookie:** XSS in the SPA can steal the session cookie. Always set `httponly=True`.
- **Polling with `refetchIntervalInBackground: true`:** This would poll even when tab is backgrounded, wasting Garmin/routes budget. Keep the default (`false`) for `/api/today`.
- **Reusing `/internal/process-update` for hub messages:** D-09 locks hub messages to a dedicated endpoint. The Telegram path deserializes a `telegram.Update` object; the hub path has a different payload shape.
- **Serving `index.html` for `/api/*` routes on 404:** The `SPAStaticFiles.lookup_path` override must only trigger when no other route matched. Since `app.mount` is last, this is automatic — but verifying with `CRON_DEV_BYPASS=true` smoke tests is essential.
- **`purpose: 'any maskable'` combined icon:** Use separate `any` and `maskable` icons in the PWA manifest. [CITED: vite-pwa-org.netlify.app/guide/pwa-minimal-requirements.html]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service worker + precache manifest | Custom Workbox config | `vite-plugin-pwa` | Precache manifest must list hashed filenames generated at build time; plugin does this automatically at build; hand-rolling requires a separate build step |
| Polling + cache invalidation | Custom `setInterval` + `fetch` | `@tanstack/react-query` `refetchInterval` | Query deduplication, background refetch on focus, error retries, stale-while-revalidate all built in |
| Optimistic mutations + rollback | Custom state machine | `@tanstack/react-query` `useMutation` `onMutate`/`onError` | Error rollback is complex; TanStack handles the snapshot/restore cycle |
| Google ID token verification | JWT decode + manual signature check | `google.oauth2.id_token.verify_oauth2_token` | Google rotates signing keys; the library fetches them automatically from JWKS endpoint |
| HMAC cookie signing | Custom HMAC | `itsdangerous.TimestampSigner` | Edge cases in base64url padding, timing-safe compare, and expiry math are all handled |
| SPA 404 fallback | Nginx / custom middleware | `SPAStaticFiles` subclass | Three-line override; stays in the Python process |

**Key insight:** The service worker precache manifest lists content-hashed filenames that don't exist until build time. Any solution that generates this at runtime is wrong.

---

## Common Pitfalls

### Pitfall 1: `app.mount` Shadows Existing Routes
**What goes wrong:** Mounting `SPAStaticFiles` at `/` before registering API routes causes ALL requests (including `/telegram-webhook`, `/api/*`) to be handled by the static files handler, returning 404 for everything except actual files.
**Why it happens:** Starlette route matching is first-match. A `Mount("/")` matches everything.
**How to avoid:** Register all routes first. Add `app.mount` as the absolute last statement. Guard with `if os.path.isdir(_DIST_PATH)` so local dev without a build doesn't accidentally hide routes.
**Warning signs:** `/health` returns 200 but `/cron/heartbeat` returns 404 during dev.

### Pitfall 2: Sync Tool Calls Blocking the Event Loop
**What goes wrong:** Calling `MealStore.get_day()`, `get_travel_time()`, `calendar_tool.list_events()` directly in an `async def` route. These are synchronous Firestore/HTTP calls that block the event loop, stalling all concurrent requests.
**Why it happens:** FastAPI routes are `async def` but existing tools use blocking I/O.
**How to avoid:** `await asyncio.get_running_loop().run_in_executor(None, sync_fn, *args)` for each tool call. Wrap in `asyncio.gather()` for concurrency. Mirrors existing `/cron/strength-sync` and `/cron/run-sync` pattern.
**Warning signs:** `/api/today` takes 8+ seconds; other requests time out while today-fetch is running.

### Pitfall 3: Stale `index.html` Blocking New Deploy
**What goes wrong:** Service worker precaches `index.html` with CacheFirst strategy. After a new deploy, users see the old app because the service worker serves the cached version.
**Why it happens:** Vite's default precache includes `index.html` without a network-first override.
**How to avoid:** Add `runtimeCaching` entry for `request.destination === 'document'` with `NetworkFirst` handler (5s timeout). vite-plugin-pwa's `registerType: 'autoUpdate'` also helps — but if the SW itself is cached, `autoUpdate` doesn't run until the new SW is fetched, which requires `index.html` to be fresh first.
**Warning signs:** After a Cloud Run redeploy, Telegram shows new behavior but the hub shows old UI.

### Pitfall 4: `DatetimeWithNanoseconds` in JSON Response
**What goes wrong:** Any Firestore document field with `SERVER_TIMESTAMP` reads back as `DatetimeWithNanoseconds`, which raises `TypeError: Object of type DatetimeWithNanoseconds is not JSON serializable` in `json.dumps`.
**Why it happens:** All of: `MealStore.get_day()`, `SelfStateStore.get()`, `UserProfileStore.load()`, the conversation store's `updated_at` — all use `SERVER_TIMESTAMP`.
**How to avoid:** Wrap every Firestore read result through `_jsonsafe_doc()` before returning in a `JSONResponse`. The helper is already in `memory/firestore_db.py` and handles nested dicts/lists. [VERIFIED: codebase — `_jsonsafe_doc` at line 882]
**Warning signs:** 500 error on `/api/today` for users with logged meals.

### Pitfall 5: `httponly` Cookie and Credentials: 'include'
**What goes wrong:** Browser does not send the session cookie with API calls. `/api/*` returns 401 for an authenticated user.
**Why it happens:** `fetch()` defaults to `credentials: 'omit'`. Cookies are not sent unless `credentials: 'include'` is set.
**How to avoid:** All `fetch` calls to `/api/*` must use `{ credentials: 'include' }`. With same-origin (no CORS), this also requires `SameSite=Strict` on the cookie (which is correct — no cross-origin requests expected).
**Warning signs:** Network tab shows requests to `/api/today` with no `Cookie` header.

### Pitfall 6: iOS EU Restriction on PWAs
**What goes wrong:** In EU countries (including Israel as of some regulatory interpretations — CHECK), iOS 17.4+ removed standalone PWA support under DMA. PWAs open in Safari tabs.
**Why it happens:** Apple's DMA compliance removed web app install for some regions.
**How to avoid:** [ASSUMED] Israel is not in the EU/EEA, so DMA does not apply. Standard iOS PWA install should work. Verify on an Israeli App Store device. If the issue arises: the banner (D-12) guides the user; the app degrades gracefully to a web clip.
**Warning signs:** Installed app opens in Safari tab instead of standalone window.

### Pitfall 7: Cloud Tasks Dispatch Deadline vs Route Handler Timeout
**What goes wrong:** Hub message triggers Cloud Tasks; the task deadline (`_DISPATCH_DEADLINE_SECONDS = 540`) must be less than Cloud Run's request timeout. If an LLM call stalls, Cloud Tasks may retry the turn, creating duplicate Klaus responses.
**Why it happens:** Same issue as the existing Telegram path — mitigated by `LLM_TIMEOUT_SECONDS=120` env var.
**How to avoid:** Hub endpoint uses the same `_DISPATCH_DEADLINE_SECONDS` and `LLM_TIMEOUT_SECONDS` as the Telegram path. No changes needed. [VERIFIED: codebase — `_DISPATCH_DEADLINE_SECONDS = 540` in task_dispatch.py]

---

## Code Examples

### `/api/today` route skeleton
```python
# interfaces/web_server.py — new route, inserted before app.mount
import asyncio
from zoneinfo import ZoneInfo
from memory.firestore_db import _jsonsafe_doc  # existing helper

@app.get("/api/today")
async def api_today(
    _email: str = Depends(require_hub_session),
) -> JSONResponse:
    """Compose today's timeline data from all sources."""
    loop = asyncio.get_running_loop()
    today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
    # All tool functions are synchronous → run_in_executor
    calendar_data, garmin_data, weather_data, meal_data, training_data = await asyncio.gather(
        loop.run_in_executor(None, _today_calendar, today_iso),
        loop.run_in_executor(None, _today_garmin),
        loop.run_in_executor(None, _today_weather),
        loop.run_in_executor(None, _today_meals, today_iso),
        loop.run_in_executor(None, _today_training),
    )
    # Routes tool: called per-event for events with a location field; cached 30 min in-process
    calendar_with_leave_by = await loop.run_in_executor(
        None, _today_routes, calendar_data, today_iso
    )
    coach_note = _jsonsafe_doc({"note": _today_coach_note()})

    return JSONResponse(content={
        "today": today_iso,
        "calendar": calendar_with_leave_by,
        "garmin": garmin_data,
        "weather": weather_data,
        "meals": meal_data,
        "training": training_data,
        "coach_note": coach_note,
    })
```

### Existing `_jsonsafe_doc` usage pattern
```python
# Source: memory/firestore_db.py lines 882–910 [VERIFIED: codebase]
# Called on EVERY Firestore document before json.dumps:
result = _jsonsafe_doc(snap.to_dict() or {})
```

### Frontend: fetch with credentials (same-origin cookie)
```typescript
// src/api/client.ts
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: 'include',  // Send httpOnly session cookie
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (res.status === 401) {
    // Session expired or not authenticated — redirect to sign-in
    window.location.href = '/?signin=required'
    throw new Error('Not authenticated')
  }
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}
```

---

## Coach Note Source (TIME-07) — Open Architecture Decision

TIME-07 requires "Klaus's one-line coach note for the day (sourced from the morning briefing)". There is currently **no Firestore field** that stores a daily coach note. The morning briefing sends a message to Telegram but does not write a structured summary to Firestore.

**Two options (planner must choose):**
1. **Write to `SelfStateStore`:** Add `daily_note: str` and `daily_note_date: str` fields. `core/morning_briefing.py` writes them after composing the briefing message. `/api/today` reads via `SelfStateStore.get()` (already cached, no new Firestore read). **Recommended** — zero new collections, consistent with existing pattern.
2. **Write to a new `DailyNoteStore`:** Clean separation but requires a new Firestore collection and store class.

For option 1: The planner should add a task to `core/morning_briefing.py` to write `daily_note` after compose, plus a Wave 0 task if the field doesn't exist (default: `None` → D-06 placeholder "Coach note coming after your morning briefing").

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Workbox CLI hand-rolled | vite-plugin-pwa | ~2022 | Plugin generates precache manifest at build time automatically |
| Google Sign-In (gapi.auth2) | Google Identity Services (GIS) | 2021 (deprecated old) | New GIS library uses `credential.response` callback with ID token; old `gapi.auth2` is fully deprecated |
| `SessionMiddleware` cookie | `itsdangerous` signed cookie | Best practice always | SessionMiddleware encrypts full session dict; for single-user, a signed email+version token is sufficient |
| `fetch` + `setInterval` | `@tanstack/react-query` refetchInterval | ~2022 | Built-in dedup, background refetch on focus, error handling |

**Deprecated/outdated:**
- `gapi.auth2` / `google-signin-button`: Fully deprecated. Use Google Identity Services `<div id="g_id_onload">` button or the GIS JavaScript SDK.
- Vite 4.x: Vite 8.x is current; ensure `vite-plugin-pwa` version is compatible with Vite 8. (vite-plugin-pwa 1.3.0 supports Vite 5+/6+; verify Vite 8 compatibility — [ASSUMED: compatible based on npm peer deps].)

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `node:20-slim` is available on Docker Hub and works for Node 20 LTS builds | Multi-stage Dockerfile | Build stage fails; use `node:20-alpine` as fallback |
| A2 | `UserProfileStore` can host `session_version` field without conflicting with existing schema | Session Auth | Need to add `DailySessionStore` or separate Firestore doc instead |
| A3 | `SelfStateStore` can host `daily_note` + `daily_note_date` fields (TIME-07) | Coach Note Source | Need new store class if field naming conflicts |
| A4 | Israel is not in EU/EEA — iOS 17.4+ PWA restrictions do not apply | PWA Install | App opens in Safari tab instead of standalone; fallback: web clip still works but not standalone |
| A5 | vite-plugin-pwa 1.3.0 is compatible with Vite 8.x (no breaking peer dep conflict) | Standard Stack | Need to pin `vite@7.x` or use `vite-plugin-pwa@latest` if incompatible |
| A6 | `itsdangerous` is not already installed in the Cloud Run container (not in `requirements.txt`) | Backend New Deps | It's already available (Starlette's `SessionMiddleware` uses it as a dep) — verify via `pip show itsdangerous` in prod |
| A7 | Package download statistics and ages listed in Package Legitimacy Audit are approximate (from training data) | Package Legitimacy Audit | Run slopcheck when available to confirm |

---

## Open Questions (RESOLVED)

*All four questions were resolved during planning (Phase 26 plans 26-02 / 26-04). Markers below record the locked decision.*

1. **Coach note field (TIME-07)**
   - What we know: No Firestore field currently stores a daily coach note. Morning briefing composes a message and sends to Telegram but doesn't write a structured field.
   - What's unclear: Whether to add `daily_note` to `SelfStateStore` or a separate store.
   - Recommendation: Add `daily_note` + `daily_note_date` to `SelfStateStore.set()`. Add a write in `core/morning_briefing.py` after compose. Planner should create a Wave 0 task if the field doesn't exist at startup (D-06 empty state).
   - **RESOLVED:** Add `daily_note` + `daily_note_date` to `SelfStateStore` (no new store) and a best-effort write in `core/morning_briefing.py` after compose. Implemented by plan **26-02** (Tasks 1–2); read by `/api/today` in **26-04** with a `daily_note_date`-staleness → D-06 placeholder.

2. **Telegram user_id for hub auth**
   - What we know: `FirestoreConversationStore` keys on `telegram_user_id`. The hub doesn't have a Telegram user ID for Amit — it has his Google email.
   - What's unclear: How the hub identifies which Firestore conversation doc to read/write. Options: (a) hardcode Amit's Telegram user ID as an env var `HUB_TELEGRAM_USER_ID`; (b) store it in `UserProfileStore`.
   - Recommendation: Add `telegram_user_id: int` to `UserProfileStore` (already exists as a Firestore doc). The hub session is single-user anyway.
   - **RESOLVED:** Add `telegram_user_id` to the `UserProfileStore` scaffold (option b). Implemented by plan **26-02** (Task 1); consumed by the chat backend in **26-05** to key the shared `FirestoreConversationStore`.

3. **`itsdangerous` in Cloud Run environment**
   - What we know: `itsdangerous` is not in `requirements.txt`. It may already be installed as a transitive dep of `starlette`/`fastapi`.
   - What's unclear: Whether it's available at runtime without being pinned.
   - Recommendation: Add `itsdangerous>=2.2` to `requirements.txt` explicitly. Never depend on transitive availability.
   - **RESOLVED:** Pin `itsdangerous>=2.2` explicitly in `requirements.txt` (never rely on transitive availability). Implemented by plan **26-02** (Task 1); used for session-cookie signing in **26-03**.

4. **Routes tool call caching in `/api/today`**
   - What we know: `get_travel_time()` makes an HTTP call to Google Routes API per event. This can be ~500ms per event, and some days have many events with locations.
   - What's unclear: Whether a simple in-process TTL dict is sufficient or if Firestore caching is needed.
   - Recommendation: Use a module-level `_routes_cache: dict[str, tuple[float, dict]]` with 30-minute TTL. Key = `(event_id, departure_time_iso)`. No Firestore needed — same process serves all requests (single worker). This mirrors the `_READ_CACHE` pattern in `memory/firestore_db.py`.
   - **RESOLVED:** Use a module-level in-process TTL dict (30-minute TTL, keyed on `(event_id, departure_time_iso)`) — no Firestore cache, single worker serves all requests. Owned by plan **26-04** (`/api/today` composition).

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Frontend build (Dockerfile Stage 1, local dev) | ✓ | v25.9.0 (local) | — |
| npm | Frontend package install | ✓ | 11.12.1 (local) | — |
| Python 3.11 | Backend runtime (Dockerfile) | ✓ | 3.14.4 (local, use 3.11 in Docker) | — |
| Google Identity Services JS | HUB-01 Google Sign-In button | ✓ (CDN) | Latest (loaded at runtime) | — |
| Cloud Tasks queue `klaus-updates` | CHAT-02 hub message dispatch | ✓ (existing, per task_dispatch.py) | — | In-process fallback (logged, not dropped) |
| `HUB_SESSION_SECRET` env var | HUB-01 session cookie signing | ✗ (new) | — | Cannot skip — must provision in Secret Manager |
| `GOOGLE_OAUTH_CLIENT_ID` env var | HUB-01 GIS ID token verify | ✗ (new, different from the agent's credentials) | — | Must provision — web OAuth client ID |
| `HUB_ALLOWED_EMAIL` env var | HUB-01 allowlist | ✗ (new, or hardcoded) | — | Hardcode `amit.grupper@gmail.com` in env |
| `itsdangerous>=2.2` Python pkg | Session cookie | ✗ (not in requirements.txt) | 2.2.0 on PyPI | None — add to requirements.txt |

**Missing dependencies with no fallback:**
- `HUB_SESSION_SECRET` — 32-byte random string; must be created and stored in GCP Secret Manager before deploy.
- `GOOGLE_OAUTH_CLIENT_ID` — a **Web** OAuth 2.0 client ID (different from the Desktop client used by `core/auth_google.py`); must be created in Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs → Web application, with the Cloud Run URL as an authorized JavaScript origin.

**Missing dependencies with fallback:**
- None — all other deps are either already present or gracefully degraded.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (existing; `pytest.ini` at repo root) |
| Config file | `pytest.ini` (existing) |
| Quick run command | `pytest tests/test_hub_auth.py tests/test_api_today.py tests/test_hub_chat.py -x` |
| Full suite command | `pytest tests/ -x` (1153+ passing baseline must hold) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HUB-01 | Session cookie issued on valid GIS token; invalid token → 401 | unit | `pytest tests/test_hub_auth.py -x` | ❌ Wave 0 |
| HUB-01 | Allowlist rejects non-Amit email → 403 | unit | `pytest tests/test_hub_auth.py::test_allowlist_rejects_other_email -x` | ❌ Wave 0 |
| HUB-01 | `require_hub_session` dep rejects missing cookie → 401 | unit | `pytest tests/test_hub_auth.py::test_no_cookie_401 -x` | ❌ Wave 0 |
| HUB-01 | Session version bump invalidates old cookie | unit | `pytest tests/test_hub_auth.py::test_revoked_session -x` | ❌ Wave 0 |
| HUB-04 | Existing routes unaffected by SPA mount | unit | `pytest tests/test_web_server.py -x` (extend existing) | ✅ extend |
| HUB-04 | `/health` still returns 200 after SPA mount | unit | `pytest tests/test_web_server.py::test_health_still_works -x` | ❌ Wave 0 |
| CHAT-02 | `enqueue_hub_message` targets correct URL | unit | `pytest tests/test_task_dispatch.py -x` (extend existing) | ✅ extend |
| CHAT-02 | `/internal/process-hub-message` verified via OIDC; rejects missing token | unit | `pytest tests/test_web_server.py::TestHubMessage -x` | ❌ Wave 0 |
| CHAT-03 | `POST /api/chat` appends to FirestoreConversationStore | integration | `pytest tests/test_hub_chat.py -x` | ❌ Wave 0 |
| TIME-01-05,07,08 | `/api/today` returns expected keys; no DatetimeWithNanoseconds leak | unit | `pytest tests/test_api_today.py -x` | ❌ Wave 0 |
| TIME-03 | Meal slot timestamps never inferred as eating times (slot caveat) | unit | `pytest tests/test_api_today.py::test_meal_slot_time_not_eating_time -x` | ❌ Wave 0 |

**Manual-only tests (no automation):**
- HUB-02: Install banner appears in Safari on iPhone, dismisses permanently — requires physical iOS device.
- HUB-03: Service worker caches app shell; loads on airplane mode — requires Chrome DevTools offline simulation or physical device.
- HUB-05: Desktop/phone layout switch at Tailwind breakpoint — visual test in browser.
- CHAT-03: "Klaus is thinking…" indicator visible during reply delay — end-to-end with real Cloud Tasks.
- CHAT-04: Unread badge clears on scroll-to-bottom — end-to-end UI test.

### Sampling Rate
- **Per task commit:** `pytest tests/test_hub_auth.py tests/test_api_today.py tests/test_hub_chat.py tests/test_task_dispatch.py tests/test_web_server.py -x`
- **Per wave merge:** `pytest tests/ -x` (full suite — 1153+ baseline must hold)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_hub_auth.py` — covers HUB-01 (sign-in, allowlist, revoke, session dep)
- [ ] `tests/test_api_today.py` — covers TIME-01..05, TIME-07, TIME-08 (mocked tools; _jsonsafe_doc; slot caveat)
- [ ] `tests/test_hub_chat.py` — covers CHAT-01..03 (mocked Firestore + Cloud Tasks)
- [ ] `interfaces/hub_auth.py` — new module (auth helpers used by tests above)
- [ ] Extend `tests/test_web_server.py` — HUB-04 (existing routes unaffected post-SPA-mount)
- [ ] Extend `tests/test_task_dispatch.py` — CHAT-02 (`enqueue_hub_message` URL target)

*(The existing test infrastructure covers all baseline requirements; Wave 0 adds new files for new routes.)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Google GIS ID token → `verify_oauth2_token` (google-auth); email allowlist |
| V3 Session Management | yes | `itsdangerous.TimestampSigner`; `httpOnly=True`, `Secure=True`, `SameSite=Strict`; session-version counter for revoke-all |
| V4 Access Control | yes | `require_hub_session` FastAPI dependency on ALL `/api/*` routes; `/cron/*` and `/internal/*` untouched (still OIDC-gated) |
| V5 Input Validation | yes | Pydantic models on `/api/chat` body; no direct Firestore writes from user-supplied keys |
| V6 Cryptography | yes | `itsdangerous` HMAC-SHA1 (min); consider HMAC-SHA256 via `TimestampSigner(secret, digest_method=hashlib.sha256)` |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS stealing session cookie | Information Disclosure | `httponly=True` prevents JS access; Content-Security-Policy header on SPA responses |
| CSRF (cross-site form submission) | Tampering | `SameSite=Strict` on cookie; same-origin architecture eliminates most CSRF surface |
| Stolen session cookie (lost phone, D-02) | Elevation of Privilege | Session-version counter in `UserProfileStore`; bump via "sign out everywhere" |
| Token leaked via CLOUD_RUN_URL timing | Information Disclosure | `hmac.compare_digest` already used in all existing `_verify_*` helpers — mirror for hub auth |
| Invalid GIS token replay | Spoofing | `verify_oauth2_token` validates `exp` claim; GIS tokens expire in 1 hour |
| Hub endpoint open to internet | Elevation of Privilege | `/api/*` requires valid session cookie; `/internal/process-hub-message` requires OIDC token |
| Cloud Tasks body injection | Tampering | Hub message body is a simple `{content, user_id}` JSON; Pydantic validates on receipt |

**Critical:** Do NOT log the session cookie value. Mirror the redacted-token logging pattern from `_verify_healthkit_request` for any auth failure logs. [VERIFIED: pattern in codebase at web_server.py lines 419–423]

---

## Sources

### Primary (HIGH confidence)
- `interfaces/web_server.py` — existing route registration patterns, OIDC verify, `_verify_cron_request` [VERIFIED: codebase]
- `core/task_dispatch.py` — `enqueue_update()` pattern [VERIFIED: codebase]
- `memory/firestore_conversation.py` — `FirestoreConversationStore.get/append` [VERIFIED: codebase]
- `memory/firestore_db.py` line 882 — `_jsonsafe_doc()` [VERIFIED: codebase]
- `Dockerfile` — existing single-stage Python build [VERIFIED: codebase]
- `requirements.txt` — existing Python dependencies [VERIFIED: codebase]
- [Google: Verify ID token server-side](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token) [CITED]
- [FastAPI Static Files docs](https://fastapi.tiangolo.com/tutorial/static-files/) [CITED]
- [vite-pwa-org: generateSW workbox config](https://vite-pwa-org.netlify.app/workbox/generate-sw) [CITED]
- [TanStack Query: Polling](https://tanstack.com/query/latest/docs/framework/react/guides/polling) [CITED]
- [TanStack Query: Optimistic Updates](https://tanstack.com/query/v4/docs/framework/react/guides/optimistic-updates) [CITED]

### Secondary (MEDIUM confidence)
- [Serving SPAs from Starlette](https://www.crccheck.com/blog/serving-spas-from-starlette/) — `lookup_path` override pattern [CITED; consistent with Starlette source]
- [Serving React from FastAPI](https://davidmuraya.com/blog/serving-a-react-frontend-application-with-fastapi/) — `get_response` override alternative [CITED]
- [PWA iOS limitations 2026](https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide) — confirmed no `beforeinstallprompt` on iOS [CITED]
- [vite-pwa-org: PWA minimal requirements](https://vite-pwa-org.netlify.app/guide/pwa-minimal-requirements.html) — icon sizes [CITED]

### Tertiary (LOW confidence / ASSUMED)
- Package download statistics in legitimacy audit [ASSUMED — training data estimates]
- vite-plugin-pwa 1.3.0 peer dep compatibility with Vite 8.x [ASSUMED — verify]
- `itsdangerous` as a transitive dep of starlette/fastapi [ASSUMED — verify via `pip show itsdangerous` in prod]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified on npm/PyPI registry; major packages confirmed via official docs
- Architecture patterns: HIGH — SPA serving, GIS auth, Workbox config all verified against official documentation
- Pitfalls: HIGH — all based on verified codebase analysis or official docs
- Coach note / Telegram user_id bridging: LOW — requires design decision; no existing code covers it

**Research date:** 2026-06-13
**Valid until:** 2026-07-13 (30 days — stable technologies; vite-plugin-pwa compatibility with Vite 8 should be re-verified at implementation time)
