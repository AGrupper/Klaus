---
phase: 23
slug: block-benchmark-tracking
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-05
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pytest.ini / pyproject.toml (existing) |
| **Quick run command** | `python -m pytest tests/test_block_store.py tests/test_benchmark_store.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~60 seconds (full suite, 845+ tests) |

---

## Sampling Rate

- **After every task commit:** Run the quick run command for the touched store/module
- **After every plan wave:** Run the full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

> Populated/refined by the planner against the final task IDs. Rows below are the validation-architecture anchors from RESEARCH.md.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | 01 | 1 | BLOCK-01 | — | BlockStore/BenchmarkStore never raise on read; `_jsonsafe_doc` ISO-converts timestamps | unit | `python -m pytest tests/test_block_store.py -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | BLOCK-01 | — | week_num derived from plan_start_date (no stored truth, D-03) | unit | `python -m pytest tests/test_block_store.py -k week_math -q` | ❌ W0 | ⬜ pending |
| TBD | 02 | 1/2 | BLOCK-01 | — | Auto-seed of 4 blocks is idempotent; dates derived from plan_start_date (D-01) | unit | `python -m pytest tests/test_seed_blocks.py -q` | ❌ W0 | ⬜ pending |
| TBD | 03 | 2 | BLOCK-02 | — | `benchmark_due` fires within 3-day window of block_end_date at W4/W8/W12 only (D-02) | unit | `python -m pytest tests/test_proactive_alerts.py -k benchmark -q` | ❌ W0 | ⬜ pending |
| TBD | 03 | 2 | BLOCK-02 | — | Validity gate defers when HRV < 70% baseline OR ACWR > 1.2; re-prompts on clear; stale-window single prompt (D-07/08/09) | unit | `python -m pytest tests/test_proactive_alerts.py -k validity_gate -q` | ❌ W0 | ⬜ pending |
| TBD | 04 | 2 | BLOCK-03 | — | `log_benchmark` records per-facet; `get_benchmark_history` returns cross-block deltas | unit | `python -m pytest tests/test_benchmark_store.py -q` | ❌ W0 | ⬜ pending |
| TBD | 05 | 3 | BLOCK-01 | — | Pre-cycle (before 2026-06-21): get_current() returns None, crons surface countdown, no benchmark logic (D-04) | unit | `python -m pytest tests/test_morning_briefing.py tests/test_weekly_training_review.py -k block -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_block_store.py` — BlockStore CRUD, get_current() date resolution, week-math, never-raises (BLOCK-01)
- [ ] `tests/test_benchmark_store.py` — log_benchmark + get_benchmark_history cross-block comparison (BLOCK-03)
- [ ] `tests/test_seed_blocks.py` — idempotent 4-block auto-seed from plan_start_date (BLOCK-01)
- [ ] Extend `tests/test_proactive_alerts.py` — benchmark_due trigger + validity gate + re-prompt + stale window (BLOCK-02)
- [ ] Extend `tests/test_morning_briefing.py` / `tests/test_weekly_training_review.py` — best-effort block gather + pre-cycle silent degrade (BLOCK-01)

*Existing pytest infrastructure (conftest isolated_modules fixture, 845-test baseline) covers framework needs — no install required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Block/benchmark framing wording reads well in live Telegram crons | BLOCK-01/02 | Tone/voice is a judgment call (JARVIS/C-3PO persona), not assertable | Trigger 21:30 alert + morning briefing on a seeded block; confirm "Week N of 16, [phase]" line and benchmark prompt read naturally |
| Threshold-pace 3-session average pulls correct Postgres rows | BLOCK-03 | Depends on live Garmin/Postgres data + open question on column names | Run `get_block_status` against a block with ≥3 logged threshold sessions; confirm sec/km average |

*Open question for planner (from RESEARCH.md): confirm `compute_recovery_concern()` exposes raw HRV baseline number for the D-08 "78% of baseline" message before wiring the gate message.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
