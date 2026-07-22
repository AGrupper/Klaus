---
phase: 32
slug: unified-situation-ambient-memory
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-22
---

# Phase 32 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0 (project standard) |
| **Config file** | `pytest.ini` (`testpaths = tests`, `python_files = test_*.py`) |
| **Quick run command** | `pytest tests/test_<touched_file>.py -x` (targeted, per-file) |
| **Full suite command** | Run each `tests/test_*.py` file as a **separate** `pytest` invocation — full-suite-in-one-process segfaults (grpc/protobuf GC on Python 3.13). The ~1775+ backend-test baseline must hold across all files. |
| **Estimated runtime** | ~2–4s per targeted file; full per-file sweep several minutes |

> **HARD gotcha:** never `pytest tests/` in one process. Verify per-file. Python 3.13 venv (never 3.14).

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_<touched_file>.py -x`
- **After every plan wave:** Run every `tests/test_*.py` file individually (per-file, never combined); confirm total count ≥ pre-phase baseline
- **Before `/gsd:verify-work`:** Full per-file suite green, plus a live/staging exercise of the budget-guard fixture against a real `TickBrain.think()` call if feasible (not only the offline tokenizer count)
- **Max feedback latency:** ~4 seconds (targeted per-file)

---

## Per-Task Verification Map

| Req ID | Behavior | Test Type | Automated Command | File Exists | Status |
|--------|----------|-----------|-------------------|-------------|--------|
| MEM-01 | Auto-recall injects "Things you remember" block, best-effort/timeout, never blocks the turn | unit + forced-failure | `pytest tests/test_main.py -k ambient_recall -x` | ❌ W0 | ⬜ pending |
| MEM-01 | Score threshold filters weak matches from the ambient block | unit | `pytest tests/test_pinecone_db.py -k score_threshold -x` (verify exact file) | ❌ W0 | ⬜ pending |
| MEM-02 | Fresh/empty session (6h+ idle) prepends tail + boundary marker | unit | `pytest tests/test_main.py -k continuity_tail -x` | ❌ W0 | ⬜ pending |
| MEM-03 | `forget_memory` deletes by id; contradiction flag surfaces in nightly, never auto-deletes | unit | `pytest tests/test_tools.py -k forget_memory -x` + `pytest tests/test_reflection.py -k contradiction -x` | ❌ W0 | ⬜ pending |
| MEM-04 | `training_reality` reconciliation: evidence > self-report > intent; same-day+modality match; terminal "done" never re-flagged | unit (stale-fact fixture: same date+slot re-read after evidence lands) | `pytest tests/test_training_checkin.py -k training_reality -x` | ❌ W0 | ⬜ pending |
| MEM-05 | All 4 new gathers are context-only in `_is_empty_signals` | unit, one assertion per gather | `pytest tests/test_autonomous.py -k is_empty_signals -x` | ❌ W0 (extend) | ⬜ pending |
| MEM-05 | Token-budget guard: maximal rendered triage prompt + `max_tokens` ≤ Groq 8K TPM ceiling | unit (deterministic, no network — pure tokenizer count) | `pytest tests/test_token_budget.py -x` | ❌ W0 (new) | ⬜ pending |
| MEM-06 | Groq ledger increments on primary (not fallback) calls; heartbeat alerts at 80% once/day | unit | `pytest tests/test_tick_brain.py -k ledger -x` + `pytest tests/test_heartbeat.py -k groq_budget -x` | ❌ W0 | ⬜ pending |
| MEM-07 | `current_location`: home-default silent, travel-signal override, ambiguity → ask (never guesses) | unit, 3+ fixtures (home/travel/ambiguous) | `pytest tests/test_autonomous.py -k current_location -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> **Wave 0 is not a separate plan.** All "W0" files below are created INLINE by the TDD tasks of their owning plan: `tests/test_token_budget.py` + `tiktoken==0.13.0` by Plan 32-01; `tests/test_training_checkin.py` cases by Plan 32-04; the extended `tests/test_autonomous.py` / `test_main.py` / `test_pinecone_db.py` / `test_reflection.py` / `test_heartbeat.py` / `test_tick_brain.py` / `test_tools.py` cases by Plans 32-03/05/06/07/08. Every task carries a concrete automated verify command.

- [ ] `tests/test_token_budget.py` — new file, MEM-05 budget-guard test (real `tiktoken.get_encoding("o200k_harmony")` count, not a char estimate)
- [ ] `pip install tiktoken==0.13.0` added to `requirements.txt` + CI/test env before `test_token_budget.py` can run
- [ ] `tests/test_training_checkin.py` — verify exact filename via `ls tests/ | grep -i training`; may be new
- [ ] Confirm exact existing test filenames + current test-function naming before writing cases (`test_main.py`, `test_pinecone_db.py`, `test_reflection.py`, `test_heartbeat.py`, `test_tick_brain.py`, `test_tools.py`) with a `grep -l` pass at plan/execute time

*Framework install: none needed — pytest already fully set up.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Prompt-cache block split actually produces cache **reads** (not perpetual writes) after the fix | MEM-05 (cost north star) | Requires observing real Anthropic `cache_read_input_tokens` on live turns; offline tests only prove block structure | On a live deploy, send 2 back-to-back chat turns; confirm the 2nd turn's usage shows non-zero `cache_read_input_tokens` for the stable block |
| `current_location` ambiguity → nightly-ask actually fires | MEM-07 | Reuses Phase 31 nightly-ask surface; end-to-end proof needs the nightly path | Seed a conflicting travel signal, run the nightly; confirm the "still in <city>, Sir?" ask appears |

---

## Validation Sign-Off

- [x] All tasks have automated verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (`test_token_budget.py`, tiktoken install) — created inline by Plan 32-01
- [x] No watch-mode flags
- [x] Feedback latency < 4s (targeted per-file)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-22 (planning)
