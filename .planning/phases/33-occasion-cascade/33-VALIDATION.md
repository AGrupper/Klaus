---
phase: 33
slug: occasion-cascade
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-29
---

# Phase 33 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `33-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`pytest.ini`: `testpaths = tests`, `python_files = test_*.py`) |
| **Config file** | `pytest.ini` (repo root) |
| **Quick run command** | `pytest tests/test_autonomous.py tests/test_nightly_review.py tests/test_morning_briefing.py tests/test_weekly_training_review.py tests/test_token_budget.py -x` |
| **Full suite command** | `pytest tests/` — run per-file where possible; full-suite-in-one-process is known to segfault on grpc/protobuf GC (project MEMORY.md), so use the project's existing isolation convention |
| **Estimated runtime** | ~45 seconds (quick run) |

---

## Sampling Rate

- **After every task commit:** the subset of the quick-run command covering the
  files the task touched — **and always** `pytest tests/test_token_budget.py -x`
  for any task touching `prompts/autonomous_triage.md` or the triage-prompt
  rendering path in `core/autonomous.py`. The current maximal triage prompt is
  7,146 / 7,200 tokens — a 54-token margin. Never raise the guard target to mask
  prompt growth (CLAUDE.md invariant).
- **After every plan wave:** the full quick-run command set.
- **Before `/gsd:verify-work`:** full suite green (per-file), plus every manual
  UAT item below completed at least once.
- **Max feedback latency:** 60 seconds.

---

## Per-Task Verification Map

Task IDs are assigned by the planner; this map is keyed by requirement and is the
contract each task's `<automated>` verify must satisfy.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | OCC-01 | — | Judgment-skip records `skipped_by_judgment`; distinct from infra failure | unit | `pytest tests/test_nightly_review.py -k skipped_by_judgment -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-01 | — | Total infra failure still sends deterministic plain-text fallback | unit | `pytest tests/test_nightly_review.py -k infra_failure_plain_text -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-02 | T-33-01 | `/trigger/morning` fires immediately — no Garmin gate, no 10:15 cutoff | unit | `pytest tests/test_morning_briefing.py -k trigger_morning -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-02 | T-33-01 | `/trigger/morning` bearer-token auth; refuse-all when env unset | unit | `pytest tests/test_morning_briefing.py -k trigger_morning_auth -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-02 | — | Daily-state-doc dedup across snooze / second alarm / focus toggle | unit | `pytest tests/test_morning_briefing.py -k dedup -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-03 | — | Weekly runs as `occasion="weekly_review"` and never self-skips (D-03) | unit | `pytest tests/test_weekly_training_review.py -k never_self_skips -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-03 | — | Standing-directive veto still overrides the weekly (P31 D-21/D-22 intact) | unit | `pytest tests/test_weekly_training_review.py -k directive_veto -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-04 | — | Occasions bypass the `_is_empty_signals` gate | unit | `pytest tests/test_autonomous.py -k occasion_bypasses_empty -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-04 | — | Occasions bypass the Layer-0.5 change-detection gate | unit | `pytest tests/test_autonomous.py -k occasion_bypasses_change_detection -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-04 | — | Topic keys are `nightly:<date>` / `morning:<date>` / `weekly:<date>` | unit | `pytest tests/test_autonomous.py -k occasion_topic_key -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-04 | — | `OutreachLog.append` still gated on send success (D-10 invariant) | unit | `pytest tests/test_autonomous.py -k outreach_log_gated -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-05 | — | `MAX_TOOL_ITERATIONS=12` holds; exhaustion forces tools-stripped final answer | unit | `pytest tests/test_main.py -k exhaustion_forces_final_answer -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-05 | T-33-02 | Proactive calendar create checks for an existing planned row first | unit | `pytest tests/test_tools.py -k calendar_create_checks_existing -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-05 | — | Triage prompt stays under the 7,200-token admission ceiling | unit (gate) | `pytest tests/test_token_budget.py -x` | ✅ exists | ⬜ pending |
| TBD | TBD | TBD | OCC-06 | — | `OCCASION_CASCADE` off → legacy composer; on → cascade (nightly + weekly) | unit | `pytest tests/test_nightly_review.py tests/test_weekly_training_review.py -k occasion_cascade_flag -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-06 | T-33-01 | `/trigger/morning` ships dark: returns 202, sends nothing until wired (D-31) | unit | `pytest tests/test_morning_briefing.py -k trigger_morning_dark -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-06 | — | Heartbeat D-28 anomalies: errored occasion, skip streak, weekly-not-firing, undisclosed actions | unit | `pytest tests/test_heartbeat.py -k anomaly -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-06 | — | `enqueue_occasion` dispatches via Cloud Tasks, not a Starlette BackgroundTask (D-32) | unit | `pytest tests/test_task_dispatch.py -k occasion -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-07 | — | `get_recent_decisions(days)` returns verdict, reasoning, sends, actions, skip-cause | unit | `pytest tests/test_tools.py -k get_recent_decisions_returns -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-07 | — | Tool is brain-direct (in `SMART_AGENT_DIRECT_TOOLS`, never worker-delegated) | unit | `pytest tests/test_tools.py -k get_recent_decisions_direct -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | OCC-07 | — | Skips never surface unasked (D-27); undisclosed actions DO surface (D-25) | unit | `pytest tests/test_autonomous.py -k disclosure -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_autonomous.py` — occasion bypass of both gates, occasion topic-key format, D-10 gating regression, disclosure rules (OCC-04, OCC-07)
- [ ] `tests/test_nightly_review.py` — `skipped_by_judgment` vs infra-failure distinguishability, `OCCASION_CASCADE` flag branching (OCC-01, OCC-06)
- [ ] `tests/test_morning_briefing.py` — `/trigger/morning` auth / immediate-fire / no-cutoff / dark-ship / dedup; delete `handle_tick` state-machine tests alongside the deleted code (OCC-02)
- [ ] `tests/test_weekly_training_review.py` — never-self-skips (D-03), directive veto, flag branching (OCC-03, OCC-06)
- [ ] `tests/test_heartbeat.py` — the four D-28 anomaly checks (OCC-06)
- [ ] `tests/test_tools.py` — `get_recent_decisions` shape + brain-direct registration; calendar-write idempotency (OCC-05, OCC-07) *(planner: confirm exact filename for tool-handler tests)*
- [ ] `tests/test_task_dispatch.py` — `enqueue_occasion` (D-32)
- [ ] Framework install: **none** — `pytest` and `tiktoken` already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Judgment-skip vs infra-failure are distinguishable in production logs | OCC-01 (SC-1) | Requires real log surface, not a mock | In dev: force one run with both LLM tiers unreachable, and one with an empty-day fixture. Diff the state-doc / log output — the two outcomes must carry different status markers. |
| iOS Shortcut actually fires `/trigger/morning` at real wake time | OCC-02 | Depends on Amit's device automation | Fire the Shortcut against the deployed URL; confirm one briefing arrives. **Gate: must pass before retiring `morning-briefing-tick`** (D-31). |
| "Why didn't you message me yesterday?" returns a real answer | OCC-07 | End-to-end conversational behavior | Post-deploy, ask Klaus in chat; verify the answer cites actual recent tick/occasion verdicts. |
| Observation-window go/no-go | OCC-06 (D-29) | Subjective message-quality judgment — no automated gate by design | 3–4 days of dual-run; Amit decides whether the cascade output beats the legacy composers before Phase 35 deletes them. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `pytest tests/test_token_budget.py -x` green after every triage-prompt edit
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
