---
phase: 26-hub-shell
plan: 01
subsystem: infra
tags: [vite, react, typescript, tailwind, vite-plugin-pwa, fastapi, docker, staticfiles]

requires: []
provides:
  - Vite + React 19 + TS + Tailwind v4 + vite-plugin-pwa frontend project building to frontend/dist
  - dark-theme design tokens (frontend/src/tokens.ts) — single source of truth for downstream frontend plans
  - multi-stage Dockerfile (Node build stage → python:3.11-slim runtime, --workers 1 preserved)
  - SPAStaticFiles catch-all mounted last in web_server.py without shadowing /api/*, /cron/*, /telegram-webhook, /health (HUB-04)
  - service-worker caching contract: network-first index.html, cache-first hashed assets (HUB-03 foundation)
affects: [26-06, 26-07, 26-08, 26-09]

tech-stack:
  added: [react@19, vite@8, typescript@6, tailwindcss@4, "@tailwindcss/vite", "@vitejs/plugin-react", vite-plugin-pwa@1.3, "@tanstack/react-query@5", zustand@5, react-router-dom@7, lucide-react, clsx, vitest]
  patterns: [SPAStaticFiles lookup_path index.html fallback, multi-stage Node→Python Docker build, end-of-file mount-last route discipline]

key-files:
  created:
    - frontend/package.json
    - frontend/vite.config.ts
    - frontend/src/tokens.ts
    - frontend/src/App.tsx
    - frontend/src/main.tsx
    - frontend/public/manifest.json
    - frontend/vitest.config.ts
  modified:
    - Dockerfile
    - .dockerignore
    - interfaces/web_server.py
    - tests/test_web_server.py

key-decisions:
  - "Package legitimacy gate (Task 1) approved by the user before any install — all 14 npm/PyPI packages verified canonical."
  - "SPAStaticFiles overrides lookup_path (not get_response) to fall back to index.html for client-side routes — avoids constructing/discarding a 404 in the hot path."
  - "SPA mount guarded by os.path.isdir(frontend/dist) so local dev without a build starts cleanly; logs a warning when absent."
  - "Added frontend/node_modules + frontend/dist to .dockerignore so stage-2 COPY . . never bloats the Python image (dist arrives fresh from the builder stage)."

patterns-established:
  - "Mount-last discipline: app.mount('/', SPAStaticFiles) is the absolute last route registration; no @app.* or include_router may follow it."
  - "Portable SPA-shadow regression test: create a temp frontend/dist/index.html so the catch-all activates even where dist is gitignored (CI)."

requirements-completed: [HUB-03, HUB-04]

duration: ~7min
completed: 2026-06-15
---

# Phase 26 Plan 01: Frontend Toolchain & SPA Serve Summary

**Stood up the greenfield Vite + React + Tailwind v4 + PWA frontend, a multi-stage Dockerfile, and a mount-last SPAStaticFiles catch-all that serves the SPA without shadowing any existing FastAPI route.**

## Performance

- **Duration:** ~7 min (executor truncated by session limit after Task 2 + uncommitted web_server.py edit; orchestrator completed Task 3 inline)
- **Completed:** 2026-06-15
- **Tasks:** 3
- **Files modified:** 24 (20 created in Task 2 + Dockerfile/.dockerignore/web_server.py/test in Task 3)

## Accomplishments
- Greenfield `frontend/` project builds to `frontend/dist` with a vite-plugin-pwa service worker (network-first `index.html`, cache-first `/assets/`) — HUB-03 foundation.
- `frontend/src/tokens.ts` holds the locked dark-theme palette (accent `#6366F1`, etc.) — single source of truth for downstream frontend plans.
- Multi-stage `Dockerfile`: `node:20-slim` builder runs `npm ci` + `npm run build`, then `COPY --from=frontend-builder /frontend/dist` into the unchanged `python:3.11-slim` image with `--workers 1` preserved.
- `SPAStaticFiles(StaticFiles)` with a `lookup_path` index.html fallback, mounted at `/` as the absolute last route — proven not to shadow `/health` by `test_health_still_works` (HUB-04 / threat T-26-01-01).

## Task Commits

1. **Task 1: Package legitimacy gate** — approved by the user (blocking-human checkpoint, never auto-advanced); no code commit.
2. **Task 2: Scaffold Vite + React + TS + Tailwind v4 + PWA** — `cbf977f` (feat)
3. **Task 3: Multi-stage Dockerfile + SPA mount + regression test** — `40967ca` (feat)

## Files Created/Modified
- `frontend/` — full Vite/React/TS/Tailwind v4/PWA scaffold (package.json, vite.config.ts with VitePWA, tokens.ts, App.tsx, manifest.json, vitest.config.ts, placeholder icons).
- `Dockerfile` — prepended `frontend-builder` Node stage; `COPY --from` dist before CMD; stage 2 otherwise identical.
- `.dockerignore` — excluded `frontend/node_modules` + `frontend/dist`.
- `interfaces/web_server.py` — `SPAStaticFiles` subclass + guarded `app.mount("/")` as the last statement.
- `tests/test_web_server.py` — `TestSPAMountRegression::test_health_still_works`.

## Decisions Made
See key-decisions in frontmatter.

## Deviations from Plan

### Execution-recovery deviation (not a scope change)

**1. Executor truncated by session limit after Task 2**
- **Found during:** Wave 0 parallel execution — the background executor committed Task 2 (scaffold) and made the `interfaces/web_server.py` SPA-mount edit but was cut off by the Anthropic session limit before committing Task 3 (the edit sat uncommitted; Dockerfile + test were not yet touched).
- **Fix:** The orchestrator completed Task 3 inline in the same worktree — wrote the multi-stage Dockerfile, added the two `.dockerignore` excludes, committed the already-correct uncommitted `web_server.py` SPA mount, and appended the `test_health_still_works` regression test.
- **Verification:** `pytest tests/test_web_server.py` all pass incl. the new SPA test; `grep` confirms `frontend-builder`, `COPY --from`, exactly one `--workers 1`; SPA mount is the last route; `npm run build` produced dist + SW; `npm test` 14/14 green.
- **Impact:** No scope change — Task 3 delivered exactly as specified.

### Minor scope addition (justified)

**2. .dockerignore: exclude frontend/node_modules + frontend/dist**
- Not in the plan's file list, but required hygiene: without it, stage-2 `COPY . .` would pull a local `frontend/node_modules` into the runtime image and risk overlaying a stale local `dist`. The runtime dist arrives fresh from the builder stage.

**Total deviations:** 1 execution-recovery + 1 justified hygiene addition. No design/scope drift.

## Issues Encountered
None beyond the session-limit truncation handled above.

## User Setup Required
None for this plan. (Note: placeholder 69-byte PNG icons are used; final icon art is a cosmetic follow-up.)

## Next Phase Readiness
Wave 1+ frontend plans (26-06 shell, 26-07 timeline, 26-08 chat, 26-09 PWA polish) inherit the toolchain, the `@/` alias, the tokens palette, and the SPA serve. The backend SPA mount is live and regression-guarded.

## Self-Check: PASSED

---
*Phase: 26-hub-shell*
*Completed: 2026-06-15*
