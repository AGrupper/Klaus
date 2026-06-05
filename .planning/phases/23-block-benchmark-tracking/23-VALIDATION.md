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
| **Quick run command** | `python -m pytest tests/test_block_store.py tests/test_benchmark_store.py tests/test_seed_blocks.py -q` |
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

> Task IDs map to the `{plan}.{task-number}` of each plan's `<task>` entries. Filenames match the files each plan actually creates.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01.1 | 01 | 1 | BLOCK-01/03 | T-23-01 | Wave-0 RED tests: store never-raises, date-range get_current, facet validation | unit | `python -m pytest tests/test_block_store.py tests/test_benchmark_store.py tests/test_seed_blocks.py -q` | ❌ W0 | ⬜ pending |
| 01.2 | 01 | 1 | BLOCK-01 | T-23-01/02 | BlockStore/BenchmarkStore never raise on read; `_jsonsafe_doc` ISO-converts timestamps; get_current resolves by DATE RANGE (D-01); week_num derived (D-03) | unit | `python -m pytest tests/test_block_store.py tests/test_benchmark_store.py -q` | ❌ W0 | ⬜ pending |
| 01.3 | 01 | 1 | BLOCK-01 | T-23-03 | Auto-seed of 4 contiguous blocks is idempotent; dates derived from plan_start_date (D-01) | unit | `python -m pytest tests/test_seed_blocks.py -q` | ❌ W0 | ⬜ pending |
| 02.1 | 02 | 2 | BLOCK-01/03 | T-23-05 | 6 new tools brain-direct, excluded from WORKER_TOOL_SCHEMAS; update_plan not duplicated | unit | `python -m pytest tests/test_tool_registration_phase23.py -q` | ❌ W0 | ⬜ pending |
| 02.2 | 02 | 2 | BLOCK-01/03 | T-23-05/06/07 | get_plan/get_block_status surface date-range block; log_benchmark facet-validated; module imports cleanly | unit | `python -m pytest tests/test_tool_registration_phase23.py -q` | ❌ W0 | ⬜ pending |
| 03.1 | 03 | 2 | BLOCK-02 | T-23-09 | `benchmark_due` fires within 3-day window of block_end_date at W4/W8/W12 only; Block 4 excluded (D-02); benchmark-only night still sends | unit | `python -m pytest tests/test_proactive_alerts.py -k "benchmark or validity or stale" -q` | ⚠️ extend | ⬜ pending |
| 03.2 | 03 | 2 | BLOCK-02 | T-23-09/10/11 | Validity gate defers when HRV < 70% baseline OR ACWR > 1.2; re-prompts on clear; stale-window single prompt (D-07/08/09); set_benchmark_due before dedup gate | unit | `python -m pytest tests/test_proactive_alerts.py -q` | ⚠️ extend | ⬜ pending |
| 04.1 | 04 | 2 | BLOCK-01/03 | T-23-13 | Pre-cycle (before 2026-06-21): get_current() None, crons surface countdown, silent degrade (D-04); best-effort gather | unit | `python -m pytest tests/test_morning_briefing.py tests/test_weekly_training_review.py -k "block or current_block or precycle or pre_cycle" -q` | ⚠️ extend | ⬜ pending |
| 04.2 | 04 | 2 | BLOCK-01/03 | T-23-13/14 | Morning briefing + weekly review gather block state best-effort; week_num derived (D-03); current_block + block_benchmarks raw deltas | unit | `python -m pytest tests/test_morning_briefing.py tests/test_weekly_training_review.py -q` | ⚠️ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · File Exists: ❌ W0 = created in Wave 0 · ⚠️ extend = new tests added to an existing file*

---

## Wave 0 Requirements

- [ ] `tests/test_block_store.py` — BlockStore CRUD, get_current() DATE-RANGE resolution (incl. Block-2-without-start_block, D-01), week-math, never-raises (BLOCK-01)
- [ ] `tests/test_benchmark_store.py` — log_benchmark + get_benchmark_history cross-block comparison, facet validation (BLOCK-03)
- [ ] `tests/test_seed_blocks.py` — idempotent 4-block auto-seed from plan_start_date, contiguous date ranges (BLOCK-01)
- [ ] `tests/test_tool_registration_phase23.py` — 6 new brain-direct tools registered, worker-excluded, update_plan not duplicated (BLOCK-01/03)
- [ ] Extend `tests/test_proactive_alerts.py` — benchmark_due trigger + validity gate + re-prompt + stale window + benchmark-only-night send (BLOCK-02)
- [ ] Extend `tests/test_morning_briefing.py` / `tests/test_weekly_training_review.py` — best-effort block gather + pre-cycle silent degrade (BLOCK-01)

*Existing pytest infrastructure (conftest isolated_modules fixture, 845-test baseline) covers framework needs — no install required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Block/benchmark framing wording reads well in live Telegram crons | BLOCK-01/02 | Tone/voice is a judgment call (JARVIS/C-3PO persona), not assertable | Trigger 21:30 alert + morning briefing on a seeded block; confirm "Week N of 16, [phase]" line and benchmark prompt read naturally |
| Threshold-pace 3-session average pulls correct Postgres rows | BLOCK-03 | Depends on live Garmin/Postgres data + open question on column names | Run `get_block_status` against a block with ≥3 logged threshold sessions; confirm sec/km average |

*Open question for planner (from RESEARCH.md): RESOLVED — Plan 03 uses `fetch_garmin_today()` `hrv_overnight`/`hrv_baseline` for the D-08 "% of baseline" message; the categorical `compute_recovery_concern()` dict is NOT used for the raw baseline.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
