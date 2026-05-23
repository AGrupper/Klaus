---
phase: 18-autonomous-engine
verified: 2026-05-23T00:00:00Z
status: human_needed
score: 10/10 must-haves verified (automated)
blocking_issues_count: 0
verdict: GREEN (automated) — AMBER pending SC-1..SC-5 live-tick smoke
test_summary:
  passed: 181
  failed: 0
  deselected_preexisting: 1   # test_cron_heartbeat_rejects_unauthenticated (sys.modules pollution; documented)
human_verification:
  - test: "SC-1: Plant overdue TickTick task → run autonomous-tick → Klaus sends Telegram"
    expected: "Telegram message references the overdue task; outreach_log/{today} written"
    why_human: "Live TickTick + Telegram + GCP Scheduler invocation"
  - test: "SC-2: Trigger again immediately → silence"
    expected: "No new Telegram; tick_logs snapshot shows prior topic_key was visible to triage"
    why_human: "Same — live infra"
  - test: "SC-3: Quiet tick → silence + ~$0 cost delta"
    expected: "LLMUsageStore.summary(today).cost diff is ~0 (Layer-0 gate skipped tick-brain)"
    why_human: "Cost telemetry verified live"
  - test: "SC-4: schedule_followup mid-chat → tick after due_at → follow-up fires"
    expected: "Klaus sends polished follow-up Telegram referencing original note"
    why_human: "Live chat + scheduled tick"
  - test: "SC-5: python scripts/eval_tick_brain.py with real TICK_BRAIN_API_KEY"
    expected: "P/R/F1 + per-trigger table printed; Errored = 0/5"
    why_human: "Requires Groq API key — automated test runs in all-errored fallback"
---

# Phase 18: The Autonomous Engine — Verification Report

**Phase Goal:** Klaus decides on his own judgment when to reach out, with repeat-suppression and an eval harness measuring judgment quality.

**Verified:** 2026-05-23
**Status:** human_needed (automated PASS; live SC-1..SC-5 smoke pending)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP Success Criteria) | Status | Evidence |
|---|------|------|------|
| 1 | Klaus initiates outreach proactively based on situation | VERIFIED (code) / PENDING (live) | `core/autonomous.py:689 run_autonomous_tick`, full 3-layer pipeline + 31 unit tests; SC-1 live smoke deferred |
| 2 | Repeat-suppression prevents redundant same-day messaging | VERIFIED (code) / PENDING (live) | `OutreachLogStore.append` called success-only (`autonomous.py:802-816`, D-10); `topics_today` flows into triage prompt; `test_outreach_log_on_success_only` PASSED |
| 3 | Klaus can schedule, list, cancel follow-ups | VERIFIED | 3 tools wired at 5 sites (16 grep hits ≥ 15 required); 13 tests in `TestFollowupTools` PASSED |
| 4 | Cron route triggers tick on schedule, OIDC-protected | VERIFIED | `interfaces/web_server.py:363 @app.post("/cron/autonomous-tick")`; `_verify_cron_request` invoked; 5/5 `TestCronAutonomousTick` PASSED |
| 5 | Eval harness measures judgment quality on seed fixtures | VERIFIED | `scripts/eval_tick_brain.py` 366 lines, P/R/F1 + per-trigger table + errored bucket (Pitfall 8); 4/4 subprocess tests PASSED; manual smoke pending (SC-5) |

**Score:** 5/5 truths verified at code level; 4/5 require live-tick smoke for full confidence.

---

## Per-Requirement Verification

| Req | Status | Evidence |
|-----|--------|----------|
| **AUTO-01** (3-layer pipeline + Layer-0 gate) | PASS | `run_autonomous_tick` at `core/autonomous.py:689`; `_SMART_LOOP_ERROR_SENTINELS` at :47; empty-signal gate at :298 (`gathered["empty"] = _is_empty_signals(...)`); `test_quiet_situation_skips_tick_brain` PASSED |
| **AUTO-02** (gather_situation 8 sources w/ isolation) | PASS | `gather_situation` at :174; 8 try/except blocks (a–h) at :206/221/230/238/250/266/280/288; `test_gather_situation_isolation` PASSED |
| **AUTO-03** (outreach log on send-success only — D-10) | PASS | `autonomous.py:790` send → :800 `decision["sent"] = True` → :802-816 `ols.append(...)`; failure path at :791-798 returns BEFORE append; `test_outreach_log_on_success_only` PASSED; same pattern at followup path :604-637 |
| **AUTO-04** (FollowupStore CRUD lifecycle) | PASS | `memory/firestore_db.py:776 class FollowupStore` with 7 methods (add/list_due/list_pending/mark_done/cancel/defer); `TestFollowupStore` 11 tests PASSED |
| **AUTO-05** (3 follow-up tools at 5 sites) | PASS | `grep -cE "schedule_followup\|list_followups\|cancel_followup" core/tools.py` = **16** (≥ 15 required); 13/13 `TestFollowupTools` PASSED; WARNING-7 ImportError catch at :1281 |
| **AUTO-06** (cron route + heartbeat staleness) | PASS | `/cron/autonomous-tick` at `web_server.py:363`; OIDC `_verify_cron_request`; `_CRON_MAX_STALENESS_HOURS["autonomous-tick"] = 1` at `heartbeat.py:114`; 5+2 PASSED |
| **AUTO-07** (triage + compose prompts) | PASS | `prompts/autonomous_triage.md` 95 lines, JSON schema {should_act,reason,draft,topic_key} at :62-65; `prompts/autonomous.md` 110 lines, 4 placeholders at :1/3/5/7; 11/11 `TestAutonomousPrompts` PASSED |
| **AUTO-08** (5 seed fixtures + schema) | PASS | 5 fixtures (0001 overdue / 0002 quiet / 0003 followup / 0004 silence / 0005 gap); fixture 0003 has `should_speak=false` (D-13 regression guard); README "What should_speak Means" section :97; 37 schema runs PASSED |
| **AUTO-09** (eval runner) | PASS | `scripts/eval_tick_brain.py` 366 lines; `_SAFE_MODE_REASONS = {"parse_failure", "llm_error"}` at :62; precision/recall/F1 + per-trigger table; `sys.exit(main())` at :366 with `main()` returning 0 always; 4/4 `TestEvalScript` PASSED |
| **INFRA-01** (DEPLOYMENT.md 9-job table + Groq + Five Fingers + Firestore index) | PASS | 9 unique `klaus-*` job-ids; §14d klaus-reflect block, §14e klaus-autonomous-tick block; `TICK_BRAIN_API_KEY` secret §20 + rotation; §21 Five Fingers quirk + migration paragraph (`gcloud scheduler jobs delete five-fingers`); §22 composite index on followups(status, due_at); 8/8 `TestDeploymentCompleteness` PASSED |

---

## Cross-Cutting Checks

| Check | Status | Evidence |
|-------|--------|----------|
| Tick-brain backward compat (heartbeat unchanged) | PASS | `heartbeat.py:721 brain.think(prompt)` — no `system_override` → default `None` → `purpose="tick"` / `"tick_fallback"` preserved (Plan 05 WARNING 1 guard) |
| Singleton orchestrator (~42/day → 1) | PASS | `_get_orchestrator` at `autonomous.py:393`; `test_orchestrator_is_module_singleton` PASSED |
| D-19 sentinel fallback to tick_brain draft | PASS | `autonomous.py:772 if not final_text or any(s in final_text for s in _SMART_LOOP_ERROR_SENTINELS)` → falls back to `draft`; `test_layer2_returns_smart_loop_error_sentinel_falls_back_to_draft` PASSED |
| Layer-2 placeholders resolved BEFORE `_run_smart_loop` | PASS | `render_smart_system` extracted in `core/main.py:221`; `test_layer2_smart_system_has_placeholders_resolved` PASSED |
| D-18 inject_into_conversation=True | PASS | `grep -c "inject_into_conversation=True" core/autonomous.py` = 5 (≥ 2 required) |
| D-14 defer force-fire at count ≥ 3 | PASS | `_DEFER_FORCE_FIRE_THRESHOLD` 4 hits; `test_defer_force_fire_at_three` PASSED |
| Pitfall 2 (synthetic message does NOT pollute history) | PASS | `test_synthetic_message_does_not_pollute_history` PASSED — `handle_message` not called, `conversation_manager.append` not called |
| Narrow calendar gate (single non-conflicting event = quiet, SC-3) | PASS | `_calendar_has_gap_or_overload`; 4 dedicated tests PASSED |

---

## Test Suite Results

Command: `pytest tests/test_autonomous.py tests/test_tick_brain.py tests/test_firestore_db.py tests/test_prompts.py tests/test_evals.py tests/test_heartbeat.py tests/test_eval_script.py tests/test_main_render_smart_system.py tests/test_tools.py tests/test_docs.py` + `tests/test_web_server.py`

| Suite | Result |
|-------|--------|
| test_autonomous.py | 31 PASSED |
| test_tick_brain.py | 27 PASSED |
| test_firestore_db.py | 21 PASSED |
| test_prompts.py | 11 PASSED |
| test_evals.py | 37 PASSED |
| test_heartbeat.py | 16 PASSED (1 deselected — see below) |
| test_eval_script.py | 4 PASSED |
| test_main_render_smart_system.py | 8 PASSED |
| test_tools.py | 13 PASSED |
| test_docs.py | 8 PASSED |
| test_web_server.py | 5 PASSED |
| **Total** | **181/181 PASSED, 1 deselected** |

### Pre-existing env-only failures (NOT Phase 18 regressions)

- `tests/test_heartbeat.py::test_cron_heartbeat_rejects_unauthenticated` — sys.modules pollution from prior store-test mocks + lifespan KeyError on `TELEGRAM_BOT_TOKEN`. Reproduced on HEAD with Plan 18 changes stashed. Documented in `deferred-items.md` (Plan 18-01 entry).
- Local env historically missing `fastapi` / `google.generativeai` / `googleapiclient` (deferred-items.md Plans 18-04, 18-08, 18-09). Current `.venv` has fastapi installed so `test_web_server.py` now passes; the other historical blockers were docs-only at the time.

---

## Phase Goal Achievement

**Does the codebase deliver "judgment-driven proactive outreach + repeat-suppression + eval harness"?**

YES at code level. All wiring is real, not stubbed:

- The 3-layer pipeline is fully present (Layer 0 gather → Layer 1 triage → Layer 2 compose) with the empty-signal gate (D-11) gating the entire pipeline before any LLM call.
- Repeat-suppression is wired success-only (D-10) and the prior day's topics flow back into the triage prompt as `today_outreach_log` (informative, not blocking — D-06).
- The 3 follow-up CRUD tools satisfy AUTO-05's spirit ("Klaus manages his own check-backs"); the dedicated follow-up path with defer/force-fire (D-13/D-14) is implemented.
- Eval harness reuses the production `_build_triage_prompt` byte-for-byte (BLOCKER 4 fix) — no eval-vs-prod drift risk.
- DEPLOYMENT.md INFRA-01 is comprehensive: 9-job inventory, both new gcloud blocks, Groq secret rotation, Five Fingers migration, Firestore composite index.

**The remaining work is live verification of the 5 success criteria** in a staging deploy with real TickTick / Telegram / Cloud Scheduler / Groq.

---

## Issues Found

None blocking. Anti-pattern scan of phase-modified files surfaced zero TODO/FIXME/placeholder/stub patterns in production code; all empty-list defaults are sentinel initializers immediately overwritten by gather logic.

One pre-existing test-ordering flake (`test_cron_heartbeat_rejects_unauthenticated`) is documented in `deferred-items.md` and reproducible on HEAD without Phase 18 changes — not a Phase 18 regression.

---

## Recommendations

1. **Run SC-1..SC-5 live-tick smoke** per `18-VALIDATION.md § Manual-Only Verifications`. This is the only thing standing between AMBER and GREEN.
2. **Create Cloud Scheduler `klaus-autonomous-tick` job** using the §14e gcloud block in `docs/DEPLOYMENT.md` against staging, then prod.
3. **Create Firestore composite index** on `followups(status, due_at)` via §22 gcloud block — without it, the first `FollowupStore.list_due()` call returns FAILED_PRECONDITION with an auto-create link (acceptable but slower than pre-creating).
4. **Verify Groq `TICK_BRAIN_API_KEY` secret** exists in GCP Secret Manager and is bound to the Cloud Run deployment per §20.
5. **Grow eval fixtures retroactively** from `tick_logs/{date}/ticks/{HH:MM}` per D-21 over the first week of live ticks; target AUTO-08's 20–30 fixture count.
6. **Optional test-hygiene chore** (separate ticket): add per-module conftest cleanup of `sys.modules['google.cloud.firestore']` to fix the `test_cron_heartbeat_rejects_unauthenticated` ordering flake. Out of Phase 18 scope.

---

## Final Verdict: **GREEN (automated)** — promote to **GREEN** once SC-1..SC-5 live smoke passes

All 10 requirements satisfied at code level. All automated tests green (181/181). Architecture matches plan: singleton orchestrator, sentinel-return detection, D-10 success-only logging, D-13/D-14 follow-up lifecycle, narrow calendar gate (SC-3 cost control), backward-compatible tick-brain (heartbeat unchanged). No blocking issues. Phase 18 is shippable pending live-tick validation.

---
*Verified: 2026-05-23*
*Verifier: Claude (gsd-verifier)*
