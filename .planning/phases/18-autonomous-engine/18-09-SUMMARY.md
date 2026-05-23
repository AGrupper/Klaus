---
phase: 18-autonomous-engine
plan: 09
subsystem: deployment-docs
tags: [docs, deployment, cloud-scheduler, secrets, firestore-indexes, infra-01]
requires:
  - "core/heartbeat.py:_CRON_MAX_STALENESS_HOURS (Plan 18-07 added autonomous-tick + reflect entries)"
  - "interfaces/web_server.py /cron/autonomous-tick route (Plan 18-07)"
  - "memory/firestore_db.py FollowupStore.list_due composite-index NOTE (Plan 18-01)"
provides:
  - "docs/DEPLOYMENT.md §19 Full Job Inventory (9 Cloud Scheduler jobs)"
  - "docs/DEPLOYMENT.md §14d klaus-reflect gcloud block (Phase 17 retroactive)"
  - "docs/DEPLOYMENT.md §14e klaus-autonomous-tick gcloud block (Phase 18 NEW)"
  - "docs/DEPLOYMENT.md §20 Groq TICK_BRAIN_API_KEY secret + rotation"
  - "docs/DEPLOYMENT.md §21 Known Quirks: Five Fingers job-id collision + legacy-job migration paragraph"
  - "docs/DEPLOYMENT.md §22 Firestore Composite Indexes (followups: status, due_at)"
  - "tests/test_docs.py::TestDeploymentCompleteness (8 grep assertions, all passing)"
affects:
  - "INFRA-01 satisfied (the only Phase 18 requirement still pending after Plan 18-08)"
  - "Phase 18 closure (9/9 plans complete)"
  - "Operators of pre-2026-05 deploys (migration paragraph)"
tech-stack:
  added: []
  patterns:
    - "grep-style docs completeness tests — tests/test_docs.py mirrors the test_self_inspect.py / test_prompts.py docs-grep pattern already in the repo"
    - "Single master table + dedicated per-job gcloud blocks — operator can scan the table for inventory and copy a block for re-deploy without reconstructing it from grep"
key-files:
  created:
    - "tests/test_docs.py (89 lines, 8 tests in TestDeploymentCompleteness)"
  modified:
    - "docs/DEPLOYMENT.md (+162 lines: §19 inventory + §14d/§14e gcloud blocks + §20 Groq + §21 quirks + §22 indexes; 1052 → 1214)"
    - ".planning/phases/18-autonomous-engine/deferred-items.md (+1 line noting Plan 18-09 also hit the pre-existing fastapi local-env block)"
decisions:
  - "Drop-in master table at §19 (NOT scattered per-section) — operator gets full inventory at-a-glance"
  - "klaus-* prefix for ALL job-ids in the inventory table — matches the canonical naming used in existing klaus-proactive-alerts / klaus-heartbeat / klaus-chat-ingest blocks; legacy unprefixed `five-fingers` covered explicitly in the migration paragraph"
  - "Fix endpoint-path drift in the inventory table: morning-briefing row uses /cron/morning-briefing-tick (matches interfaces/web_server.py:427), NOT the plan-template's `/cron/morning-briefing` — Rule 1 (bug: doc would contradict reality)"
  - "Five Fingers migration paragraph put inline under the quirk section (NOT a separate top-level section) — keeps the historical context and the migration adjacent"
  - "Composite-index doc references `gcloud firestore indexes composite create` as primary creation method + the FAILED_PRECONDITION click-link as fallback — covers both deploy-ahead and discover-on-first-prod-query workflows"
metrics:
  duration: "~15 min (planning context cached from STATE.md + 18-PATTERNS.md; single-task plan, no checkpoints)"
  date_completed: "2026-05-23"
  task_count: 1
  file_count: 3
---

# Phase 18 Plan 09: Deployment Docs Summary

INFRA-01 satisfied — operator-facing `docs/DEPLOYMENT.md` now exhaustively
documents all 9 Cloud Scheduler jobs (the 7 existing + Phase 17's
`klaus-reflect` + Phase 18's `klaus-autonomous-tick`), the Groq
`TICK_BRAIN_API_KEY` secret access/rotation procedure, the Five Fingers
job-id collision quirk with a legacy-job migration paragraph (bonus
WARNING fix), and the required Firestore composite index on
`(status, due_at)` for the `followups` collection.

## What changed

| File | Delta | Purpose |
|------|-------|---------|
| `docs/DEPLOYMENT.md` | +162 lines (1052 → 1214) | 6 additions: §19 inventory table, §14d klaus-reflect, §14e klaus-autonomous-tick, §20 Groq secret, §21 Five Fingers quirk + migration, §22 Firestore composite indexes |
| `tests/test_docs.py` | +89 lines NEW | 8 grep-style completeness tests, all passing |
| `.planning/phases/18-autonomous-engine/deferred-items.md` | +1 line | Note that Plan 18-09 also encountered the pre-existing fastapi local-env block (Rule 4 scope boundary, identical to Plan 18-08) |

## Sections added to docs/DEPLOYMENT.md

1. **§19 — Cloud Scheduler Full Job Inventory.** Single master table with 9 rows: `# | Job ID | Schedule | Endpoint | Phase`. Notes that schedules are illustrative (verify with `gcloud scheduler jobs list`) and points readers at `_CRON_MAX_STALENESS_HOURS` for heartbeat tolerance.
2. **§14d — klaus-reflect (Phase 17) gcloud block.** Retroactive documentation of the daily reflection cron (`0 22 * * *`, `/cron/reflect`).
3. **§14e — klaus-autonomous-tick (Phase 18) gcloud block.** NEW cron: `*/20 7-21 * * *`, Asia/Jerusalem, `/cron/autonomous-tick`. Includes pre-flight `gcloud scheduler jobs list --filter="name~autonomous-tick"` to prevent historical/staging collisions.
4. **§20 — TICK_BRAIN_API_KEY (Groq) Secret.** Secret name (`klaus-tick-brain-api-key`), `--set-secrets` binding for Cloud Run, 4-step rotation procedure (generate at https://console.groq.com/keys → `gcloud secrets versions add` → redeploy → `gcloud secrets versions disable` previous version). Documents the Gemini-fallback safety net (TICK-02 / Phase 14).
5. **§21 — Known Quirks: Five Fingers job-id collision + migration paragraph.** Documents the historical `"five-fingers"` shared job-id quirk and the canonical morning/evening split. Bonus WARNING fix: 4-step migration paragraph for legacy deploys predating 2026-05 — list existing jobs, create the two new canonical jobs first (no coverage gap), then `gcloud scheduler jobs delete five-fingers`, then verify via Firestore `cron_runs`.
6. **§22 — Firestore Composite Indexes.** Single-row table for `followups: status ASC, due_at ASC`, required by `FollowupStore.list_due()`. Documents both pre-deploy creation (`gcloud firestore indexes composite create --collection-group=followups --field-config=...`) and discover-on-FAILED_PRECONDITION fallback.

## Test results

`pytest tests/test_docs.py::TestDeploymentCompleteness -x -v` — **8/8 pass**:

| Test | Asserts |
|------|---------|
| `test_all_nine_job_ids_present` | All 9 `klaus-*` job-id strings appear |
| `test_autonomous_tick_schedule_present` | `*/20 7-21 * * *` + `/cron/autonomous-tick` present |
| `test_reflect_schedule_present` | `/cron/reflect` present |
| `test_gcloud_create_block_present_for_autonomous_tick` | A `gcloud scheduler jobs create` block lives within ±1000 chars of the `klaus-autonomous-tick` mention |
| `test_groq_secret_documented` | `TICK_BRAIN_API_KEY` + `klaus-tick-brain-api-key` + `gcloud secrets versions add` all present |
| `test_five_fingers_quirk_documented` | "Five Fingers" + "job-id"/"job id" present |
| **`test_five_fingers_migration_paragraph_present`** | **Bonus WARNING regression guard — asserts `gcloud scheduler jobs delete five-fingers` literal string present** |
| `test_followups_composite_index_documented` | "composite index" (case-insensitive) + "followups" + "status" + "due_at" all present |

## Adjacent regression

`pytest tests/test_autonomous.py tests/test_tick_brain.py tests/test_firestore_db.py tests/test_prompts.py tests/test_evals.py tests/test_web_server.py tests/test_heartbeat.py tests/test_eval_script.py tests/test_main_render_smart_system.py -k "not TestCronAutonomousTick and not test_cron_heartbeat_rejects_unauthenticated"` — **155/155 pass**, 6 deselected. The 6 deselected are the pre-existing fastapi local-env block (reproduced on HEAD before any Plan 18-09 changes, identical to Plan 18-08; both are logged in `.planning/phases/18-autonomous-engine/deferred-items.md`). Plan 18-09 touches docs + a new test file only, so this regression set is necessarily green on its own changes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Fixed endpoint-path drift for morning-briefing row in §19 inventory table**
- **Found during:** Task 1, while cross-checking endpoint paths against `interfaces/web_server.py`
- **Issue:** The plan template specified `/cron/morning-briefing` for the klaus-morning-briefing row, but the actual FastAPI route is `@app.post("/cron/morning-briefing-tick")` at `interfaces/web_server.py:427`.
- **Fix:** Used `/cron/morning-briefing-tick` in the inventory table so DEPLOYMENT.md does not contradict the live code.
- **Files modified:** `docs/DEPLOYMENT.md` (§19 row 3, endpoint cell)
- **Commit:** 4ff06e5

No other deviations. The plan executed as a single task, end-to-end.

## Auth gates

None — docs-only plan.

## Commits

| Commit | Type | Subject |
|--------|------|---------|
| 4ff06e5 | docs(18-09) | document all 9 Cloud Scheduler jobs + Groq secret + Five Fingers migration + Firestore composite index |

## Phase 18 closure — SC-1..SC-5 manual smoke procedures ready

With Plan 18-09 complete, all 9 plans of Phase 18 — The Autonomous Engine — are done. The phase-level success criteria (SC-1 through SC-5 from `18-VALIDATION.md`) are now runnable end-to-end against a staging deploy:

- **SC-1** Plant overdue TickTick task → trigger `/cron/autonomous-tick` → expect Telegram message (autonomous outreach proves judgment-driven decision making).
- **SC-2** Trigger immediately again → expect silence (repeat-suppression via `outreach_log/{date}` proves de-dup wiring).
- **SC-3** Trigger on a quiet situation → expect silence and ~zero LLM cost on that tick (Layer-0 gate from Plan 18-06).
- **SC-4** Use `schedule_followup` mid-chat, advance time past due → expect follow-up to fire (dedicated `_compose_followup` path from Plan 18-06).
- **SC-5** Run `python scripts/eval_tick_brain.py` → expect precision/recall/F1 report + per-trigger-type table (Plan 18-08 runner against Plan 18-04 seed fixtures).

All five smoke tests now have their full operational scaffold documented in `docs/DEPLOYMENT.md` — the autonomous engine is shippable.

## Self-Check: PASSED

- File `docs/DEPLOYMENT.md`: FOUND (1214 lines, +162 vs pre-plan baseline 1052)
- File `tests/test_docs.py`: FOUND (89 lines, 8 tests, all passing)
- Commit `4ff06e5`: FOUND in `git log --oneline`
- Grep verifications:
  - `grep -c "klaus-autonomous-tick" docs/DEPLOYMENT.md`: 3 (>= 2 required)
  - `grep -c "klaus-reflect" docs/DEPLOYMENT.md`: 3 (>= 2 required)
  - `grep -c "TICK_BRAIN_API_KEY" docs/DEPLOYMENT.md`: 2 (>= 1 required)
  - `grep -ic "composite index" docs/DEPLOYMENT.md`: 2 (>= 1 required)
  - `grep -c "gcloud scheduler jobs delete five-fingers" docs/DEPLOYMENT.md`: 1 (>= 1 required — bonus WARNING fix verified)
  - Unique job-id count in DEPLOYMENT.md: 9 (== 9 required)
