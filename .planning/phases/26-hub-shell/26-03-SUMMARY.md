---
phase: "26-hub-shell"
plan: "03"
subsystem: "hub-auth"
tags: ["auth", "session-cookie", "gis", "itsdangerous", "fastapi", "react", "zustand"]
dependency_graph:
  requires: ["26-02"]
  provides: ["hub-auth-boundary", "require_hub_session", "api-auth-routes", "sign-in-page"]
  affects: ["interfaces/web_server.py", "interfaces/hub_auth.py", "frontend/src/"]
tech_stack:
  added:
    - "itsdangerous>=2.2 (HMAC-SHA256 TimestampSigner)"
    - "zustand 5.0.14 (auth store)"
  patterns:
    - "FastAPI Depends() dependency injection for session auth"
    - "itsdangerous.TimestampSigner with digest_method=hashlib.sha256"
    - "CRON_DEV_BYPASS bypass pattern (Shared Pattern 8)"
    - "refuse-all-on-unset-env (Shared Pattern 7)"
    - "hmac.compare_digest for all comparisons (Shared Pattern 3)"
    - "credentials:include on all apiFetch calls (RESEARCH Pitfall 5)"
key_files:
  created:
    - "interfaces/hub_auth.py"
    - "frontend/src/api/client.ts"
    - "frontend/src/api/auth.ts"
    - "frontend/src/store/auth.ts"
    - "frontend/src/store/auth.test.ts"
    - "frontend/src/components/auth/SignInPage.tsx"
  modified:
    - "interfaces/web_server.py (added /api/auth/* routes + Response/Depends imports)"
    - "tests/test_hub_auth.py (flipped 4 skip stubs to real assertions)"
decisions:
  - "Removed load_dotenv from hub_auth.py — web_server owns dotenv; avoids .env override silently re-setting CRON_DEV_BYPASS=true in tests, which broke test_no_cookie_401"
  - "_get_signer() is lazy (called at auth time, not module import) so /healthz cold-starts don't fail when HUB_SESSION_SECRET is absent"
  - "Session cookie name constant _COOKIE_NAME='hub_session' exported for use in web_server.py set_cookie call"
  - "D-01 refresh-on-visit: 365-day max_age is sufficient for v5.0; re-issuing the cookie on each visit to slide the window is a future enhancement"
metrics:
  completed_at: "2026-06-15T10:40:00Z"
  task_count: 3
  file_count: 8
requirements_satisfied: ["HUB-01"]
---

# Phase 26 Plan 03: Hub Auth (GIS verify + signed session cookie + require_hub_session) Summary

HMAC-SHA256-signed httpOnly session cookie with Google Sign-In verification, a bumpable session_version revocation counter (D-02), and a FastAPI `require_hub_session` dependency protecting `/api/*` routes.

## What Was Built

### Task 1: `interfaces/hub_auth.py` (commit 6da0709)

New module implementing the complete hub auth boundary:

- `create_session_cookie(email, session_version)` — signs `"email:session_version"` using `itsdangerous.TimestampSigner` with `digest_method=hashlib.sha256` (ASVS V6).
- `verify_session_cookie(cookie_value, current_version)` — unsigns with `max_age=365d`, splits on last `:` via `rsplit(":", 1)`, raises 401 on `BadSignature`/`SignatureExpired`/version mismatch, 403 on allowlist miss, 500 on unset secret. Cookie value is never logged in full (redacted prefix).
- `get_session_version()` — reads `UserProfileStore.session_version` (defaults to 0 if absent).
- `verify_google_id_token(token)` — calls `google.oauth2.id_token.verify_oauth2_token`, rejects `email_verified=false`, rejects non-allowlist email.
- `require_hub_session(request)` — FastAPI `async def` dependency; honors `CRON_DEV_BYPASS=true`; reads `hub_session` cookie; delegates to `verify_session_cookie`.
- All STRIDE mitigations from the threat model applied (T-26-03-01 through T-26-03-08).

### Task 2: `/api/auth/*` routes in `web_server.py` (commit d194890)

Four new routes added BEFORE the `SPAStaticFiles` mount (Pitfall 1 prevention, verified by line number):

- `POST /api/auth/google` — reads `{"credential": str}`, calls `verify_google_id_token`, sets cookie: `httponly=True, secure=True, samesite="strict", max_age=365*86400, path="/"`.
- `POST /api/auth/logout` — single-device sign-out; deletes `hub_session` cookie. Does NOT bump `session_version`.
- `POST /api/auth/revoke-all` — gated by `require_hub_session`; bumps `session_version` via `run_in_executor`; deletes cookie. Every existing cookie on every device now returns 401 (D-02).
- `GET /api/auth/me` — gated by `require_hub_session`; returns `{"email": email}` for frontend session-validity check on load.

Added `Response` and `Depends` to top-level fastapi imports.

### Task 3: Tests + frontend auth (commit ee43dba)

**Backend tests (`tests/test_hub_auth.py`):** Removed all four `@pytest.mark.skip` markers. Implemented real assertions:
- `test_valid_gis_token_issues_cookie` — round-trip `create_session_cookie` → `verify_session_cookie` returns email.
- `test_allowlist_rejects_other_email` — non-allowlisted email in cookie → `HTTPException(403, {"error": "Forbidden"})`.
- `test_no_cookie_401` — `require_hub_session` with no cookie → `HTTPException(401, {"error": "Not authenticated"})`.
- `test_revoked_session` — cookie signed at version 0, verified against version 1 → `HTTPException(401, {"error": "Session revoked"})`.

**Frontend:**
- `frontend/src/api/client.ts` — shared `apiFetch` wrapper with `credentials: 'include'`.
- `frontend/src/api/auth.ts` — `signInWithGoogle`, `logout`, `revokeAll`, `fetchMe` calling the four `/api/auth/*` routes.
- `frontend/src/store/auth.ts` — zustand store `{ email, signedIn, setSignedIn, signOut }`.
- `frontend/src/store/auth.test.ts` — vitest spec (3 tests: initial state, setSignedIn, signOut).
- `frontend/src/components/auth/SignInPage.tsx` — full-screen `#0A0A0A`, "Klaus" at Display (28px/600/`#F9FAFB`), "Your personal agent" at Body (`#9CA3AF`), GIS script load + button render via `google.accounts.id.initialize`, async `signInWithGoogle` → `setSignedIn`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed `load_dotenv(override=True)` from `hub_auth.py`**
- **Found during:** Task 3 — `test_no_cookie_401` was not raising because `CRON_DEV_BYPASS` was being reset to `"true"` by the `.env` file every time `hub_auth` was imported (since `load_dotenv(override=True)` runs at module import time).
- **Issue:** `hub_auth.py` called `load_dotenv(override=True)` at module level. The `.env` file has `CRON_DEV_BYPASS=true`. When the test used `monkeypatch.setenv("CRON_DEV_BYPASS", "false")` and then forced a re-import, the re-import ran `load_dotenv(override=True)` again, re-setting `CRON_DEV_BYPASS=true` from `.env`. This silently bypassed the `require_hub_session` auth check.
- **Fix:** Removed `load_dotenv` from `hub_auth.py`. `web_server.py` already calls `load_dotenv(override=True)` at line 45 at process startup — `hub_auth` is always imported from `web_server` and doesn't need its own dotenv init. Tests set env vars via `monkeypatch.setenv` before import.
- **Files modified:** `interfaces/hub_auth.py`
- **Commit:** ee43dba

## Known Stubs

None — all routes are wired to real implementations. The GIS button in `SignInPage.tsx` requires `VITE_GOOGLE_CLIENT_ID` at build time; the button renders empty if the env var is absent (the GIS SDK handles graceful degradation).

## Threat Flags

No new threat surface beyond what was already modeled in the plan's `<threat_model>`. All STRIDE entries (T-26-03-01 through T-26-03-08) are implemented and verified.

## Note: D-01 Refresh-on-Visit

The plan notes that `require_hub_session` could re-issue the cookie on each valid request to slide the 365-day window. This is not implemented — for v5.0 the 365-day `max_age` is sufficient and re-issuing on every request adds unnecessary cookie write overhead. If sliding-window refresh is desired in a future phase, add it to `require_hub_session` by calling `response.set_cookie(...)` on the FastAPI `Response` object.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| interfaces/hub_auth.py | FOUND |
| tests/test_hub_auth.py | FOUND (4 tests passing, 0 skipped) |
| interfaces/web_server.py | MODIFIED (4 auth routes before SPA mount) |
| frontend/src/api/client.ts | FOUND |
| frontend/src/api/auth.ts | FOUND |
| frontend/src/store/auth.ts | FOUND |
| frontend/src/store/auth.test.ts | FOUND (3 tests passing) |
| frontend/src/components/auth/SignInPage.tsx | FOUND |
| .planning/phases/26-hub-shell/26-03-SUMMARY.md | FOUND |
| Commit 6da0709 (hub_auth.py) | VERIFIED |
| Commit d194890 (web_server routes) | VERIFIED |
| Commit ee43dba (tests + frontend) | VERIFIED |
