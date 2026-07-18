---
phase: 31
slug: standing-directives
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-19
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

- **After every task commit:** Run `pytest tests/test_firestore_db.py tests/test_tools.py tests/test_firestore_conversation.py tests/test_main.py tests/test_autonomous.py tests/test_reflection.py -x` (the 6 files this phase touches)
- **After every plan wave:** Full suite run per-file (known segfault workaround — never single-process `pytest tests/`)
- **Before `/gsd:verify-work`:** Per-file full suite green; re-confirm the 1775+ baseline count did not drop
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD (filled by planner) | — | — | DIR-01 | — | N/A | unit | `pytest tests/test_tools.py -k standing_directive -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | DIR-02 | — | N/A | unit | `pytest tests/test_firestore_db.py -k StandingDirectiveStore -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | DIR-03 | — | N/A | integration | `pytest tests/test_main.py tests/test_autonomous.py -k standing_directives -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | DIR-04 | — | N/A | unit | `pytest tests/test_tools.py -k standing_directive -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | DIR-05 | — | N/A | unit | `pytest tests/test_firestore_db.py -k supersede -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | DIR-06 | — | N/A | unit | `pytest tests/test_firestore_conversation.py -k recent_window -x` | ❌ W0 | ⬜ pending |
| TBD | — | — | DIR-07 | — | N/A | integration | `pytest tests/test_reflection.py -k directive_proposal -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_firestore_db.py` — `TestStandingDirectiveStore` class (add/list_active/cancel/supersede/expire); no existing coverage (store is new this phase)
- [ ] `tests/test_tools.py` — 3 new handler tests (`set_standing_directive` / `list_standing_directives` / `cancel_standing_directive`), mirroring the existing `FollowupStore`-handler test shape
- [ ] `tests/test_firestore_conversation.py` — `get_recent_window` coverage: (a) returns messages within 24h ignoring the 6h session timeout, (b) tolerates legacy messages without `ts`, (c) respects `max_messages` cap
- [ ] `tests/test_reflection.py` — (a) `_gather_day` uses `get_recent_window` not `conv_store.get`, (b) reaction-pairing classification (replied / ignored-topic / ignored) against `OutreachLogStore` entries, (c) self-directive-proposal fixture, (d) veto-then-no-re-propose fixture (D-13)
- [ ] `tests/test_autonomous.py` — (a) `_gather_standing_directives` context-only exclusion from `_is_empty_signals`, (b) directives block in `_build_triage_prompt` snapshot, (c) directives block in Layer-2 + follow-up compose content
- [ ] `tests/test_main.py` — `{standing_directives}` placeholder resolution in `render_smart_system`, asserting ORDERING (after `{training_profile}`, before `{today_date}`) — cache-prefix ordering is load-bearing
- Framework install: none — pytest + existing monkeypatch/`isolated_modules` fixtures cover this pattern

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Capture ack reads as JARVIS-register Klaus ("Standing order, Sir: …") | DIR-01 | Voice/tone is a judgment call | State a lasting wish in Hub chat; confirm one-line echo + expiry read-back in Klaus's voice |
| Nightly message weaves directive items into narrative (no fixed section) | DIR-06/07 | Compose-quality judgment | Inspect a live nightly message on a day with directive activity |
| Step-0 veto topic-scoping doesn't over-suppress unrelated outreach | DIR-03 | Judgment-quality; negative fixtures arrive Phase 35 | Observe tick behavior with an active narrow directive; unrelated topics still go out |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
