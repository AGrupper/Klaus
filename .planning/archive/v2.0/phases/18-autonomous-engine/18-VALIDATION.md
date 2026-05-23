---
phase: 18
slug: autonomous-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-20
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `18-RESEARCH.md § Validation Architecture`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (established Phase 14, confirmed in Phase 17) |
| **Config file** | `pyproject.toml` or `pytest.ini` (verify in Wave 0 — Phase 17 used pytest) |
| **Quick run command** | `pytest tests/test_autonomous.py tests/test_firestore_db.py tests/test_tools.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~5s quick, ~30s full |

---

## Sampling Rate

- **After every task commit:** `pytest tests/test_autonomous.py tests/test_firestore_db.py tests/test_tools.py -x`
- **After every plan wave:** `pytest tests/ -x`
- **Before `/gsd-verify-work`:** Full suite must be green AND live-tick smoke SC-1..SC-5 verified
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | AUTO-04 | — | FollowupStore writes/reads doc lifecycle correctly | unit | `pytest tests/test_firestore_db.py::test_followup_store -x` | ❌ W0 (extend) | ⬜ pending |
| 18-01-02 | 01 | 1 | AUTO-03 | — | OutreachLogStore append-on-success, daily reset by date key | unit | `pytest tests/test_firestore_db.py::test_outreach_log_store -x` | ❌ W0 (extend) | ⬜ pending |
| 18-02-01 | 02 | 1 | AUTO-05 | — | All 3 follow-up tools registered at 15 sites + ISO/NL `when` parsing + idempotent cancel | unit | `pytest tests/test_tools.py::test_followup_tools -x` | ❌ W0 (extend) | ⬜ pending |
| 18-02-02 | 02 | 1 | AUTO-05 | — | 15-edit-point grep verification (≥15 hits in core/tools.py) | unit | `grep -cE "schedule_followup\|list_followups\|cancel_followup" core/tools.py` ≥ 15 | n/a (grep check) | ⬜ pending |
| 18-03-01 | 03 | 1 | AUTO-07 | — | `prompts/autonomous_triage.md` + `prompts/autonomous.md` present with wide-latitude framing + JSON-output spec | unit | `pytest tests/test_prompts.py::test_autonomous_prompts -x` | ❌ W0 | ⬜ pending |
| 18-04-01 | 04 | 1 | AUTO-08 | — | `evals/tick_brain/fixtures/` ≥5 fixture JSON files with valid schema | unit | `pytest tests/test_evals.py::test_fixture_schema -x` | ❌ W0 | ⬜ pending |
| 18-05-01 | 05 | 2 | (extends Phase 14 TICK-*) | — | `TickBrain.think()` accepts `system_override` kwarg (default None preserves heartbeat behavior); `_parse_response` passes through `topic_key` | unit | `pytest tests/test_tick_brain.py::test_topic_key_passthrough -x` AND `pytest tests/test_tick_brain.py::test_system_override -x` | ❌ W0 (extend) | ⬜ pending |
| 18-06-01 | 06 | 2 | AUTO-02 | — | `gather_situation()` aggregates 8 sources with per-source try/except isolation | unit | `pytest tests/test_autonomous.py::test_gather_situation_isolation -x` | ❌ W0 | ⬜ pending |
| 18-06-02 | 06 | 2 | AUTO-01 | — | `run_autonomous_tick()` returns correct decision trail across 4 scenarios (empty-signal skip, triage-no, triage-yes→compose-yes, triage-yes→compose-fail-fallback) | unit | `pytest tests/test_autonomous.py::test_run_autonomous_tick_decision_trail -x` | ❌ W0 | ⬜ pending |
| 18-06-03 | 06 | 2 | AUTO-01 / SC-3 | — | Empty-signal Layer-0 gate skips tick-brain entirely (D-11; SC-3 cost control) | unit | `pytest tests/test_autonomous.py::test_quiet_situation_skips_tick_brain -x` | ❌ W0 | ⬜ pending |
| 18-06-04 | 06 | 2 | AUTO-03 | — | OutreachLogStore.append called ONLY after `send_and_inject` succeeds (D-10) | unit | `pytest tests/test_autonomous.py::test_outreach_log_on_success_only -x` | ❌ W0 | ⬜ pending |
| 18-06-05 | 06 | 2 | AUTO-01 | — | Synthetic Layer-2 user message does NOT pollute conversation history (Pitfall 2) | unit | `pytest tests/test_autonomous.py::test_synthetic_message_does_not_pollute_history -x` | ❌ W0 | ⬜ pending |
| 18-06-06 | 06 | 2 | (D-14) | — | `defer_count >= 3` force-fires next due tick (handler-enforced, not prompt) | unit | `pytest tests/test_autonomous.py::test_defer_force_fire_at_three -x` | ❌ W0 | ⬜ pending |
| 18-06-07 | 06 | 2 | (D-19) | — | Layer-2 LLM total failure falls back to tick-brain `draft` and ships | unit | `pytest tests/test_autonomous.py::test_layer2_fallback_to_draft -x` | ❌ W0 | ⬜ pending |
| 18-06-08 | 06 | 2 | (D-07) | — | Empty/missing `topic_key` from tick-brain triggers handler synthesis (`"<trigger>:auto-<idx>"`) | unit | `pytest tests/test_autonomous.py::test_topic_key_fallback -x` | ❌ W0 | ⬜ pending |
| 18-07-01 | 07 | 2 | AUTO-06 | — | `/cron/autonomous-tick` returns 200 on valid OIDC + invokes `run_autonomous_tick`; 401 on bad bearer; `_log_cron_run` called | integration | `pytest tests/test_web_server.py::test_cron_autonomous_tick -x` | ❌ W0 (extend) | ⬜ pending |
| 18-07-02 | 07 | 2 | AUTO-06 | — | Heartbeat staleness check picks up `autonomous-tick` job-id | unit | `pytest tests/test_heartbeat.py::test_autonomous_tick_staleness -x` | ❌ W0 (extend) | ⬜ pending |
| 18-08-01 | 08 | 3 | AUTO-09 | — | `scripts/eval_tick_brain.py` exits 0 on 5-fixture run; prints precision/recall/F1 + per-trigger-type table; safe-mode returns counted as "errored" not "predicted False" | integration | `pytest tests/test_eval_script.py::test_eval_runs -x` | ❌ W0 | ⬜ pending |
| 18-09-01 | 09 | 3 | INFRA-01 | — | `docs/DEPLOYMENT.md` lists all 9 cron jobs with schedules/endpoints; documents Groq secret; documents Five Fingers job-id quirk | docs-grep | `pytest tests/test_docs.py::test_deployment_completeness -x` | ❌ W0 (extend) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> SC-1, SC-2, SC-4, SC-5 — covered by live-tick smoke (see "Manual-Only Verifications" below). SC-3 unit-covered above (18-06-03); cost-side of SC-3 manual-verified.

---

## Wave 0 Requirements

- [ ] `tests/test_autonomous.py` — NEW; stubs for AUTO-01, AUTO-02, AUTO-03, SC-3 unit, D-07/D-10/D-14/D-19 pitfall tests
- [ ] `tests/test_firestore_db.py` — extend with `FollowupStore` + `OutreachLogStore` test classes (AUTO-03, AUTO-04)
- [ ] `tests/test_tools.py` — extend with follow-up-tools test class incl. ISO/NL `when` parsing and idempotent cancel (AUTO-05)
- [ ] `tests/test_tick_brain.py` — extend with `topic_key` pass-through + `system_override` kwarg tests
- [ ] `tests/test_web_server.py` — extend with `/cron/autonomous-tick` route tests (AUTO-06)
- [ ] `tests/test_prompts.py` — NEW; assert key phrases in `prompts/autonomous_triage.md` + `prompts/autonomous.md` (AUTO-07)
- [ ] `tests/test_evals.py` — NEW; fixture schema validation (AUTO-08)
- [ ] `tests/test_eval_script.py` — NEW; subprocess invocation of `scripts/eval_tick_brain.py` (AUTO-09)
- [ ] `tests/test_docs.py` — extend with DEPLOYMENT.md completeness assertion (INFRA-01)
- [ ] `tests/test_heartbeat.py` — extend with `autonomous-tick` staleness entry test
- [ ] Shared fixture in `tests/conftest.py` — in-memory `FollowupStore` + `OutreachLogStore` mocks mirroring real interfaces
- [ ] `python-dateutil` in `requirements.txt` (verify; add if absent — needed for NL `when` parsing per D-12)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Plant overdue TickTick task → trigger `/cron/autonomous-tick` → Klaus sends Telegram | SC-1 | Requires live TickTick + Telegram + GCP scheduler invocation against staging | 1) Create an overdue task in TickTick (due_at in past). 2) `gcloud scheduler jobs run autonomous-tick`. 3) Verify Telegram receives a message referencing the overdue task. 4) Verify Firestore `outreach_log/{today}` has the entry. |
| Trigger again immediately → silence | SC-2 | Same — live infra required | 5) `gcloud scheduler jobs run autonomous-tick` again within minutes. 6) Verify NO new Telegram. 7) Verify tick-brain prompt saw the prior `topic_key` (check `tick_logs/{today}/{tick_time}` snapshot). |
| Quiet situation cost check | SC-3 (cost side) | `LLMUsageStore` cost-delta has to be checked live | 8) On a quiet tick (no overdue, no due follow-ups, no calendar event), record `LLMUsageStore.summary(today).cost` before/after. Diff should be ~$0 (Layer 0 gate skipped tick-brain). |
| `schedule_followup` mid-chat → tick after due_at → follow-up fires | SC-4 | Requires live chat + scheduled tick | 9) In Telegram chat: ask Klaus to schedule a follow-up 10 min from now. 10) Wait for the tick after `due_at`. 11) Verify Klaus sends a follow-up Telegram referencing the original note. |
| Eval script smoke | SC-5 | Already covered by automated `test_eval_runs`; manual run also documented for PR description | `python scripts/eval_tick_brain.py` from project root; verify precision/recall/F1 + per-trigger-type table prints. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
