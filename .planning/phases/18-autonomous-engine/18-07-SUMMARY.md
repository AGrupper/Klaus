---
phase: 18-autonomous-engine
plan: 07
subsystem: cron-routing
tags: [cron, autonomous, heartbeat, staleness, oidc, fastapi, cloud-scheduler]

# Dependency graph
requires:
  - phase: 18-autonomous-engine/06
    provides: core.autonomous.run_autonomous_tick(bot, now) — the async entry point the new route awaits
provides:
  - POST /cron/autonomous-tick — Cloud Scheduler entry point for the Phase 18 autonomous tick (interfaces/web_server.py:363)
  - _CRON_MAX_STALENESS_HOURS['autonomous-tick'] = 1 — heartbeat staleness alarm registered (core/heartbeat.py:114)
affects:
  - 18-09 (deployment-docs): the new route + heartbeat entry must appear in docs/DEPLOYMENT.md's 9-cron table and the gcloud scheduler create snippet
  - heartbeat liveness ledger: check_cron_health() will now emit a SEVERITY_CRITICAL signal if the autonomous-tick ledger doc is missing or > 1h stale

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Verbatim cron route template — copy cron_reflect shape, change three points (path, schedule docstring, call target) plus _application guard from cron_proactive_alerts; preserves _verify_cron_request → guard → try/_log_cron_run(ok=True) → except/_log_cron_run(ok=False)/raise sequence so all 8 cron handlers stay structurally identical"
    - "Staleness threshold scales to cron interval — */20 schedule uses 1h threshold (3 missed ticks); daily schedules use 26h. Per RESEARCH Pitfall 5: tolerance must be > 1 fire interval but tight enough to alert before user notices silence"
    - "Deferred import inside cron handler (`import core.autonomous as _auto` inside the try-block) — keeps /health cold-start fast by not loading the heavy tick-brain + orchestrator graph at web_server import time. Mirrors the existing pattern for core.reflection, core.proactive_alerts, core.five_fingers, core.morning_briefing"
    - "TestClient stub-pattern for cron-route tests — patch.dict(sys.modules, {telegram, core.auth_google, core.main, interfaces._router: MagicMock()}) scoped to the test's `with` block, then delete interfaces.web_server so the fresh import sees the stubs. Prevents stub leakage to adjacent test files (lesson learned in 17-01 test_cron_reflect_route)"

key-files:
  created:
    - tests/test_web_server.py (218 lines) — Phase 18 test scaffold; currently 5 tests in TestCronAutonomousTick covering the full happy-path + 401 + 500 + ledger-write contract
    - .planning/phases/18-autonomous-engine/18-07-SUMMARY.md (this file)
  modified:
    - interfaces/web_server.py — new POST /cron/autonomous-tick handler inserted at line 363 between cron_reflect (line 339) and cron_five_fingers_evening (line 405). +40 lines.
    - core/heartbeat.py — _CRON_MAX_STALENESS_HOURS gained the 'autonomous-tick': 1 entry at line 114, immediately after the Phase 17 reflect entry. +1 line; the comment on the preceding 'reflect' line was retitled from "NEW" to "Phase 17" for chronological clarity.
    - tests/test_heartbeat.py — 2 new tests at lines 188-222: test_autonomous_tick_staleness_threshold_is_one_hour (the targeted entry-presence + value assertion) and test_all_cron_jobs_have_staleness_entry (sanity guard over the full dict).

key-decisions:
  - "Threshold = 1 (one hour, integer) — chosen over 1.0 float and over 2h. One hour = 3 missed 20-minute ticks, a clear pattern (not a single flake). The current dict mixes types implicitly; Python's `==` handles `1 == 1.0` either way, but using int matches the existing entries' style"
  - "Route lives between cron_reflect and cron_five_fingers_evening, not at end of file — preserves the file's loose chronological ordering by phase (Phase 17 reflect is just above; Phase 18 autonomous-tick fits naturally before the older five-fingers-evening). Also keeps the two Phase 18 follow-on plans (08, 09) from needing to re-order"
  - "Deferred `import core.autonomous as _auto` inside the handler, not at module top — explicit choice over a top-level import. Saves ~200ms on /health cold start since core.autonomous transitively imports tick_brain, llm_client, telegram-bot internals, and the prompt files. Pattern is consistent with every other cron handler in this file"
  - "Re-raise after _log_cron_run(ok=False) — Cloud Run must see the 500 for its retry / consecutive_failures metric to tick correctly. A silent return-200-with-failure would hide outages from both the heartbeat ledger streak and Cloud Monitoring 5xx counts (which are what check_degradation reads). Mirrors cron_reflect, cron_proactive_alerts, cron_morning_briefing_tick exactly"
  - "Test patches `core.autonomous.run_autonomous_tick` (the module attribute), not `interfaces.web_server._auto.run_autonomous_tick` — the route does `import core.autonomous as _auto` then `await _auto.run_autonomous_tick(...)`, which resolves through the module dict each call, so attribute-on-the-source-module is the right patch site. Verified by all 5 tests passing without monkeypatching the local `_auto` alias"

requirements-completed: [AUTO-06]

# Metrics
duration: ~10min
completed: 2026-05-23
---

# Phase 18 Plan 07: Cron Route + Heartbeat Staleness Summary

**Wires Klaus's autonomous tick into Cloud Run by adding the POST /cron/autonomous-tick OIDC-protected route that awaits core.autonomous.run_autonomous_tick, plus registers the 'autonomous-tick' job-id with a 1-hour staleness threshold (3 missed ticks) in core/heartbeat.py so check_cron_health() will alert on silence — AUTO-06 complete.**

## Performance

- **Duration:** ~10 min (RED ~3 min, GREEN ~2 min, regression sweep + SUMMARY ~5 min)
- **Completed:** 2026-05-23
- **Tasks:** 1 (a single TDD task in the plan, executed as RED → GREEN with no REFACTOR needed)
- **Commits:** 2 atomic
  - `6d51fd7 test(18-07): add failing tests for /cron/autonomous-tick + heartbeat staleness`
  - `078263b feat(18-07): add /cron/autonomous-tick route + heartbeat staleness entry`

## Insertion Points

| File | Line | What |
|------|-----:|------|
| `interfaces/web_server.py` | 363 | `@app.post("/cron/autonomous-tick")` decorator |
| `interfaces/web_server.py` | 364 | `async def cron_autonomous_tick(request: Request)` |
| `interfaces/web_server.py` | 396 | `_log_cron_run("autonomous-tick", ok=True)` |
| `interfaces/web_server.py` | 398 | `_log_cron_run("autonomous-tick", ok=False)` |
| `core/heartbeat.py` | 114 | `"autonomous-tick": 1,         # Phase 18 — */20 cron; 1h = 3 missed ticks` |

## Test Suite — 7/7 Passing

```
tests/test_web_server.py::TestCronAutonomousTick::test_returns_200_with_dev_bypass_and_app_present PASSED
tests/test_web_server.py::TestCronAutonomousTick::test_returns_401_without_bearer PASSED
tests/test_web_server.py::TestCronAutonomousTick::test_returns_500_when_application_is_none PASSED
tests/test_web_server.py::TestCronAutonomousTick::test_logs_cron_run_ok_true_on_success PASSED
tests/test_web_server.py::TestCronAutonomousTick::test_logs_cron_run_ok_false_on_exception PASSED
tests/test_heartbeat.py::test_autonomous_tick_staleness_threshold_is_one_hour PASSED
tests/test_heartbeat.py::test_all_cron_jobs_have_staleness_entry PASSED
```

### Adjacent suites — full regression (135/135 passing)

```
tests/test_autonomous.py           31 passed
tests/test_main_render_smart_system.py  8 passed
tests/test_tick_brain.py           27 passed
tests/test_firestore_db.py         21 passed
tests/test_prompts.py              11 passed
tests/test_evals.py                37 passed
```

### web_server + heartbeat (22/22 passing)

The 5 new TestCronAutonomousTick tests join the 17 existing heartbeat tests with no regressions; `test_cron_heartbeat_rejects_unauthenticated` continues to demonstrate the OIDC 401 path on a separate cron handler.

## Verification Gate Results

| Check | Required | Actual |
|---|---|---|
| `grep -c '@app.post."/cron/autonomous-tick"' interfaces/web_server.py` | ≥1 | 1 |
| `grep -c 'cron_autonomous_tick' interfaces/web_server.py` | ≥1 | 1 |
| `grep -c "_log_cron_run.*autonomous-tick" interfaces/web_server.py` | ≥2 | 3 (2 calls + 1 docstring mention) |
| `grep -c "autonomous-tick" core/heartbeat.py` | ≥1 | 1 |
| `python -c "from core.heartbeat import _CRON_MAX_STALENESS_HOURS; assert _CRON_MAX_STALENESS_HOURS.get('autonomous-tick') == 1"` | OK | OK |
| `grep -E "autonomous-tick" interfaces/web_server.py core/heartbeat.py \| wc -l` | ≥4 | 5 |

All plan-spec'd verification gates exceed the required threshold.

## TDD Gate Compliance

Plan task carries `tdd="true"`. Gate sequence respected:

1. **RED (commit 6d51fd7):** 7 tests written against routes/dict entries that did not yet exist; full pytest run confirmed `7 failed` before any production code change.
2. **GREEN (commit 078263b):** Production code added (route + staleness entry); same 7 tests now pass; regression suite stays green.
3. **REFACTOR:** Skipped — the route is a verbatim copy of the cron_reflect template with the three specified replacements (path, docstring, call target), and the heartbeat entry is a single dict line. No cleanup opportunity exists.

## Deviations from Plan

None — the plan executed exactly as written.

The only minor judgment call was retitling the comment on the existing `'reflect': 26` line from `NEW — daily reflect cron, 26h tolerance` (a stale Phase-17-era comment) to `Phase 17 — daily reflect cron, 26h tolerance` so the new `Phase 18 — */20 cron` comment on the autonomous-tick line below has a parallel phase prefix. This is a documentation-only adjustment with no behavioral change; it was applied within the same Edit op for the GREEN commit rather than as a separate refactor.

## Threat Flags

None — this plan only exposes a new POST endpoint that is OIDC-protected via the existing `_verify_cron_request` helper (audience-checked OIDC bearer token, service-account email allow-list), and a single key in a server-internal heartbeat dict. No new auth path, no new file access, no new schema. Cloud Scheduler will be the sole authorized caller in production; CRON_DEV_BYPASS=true is documented and limited to local dev.

## Known Stubs

None — both the route handler and the heartbeat dict entry are fully wired:

- The route imports `core.autonomous` lazily and awaits the real `run_autonomous_tick` coroutine; tests substitute a mock at the module-attribute level, but production resolves through `sys.modules` to the real implementation shipped in Plan 06.
- The heartbeat dict entry is consumed verbatim by the existing `check_cron_health()` loop (`for job_id, max_hours in _CRON_MAX_STALENESS_HOURS.items():` at core/heartbeat.py:145); no further wiring needed.

## Cloud Scheduler Job Creation (Deferred to Plan 09)

The production rollout still requires:

```bash
gcloud scheduler jobs create http klaus-autonomous-tick \
  --schedule="*/20 7-21 * * *" \
  --time-zone="Asia/Jerusalem" \
  --uri="${CLOUD_RUN_URL}/cron/autonomous-tick" \
  --http-method=POST \
  --oidc-service-account-email="${CLOUD_SCHEDULER_SA_EMAIL}" \
  --oidc-token-audience="${CLOUD_RUN_URL}"
```

This belongs in Plan 18-09's `docs/DEPLOYMENT.md` 9-cron table along with the Five Fingers duplicate job-id quirk (INFRA-01).

## Self-Check: PASSED

- `[ -f interfaces/web_server.py ]` → FOUND (route at line 363)
- `[ -f core/heartbeat.py ]` → FOUND (dict entry at line 114)
- `[ -f tests/test_web_server.py ]` → FOUND
- `[ -f tests/test_heartbeat.py ]` → FOUND (extended)
- `git log --oneline | grep 6d51fd7` → FOUND (RED commit)
- `git log --oneline | grep 078263b` → FOUND (GREEN commit)
