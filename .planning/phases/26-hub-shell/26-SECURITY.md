---
phase: 26
slug: hub-shell
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-16
---

# Phase 26 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Phase 26 (hub-shell) introduced the Klaus Hub — an authenticated PWA + `/api/*`
> surface (Google Sign-In → signed session cookie → today view + live chat).
> This is the first internet-facing authenticated surface in Klaus, so the auth /
> session / CSRF boundary is the crown-jewel of this register.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| internet → static asset serving (`/`) | SPA shell + hashed assets served unauthenticated by design; the SPA bootstraps then calls authed `/api/*` | Public app shell (no PII) |
| internet → `/api/auth/google` | Untrusted GIS ID token verified server-side via `verify_oauth2_token` before any cookie issues | Google ID token |
| browser cookie → `/api/*` | The signed `hub_session` cookie is the sole credential for every authed hub route | Session credential |
| browser → `POST /api/chat` | Live, write-capable command channel into Klaus (Gmail/calendar writes, LLM spend); gated by `require_hub_session` | User chat content |
| Cloud Tasks → `/internal/process-hub-message` | OIDC-gated internal endpoint; only the Cloud Tasks SA may invoke it | Agent turn payload |
| `/api/today` → external tools (Routes/Garmin/weather) | Server-side egress; results cached in-process; raw upstream errors never exposed to client | Health/calendar data |
| `/api/auth/revoke-all` → UserProfileStore.session_version | Server-side control surface for sign-out-everywhere (D-02) | Revocation counter |
| build pipeline → runtime image | npm + PyPI packages pulled at Docker build become runtime code | Dependency code |
| service worker cache → rendered shell | A stale cached shell could mask a security fix; mitigated network-first | Cached app shell |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-26-01-SC | Tampering | npm + PyPI installs | mitigate | Blocking-human legitimacy checkpoint verified every package before install (26-01-SUMMARY); deps pinned in `requirements.txt` / `frontend/package.json` | closed |
| T-26-01-01 | Elevation of Privilege | `app.mount("/")` shadowing `/cron/*`, `/internal/*`, `/telegram-webhook` | mitigate | Mount is the last statement (`web_server.py:1712`, guard comment :1679); `/cron/*` still OIDC-404s, not auth-bypassed | closed |
| T-26-01-02 | Information Disclosure | Stale cached `index.html` after deploy | mitigate | `NetworkFirst` for document + `registerType:'autoUpdate'` (`vite.config.ts:13,22`) | closed |
| T-26-01-03 | Tampering | Static assets served without subresource integrity (cache poisoning) | accept | Content-hashed filenames + same-origin HTTPS (Cloud Run TLS); single-user, low-value target | closed |
| T-26-02-01 | Denial of Service | `daily_note` write failing and blocking the morning briefing | mitigate | Write wrapped in try/except → WARNING; briefing send is primary and proceeds (`morning_briefing.py:191-196`) | closed |
| T-26-02-02 | Tampering | `itsdangerous` relied on transitively → cookie signing breaks on a dep change | mitigate | Pinned `itsdangerous>=2.2` explicitly (`requirements.txt:39`) | closed |
| T-26-02-03 | Elevation of Privilege | `session_version` absent → revoke-all silently no-ops | mitigate | Scaffold defaults `session_version: 0` (`firestore_db.py:217`); field-presence test | closed |
| T-26-03-01 | Spoofing | Forged/replayed GIS ID token at `/api/auth/google` | mitigate | `id_token.verify_oauth2_token` validates signature + exp + audience; `email_verified` enforced (`hub_auth.py:227-243`) | closed |
| T-26-03-02 | Elevation of Privilege | Any non-Amit verified Google account signing in | mitigate | Allowlist `hmac.compare_digest(email, HUB_ALLOWED_EMAIL)` in BOTH sign-in AND every request (`hub_auth.py:150,248`) → 403 | closed |
| T-26-03-03 | Information Disclosure | XSS in SPA reading the session cookie | mitigate | `httponly=True` (`web_server.py:930`); cookie value never logged (redacted prefix only, `hub_auth.py:118-124`) | closed |
| T-26-03-04 | Tampering | CSRF — cross-site POST to a cookie-authed `/api/*` route | mitigate | `samesite="strict"` (`web_server.py:932`); same-origin architecture (no CORS) | closed |
| T-26-03-05 | Elevation of Privilege | Stolen cookie on a lost phone (D-02) | mitigate | `session_version` counter; `/api/auth/revoke-all` bumps it; every old cookie fails version check → 401 (`hub_auth.py:141-145`, `web_server.py:982`) | closed |
| T-26-03-06 | Tampering | Forged/tampered session cookie payload | mitigate | `itsdangerous.TimestampSigner` HMAC-SHA256; tamper → `BadSignature` → 401 (`hub_auth.py:67,116-129`) | closed |
| T-26-03-07 | Denial of Service | `HUB_SESSION_SECRET` unset → fail-open signing | mitigate | Refuse-all-on-unset-env → 500 "Server misconfigured"; never signs with an empty secret (`hub_auth.py:57-66`) | closed |
| T-26-03-08 | Elevation of Privilege | New auth path weakening existing OIDC on `/cron/*`, `/internal/*` | mitigate | `require_hub_session` is a NEW dependency on `/api/*` only; `_verify_cron_request`/`_verify_healthkit_request` untouched; SPA mount stays last | closed |
| T-26-04-01 | Information Disclosure | Unauthenticated read of calendar/Garmin/meals via `/api/today` | mitigate | `Depends(require_hub_session)` (`web_server.py:1391`); `test_unauthenticated_returns_401` | closed |
| T-26-04-02 | Denial of Service | Sync tool calls blocking the single-worker event loop | mitigate | All sources via `run_in_executor` + `asyncio.gather`; per-helper try/except (`web_server.py:1425-1426`) | closed |
| T-26-04-03 | Tampering | Slot timestamps mis-presented as actual eating times (CLAUDE.md §6 invariant) | mitigate | Meals emit slot LABELS only; no `eaten_at`/`eating_time` field (`web_server.py:1139-1160`); `test_meal_slot_time_not_eating_time` | closed |
| T-26-04-04 | Denial of Service | Routes API quota exhaustion from refresh-on-focus (D-05) | mitigate | 30-min in-process TTL `_routes_cache` keyed on (event_id, departure_iso) | closed |
| T-26-04-05 | Information Disclosure | `DatetimeWithNanoseconds` 500 leaking a stack trace | mitigate | `_jsonsafe_doc` on the whole response (`web_server.py:1442`); `test_no_datetimewithnanoseconds_leak` | closed |
| T-26-05-01 | Elevation of Privilege | Unauthenticated user driving Klaus's tools via `/api/chat` | mitigate | `Depends(require_hub_session)` is the control boundary; 401 without it (`web_server.py:1520`) | closed |
| T-26-05-02 | Elevation of Privilege | Open `/internal/process-hub-message` accepting arbitrary turns | mitigate | `_verify_cron_request` OIDC gate (same SA + audience as `/internal/process-update`) (`web_server.py:1651`) | closed |
| T-26-05-03 | Denial of Service | Agent turn as Starlette BackgroundTask → CPU-throttled → 18-min replies | mitigate | Turn runs INSIDE the tracked Cloud Tasks request; no `background_tasks.add_task` on the hub path (D-09 / CLAUDE.md invariant) | closed |
| T-26-05-04 | Tampering | Malformed/oversized chat body injecting into the agent loop | mitigate | Pydantic-lite body parser — non-empty + max length (ASVS V5) (`web_server.py:1475`) | closed |
| T-26-05-05 | Tampering | Cloud Tasks retry on a stalled LLM call → duplicate replies | mitigate | Same `_DISPATCH_DEADLINE_SECONDS=540` + `LLM_TIMEOUT_SECONDS=120` as the Telegram path — no new exposure | closed |
| T-26-05-06 | Information Disclosure | `DatetimeWithNanoseconds` 500 on `/api/chat/messages` | mitigate | `_jsonsafe_doc` on the messages response (`web_server.py:1627`) | closed |
| T-26-06-01 | Elevation of Privilege | Client-side route guard treated as the security boundary | mitigate | Guard is UX only; every `/api/*` route enforces `require_hub_session` server-side; a bypassed guard still gets 401 | closed |
| T-26-06-02 | Information Disclosure | Session cookie not sent → silent unauth, or sent cross-origin | mitigate | `credentials:'include'` + same-origin (no CORS) + `SameSite=Strict`; 401 → sign-in redirect | closed |
| T-26-06-03 | Tampering | Bundling a third-party testing-library of unknown provenance | accept | `@testing-library/react` / `jest-dom` are canonical, dev-only (never shipped in the PWA bundle) | closed |
| T-26-06-04 | Information Disclosure | Stale cached shell after deploy masking a security fix | mitigate | Network-first `index.html` SW from 26-01 (HUB-03) | closed |
| T-26-07-01 | Tampering | Client re-framing meal slot times as actual eating times | mitigate | Components render server `slot_label` + macros only (`TimelineItem.tsx:10-17`); vitest asserts no eating-time phrase (TIME-03) | closed |
| T-26-07-02 | Denial of Service | refetch-on-focus storm exhausting Routes/Garmin quota (D-05) | mitigate | No timer polling in `useToday` (mount + focus only); server-side 30-min `_routes_cache` bounds upstream calls | closed |
| T-26-07-03 | Information Disclosure | 401 mid-session rendering stale private data instead of re-auth | mitigate | `apiFetch` redirects to sign-in on 401; the query errors rather than silently rendering stale data | closed |
| T-26-07-04 | Information Disclosure | D-06 placeholder vs skeleton confusion masking a failed fetch | accept | Placeholders are for known-absent data only; fetch errors surface via the query error path, not a placeholder | closed |
| T-26-08-01 | Tampering | Rendering Klaus/Telegram message content as raw HTML (stored XSS) | mitigate | Content rendered as text (React escapes by default); never `dangerouslySetInnerHTML` (`MessageBubble.tsx:129`) | closed |
| T-26-08-02 | Denial of Service | Polling continuing in the background, wasting agent turns / Routes budget | mitigate | `refetchInterval` gated on visibility; `refetchIntervalInBackground:false` (`useChat.ts:39,42`) | closed |
| T-26-08-03 | Information Disclosure | Unread badge leaking count after session expiry | mitigate | `apiFetch` 401 → sign-in redirect; badge derives from authed `/api/chat/messages` only | closed |
| T-26-08-04 | Spoofing | Optimistic "sent" state shown when the enqueue actually failed | mitigate | `onError` rolls back + marks `status:'error'`; "sent" only after the POST ACKs | closed |
| T-26-09-01 | Information Disclosure | Stale cached app shell serving an outdated/insecure UI after deploy | mitigate | Network-first `index.html` + `registerType:'autoUpdate'` (`vite.config.ts:13,22`) | closed |
| T-26-09-02 | Tampering | Offline mode masking a failed auth re-check (rendering stale private data) | accept | Offline indicator labels "showing cached data"; no offline writes (HUBX-05 deferred); reconnect re-auths via cookie | closed |
| T-26-09-03 | Spoofing | A non-iOS / already-installed user shown a misleading install prompt | mitigate | `isIOS && !isStandalone && !dismissed` gate (`InstallBanner.tsx`) | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-26-01 | T-26-01-03 | No SRI on static assets — content-hashed filenames + same-origin HTTPS (Cloud Run TLS); single-user, low-value target | Amit (plan disposition) | 2026-06-16 |
| AR-26-02 | T-26-06-03 | Bundling testing libraries of unknown provenance — `@testing-library/react` / `jest-dom` are canonical and dev-only; never shipped in the PWA bundle | Amit (plan disposition) | 2026-06-16 |
| AR-26-03 | T-26-07-04 | D-06 placeholder vs skeleton ambiguity — placeholders are for known-absent data only; genuine fetch errors surface via the query error path | Amit (plan disposition) | 2026-06-16 |
| AR-26-04 | T-26-09-02 | Offline mode shows cached private data — offline indicator labels it explicitly; no offline writes exist (HUBX-05 deferred); `/api/*` re-auths on reconnect | Amit (plan disposition) | 2026-06-16 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-16 | 41 | 41 | 0 | /gsd:secure-phase (orchestrator code-evidence verification) |

**Method:** `register_authored_at_plan_time: true` (all 9 PLAN files carried a parseable
`<threat_model>` block). Rather than rely on SUMMARY prose, each `mitigate` disposition
was confirmed against live implementation (`interfaces/hub_auth.py`,
`interfaces/web_server.py`, `core/morning_briefing.py`, `memory/firestore_db.py`,
`frontend/vite.config.ts`, `frontend/src/**`) with file:line evidence recorded above.
The 4 `accept` dispositions are logged in the Accepted Risks Log. No new threat surface
was reported in any SUMMARY beyond the planned register.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-16
