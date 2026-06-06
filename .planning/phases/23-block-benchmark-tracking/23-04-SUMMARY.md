---
phase: 23-block-benchmark-tracking
plan: "04"
subsystem: core/coaching-crons
tags: [morning-briefing, weekly-review, block, benchmark, best-effort-gather, tdd, prompt]
dependency_graph:
  requires: [BlockStore, BenchmarkStore, get_current, get_block_benchmarks]
  provides: [morning-briefing-block-gather, weekly-review-block-gather]
  affects: [core/morning_briefing.py, core/weekly_training_review.py, prompts/morning_briefing.md, prompts/weekly_training_review.md]
tech_stack:
  added: []
  patterns: [best-effort-try-except, silent-omit, date-range-resolution, derived-week-num, conditional-prompt-section]
key_files:
  created: []
  modified:
    - core/morning_briefing.py
    - core/weekly_training_review.py
    - prompts/morning_briefing.md
    - prompts/weekly_training_review.md
    - tests/test_morning_briefing.py
    - tests/test_weekly_training_review.py
decisions:
  - "Morning briefing: data['block'] (label, week_num, benchmark_due, end_date, block_id) when active; data['pre_cycle_countdown'] before 2026-06-21; NEITHER post-cycle (silent omit)"
  - "Weekly review: data['current_block'] = {**block, week_num} + data['block_benchmarks'] list; defaults None/[] on None block or failure; pre_cycle_countdown when pre-cycle"
  - "Active block resolved by date range via get_current() (D-01) — no start_block dependency at gather time"
  - "week_num derived inline from plan_start_date 2026-06-21 at gather time (D-03), never read from a stored field"
  - "Weekly review shows RAW block-over-block deltas only — no trend projection (deferred to Phase 25)"
  - "Both gathers best-effort try/except — None block / empty store / store failure degrade silently, never crash the cron (Pitfall 4)"
metrics:
  duration: "~25 minutes"
  completed: "2026-06-06"
  tasks_completed: 3
  tasks_total: 3
  files_created: 0
  files_modified: 4
requirements: [BLOCK-01, BLOCK-03]
---

# Phase 23 Plan 04: Block Context in Coaching Crons Summary

## One-liner

Best-effort block-state gather added to the morning briefing and Sunday weekly review crons (plus their prompts): "Week N of 16, [label]" framing, a pre-cycle countdown before the 2026-06-21 anchor, and this-block benchmarks as raw deltas in the weekly review — all silent-omit on None/empty/failure.

## What Was Built

### `core/morning_briefing.py` `_gather_data`
Best-effort `BlockStore.get_current()` gather appended after the nutrition block, before `return data`. When a block is active: `data["block"] = {label, week_num, benchmark_due, end_date, block_id}` with `week_num` derived inline from the 2026-06-21 anchor. When no block and pre-cycle: `data["pre_cycle_countdown"] = days_until` (only when > 0). Post-cycle with no block: neither key (silent omit). Wrapped in try/except `logger.warning("morning_briefing: block state fetch failed")`.

### `core/weekly_training_review.py` `_gather_week_data`
New "section 6. BlockStore + BenchmarkStore" after the UserProfileStore section. Active block → `data["current_block"] = {**block, "week_num": ...}` + `data["block_benchmarks"] = get_block_benchmarks(block_id)`. No block → `current_block=None`, `block_benchmarks=[]`, and `pre_cycle_countdown` when pre-cycle. On exception → defaults `current_block=None`, `block_benchmarks=[]` (matches the file's defensive-default convention).

### `prompts/morning_briefing.md`
New `## Current Training Block (when block key is present in data)` section: "Week {block.week_num} of 16 — {block.label}, sir." (+ benchmark-due clause), the pre_cycle_countdown line, and an explicit "omit when both absent" rule.

### `prompts/weekly_training_review.md`
Added `current_block`, `block_benchmarks`, `pre_cycle_countdown` to the data-key list plus a **Training block framing** rule: "Week N of 16, {label}" framing and per-facet RAW block-over-block deltas only — explicit "do NOT project trajectories/paces/trends (Phase 25)".

## Tests Written (7 new)

`tests/test_morning_briefing.py` (4, via a `_quiet_gather` helper that neutralizes the heavy collaborators so the block gather is the only meaningful work):
- `test_gather_data_includes_block_state` — active block → `data["block"]`, `week_num == 2` for 2026-06-28
- `test_gather_data_precycle_countdown` — 2026-06-12 → `pre_cycle_countdown == 9`, no `block`
- `test_gather_data_block_failure_silent` — store raises → neither key, no exception
- `test_gather_data_postcycle_no_active_silent` — 2026-11-01 + None → neither key

`tests/test_weekly_training_review.py` (3, fixture extended to stub BlockStore/BenchmarkStore):
- `test_gather_week_includes_current_block` — active block → `current_block` (with week_num) + stubbed `block_benchmarks`
- `test_gather_week_precycle` — None + pre-cycle date → `pre_cycle_countdown`, `current_block None`
- `test_gather_week_block_failure_sets_defaults` — store raises → `current_block None`, `block_benchmarks []`

Combined: 37 passed, 3 skipped across both files.

## Deviations from Plan

None. The `patched_sources` fixture was extended (not replaced) with `block_store`/`benchmark_store` handles defaulting to no active block, so all pre-existing weekly-review tests still pass unchanged.

## Known Stubs

None.

## TDD Gate Compliance

- RED gate: commit adding 7 failing block-gather tests
- GREEN gate: gather implementations + prompt rendering → 37 pass / 3 skip

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: dos-resilience | core/morning_briefing.py, core/weekly_training_review.py | Block gather best-effort try/except with if-block guards; cron always completes (T-23-13) |
| threat_flag: derived-truth | both crons | week_num derived from 2026-06-21 anchor at gather time, never stored — cannot drift (T-23-14) |

## Self-Check: PASSED

Files verified:
- FOUND: core/morning_briefing.py (BlockStore gather + pre_cycle_countdown)
- FOUND: core/weekly_training_review.py (BlockStore + BenchmarkStore gather)
- FOUND: prompts/morning_briefing.md (## Current Training Block)
- FOUND: prompts/weekly_training_review.md (current_block + block_benchmarks)
- FOUND: .planning/phases/23-block-benchmark-tracking/23-04-SUMMARY.md

Guards verified:
- `2026-06-21` derived-week formula present in both crons (grep count 3 each)
- both block gathers wrapped in try/except logger.warning
