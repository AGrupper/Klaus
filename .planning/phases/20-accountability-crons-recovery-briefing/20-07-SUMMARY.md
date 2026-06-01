---
phase: 20-accountability-crons-recovery-briefing
plan: 07
subsystem: ops/docs/manifest
tags: [bootstrap, deployment, self-manifest, cloud-scheduler, telegram-webhook]

# Dependency graph
requires:
  - plan: 20-01
    provides: "log_training + get_training_history tools (surfaced in SELF.md)"
  - plan: 20-06
    provides: "/cron/weekly-training-review route (surfaced in SELF.md + DEPLOYMENT.md)"
provides:
  - "scripts/bootstrap_shifu_crons.sh: re-runnable single-job create/update (CRON-01)"
  - "docs/DEPLOYMENT.md §24 Phase Shifu section + §19 inventory row (CRON-02)"
  - "docs/SELF.md regenerated: log_training + get_training_history + /cron/weekly-training-review"
affects:
  - "Operator: run bootstrap_shifu_crons.sh to register the Sunday 10:00 cron job"
  - "Operator: re-run setWebhook with allowed_updates=[\"message\",\"callback_query\"] (Pitfall 1)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Describe-or-create/update idempotency: gcloud scheduler jobs describe → update or create"
    - "SELF.md Cron Jobs table hardcoded in self_manifest.py (not auto-extracted) — manually extended per-phase"

key-files:
  created:
    - "scripts/bootstrap_shifu_crons.sh"
  modified:
    - "docs/DEPLOYMENT.md"
    - "docs/SELF.md"
    - "core/self_manifest.py"
    - "tests/test_docs.py"

key-decisions:
  - "Rule 1 fix: self_manifest.py Cron Jobs table is hardcoded (not dynamically extracted from web_server.py); added weekly-training-review row manually as a required correction"
  - "bootstrap_shifu_crons.sh creates ONLY the single new weekly-training-review job (D-09/D-25); the training check-in folds into existing proactive-alerts, requiring no new scheduler job"
  - "DEPLOYMENT.md §24 (not §25) — follows the last section numbering after §23 HEALTHKIT_WEBHOOK_TOKEN"

# Metrics
duration: ~4min
completed: 2026-06-01
---

# Phase 20 Plan 07: Ops Layer — Bootstrap Script, Deployment Docs, SELF.md Regen Summary

**Re-runnable bootstrap creates the weekly-training-review Cloud Scheduler job; DEPLOYMENT.md Phase Shifu section documents the single new OIDC job + the mandatory allowed_updates callback_query re-registration pitfall; SELF.md regenerated to surface log_training + get_training_history tools and /cron/weekly-training-review route**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-01T09:27:29Z
- **Completed:** 2026-06-01T09:31:08Z
- **Tasks:** 3
- **Files modified/created:** 5

## Accomplishments

- `scripts/bootstrap_shifu_crons.sh` created: re-runnable (describe-or-create/update), creates ONLY `klaus-weekly-training-review` at `0 10 * * 0 Asia/Jerusalem`, OIDC via existing `CLOUD_SCHEDULER_SA_EMAIL`, executable, syntax-clean (CRON-01, D-09, D-25, T-20-16 mitigated)
- `docs/DEPLOYMENT.md` §19 inventory table updated: 8 jobs now listed, row 8 is `klaus-weekly-training-review` with Phase 20 (Shifu) tag; note that no `klaus-training-checkin` job exists (D-09 fold documented)
- `docs/DEPLOYMENT.md` §24 Phase Shifu section added: `gcloud scheduler jobs create` block + pointer to `bootstrap_shifu_crons.sh`; D-09 training check-in fold note; Pitfall 1 WARNING with exact `setWebhook` curl block updating `allowed_updates` to `["message","callback_query"]` (CRON-02)
- `core/self_manifest.py` extended: weekly-training-review row added to hardcoded Cron Jobs table (Rule 1 fix — the table was hardcoded and did not auto-extract routes)
- `docs/SELF.md` regenerated via `python core/self_manifest.py`: now surfaces `log_training` (brain-direct), `get_training_history` (worker-delegated), and `/cron/weekly-training-review` (Sun 10:00) — not hand-edited
- `tests/test_docs.py::TestDeploymentCompleteness` extended with 3 new assertions: `test_phase_shifu_section_present`, `test_allowed_updates_callback_query_documented`, `test_no_separate_training_checkin_job` — all 16 tests green

## Task Commits

1. **Task 1: bootstrap_shifu_crons.sh** — `00374ec` (feat)
2. **Task 2: DEPLOYMENT.md Phase Shifu section + docs tests** — `f2d659b` (feat)
3. **Task 3: Regenerate SELF.md** — `9800729` (feat)

## Files Created/Modified

- `scripts/bootstrap_shifu_crons.sh` — re-runnable single-job OIDC bootstrap (CRON-01)
- `docs/DEPLOYMENT.md` — §19 inventory row + §24 Phase Shifu section + setWebhook Pitfall 1 step (CRON-02)
- `tests/test_docs.py` — 3 new TestDeploymentCompleteness assertions (16/16 passing)
- `core/self_manifest.py` — weekly-training-review added to hardcoded Cron Jobs table
- `docs/SELF.md` — regenerated (not hand-edited): new tools + new cron route surfaced

## Decisions Made

- `self_manifest.py` Cron Jobs table is hardcoded (not auto-extracted from `web_server.py`); the SHA computation correctly tracks new routes but the rendered table rows must be manually added. Fixed as Rule 1 bug — the table was drifting from reality without this row.
- `bootstrap_shifu_crons.sh` creates exactly one scheduler job (D-09/CRON-01): `proactive-alerts` already handles the 21:30 training check-in; adding a separate `training-checkin` job would double-fire the check-in logic
- `docs/DEPLOYMENT.md` new section numbered §24 (following §23 HEALTHKIT_WEBHOOK_TOKEN)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] core/self_manifest.py Cron Jobs table hardcoded — missing weekly-training-review row**
- **Found during:** Task 3
- **Issue:** The `_render_manifest()` function in `core/self_manifest.py` has a hardcoded Cron Jobs table. The `_compute_schema_hash()` correctly greps `/cron/` routes from `web_server.py` to track schema drift, but the rendered table content is not auto-extracted. After adding `/cron/weekly-training-review` in Plan 06, the regenerated SELF.md did not include it in the Cron Jobs section because the hardcoded table still had only 7 rows.
- **Fix:** Added the weekly training review row to the hardcoded table in `core/self_manifest.py`, then re-ran the generator.
- **Files modified:** `core/self_manifest.py`
- **Commit:** `9800729`

## Known Stubs

None — all three deliverables are complete and functional:
- `bootstrap_shifu_crons.sh` executes real gcloud commands
- `DEPLOYMENT.md` documents live operational procedures
- `SELF.md` is regenerated from live source (not mocked)

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-20-16 mitigated | scripts/bootstrap_shifu_crons.sh | --oidc-service-account-email + --oidc-token-audience set; route enforces _verify_cron_request |
| T-20-17 accepted | docs/DEPLOYMENT.md | allowed_updates widens Telegram delivery only; router enforces user allow-list on every callback |

## Self-Check: PASSED

Files verified:
- `scripts/bootstrap_shifu_crons.sh` — FOUND (syntax ok, `0 10 * * 0`, `Asia/Jerusalem`, `CLOUD_SCHEDULER_SA_EMAIL`, no `training-checkin`, executable)
- `docs/DEPLOYMENT.md` — FOUND (Phase Shifu at line 1221, callback_query present, folds into proactive-alerts at lines 1072+1253)
- `docs/SELF.md` — FOUND (`log_training`, `get_training_history`, `weekly-training-review` all present; generated_at updated)
- `core/self_manifest.py` — FOUND (weekly-training-review row added to Cron Jobs table)
- `tests/test_docs.py` — FOUND (3 new assertions; 16/16 passing)

Commits verified:
- `00374ec` — feat(20-07): add re-runnable scripts/bootstrap_shifu_crons.sh
- `f2d659b` — feat(20-07): add DEPLOYMENT.md Phase Shifu section + extend docs tests
- `9800729` — feat(20-07): regenerate docs/SELF.md with log_training + get_training_history + weekly-training-review

---
*Phase: 20-accountability-crons-recovery-briefing*
*Completed: 2026-06-01*
