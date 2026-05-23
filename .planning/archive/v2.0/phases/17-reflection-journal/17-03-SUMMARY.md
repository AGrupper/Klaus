---
phase: 17-reflection-journal
plan: 03
subsystem: interfaces
tags: [cron, fastapi, heartbeat, self-manifest, oidc, reflection, journal]

# Dependency graph
requires:
  - phase: 17-02
    provides: core/reflection.py with run_reflection(target_date) synchronous orchestrator

provides:
  - POST /cron/reflect FastAPI route in interfaces/web_server.py (OIDC-authed, executor pattern)
  - "reflect" entry in _CRON_MAX_STALENESS_HOURS in core/heartbeat.py (26h staleness tolerance)
  - Updated core/self_manifest.py generator (Phase 17 cron row, resolved TODO, Current Limits)
  - Regenerated docs/SELF.md listing /cron/reflect (sha=e3ffa2c4)
  - test_cron_reflect_route GREEN in tests/test_reflection.py

affects:
  - 17-04-PLAN (digest injection and get_self_status depend on /cron/reflect existing)
  - Production deployment (Cloud Scheduler job creation documented below)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Executor pattern: loop.run_in_executor(None, _reflection.run_reflection, today) — synchronous blocking work off the event loop"
    - "Lazy import pattern: import core.reflection as _reflection inside async route body (matches cron_ingest_chats)"
    - "OIDC-first pattern: _verify_cron_request(request) called BEFORE any work in all cron routes"
    - "Test isolation: patch('core.reflection.run_reflection') on cached module object + patch.dict(sys.modules) for web_server stubs with automatic restoration"

key-files:
  created:
    - .planning/phases/17-reflection-journal/17-03-SUMMARY.md
  modified:
    - interfaces/web_server.py
    - core/heartbeat.py
    - core/self_manifest.py
    - docs/SELF.md
    - tests/test_reflection.py

key-decisions:
  - "Patch run_reflection on the cached module object (patch('core.reflection.run_reflection')) rather than sys.modules injection — the route's lazy import gets the cached module, so attribute-patching is the correct interception point"
  - "Use patch.dict(sys.modules) for web_server dependency stubs so they restore after the test block, preventing leakage to test_heartbeat.py in the same process"
  - "gcloud command documented in plan + SUMMARY rather than docs/SELF.md (SELF.md is generated — any direct edit is reverted on regen)"

# Metrics
duration: ~17min
completed: 2026-05-19
---

# Phase 17 Plan 03: Production Cron Wiring Summary

**POST /cron/reflect route (OIDC-authed, executor pattern) wired into interfaces/web_server.py; "reflect" job registered in heartbeat staleness monitor; core/self_manifest.py updated for Phase 17 and docs/SELF.md regenerated**

## Performance

- **Duration:** ~17 min
- **Started:** 2026-05-19T12:17:18Z
- **Completed:** 2026-05-19T12:33:46Z
- **Tasks:** 3
- **Files modified:** 5 (1 created)

## Accomplishments

- **Task 1 (TDD):** `POST /cron/reflect` route added to `interfaces/web_server.py`:
  - `_verify_cron_request(request)` called first (OIDC; honors `CRON_DEV_BYPASS`)
  - Lazy `import core.reflection as _reflection` inside route body (matches `cron_ingest_chats` pattern)
  - `run_reflection` dispatched via `loop.run_in_executor(None, _reflection.run_reflection, today)` — blocking work off the event loop
  - `try/except` with `_log_cron_run("reflect", ok=True/False)` on success/exception
  - Returns `JSONResponse({"ok": True})`
  - `test_cron_reflect_route` implemented and GREEN: asserts 200, body, `run_reflection` called once with date arg, `_log_cron_run("reflect", ok=True)` called

- **Task 2:** `"reflect": 26` added to `_CRON_MAX_STALENESS_HOURS` in `core/heartbeat.py` — heartbeat now flags a stalled reflect cron as stale after 26 hours

- **Task 3:** `core/self_manifest.py` generator updated for Phase 17:
  - §4 Cron Jobs: new row `| Daily reflection | 0 22 * * * (22:00 IDT) | /cron/reflect |`
  - §4 TODO comment: Phase 17 marker resolved, only Phase 18 remains
  - §7 Current Limits: Pinecone `kind` list updated to include `self` (Phase 17 ships it)
  - §7 Current Limits: "Reflection and journal: not yet implemented" line removed
  - `docs/SELF.md` regenerated (`sha=e3ffa2c4`); `/cron/reflect` appears in the committed manifest

## Task Commits

Each task committed atomically:

| Task | Type | Hash | Description |
|------|------|------|-------------|
| Task 1 RED | test | `cead4be` | Failing test for /cron/reflect route |
| Task 1 GREEN route | feat | `2e9c281` | Add POST /cron/reflect to web_server.py |
| Task 1 GREEN test | feat | `cbc6c5d` | Implement test_cron_reflect_route GREEN |
| Task 2 | feat | `e52d486` | Register "reflect" in _CRON_MAX_STALENESS_HOURS |
| Task 3 | feat | `fcfcea1` | Update self_manifest.py + regen docs/SELF.md |

## Files Created/Modified

- `interfaces/web_server.py` — 24 lines added; `cron_reflect` route placed after `cron_proactive_alerts`
- `core/heartbeat.py` — 1 line added: `"reflect": 26` entry in `_CRON_MAX_STALENESS_HOURS`
- `core/self_manifest.py` — 3 edits: new cron row, resolved TODO comment, updated Current Limits (removes 2 stale lines, updates Pinecone kinds)
- `docs/SELF.md` — regenerated: cron table has Daily reflection row; `sha=e3ffa2c4`
- `tests/test_reflection.py` — `test_cron_reflect_route` stub replaced with 70-line real test

## Decisions Made

- **Attribute-patch instead of sys.modules injection:** The route's lazy `import core.reflection as _reflection` retrieves the already-cached real module object from `sys.modules`. Setting `sys.modules["core.reflection"]` to a stub works if done before any import, but fails when the module is already cached. `patch("core.reflection.run_reflection")` replaces the attribute on the cached object — this is the correct interception point regardless of import order.

- **patch.dict(sys.modules) for web_server stubs:** `core.auth_google`, `core.main`, and `interfaces._router` are stubbed using `patch.dict(sys.modules, ...)` so they are automatically restored after the test block. This prevents stub leakage to `test_heartbeat.py` (which imports real `google.auth`).

- **gcloud command in plan + SUMMARY only (not SELF.md):** `docs/SELF.md` is generated — a direct edit is reverted on the next regen. The command is preserved in the plan's `<interfaces>` block and copied verbatim below.

## Cloud Scheduler Job Creation Command (D-11)

```bash
gcloud scheduler jobs create http reflect \
  --schedule="0 22 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="${CLOUD_RUN_URL}/cron/reflect" \
  --http-method=POST \
  --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
  --oidc-token-audience="${CLOUD_RUN_URL}" \
  --location="${SCHEDULER_LOCATION}"
```

This command is discoverable here until `DEPLOYMENT.md` is created in Phase 18.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test isolation: sys.modules stubs must be restored after test**
- **Found during:** Task 1 GREEN test implementation
- **Issue:** Setting `sys.modules["core.auth_google"] = MagicMock()` without restoration caused `test_cron_heartbeat_rejects_unauthenticated` to fail when run in the same process after `test_reflection.py` (the poisoned stub replaced real `google.auth` for heartbeat's OIDC verification import).
- **Fix:** Wrapped all `sys.modules` stubs in `patch.dict(sys.modules, stubs_without_ws)` so they are automatically restored after the test block.
- **Files modified:** `tests/test_reflection.py`
- **Commit:** `cbc6c5d`

**2. [Rule 1 - Bug] Test must patch module attribute, not sys.modules, for cached module**
- **Found during:** Task 1 GREEN test implementation (test passed in isolation but failed when run after other tests in the file)
- **Issue:** Earlier tests import `core.reflection` (caching the real module object). Setting `sys.modules["core.reflection"] = stub` does not affect the route's `import core.reflection as _reflection` because Python returns the **cached object** — the stub only intercepts fresh (uncached) imports. Result: `run_reflection_mock.assert_called_once()` failed because the real `run_reflection` ran instead.
- **Fix:** Used `patch("core.reflection.run_reflection", run_reflection_mock)` which replaces the attribute on the already-cached real module object, intercepting the call regardless of which object `_reflection` points to.
- **Files modified:** `tests/test_reflection.py`
- **Commit:** `cbc6c5d`

## Known Stubs

- `test_journal_digest_assembly` — remains skipped; implemented in 17-04 (digest injection plan)

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: unauthenticated-cron | interfaces/web_server.py | New `/cron/reflect` route at internet→route boundary |

Mitigation in place: `await _verify_cron_request(request)` is the first statement in `cron_reflect` — OIDC token + audience + SA-email check runs before any reflection work (T-17-07 mitigated). `CRON_DEV_BYPASS` defaults to `"false"` (T-17-08 mitigated). `run_in_executor` prevents event loop stalling (T-17-09 mitigated).

## Self-Check: PASSED

- FOUND: interfaces/web_server.py — contains `/cron/reflect` at line 334
- FOUND: core/heartbeat.py — contains `"reflect": 26` at line 113
- FOUND: core/self_manifest.py — contains `/cron/reflect` (1 match), 0 TODO Phase 17 matches
- FOUND: docs/SELF.md — contains `/cron/reflect` at line 72 (Daily reflection row)
- FOUND: tests/test_reflection.py — `test_cron_reflect_route` implemented and GREEN
- FOUND: commit `cead4be` (RED test)
- FOUND: commit `2e9c281` (route implementation)
- FOUND: commit `e52d486` (heartbeat entry)
- FOUND: commit `cbc6c5d` (GREEN test)
- FOUND: commit `fcfcea1` (self_manifest + SELF.md)
- No unexpected file deletions

---
*Phase: 17-reflection-journal*
*Completed: 2026-05-19*
