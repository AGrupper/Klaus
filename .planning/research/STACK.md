# Stack Research

**Domain:** Web PWA hub — React + TypeScript frontend served from existing FastAPI/Cloud Run service
**Researched:** 2026-06-13
**Confidence:** HIGH for frontend stack (well-established ecosystem, verified versions); HIGH for auth pattern (official Google docs + existing `google-auth` library already in `requirements.txt`); MEDIUM for Web Push iOS constraints (behavior is documented but Apple's reliability is an observed characteristic, not a spec guarantee)

---

## Executive Context

This research covers only the NEW technology needed for v5.0 Klaus Hub. The existing Python/FastAPI/Firestore/Cloud Run stack is validated and unchanged. The question is: what gets added?

Five decision areas need research:
1. Frontend build: React + Vite + TypeScript + Tailwind versions and tooling
2. PWA: `vite-plugin-pwa` vs hand-rolled service worker
3. Web Push: Python-side VAPID library + iOS Safari constraints
4. Auth: Google Identity Services (GSI) one-tap → FastAPI session cookie
5. Serving: StaticFiles mount, SPA fallback, cache headers

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| React | 19.x | UI framework | Latest stable; concurrent features clean up polling + async UX; no breaking changes from v18 for this scope |
| TypeScript | 5.x | Type safety | Standard; Vite templates default to TS5; no reason to use 4.x |
| Vite | 6.x | Build tool (NOT 7) | Vite 7 breaks `@tailwindcss/vite` peer dep (`^5.2.0 \|\| ^6` only); stay on 6.x until Tailwind ships Vite 7 support |
| Tailwind CSS | 4.x | Styling | v4 ships a Vite plugin (`@tailwindcss/vite`) — no PostCSS config file needed, just `import 'tailwindcss'` in CSS |
| `vite-plugin-pwa` | 1.x | PWA manifest + service worker | Zero-config manifest generation, Workbox integration, TypeScript types; use `injectManifest` strategy to keep control of push event handlers |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@tanstack/react-query` | v5.x (5.90+) | Server state, polling, cache | Every `/api/*` call; `refetchInterval` for chat polling while app is open |
| `react-router` | v7.x | Client-side routing | Declarative mode only (not framework mode); 5 top-level tabs map naturally to routes |
| `lucide-react` | latest | Icons | Ships tree-shakeable SVGs; pairs with Tailwind; shadcn/ui's default icon set |
| `pywebpush` | 2.3.0 | Python-side Web Push (VAPID) | Send push to subscribed browser from FastAPI routes and from `core/scheduled_message.py` |
| `itsdangerous` | bundled with Starlette | Session cookie signing | Already a Starlette/FastAPI dependency; `SessionMiddleware` is built on it — no new package |
| `aiohttp` | >=3.9 | Async HTTP for push sends | Required by `pywebpush` 2.1+ `async_webpush`; keeps push sends non-blocking inside FastAPI handlers |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `@vitejs/plugin-react` | React fast refresh + JSX | Required peer for Vite + React; version must be compatible with Vite 6 (4.x works) |
| `@tailwindcss/vite` | Tailwind v4 Vite integration | Replaces PostCSS config entirely; just `plugins: [tailwindcss()]` in `vite.config.ts` |
| `vitest` | Frontend unit tests | Same config as Vite; keep separate from the Python `pytest` suite |
| `typescript` | 5.x | TS compiler | Vite handles transpilation; tsc only for type checking |

---

## Detailed Decisions

### 1. Vite + React + Tailwind Scaffold

Use Vite 6 (not 7). As of 2026-06-13, `@tailwindcss/vite` declares `"vite": "^5.2.0 || ^6"` as a peer dependency — Vite 7 installs fail. Tailwind v4 eliminates the old `tailwind.config.js` and PostCSS chain entirely; configuration lives in the CSS file via `@import "tailwindcss"` and `@theme {}` blocks.

Vite 6 requires Node 18+ (use Node 22 LTS in the Docker build layer).

TypeScript project: `tsconfig.json` must include `"vite-plugin-pwa/client"` in `compilerOptions.types` so the service worker globals are typed.

### 2. vite-plugin-pwa vs Hand-Rolled Service Worker

Use `vite-plugin-pwa` v1.x with the **`injectManifest` strategy** — not `generateSW`.

Why `injectManifest`: `generateSW` auto-generates the entire service worker from Workbox options with no escape hatch for custom push event handlers. `injectManifest` lets you write `src/sw.ts` with your own `push` and `notificationclick` listeners while Workbox still injects the pre-cache manifest. This is the documented approach for push notifications in vite-plugin-pwa (see GitHub issue #84).

The service worker (`src/sw.ts`) needs:
```typescript
self.addEventListener('push', (event) => {
  const data = event.data?.json();
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/icon-192.png',
      badge: '/badge-72.png',
      data: { url: data.url },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
```

`event.waitUntil` is mandatory on iOS — a push handler that doesn't call `showNotification` inside `waitUntil` causes iOS to silently kill the service worker.

### 3. Web Push (VAPID) — Python Side

**Library:** `pywebpush==2.3.0` (released 2026-02-09; async support added in 2.1.0 via `async_webpush`).

VAPID keys: Generate once with OpenSSL (`ec -name prime256v1`), store private key as Secret Manager secret, public key as env var `VAPID_PUBLIC_KEY`. The private key can be passed to `pywebpush` as a base64-encoded DER string (not a file path) — better for Cloud Run where you can't guarantee a writable filesystem path.

VAPID claims must include `"sub": "mailto:amit.grupper@gmail.com"` and `"aud"` is auto-populated from the endpoint URL by pywebpush.

`async_webpush` uses `aiohttp` under the hood. Add `aiohttp>=3.9` to `requirements.txt`.

Push send pattern in `core/scheduled_message.py`:
```python
from pywebpush import async_webpush
await async_webpush(
    subscription_info=sub.to_dict(),  # from PushSubscriptionStore
    data=json.dumps({"title": "Klaus", "body": msg, "url": "/"}),
    vapid_private_key=os.environ["VAPID_PRIVATE_KEY_DER"],
    vapid_claims={"sub": "mailto:amit.grupper@gmail.com"},
)
```

**PushSubscriptionStore** (new Firestore store in `memory/firestore_db.py`): stores `endpoint`, `keys.auth`, `keys.p256dh` from the browser `PushSubscription` object. Single document per device (Amit only); support multiple devices (iPhone + PC).

### 4. iOS Safari Web Push Constraints

These are hard constraints, not soft best practices:

| Constraint | Detail |
|------------|---------|
| Install required | Push only works for PWAs added to home screen via Safari → Share → Add to Home Screen. An open Safari tab never gets push. |
| iOS 16.4+ required | Amit is on iPhone; over 95% of iPhones run ≥16 as of 2026. Non-issue. |
| Gesture-gated permission | `Notification.requestPermission()` must be called inside a click handler — not on page load, not in `setTimeout`. Show a button in the UI; request on tap. |
| `display: standalone` mandatory | The `manifest.webmanifest` must have `"display": "standalone"`. vite-plugin-pwa sets this via config. |
| `event.waitUntil` mandatory | Service worker push handler must call `showNotification` inside `waitUntil` or iOS drops the notification silently. |
| HTTPS required | Cloud Run already serves HTTPS — no action needed. |
| Delivery reliability | ~70-85% vs Android ~90-95%. Acceptable for personal use; Telegram mirror flag (per the design spec) covers the gap during transition. |
| EU DMA exception | Apple removed standalone PWA (and therefore push) in the EU with iOS 17.4. Amit is in Tel Aviv (Israel), not EU — no impact. |
| Subscription stability | iOS subscriptions can expire after prolonged inactivity. Implement re-subscription logic on hub open: check if subscription is still valid, re-register if not. |

### 5. Google Sign-In (GSI) Auth Flow

The existing `google-auth>=2.30` in `requirements.txt` is the verification library — no new package needed.

**Flow:**
1. Frontend loads the Google Identity Services One Tap JS library (`accounts.google.com/gsi/client`) — not OAuth redirect, just the credential token flow.
2. On successful sign-in, GSI returns a JWT credential to the frontend callback.
3. Frontend POSTs the credential to `POST /api/auth/google` (new FastAPI route).
4. Backend verifies with `google.oauth2.id_token.verify_oauth2_token(credential, GoogleRequest(), audience=CLIENT_ID)`.
5. Check `payload["email"] == "amit.grupper@gmail.com"` — allowlist of one. Reject all others with 403.
6. Set a server-side session cookie using Starlette's `SessionMiddleware` (already bundled with FastAPI/Starlette):
   ```python
   request.session["user"] = payload["sub"]  # Google sub, not email
   ```
7. All `/api/*` routes check `request.session.get("user")` — raise 401 if absent.

`SessionMiddleware` configuration:
```python
from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],  # new Secret Manager secret
    https_only=True,    # Secure flag — Cloud Run is always HTTPS
    same_site="lax",    # Prevents CSRF for top-level navigations; fine for same-origin hub
    max_age=30 * 24 * 3600,  # 30 days — personal device, no public terminal risk
)
```

CSRF: `SameSite=Lax` covers the CSRF attack surface for same-origin form submissions. GSI also validates `g_csrf_token` automatically. No additional CSRF library needed.

Note: `google-auth-oauthlib` is for the *server-side* Google OAuth flow (used by `core/auth_google.py` for Calendar/Gmail). The GSI credential token flow for the hub uses only `google-auth` + `google.oauth2.id_token.verify_oauth2_token` — no OAuth redirect, no callback URL, simpler.

### 6. Serving Vite Build from FastAPI

**Build output:** `frontend/dist/` (Vite default). Add a Docker build step that runs `npm run build` and copies `frontend/dist/` into the image. The `frontend/` directory lives alongside `interfaces/`, `core/`, etc.

**StaticFiles mount:** Mount with a SPA fallback. FastAPI's `StaticFiles` returns 404 for unknown paths by default; React Router needs the server to return `index.html` for any non-API path.

```python
# In web_server.py, after all /api/* and /cron/* routes:
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import pathlib

FRONTEND_DIR = pathlib.Path(__file__).parent.parent / "frontend" / "dist"

@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    candidate = FRONTEND_DIR / full_path
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(FRONTEND_DIR / "index.html")
```

**Cache headers:** Vite hashes asset filenames (`/assets/index-Bz3xYK.js`). These can be served with `Cache-Control: public, max-age=31536000, immutable`. `index.html` and the service worker (`sw.js`) must NOT be cached aggressively — use `Cache-Control: no-cache` so the browser always re-checks. Implement via a custom `StaticFiles` subclass or a response header middleware that checks the path pattern.

**Cloud Run:** No CDN is needed for a personal tool (one user). The container serves assets directly. If latency ever matters, Cloud CDN can be bolted on later with zero app changes.

### 7. Data Fetching with TanStack Query v5

Use `@tanstack/react-query` v5.90+ (latest stable). For this app:

- `/api/today` — fetch on mount, refetch on window focus, manual pull-to-refresh
- `/api/chat/messages` — poll every 3 seconds while the chat tab is active (`refetchInterval: 3000`); disable when tab is backgrounded via `refetchIntervalInBackground: false`
- `/api/tasks`, `/api/habits` — standard cache with `staleTime: 60_000`; invalidate on mutation

v5 API change to note: `refetchInterval` callback now receives the `Query` object (not `data` + `Query`). Minor — just don't use the old v4 signature.

No global state library (Zustand, Redux) is needed. TanStack Query handles all server state. Local UI state (open/close panels, form inputs) uses React's own `useState`/`useReducer`.

---

## Installation

```bash
# In frontend/ directory
npm create vite@latest . -- --template react-ts
npm install react-router @tanstack/react-query lucide-react
npm install -D vite-plugin-pwa @tailwindcss/vite tailwindcss

# Python side (add to requirements.txt)
# pywebpush>=2.3.0
# aiohttp>=3.9
```

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| `vite-plugin-pwa` (`injectManifest`) | Hand-rolled service worker | Plugin handles manifest generation, Workbox precaching, TypeScript types; only the push event listener needs to be custom — `injectManifest` gives both |
| `vite-plugin-pwa` (`injectManifest`) | `generateSW` strategy | `generateSW` gives no escape hatch for custom push handlers; documented dead-end |
| `pywebpush` | `web-push` (Node), Firebase FCM | pywebpush is the canonical Python VAPID library; FCM adds a GCP dependency and intermediary that breaks the direct VAPID model |
| `async_webpush` | Sync `webpush()` in executor | Push sends happen inside FastAPI route handlers and cron flows — blocking an executor thread for every push send is wasteful; async is cleaner |
| `SessionMiddleware` (Starlette built-in) | `authlib`, `fastapi-users`, Auth0 | Single user, single identity provider; a full auth library is massive overkill; `google-auth` is already in requirements |
| Vite 6 | Vite 7 | Tailwind v4's `@tailwindcss/vite` peer dep breaks on Vite 7 as of 2026-06-13 |
| `react-router` v7 (declarative) | `wouter` | wouter is 1.2kB vs 17kB — for a personal tool loaded on fast connections, the bundle savings don't justify losing React Router's `useNavigate`, `useParams`, nested routes, and `<NavLink>` active state |
| `@tanstack/react-query` | SWR | TanStack Query has cleaner mutation invalidation, `refetchInterval` with conditional function signature, devtools; SWR is fine but TQ is more capable for the Today + Chat polling pattern |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Next.js / Remix | SSR frameworks; Cloud Run already serves FastAPI; adding Node.js SSR creates a second runtime, second container, CORS headaches | Vite SPA served as static files from FastAPI |
| Firebase Cloud Messaging (FCM) | Adds an extra intermediary and GCP service just to wrap VAPID; direct VAPID works fine for one user and is simpler to debug | `pywebpush` direct VAPID |
| Zustand / Redux | No complex shared state; server state is TanStack Query's job; UI state is local | React `useState` + TanStack Query |
| `google-auth-oauthlib` OAuth redirect flow for hub auth | Full OAuth redirect is for acquiring service credentials (Calendar, Gmail) — the hub only needs to verify who the user is, which GSI credential token does in one step | GSI One Tap + `verify_oauth2_token` |
| `@vitejs/plugin-react-swc` | SWC variant is faster in CI but introduces a native binary; the standard `@vitejs/plugin-react` (Babel) is fast enough for a small personal app and avoids native dep complexity | `@vitejs/plugin-react` |
| Vite 7 | Breaks `@tailwindcss/vite` peer dependency (^5.2.0 \|\| ^6 only) | Vite 6 |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `vite@6.x` | `@tailwindcss/vite@4.x` | Tailwind v4 Vite plugin peer dep is `^5.2.0 \|\| ^6` — Vite 7 fails |
| `vite@6.x` | `@vitejs/plugin-react@4.x` | 4.3.4+ added Vite 6 to peerDependencies |
| `vite-plugin-pwa@1.x` | `vite@6.x` | 1.x requires Vite 5 or 6 |
| `pywebpush@2.3.0` | Python 3.10+ | Prod Dockerfile is Python 3.11 — compatible |
| `aiohttp>=3.9` | `asyncio` / FastAPI | Used by `async_webpush`; no conflict with existing dependencies |
| `react@19.x` | `react-router@7.x` | RR v7 officially targets React 18+/19 |
| `@tanstack/react-query@5.x` | `react@18 \| react@19` | v5 supports both |

---

## New Environment Variables / Secrets

| Name | Where Stored | Used By |
|------|-------------|---------|
| `VAPID_PRIVATE_KEY_DER` | Secret Manager | `pywebpush` in push send paths |
| `VAPID_PUBLIC_KEY` | Env var (not secret) | Served to frontend at `/api/push/vapid-public-key` |
| `GOOGLE_CLIENT_ID` | Secret Manager | GSI One Tap config on frontend + `verify_oauth2_token` on backend |
| `SESSION_SECRET` | Secret Manager | `SessionMiddleware` cookie signing |

---

## Sources

- [pywebpush GitHub CHANGELOG](https://github.com/web-push-libs/pywebpush/blob/main/CHANGELOG.md) — confirmed v2.3.0 latest (2026-02-09), async since 2.1.0 (HIGH confidence)
- [pywebpush PyPI](https://pypi.org/project/pywebpush/) — Python >=3.10 requirement (HIGH confidence)
- [Google: Verify Google ID token](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token) — `verify_oauth2_token`, CSRF, `sub` as canonical ID (HIGH confidence)
- [Starlette docs: Middleware](https://starlette.dev/middleware/) — `SessionMiddleware` config, itsdangerous signing (HIGH confidence)
- [vite-pwa-org: Guide](https://vite-pwa-org.netlify.app/guide/) — v1.2.0, injectManifest strategy for custom push handlers (HIGH confidence)
- [vite-plugin-pwa GitHub issue #84](https://github.com/vite-pwa/vite-plugin-pwa/issues/84) — confirmed `injectManifest` is the path for push notification handlers (MEDIUM confidence)
- [TanStack Query v5 docs: Polling](https://tanstack.com/query/latest/docs/framework/react/guides/polling) — `refetchInterval` API (HIGH confidence)
- [PWA Push Notifications on iOS in 2026](https://webscraft.org/blog/pwa-pushspovischennya-na-ios-u-2026-scho-realno-pratsyuye?lang=en) — iOS constraints, EU DMA exception, 70-85% delivery reliability (MEDIUM confidence — observed behavior, not Apple spec)
- [Vite 7 / Tailwind peer dep issue](https://github.com/vitejs/vite/issues/20284) — confirmed Tailwind v4 plugin breaks on Vite 7 (HIGH confidence)
- [React Router v7 modes — LogRocket](https://blog.logrocket.com/react-router-v7-modes/) — declarative mode recommendation (MEDIUM confidence)
- [FastAPI serving Vite SPA discussion](https://github.com/fastapi/fastapi/discussions/5134) — SPA fallback pattern for StaticFiles (MEDIUM confidence)

---

*Stack research for: Klaus Hub v5.0 PWA — new frontend capabilities only*
*Researched: 2026-06-13*
