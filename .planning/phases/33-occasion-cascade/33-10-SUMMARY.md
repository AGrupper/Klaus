---
phase: 33-occasion-cascade
plan: 10
subsystem: infra
tags: [cloud-tasks, dispatch, fastapi, trigger-routes, cron, background-task-fix]

# Dependency graph
requires:
  - phase: 33-occasion-cascade
    provides: "33-06 core.nightly_review.run_nightly(bot, target_date, *, trigger, dedup) — dispatch target; 33-07 core.morning_briefing.run_morning_briefing_triggered(bot, today_iso, *, trigger, dedup) — dispatch target; 33-08 core.weekly_training_review.run_weekly_review(bot, today_iso) — dispatch target"
provides:
  - "core/task_dispatch.py::enqueue_occasion(occasion, *, trigger, target_date=None) -> bool — Cloud Tasks dispatch for occasion composes, never raises"
  - "interfaces/web_server.py::POST /internal/process-occasion — single OIDC-gated Cloud Tasks target dispatching nightly/morning/weekly_review by literal occasion value"
  - "interfaces/web_server.py::POST /trigger/morning — dedicated MORNING_TRIGGER_TOKEN push trigger, ships dark (D-31)"
  - "interfaces/web_server.py::_verify_morning_trigger_request — least-privilege auth mirror of _verify_trigger_request"
  - "interfaces/web_server.py::/trigger/nightly, /cron/nightly-backstop, /cron/weekly-training-review — all rewired onto the enqueue-then-202/503 dispatch path (D-32 fix)"
affects: [33-11, 33-12, 33-13, 35]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "enqueue_occasion mirrors enqueue_hub_message byte-for-byte (same queue/OIDC/dispatch-deadline construction), targeting /internal/process-occasion with a {occasion, trigger, target_date?} JSON body instead of {content, user_id}."
    - "Route-side dispatch: every occasion-trigger route (POST /trigger/morning, POST /trigger/nightly, POST /cron/nightly-backstop, POST /cron/weekly-training-review) now follows api_chat_send's proven shape — run_in_executor(None, lambda: enqueue_occasion(...)) → ACK 202 on True, degrade to 503 on False. Never background_tasks.add_task for agent-turn work."
    - "_verify_morning_trigger_request is a literal byte-for-byte copy of _verify_trigger_request with only the env var name and two log strings substituted — same hmac.compare_digest, refuse-all-on-unset-env, and redacted-prefix-logging invariants, deliberately not parameterized into one shared function so each trigger keeps its own explicit, greppable auth path."
    - "/internal/process-occasion validates the incoming occasion string against a literal 3-member set before dispatch (never a dict-keyed lookup that could KeyError on a hostile body) and returns 400 rather than 500 on an unrecognized value — the malformed-body case is a client error, not a server fault."

key-files:
  created: []
  modified:
    - core/task_dispatch.py
    - interfaces/web_server.py
    - tests/test_task_dispatch.py
    - tests/test_web_server.py
    - tests/test_nightly_review.py

key-decisions:
  - "Trimmed the enqueue_occasion docstring aggressively (to ~13 lines) specifically so the function's audience/URL/occasion literals all fall within the plan's own `grep -n \"enqueue_occasion\" -A 40 | grep -c \"audience\"` == 1 window — the first drafted docstring (mirroring enqueue_hub_message's fuller WHY-prose) pushed \"audience\": base_url past line 146, failing the plan's literal acceptance criterion. Functionally identical; only comment density changed."
  - "/cron/nightly-backstop's response body changes from {\"sent\": bool} to {\"accepted\": true} per the plan's explicit instruction — the send/skip outcome is no longer knowable at ACK time now that compose runs on the Cloud Tasks worker. Cloud Scheduler only checks the status code, so nothing downstream consumes the old shape."
  - "/cron/weekly-training-review's response body changes from {\"ok\": true} to {\"accepted\": true} for the same reason and by the same enqueue-then-ACK pattern, even though the plan's <interfaces> block only spelled this out for /trigger/nightly and /trigger/morning explicitly — Rule-1-adjacent consistency fix so all four occasion routes share one response contract, not three different ones."
  - "Test method names for the new /trigger/morning and /internal/process-occasion test classes were deliberately prefixed with the plan's own filter keywords (test_trigger_morning_*, test_process_occasion_*, test_weekly_cron_*) rather than left as bare CamelCase-only class names — pytest -k does literal substring matching against the full node id, and \"TriggerMorning\" does not substring-match \"trigger_morning\". Without the prefix, the plan's own <verify> commands (-k \"trigger_morning or process_occasion\", -k \"trigger_nightly or backstop or weekly_cron\") would silently collect 0 tests and report a false green."

requirements-completed: [OCC-02, OCC-06]

# Metrics
duration: ~50min
completed: 2026-07-30
---

# Phase 33 Plan 10: Occasion Dispatch — Cloud Tasks Full-CPU Path Summary

**`enqueue_occasion` + `/internal/process-occasion` give every occasion compose (nightly/morning/weekly_review) a tracked Cloud Tasks request with full CPU, closing the pre-existing `/trigger/nightly` BackgroundTask defect (D-32) and giving the morning briefing its own dark-shipped, least-privilege push trigger (`POST /trigger/morning`, D-08/D-13/D-31).**

## Performance

- **Duration:** ~50 min (worktree base-correction — the worktree had landed one commit behind wave 3's tip — through final commit)
- **Started:** 2026-07-30 (session start)
- **Completed:** 2026-07-30T01:38+03:00 (final task commit)
- **Tasks:** 3/3
- **Files modified:** 5 (`core/task_dispatch.py`, `interfaces/web_server.py`, `tests/test_task_dispatch.py`, `tests/test_web_server.py`, `tests/test_nightly_review.py`)

## Accomplishments

- **`enqueue_occasion(occasion, *, trigger, target_date=None) -> bool`** (Task 1) — byte-for-byte mirror of `enqueue_hub_message`'s Cloud Tasks construction (same `CLOUD_TASKS_QUEUE` early-return-False, same project/location/base-URL/SA-email reads, same OIDC `audience=base_url`, same `_DISPATCH_DEADLINE_SECONDS`), targeting `/internal/process-occasion` with `{"occasion", "trigger", "target_date"?}`. Never raises — every exception is caught, logged, and returns `False` so callers can degrade to a 503 rather than crash.
- **`POST /internal/process-occasion`** (Task 2) — the single OIDC-gated (`_verify_cron_request`) Cloud Tasks target for all three occasions. Validates `occasion` against the literal set `{"nightly", "morning", "weekly_review"}` (400 on anything else, before any dispatch), then routes to `core.nightly_review.run_nightly`, `core.morning_briefing.run_morning_briefing_triggered`, or `core.weekly_training_review.run_weekly_review` by exact name/signature per the prior-wave contracts. Records `_log_cron_run(f"occasion-{occasion}", ok=...)` and re-raises on exception so Cloud Tasks retries and the failure is visible.
- **`POST /trigger/morning`** (Task 2) — the D-08 push trigger mirroring the existing Sleep-Focus-on → `/trigger/nightly` automation. `_verify_morning_trigger_request` is a literal copy of `_verify_trigger_request` with `MORNING_TRIGGER_TOKEN` substituted for `NIGHTLY_TRIGGER_TOKEN` — no fallback between the two secrets (D-13 least privilege). Enqueues via `enqueue_occasion("morning", trigger="focus", target_date=today_iso)` dispatched through `run_in_executor` (the Cloud Tasks client is synchronous, mirrors `api_chat_send`), ACKs 202 on success / 503 on `False`. Ships dark per D-31 — a module comment documents the route→Shortcut→confirm→retire-legacy-cron sequencing so `morning-briefing-tick` is not retired early.
- **D-32 fix applied to `/trigger/nightly`** (Task 3) — dropped the `BackgroundTasks` parameter and the `background_tasks.add_task(_run_nightly_background, ...)` call entirely; `_run_nightly_background` is deleted (no remaining caller). The route now enqueues via `enqueue_occasion("nightly", trigger="focus", target_date=...)` and ACKs 202/503 — the exact same response contract for the happy path, so Amit's existing iOS Shortcut needs no changes.
- **`/cron/nightly-backstop` and `/cron/weekly-training-review` moved to the same dispatch path** (Task 3), honestly documented as *not* a defect fix for these two — holding the request open kept CPU allocated for the inline compose; they move for consistency and request-timeout headroom now that Layer 2 can run up to 12 tool-calling turns (and the weekly surface has its own 500-incident history from event-loop starvation). `/cron/nightly-backstop`'s response body changes `{"sent": bool}` → `{"accepted": true}` per the plan; `/cron/weekly-training-review`'s changes `{"ok": true}` → `{"accepted": true}` for the same reason (documented as a Decision, not spelled out verbatim in the plan's `<action>` text but consistent with its own reasoning).
- **`/cron/morning-briefing-tick` deliberately untouched** — D-31's dark-ship window keeps the legacy polling cron running until the Shortcut is confirmed live (plan 33-12 retires it).
- **`background_tasks.add_task` count**: 3 → 2 in `interfaces/web_server.py` (pre-change: webhook fallback line 281, the nightly BackgroundTask line, and a comment reference at what's now line ~2512; post-change: only the webhook fallback code path plus the same comment). The nightly one is gone; the Telegram-webhook fallback (unrelated to this plan) is untouched.

## Task Commits

1. **Task 1: `enqueue_occasion` — Cloud Tasks dispatch for occasion composes** - `95a801e` (feat) - `core/task_dispatch.py` + `tests/test_task_dispatch.py`
2. **Task 2: `/internal/process-occasion` and `POST /trigger/morning`** - `92ae627` (feat) - `interfaces/web_server.py` + `tests/test_web_server.py`
3. **Task 3: Rewire `/trigger/nightly` and the `/cron/*` occasions onto the dispatch path (D-32)** - `6ee068d` (feat) - `interfaces/web_server.py` + `tests/test_nightly_review.py` + `tests/test_web_server.py`

_No plan-metadata commit — worktree mode; the orchestrator commits STATE.md/ROADMAP.md centrally after merge. This SUMMARY.md itself is committed separately per the worktree protocol._

## Files Created/Modified

- `core/task_dispatch.py` — new `enqueue_occasion(occasion, *, trigger, target_date=None) -> bool`, inserted between `_get_client` and `enqueue_hub_message`, mirroring the latter's construction exactly (deadline, OIDC audience, never-raises contract).
- `interfaces/web_server.py` — new `_verify_morning_trigger_request` (byte-for-byte `_verify_trigger_request` mirror), new `POST /internal/process-occasion` (registered alongside `/internal/process-update`), new `POST /trigger/morning` (ships dark, D-31 sequencing comment), `/trigger/nightly` rewired to enqueue-then-ACK (dropped `BackgroundTasks` param), `_run_nightly_background` deleted, `/cron/nightly-backstop` and `/cron/weekly-training-review` rewired to the same enqueue-then-ACK pattern with updated response bodies, `enqueue_occasion` added to the `core.task_dispatch` import line.
- `tests/test_task_dispatch.py` — `TestEnqueueOccasion`: happy path with/without `target_date`, queue-unset → `False`, `create_task` exception → `False`.
- `tests/test_web_server.py` — `TestTriggerMorning` (8 tests: missing/malformed/wrong auth, unset-token 500, no-fallback-to-nightly-token, valid-token enqueue+202, dark-ship no-send-in-request, enqueue-failure 503), `TestInternalProcessOccasion` (6 tests: unauthenticated, `_application is None`, morning/nightly/weekly_review dispatch-by-name, bogus-occasion 400-without-calling-anything), `TestCronWeeklyTrainingReview` rewritten for the enqueue shape (5 tests, all method names prefixed `test_weekly_cron_*` for `-k` filterability).
- `tests/test_nightly_review.py` — `test_trigger_nightly_dev_bypass_acks_and_enqueues` (renamed + rewritten from the old BackgroundTask-assertion test), new `test_trigger_nightly_enqueue_failure_returns_503`, `test_nightly_backstop_dev_bypass_enqueues` (renamed + rewritten), new `test_nightly_backstop_enqueue_failure_returns_503`.

## Decisions Made

See `key-decisions` in the frontmatter for full rationale — summarized: (1) the `enqueue_occasion` docstring was trimmed specifically to satisfy the plan's literal `grep -A 40 | grep -c "audience"` window criterion; (2) `/cron/nightly-backstop`'s response body changed from `{"sent": bool}` to `{"accepted": true}` per the plan's explicit instruction; (3) `/cron/weekly-training-review`'s response body changed from `{"ok": true}` to `{"accepted": true}` for consistency with the other three occasion routes, extending the plan's stated pattern to a route the `<action>` text didn't spell out verbatim; (4) new test method names were prefixed with the plan's own `-k` filter keywords so the plan's literal `<verify>` commands actually collect the tests they're meant to gate.

## Deviations from Plan

### Auto-fixed Issues

None — no bugs, missing critical functionality, or blocking issues were found in the codebase this plan builds on.

### Documented Interpretive Extensions (not Rule 1/2/3 fixes)

**1. `/cron/weekly-training-review` response body changed to `{"accepted": true}`.**
- **Why:** The plan's `<action>` text for Task 3 explicitly specifies this shape change for `/cron/nightly-backstop` (`"sent": bool` → `{"accepted": true}`) but does not repeat the instruction for `/cron/weekly-training-review`, which previously returned `{"ok": true}`. Since the same underlying fact is now true for both routes — the compose outcome is no longer known at ACK time — I applied the identical shape change for consistency across all four occasion-dispatch routes, rather than leaving one route with a stale `{"ok": true}` contract that implies synchronous completion it no longer has. Cloud Scheduler only checks the HTTP status code for both routes, so nothing downstream consumes either shape.
- **Verification:** `test_weekly_cron_returns_202_with_dev_bypass_and_app_present` asserts `resp.json() == {"accepted": True}` and status 202.

**2. Test method renaming to satisfy the plan's own `-k` filter literals.**
- **Why:** pytest `-k` does substring matching against the full test node id. The plan's `<verify>` commands specify `-k "trigger_morning or process_occasion"` and `-k "trigger_nightly or backstop or weekly_cron"`. My first draft used CamelCase class names only (`TestTriggerMorning`, `TestInternalProcessOccasion`, `TestCronWeeklyTrainingReview`) with bare method names (`test_missing_auth_returns_401`, etc.) — none of which substring-match the lowercase-with-underscores filter keywords, so the plan's literal verify commands would have silently collected 0 tests and reported a false "0 passed, 0 failed" green. Renamed the affected methods to include the literal keywords (`test_trigger_morning_missing_auth_returns_401`, `test_process_occasion_unauthenticated_rejected`, `test_weekly_cron_returns_401_without_bearer`, etc.) so the plan's own verify commands actually exercise the new tests.
- **Verification:** Ran the plan's exact `<verify>` commands from both Task 2 and Task 3 and confirmed non-zero pass counts (14 and 14 tests respectively — see Self-Check).

## Issues Encountered

- **Worktree base drift.** The worktree's initial `HEAD` (`e407dd3`) was an ancestor of, not equal to, the expected base commit `0edd1ae` — meaning `.planning/phases/33-occasion-cascade/` and all of waves 1–3's code did not yet exist in the worktree. The `<worktree_branch_check>` step's `git merge-base` comparison caught this correctly; `git reset --hard 0edd1ae7ed99e8f0fb71ae82ee0148c52777ddee` on a clean working tree corrected it before any file reads or edits began.
- **`enqueue_occasion` docstring/audience-window acceptance criterion.** First draft's fuller docstring (mirroring `enqueue_hub_message`'s WHY-prose) pushed the `"audience": base_url` line past the plan's `-A 40` grep window from the `def enqueue_occasion` line. Trimmed the docstring to ~13 lines to bring `audience` back within the window — purely a comment-density change, no functional impact (see Decisions Made).

## User Setup Required

None — no new env vars beyond what plan 33-06/33-07 already documented as pending (`MORNING_TRIGGER_TOKEN` and `OCCASION_CASCADE` are operator/deploy-config decisions downstream of the whole Phase 33 rollout, per those plans' own "User Setup Required" sections). This plan does not touch `docs/DEPLOYMENT.md` or `deploy.yml` — both are out of this plan's `files_modified` scope; a future plan (or an operator step before `/trigger/morning` goes live) must add `MORNING_TRIGGER_TOKEN` to Secret Manager + `deploy.yml`'s `--set-secrets`, mirroring `NIGHTLY_TRIGGER_TOKEN`'s existing entry.

## Next Phase Readiness

- Every occasion compose (nightly, morning, weekly_review) now runs inside a tracked Cloud Tasks request via `/internal/process-occasion` — the D-32 CLAUDE.md invariant (never a Starlette BackgroundTask) holds across all three occasions, not just the two that already routed through `run_in_executor`.
- `POST /trigger/morning` is live and authenticated but dark-shipped (D-31) — sends nothing until Amit's iOS Sleep-Focus-off Shortcut starts hitting it. `morning-briefing-tick` (`*/10 6-10`) is untouched and keeps running; plan 33-12 is responsible for retiring it once the Shortcut is confirmed firing.
- All four occasion-dispatch routes (`/trigger/nightly`, `/trigger/morning`, `/cron/nightly-backstop`, `/cron/weekly-training-review`) share one response contract now: `202 {"accepted": true}` on successful enqueue, `503 {"accepted": false, "error": "dispatch unavailable"}` on Cloud Tasks outage — no route-specific shape drift.
- No blockers or concerns for downstream plans. `docs/DEPLOYMENT.md`/`deploy.yml` updates for `MORNING_TRIGGER_TOKEN` (Secret Manager binding + `--set-secrets`) remain an operator step before `/trigger/morning` can authenticate in production — flagged here, not silently assumed done.

## Self-Check: PASSED

- FOUND: `core/task_dispatch.py`
- FOUND: `interfaces/web_server.py`
- FOUND: `tests/test_task_dispatch.py`
- FOUND: `tests/test_web_server.py`
- FOUND: `tests/test_nightly_review.py`
- FOUND: `.planning/phases/33-occasion-cascade/33-10-SUMMARY.md`
- FOUND commit: `95a801e` (Task 1)
- FOUND commit: `92ae627` (Task 2)
- FOUND commit: `6ee068d` (Task 3)
- `grep -c "def enqueue_occasion" core/task_dispatch.py` → 1
- `grep -c "/internal/process-occasion" core/task_dispatch.py` → 1
- `grep -n "enqueue_occasion" -A 40 core/task_dispatch.py | grep -c "audience"` → 1 (audience value is `base_url`)
- `grep -c "_verify_morning_trigger_request" interfaces/web_server.py` → 2 (≥2 required)
- `grep -c "MORNING_TRIGGER_TOKEN" interfaces/web_server.py` → 5 (≥1 required, no fallback to `NIGHTLY_TRIGGER_TOKEN`)
- `grep -c "_run_nightly_background" interfaces/web_server.py` → 0
- `grep -c "background_tasks.add_task" interfaces/web_server.py` → 2 (pre-change: 3; the nightly one is gone, only the Telegram-webhook fallback remains)
- `grep -n "def trigger_nightly" -A 3 interfaces/web_server.py` → no `BackgroundTasks` parameter
- `grep -c "enqueue_occasion" interfaces/web_server.py` → 10 (≥4 required)
- `grep -c "@app.post(\"/cron/morning-briefing-tick\")" interfaces/web_server.py` → 1
- `pytest tests/test_task_dispatch.py -k occasion -x -q` → 4 passed
- `pytest tests/test_web_server.py -k "trigger_morning or process_occasion" -x -q` → 14 passed
- `pytest tests/test_nightly_review.py tests/test_web_server.py -k "trigger_nightly or backstop or weekly_cron" -x -q` → 14 passed
- `pytest tests/test_task_dispatch.py tests/test_web_server.py tests/test_nightly_review.py -x -q` → 117 passed
- `pytest tests/test_morning_briefing.py -x -q` → 76 passed, 3 skipped (unaffected — no code in this plan touches `core/morning_briefing.py`)
- `pytest tests/test_weekly_training_review.py -x -q` → 52 passed

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-30*
