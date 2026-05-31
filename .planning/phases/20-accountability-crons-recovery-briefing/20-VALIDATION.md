---
phase: 20
slug: accountability-crons-recovery-briefing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-31
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `20-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0 |
| **Config file** | none — direct pytest invocation |
| **Quick run command** | `pytest tests/ -x -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~30–60 seconds (465+ existing tests; mocked Firestore/Garmin/Telegram) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/ -x -q` (fail-fast)
- **After every plan wave:** Run `pytest tests/ -q` (full suite, no fail-fast)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

Requirement → behavior → automated command. Plan/task IDs assigned by the planner; mapping below is the requirement-level contract every plan must satisfy.

| Requirement | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| LOG-01 | `TrainingLogStore.log_session` writes `training_log/{date}_{slot}` with all fields | — | N/A | unit | `pytest tests/test_training_log_store.py -x` | ❌ W0 | ⬜ pending |
| LOG-02 | `get_recent(days)` + `get_by_date(date)` return correct entries | — | N/A | unit | `pytest tests/test_training_log_store.py -x` | ❌ W0 | ⬜ pending |
| LOG-03 | `log_training` brain-direct (in SMART_AGENT_DIRECT_TOOLS + TOOL_SCHEMAS, NOT in WORKER_TOOL_SCHEMAS) | — | N/A | unit | `pytest tests/test_tool_registration_phase20.py -x` | ❌ W0 | ⬜ pending |
| LOG-04 | `get_training_history` worker-delegated | — | N/A | unit | `pytest tests/test_tool_registration_phase20.py -x` | ❌ W0 | ⬜ pending |
| CHECKIN-02 | Silent Garmin sync writes `source="garmin"` (no Telegram) | — | N/A | unit | `pytest tests/test_training_checkin.py::test_silent_garmin_sync -x` | ❌ W0 | ⬜ pending |
| CHECKIN-03 | Prompts only for unlogged, past-start planned workouts; branch RPE vs watch-off | — | N/A | unit | `pytest tests/test_training_checkin.py -x` | ❌ W0 | ⬜ pending |
| CHECKIN-04 | RPE keyboard: two rows of 5, callback_data `rpe:{key}:{val}` | T-20 input-val | Parse prefix + split; unknown prefix discarded | unit | `pytest tests/test_training_checkin.py::test_rpe_keyboard_layout -x` | ❌ W0 | ⬜ pending |
| CHECKIN-05 | Fully silent when all planned workouts covered | — | N/A | unit | `pytest tests/test_training_checkin.py::test_silent_when_all_covered -x` | ❌ W0 | ⬜ pending |
| RECOVERY-01 | `compute_recovery_concern` → None on no-trigger; mild/strong on threshold crossings | — | N/A | unit | `pytest tests/test_recovery_concern.py -x` | ❌ W0 | ⬜ pending |
| RECOVERY-02 | `RECOVERY_THRESHOLDS` dict exists with all required keys + docstring | — | N/A | unit | `pytest tests/test_recovery_concern.py::test_thresholds_dict_shape -x` | ❌ W0 | ⬜ pending |
| REVIEW-01 | `/cron/weekly-training-review`: 200 dev-bypass, 500 app-absent, 401 bad token | — | OIDC verify mirrors `_verify_cron_request` | unit | `pytest tests/test_web_server.py::TestCronWeeklyTrainingReview -x` | ❌ W0 | ⬜ pending |
| REVIEW-03 | `prompts/weekly_training_review.md` exists with required placeholders | — | N/A | smoke | `pytest tests/test_docs.py::test_weekly_training_review_prompt_exists -x` | ❌ W0 | ⬜ pending |
| REVIEW-04 | `_log_cron_run` called on success AND exception path | — | N/A | unit | `pytest tests/test_web_server.py::TestCronWeeklyTrainingReview -x` | ❌ W0 | ⬜ pending |
| callback_query dispatch | Router dispatches callback_query; existing message path unaffected | T-20 access | `effective_user.id` in `allowed_user_ids` before processing | unit | `pytest tests/test_router_callback_query.py -x` | ❌ W0 | ⬜ pending |
| PendingPromptStore | set/get/delete/get_open_note_session + soft TTL (~20h) | T-20 session | Reject sessions older than TTL; session_key user-scoped | unit | `pytest tests/test_pending_prompt_store.py -x` | ❌ W0 | ⬜ pending |
| weekly-review staleness | Heartbeat staleness key for weekly-review cron (~170h) | — | N/A | unit | `pytest tests/test_heartbeat.py -x` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Manual-only / smoke (not pytest-automatable):**

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Bootstrap creates exactly one job (`klaus-weekly-training-review`, NOT `klaus-training-checkin` per D-09) | CRON-01 | Bash + live Cloud Scheduler | Run `scripts/bootstrap_shifu_crons.sh`; `gcloud scheduler jobs list` shows the one new job; re-run is idempotent (describe-or-update) |
| DEPLOYMENT.md Phase Shifu section documents the new job | CRON-02 | Doc inspection | `grep -A5 "Phase Shifu" docs/DEPLOYMENT.md` lists `klaus-weekly-training-review` |
| RECOVERY-03 prompt tone shift | RECOVERY-03 | LLM output quality | Eyeball morning_briefing.md / proactive_alert.md render with `recovery_concern` set; metric-anchored, suggesting, no invented numbers |
| End-to-end inline-keyboard check-in | CHECKIN-03/04 | Live Telegram + Garmin | Live UAT once Training calendar populated (forward-only per D-04) |

---

## Wave 0 Requirements

New test files (RED before GREEN per project TDD convention):

- [ ] `tests/test_training_log_store.py` — LOG-01, LOG-02
- [ ] `tests/test_tool_registration_phase20.py` — LOG-03, LOG-04 (mirror existing `TestPhase19ToolRegistration`)
- [ ] `tests/test_training_checkin.py` — CHECKIN-02..05
- [ ] `tests/test_pending_prompt_store.py` — PendingPromptStore CRUD + TTL
- [ ] `tests/test_recovery_concern.py` — RECOVERY-01, RECOVERY-02
- [ ] `tests/test_router_callback_query.py` — callback_query dispatch + allow-list guard
- [ ] `tests/test_web_server.py` — extend with `TestCronWeeklyTrainingReview` (REVIEW-01, REVIEW-04)
- [ ] `tests/test_docs.py` — extend with `test_weekly_training_review_prompt_exists` (REVIEW-03)
- [ ] `tests/test_heartbeat.py` — extend with `test_weekly_training_review_staleness_threshold`

---

## Manual-Only Verifications

See the "Manual-only / smoke" block above (CRON-01, CRON-02, RECOVERY-03 tone, live Telegram check-in UAT). All other phase behaviors have automated verification.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
