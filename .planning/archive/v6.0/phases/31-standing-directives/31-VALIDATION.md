---
phase: 31
slug: standing-directives
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-19
updated: 2026-07-19
---

# Phase 31 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`pytest.ini`: `testpaths = tests`, `python_files = test_*.py`) |
| **Config file** | `pytest.ini` |
| **Quick run command** | `pytest tests/test_firestore_conversation.py tests/test_autonomous.py tests/test_reflection.py -x` |
| **Full suite command** | Per-file runs over `tests/` (single-process `pytest tests/` segfaults — grpc/protobuf gotcha; 1775+ passing baseline must hold) |
| **Estimated runtime** | ~60 seconds (touched files); several minutes per-file full sweep |

---

## Sampling Rate

- **After every task commit:** Run the touched test file(s) named in that task's `<verify>` block; then the phase's touched-files sweep: `pytest tests/test_firestore_db.py tests/test_tools.py tests/test_firestore_conversation.py tests/test_main_render_smart_system.py tests/test_autonomous.py tests/test_morning_briefing.py tests/test_weekly_training_review.py tests/test_reflection.py tests/test_nightly_review.py -x`
- **After every plan wave:** Full suite run per-file (known segfault workaround — never single-process `pytest tests/`)
- **Before `/gsd:verify-work`:** Per-file full suite green; re-confirm the 1775+ baseline count did not drop
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 31-01-T1 | 31-01 | 1 | DIR-02, DIR-05 | T-31-02 | never hard-delete (status-transition-only) | unit (RED) | `pytest tests/test_firestore_db.py -k StandingDirectiveStore -x` | ❌ W0 (this task creates it) | ⬜ pending |
| 31-01-T2 | 31-01 | 1 | DIR-02, DIR-05 | T-31-02 | never hard-delete (status-transition-only) | unit | `pytest tests/test_firestore_db.py -k StandingDirectiveStore -x` | ✅ after T1 | ⬜ pending |
| 31-02-T1 | 31-02 | 1 | DIR-06 | T-31-03 | Anthropic-backend read (reflection) | unit (RED) | `pytest tests/test_firestore_conversation.py -k "recent_window or ts" -x` | ❌ W0 (this task creates it) | ⬜ pending |
| 31-02-T2 | 31-02 | 1 | DIR-06 | T-31-03 | Anthropic-backend read (reflection) | unit | `pytest tests/test_firestore_conversation.py -x` | ✅ after T1 | ⬜ pending |
| 31-03-T1 | 31-03 | 2 | DIR-01, DIR-04, DIR-05 | T-31-01 | capture scoped to live Amit chat turns only | unit | `pytest tests/test_tools.py -k standing_directive -x` | ✅ (extends test_tools.py) | ⬜ pending |
| 31-03-T2 | 31-03 | 2 | DIR-03 | T-31-01 | cache-safe prompt placement | unit | `pytest tests/test_main_render_smart_system.py -k "standing_directive or StandingDirectives" -x` | ✅ (extends file) | ⬜ pending |
| 31-04-T1 | 31-04 | 3 | DIR-03 | T-31-04 | context-only gather (never wakes free tier) | unit | `pytest tests/test_autonomous.py -k "standing_directive or empty_signal" -x` | ✅ (extends file) | ⬜ pending |
| 31-04-T2 | 31-04 | 3 | DIR-03 | T-31-07 | topic-scoped Step-0 veto | integration | `pytest tests/test_autonomous.py -k "standing_directive or triage or compose" -x` | ✅ (extends file) | ⬜ pending |
| 31-05-T1 | 31-05 | 3 | DIR-03 | T-31-08, T-31-09 | skip logged distinctly; hub contract intact | integration | `pytest tests/test_morning_briefing.py -k "directive or skip" -x` | ✅ (extends file) | ⬜ pending |
| 31-05-T2 | 31-05 | 3 | DIR-03 | T-31-08 | skip logged distinctly from failure | integration | `pytest tests/test_weekly_training_review.py -k "directive or skip" -x` | ✅ (extends file) | ⬜ pending |
| 31-06-T1 | 31-06 | 3 | DIR-06 | T-31-03 | 24h window fixes bug B3 | unit | `pytest tests/test_reflection.py -k "recent_window or gather_day or reaction" -x` | ✅ (extends file) | ⬜ pending |
| 31-06-T2 | 31-06 | 3 | DIR-02, DIR-07 | T-31-06, T-31-10 | single-signal (locked); writes non-fatal to journal | integration | `pytest tests/test_reflection.py -k "proposal or expiry or prune or veto or reflection_json" -x` | ✅ (extends file) | ⬜ pending |
| 31-06-T3 | 31-06 | 3 | DIR-03, DIR-07 | T-31-06 | nightly exempt; rendered block + veto option | integration | `pytest tests/test_nightly_review.py -k "directive or veto or expiry" -x` | ✅ (extends file) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 gaps are created inside the plans themselves as the first (RED) task of each foundational plan, not as a separate pre-wave:

- [ ] `tests/test_firestore_db.py` — `TestStandingDirectiveStore` (add/list_active/cancel/supersede/expire, cache behavior) — created by 31-01-T1 (RED)
- [ ] `tests/test_firestore_conversation.py` — `get_recent_window` coverage: (a) 24h window ignoring 6h timeout, (b) legacy no-ts tolerance, (c) max_messages cap, (d) ts stamping — created by 31-02-T1 (RED)
- [ ] `tests/test_tools.py` — 3 handler tests + brain-direct-registration assertions — added in 31-03-T1 (file exists)
- [ ] `tests/test_main_render_smart_system.py` — `{standing_directives}` placeholder resolution + ORDERING assertion (after `{training_profile}`, before `{today_date}`) — added in 31-03-T2 (file exists)
- [ ] `tests/test_autonomous.py` — context-only exclusion from `_is_empty_signals` + triage/compose injection — added in 31-04 (file exists)
- [ ] `tests/test_morning_briefing.py` / `tests/test_weekly_training_review.py` — directive-skip veto + `skipped_by_directive` + hub-contract-intact — added in 31-05 (files exist)
- [ ] `tests/test_reflection.py` — `_gather_day` uses `get_recent_window`; reaction pairing; self-directive proposal; veto-then-no-re-propose (D-13) — added in 31-06 (file exists)
- [ ] `tests/test_nightly_review.py` — rendered directives block + `directive_items` weaving + veto option + exemption — added in 31-06 (file exists)
- Framework install: none — pytest + existing monkeypatch/`isolated_modules` fixtures cover this pattern

> **Correction (from 31-PATTERNS.md):** the render-smart-system placeholder tests live in
> `tests/test_main_render_smart_system.py`, NOT `tests/test_main.py` (the earlier draft cited the wrong file).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Capture ack reads as JARVIS-register Klaus ("Standing order, Sir: …") | DIR-01 | Voice/tone is a judgment call | State a lasting wish in Hub chat; confirm one-line echo + expiry read-back in Klaus's voice |
| Nightly message weaves directive items into narrative (no fixed section) | DIR-06/07 | Compose-quality judgment | Inspect a live nightly message on a day with directive activity |
| Step-0 veto topic-scoping doesn't over-suppress unrelated outreach | DIR-03 | Judgment-quality; negative fixtures arrive Phase 35 | Observe tick behavior with an active narrow directive; unrelated topics still go out |
| Prompt-cache stability after `{standing_directives}` insertion | DIR-03 | Requires live cache-read metering (Phase 30.5) | After deploy, confirm `cache_read_input_tokens` does not drop toward 0 (Pitfall 3) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (each foundational plan's first task is RED)
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (planner, 2026-07-19) — `wave_0_complete` flips true during execution once the RED scaffolds (31-01-T1, 31-02-T1) land.
