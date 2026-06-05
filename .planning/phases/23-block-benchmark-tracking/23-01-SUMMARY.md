---
phase: 23-block-benchmark-tracking
plan: "01"
subsystem: memory/stores
tags: [firestore, block-store, benchmark-store, tdd, seed-script]
dependency_graph:
  requires: []
  provides: [BlockStore, BenchmarkStore, get_week_num, seed_training_blocks]
  affects: [memory/firestore_db.py, UserProfileStore._SCAFFOLD]
tech_stack:
  added: []
  patterns: [date-range-resolution, never-raises-read, merge-true-write, _jsonsafe_doc]
key_files:
  created:
    - scripts/seed_training_blocks.py
    - tests/test_block_store.py
    - tests/test_benchmark_store.py
    - tests/test_seed_blocks.py
  modified:
    - memory/firestore_db.py
decisions:
  - "get_current() resolves by DATE RANGE (start_date <= today <= end_date), NOT status==active filter — D-01 automatic inter-block transition contract"
  - "5-facet closed set enforced via ValueError in log_benchmark (T-23-01)"
  - "get_week_num() is a module-level pure function — never stored as truth (D-03)"
  - "UserProfileStore._SCAFFOLD gets current_block_id: None — primed by seed script to Block 1"
  - "seed_if_absent patches at memory.firestore_db.BlockStore (lazy imports inside function)"
metrics:
  duration: "~20 minutes"
  completed: "2026-06-05"
  tasks_completed: 3
  tasks_total: 3
  files_created: 4
  files_modified: 1
requirements: [BLOCK-01, BLOCK-03]
---

# Phase 23 Plan 01: BlockStore + BenchmarkStore + Seed Script Summary

## One-liner

Date-range BlockStore + 5-facet BenchmarkStore in Firestore, with `get_week_num` helper and idempotent `seed_training_blocks.py` seeding 4 contiguous 16-week mesocycle blocks.

## What Was Built

### BlockStore (`memory/firestore_db.py`)

- Collection: `training_blocks`, doc_id `{YYYY-MM-DD}_{label_slug}`
- `get_current(today)` — **DATE-RANGE resolution (D-01)**: streams all blocks, returns the single block where `start_date <= today <= end_date`. Does NOT filter on `status`. This means Block 1 → Block 2 transition is automatic as time advances (even if `start_block()` is never called).
- `get_all()` — returns all blocks, never raises
- `upsert(block)` — merge=True + SERVER_TIMESTAMP, re-raises on failure
- `set_benchmark_due(block_id, due)` — merge-writes `benchmark_due` flag
- `start_block(block_id)` / `end_block(block_id)` — bookkeeping: status `active`/`complete` via merge. NOT preconditions of `get_current()`.
- Every `snap.to_dict()` wrapped in `_jsonsafe_doc()` (Pitfall 1 prevention)

### `get_week_num(plan_start_date, today)` (module-level)

- Returns `(today - start).days // 7 + 1` or `None` pre-cycle (D-03)
- Never stored as truth — always derived from `plan_start_date`

### BenchmarkStore (`memory/firestore_db.py`)

- Collection: `benchmarks`, doc_id `{YYYY-MM-DD}_{facet}`
- `log_benchmark(date, facet, value, unit, block_id, notes)` — validates facet against 5-facet closed set `{bench_press_1rm, squat_1rm, push_ups, pull_ups, threshold_pace}`, raises `ValueError` on unknown (T-23-01). Writes merge=True + SERVER_TIMESTAMP. Re-raises on Firestore failure.
- `get_facet_history(facet, n=10)` — streams all, filters by facet, sorts date-desc, caps at n. Never raises.
- `get_block_benchmarks(block_id)` — FieldFilter server-side query by block_id, date-desc. Never raises.

### UserProfileStore._SCAFFOLD

- Added `"current_block_id": None` — FK primed by seed script to Block 1

### `scripts/seed_training_blocks.py`

- `build_blocks_list()` — pure builder, no env deps. Returns 4 blocks from blueprint §4:
  - Block 1: "Aerobic Base" 2026-06-21→2026-07-18 status "active"
  - Block 2: "Capacity Build" 2026-07-19→2026-08-15 status "pending"
  - Block 3: "Deep Waters → Peak Engine" 2026-08-16→2026-09-12 status "pending"
  - Block 4: "Race Specificity → Taper → Race Week" 2026-09-13→2026-10-10 status "pending"
  - All: 5 standard facets, `benchmark_due=False`, `weekly_split_override=None`
  - Ranges are contiguous and non-overlapping (gap of exactly 1 day between blocks)
- `seed_if_absent(project_id, database, force)` — idempotency gate via `BlockStore.get_all()`; upserts 4 blocks + primes `current_block_id` FK; returns `True/False`
- `main()` — `--dry-run` (prints JSON, no writes), `--force`; `load_dotenv(override=True)` invariant

## Tests Written (38 total, all passing)

### `tests/test_block_store.py` (19 tests)
- `test_get_current_resolves_by_date_range` — Block 1 returned when today is in its range
- `test_get_current_returns_block2_without_start_block` — **D-01 contract**: Block 2 returned with no `start_block` call, Block 2 status still "pending"
- `test_get_current_returns_none_pre_cycle` / `test_get_current_returns_none_post_cycle`
- `test_get_current_never_raises` — RuntimeError → None
- `test_get_current_jsonsafe` — datetime in block → `json.dumps()` succeeds
- `test_week_num_formula_*` — 4 boundary tests
- `test_upsert_uses_merge_true` / `test_set_benchmark_due_writes_flag`
- `test_start_end_block_update_status` — bookkeeping-only via merge

### `tests/test_benchmark_store.py` (13 tests)
- `test_log_benchmark_idempotent` + `test_log_benchmark_payload_fields`
- `test_log_benchmark_rejects_unknown_facet` (ValueError)
- `test_log_benchmark_accepts_all_valid_facets[×5]` (parametrized)
- `test_get_facet_history` + `test_get_facet_history_capped_at_n` + doc_id attachment
- `test_benchmark_reads_never_raise_*` (both read paths)
- `test_get_block_benchmarks`

### `tests/test_seed_blocks.py` (11 tests)
- `test_build_blocks_list_returns_four` / labels / dates / facets
- `test_block_4_benchmark_due_false` / `test_blocks_all_benchmark_due_false`
- `test_blocks_cover_contiguous_date_range` — gap exactly 1 day between all consecutive blocks
- `test_blocks_block1_status_active` / `test_blocks_remaining_status_pending`
- `test_seed_idempotent` / `test_seed_force_overwrites`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing `firestore_v1.base_query` mock in BenchmarkStore test**
- **Found during:** Task 2 GREEN run
- **Issue:** `BenchmarkStore.get_block_benchmarks` imports `from google.cloud.firestore_v1.base_query import FieldFilter` inside the method; test mock only covered `google.cloud.firestore` but not `google.cloud.firestore_v1`, causing `ModuleNotFoundError`
- **Fix:** Added `google.cloud.firestore_v1.base_query` stub to `_install_firestore_mock()` in `tests/test_benchmark_store.py`
- **Files modified:** `tests/test_benchmark_store.py`
- **Commit:** fe1fdd6

**2. [Rule 1 - Bug] Wrong patch targets for seed idempotency tests**
- **Found during:** Task 3 test run
- **Issue:** `seed_if_absent` imports `BlockStore`/`UserProfileStore` lazily inside the function body; `patch("seed_training_blocks.BlockStore")` fails because those names are not module-level attributes
- **Fix:** Updated test to `patch("memory.firestore_db.BlockStore")` and `patch("memory.firestore_db.UserProfileStore")` — patching at the source module, not the importer
- **Files modified:** `tests/test_seed_blocks.py`
- **Commit:** a55f60d

## Known Stubs

None — all 4 blocks have real dates, real labels, real facets. No hardcoded empty values that flow to UI rendering.

## TDD Gate Compliance

- RED gate (test commit): 6a3ca21 — 38 failing tests, `BlockStore`/`BenchmarkStore`/`build_blocks_list` absent
- GREEN gate (feat commit): fe1fdd6 (stores), a55f60d (seed script) — all 38 tests passing

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: input-validation | memory/firestore_db.py | BenchmarkStore.log_benchmark validates facet against 5-facet closed set (T-23-01 — mitigated per threat register) |

## Self-Check: PASSED

Files verified:
- FOUND: memory/firestore_db.py
- FOUND: scripts/seed_training_blocks.py
- FOUND: tests/test_block_store.py
- FOUND: tests/test_benchmark_store.py
- FOUND: tests/test_seed_blocks.py
- FOUND: .planning/phases/23-block-benchmark-tracking/23-01-SUMMARY.md

Commits verified:
- FOUND: 6a3ca21 (RED tests)
- FOUND: fe1fdd6 (GREEN stores)
- FOUND: a55f60d (seed script)
