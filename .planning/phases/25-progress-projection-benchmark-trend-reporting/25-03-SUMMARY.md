---
phase: 25-progress-projection-benchmark-trend-reporting
plan: "03"
subsystem: core/weekly_training_review + prompts/weekly_training_review
tags: [tdd, projection, PROG-02, weekly-review, fence-lift, D-04, COACH-05, dense-pace]
dependency_graph:
  requires:
    - core/projection.py::project_goal_progress  # Plan 25-01
    - core/pace_history.py::fetch_dense_pace_history  # Plan 25-02
    - memory/firestore_db.py::BenchmarkStore
    - memory/firestore_db.py::UserProfileStore
    - memory/firestore_db.py::CoachingTopicStore
  provides:
    - core/weekly_training_review.py::_gather_week_data (block #8 projections, D-04 dense pace)
    - core/weekly_training_review.py::_derive_structural_topics (projection topic keys)
    - prompts/weekly_training_review.md (fence lifted, projection instruction)
  affects:
    - Sunday /cron/weekly-training-review: now injects projections dict + projection dedup keys
    - 21:30 cron: structural-critique:projection:<facet> dedup prevents same-day re-raise
tech_stack:
  added: []
  patterns:
    - tdd-red-green
    - fail-open-gather-block
    - D-04-dense-Garmin-vs-sparse-BenchmarkStore
    - COACH-05-write-after-send-dedup
    - D-01-confidence-tiers
    - D-02-behind-one-rec-your-call-Sir
key_files:
  created: []
  modified:
    - core/weekly_training_review.py
    - prompts/weekly_training_review.md
    - tests/test_weekly_training_review.py
    - tests/test_prompts.py
decisions:
  - "Gather block #8 uses local imports (lazy, consistent with all other blocks) so patch() mocks resolve at call time"
  - "test fixture _ensure_firestore_stubs() pre-populates sys.modules for google.cloud + dotenv + mcp_tools to enable patch() resolution in Python 3.14 test env where wheels are absent"
  - "threshold_pace dense-to-sparse logic: fetch_dense_pace_history first; empty list triggers BenchmarkStore fallback (D-04 exactly)"
  - "projection keys emitted by _derive_structural_topics flow unchanged through existing coaching_topics_included post-send loop (Extension point C — no new write code)"
  - "November speed goals (3k_time, 400m_time) documented as non-projectable in prompt (RESEARCH open question 3)"
metrics:
  duration_seconds: 1400
  completed_date: "2026-06-08"
  tasks_completed: 3
  files_created: 0
  tests_added: 5
---

# Phase 25 Plan 03: Projection Gather + Prompt Fence Lift Summary

**One-liner:** Sunday weekly review now computes per-facet projections server-side via the Plan-01 helper (D-04 dense Garmin pace / sparse BenchmarkStore strength split), emits COACH-05 dedup keys, and the prompt instructs one consolidated pace-to-deadline block per D-01/D-02 with Week N of 16 framing preserved.

## What Was Built

**`core/weekly_training_review.py` — gather block #8 + `_derive_structural_topics` extension:**

- Gather block #8 (inside `_gather_week_data`, after block 7): loops over the 5 closed-set facets `["bench_press_1rm", "squat_1rm", "threshold_pace", "push_ups", "pull_ups"]`. For `threshold_pace`, calls `fetch_dense_pace_history(today_iso)` first; if that returns `[]`, falls back to `benchmarks.get_facet_history("threshold_pace", n=10)` (D-04). All other facets use `BenchmarkStore.get_facet_history`. Calls `project_goal_progress(facet, history, dated_goals, today_iso)` (Plan-01 helper) for each facet. Sets `data["projections"]` to the result dict. Wrapped in `try/except` → `data["projections"] = {}` on any error (fail-open, T-25-10).

- `_derive_structural_topics` extended: after the existing `session-quality` derivation, reads `week_data.get("projections") or {}` and emits `f"structural-critique:projection:{facet}"` for each facet where `result.get("confidence") != "no_data"` (at least 1 data point). Preserves first-seen-order dedup. No `CoachingTopicStore.add_topic` call (write-after-send D-10 preserved).

- `run_weekly_review` post-send loop unchanged — projection keys flow through `coaching_topics_included` into the existing loop at lines 417–426. No new write code (Extension point C).

**`prompts/weekly_training_review.md` — three fence lift edits:**

- Line 37: replaced "PHASE 25 FENCE — ABSOLUTELY FORBIDDEN" paragraph with "Pace-to-deadline projection (PROG-02)" instruction: D-01 tiers (≥2pts / 1pt / 0pts), confidence-label-names-count, on-track/behind framing with D-02 "one ranked recommendation + your call, Sir". Tier A target vs Tier B measured trend distinguished.
- Line 47: removed "— never a dated projection:" clause; replaced with "for within-block status; the dated projection block follows separately:" (Week N of 16 preserved).
- Line 147 (Voice Rules): replaced "Never project to a deadline — report current/within-block movement only (Phase 25 fence)" with D-01 projection directive.
- Added note: November speed goals (3k_time, 400m_time) have no benchmark facet and cannot be projected.

**Tests (TDD RED → GREEN):**

- `test_gather_includes_projections`: confirms `data["projections"]` key is a dict on happy path (PROG-02-H)
- `test_projection_gather_fails_open`: confirms `data["projections"] == {}` when exception, no raise (PROG-02-I)
- `test_threshold_pace_uses_dense_garmin`: asserts `fetch_dense_pace_history` called; dense points reach `project_goal_progress`; empty dense triggers BenchmarkStore fallback (D-04)
- `test_derive_projection_topics`: `structural-critique:projection:bench_press_1rm` emitted for `confidence="low"`; `squat_1rm` with `confidence="no_data"` suppressed (PROG-02-M)
- `test_no_phase25_fence` (test_prompts.py): asserts "PHASE 25 FENCE" and "ABSOLUTELY FORBIDDEN" absent; "Week" present (PROG-02-L)

## TDD Gate Compliance

- RED commit: `adf4409` — `test(25-03): add failing tests for projection gather, dense pace source, and prompt fence (RED)` — all 5 tests fail because gather block #8 not yet implemented and fence still present
- GREEN commit (Task 2): `65b2ccc` — `feat(25-03): extend _gather_week_data (block #8) + _derive_structural_topics (GREEN)` — WTR projection tests pass
- GREEN commit (Task 3): `5e9538b` — `feat(25-03): lift Phase-24 fence in weekly_training_review.md` — prompt test passes

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Lazy imports in gather block #8 (inside try block) | Consistent with blocks 1–7; patch() mocks resolve at call time, not module load |
| `_ensure_firestore_stubs()` in test fixture | Python 3.14 test env lacks google.cloud wheels; stubs allow patch() dotted-path resolution without segfault risk |
| `threshold_pace` dense → sparse fallback order | D-04 decision: Garmin Postgres activities give denser trend; BenchmarkStore is the safety net |
| Projection keys flow through existing post-send loop | Extension point C — zero new write code in run_weekly_review; COACH-05 gate preserved unchanged |
| Speed goals note in prompt | Closes RESEARCH open question 3: 3k_time/400m_time have no BenchmarkStore facet; brain told to acknowledge but not fabricate |

## Success Criteria Verification

| Criterion | Status |
|-----------|--------|
| `python3 -m pytest tests/test_weekly_training_review.py -x -k projection` exits 0 | PASS (5/5) |
| `python3 -m pytest tests/test_prompts.py -x -k phase25` exits 0 | PASS (1/1) |
| `grep "fetch_dense_pace_history" core/weekly_training_review.py` shows dense source in block #8 | PASS |
| `grep -E "PHASE 25 FENCE|ABSOLUTELY FORBIDDEN" prompts/weekly_training_review.md` returns nothing | PASS |
| `grep "Week" prompts/weekly_training_review.md` matches | PASS |
| No `CoachingTopicStore.add_topic` in `_gather_week_data` or `_derive_structural_topics` | PASS |
| Prompt contains "Pace-to-deadline" projection instruction | PASS |
| Prompt distinguishes Tier A target from Tier B measured trend | PASS |
| Behind framing = exactly ONE ranked recommendation + "your call, Sir" | PASS |
| November speed goals (3k_time, 400m_time) noted as non-projectable | PASS |

## Commits

| Task | Commit | Files |
|------|--------|-------|
| Task 1: TDD RED — failing tests | adf4409 | tests/test_weekly_training_review.py, tests/test_prompts.py |
| Task 2: GREEN — gather block #8 + _derive_structural_topics | 65b2ccc | core/weekly_training_review.py |
| Task 3: Prompt fence lift | 5e9538b | prompts/weekly_training_review.md |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Python 3.14 test env lacks google.cloud wheels**
- **Found during:** Task 1 (RED) — `patched_sources_with_projection` fixture could not call `patch("memory.firestore_db.*")` because `memory.firestore_db` couldn't be imported
- **Issue:** `google.cloud.firestore` native wheels not installed in Python 3.14 venv; `importlib.import_module("memory.firestore_db")` raised `ModuleNotFoundError` before patch() could resolve the attribute path
- **Fix:** Added `_ensure_firestore_stubs()` helper to the test file that pre-populates `sys.modules` with minimal stubs for `google.cloud.firestore`, `google.api_core`, `dotenv`, `pinecone`, and `mcp_tools` submodules — same pattern as `_install_tools_mocks()` in `test_tool_registration_phase25.py`
- **Files modified:** `tests/test_weekly_training_review.py`
- **Commit:** adf4409 (included in RED commit)

## Known Stubs

None — gather block #8 calls `project_goal_progress` (Plan-01) and `fetch_dense_pace_history` (Plan-02) which are both complete implementations. All five facets loop through the real helper.

## Threat Flags

None. No new network endpoints, no new auth paths, no new schema changes at trust boundaries.

## Self-Check: PASSED

- `core/weekly_training_review.py` exists: FOUND
- `prompts/weekly_training_review.md` exists: FOUND
- Commit adf4409 (RED): FOUND
- Commit 65b2ccc (GREEN): FOUND
- Commit 5e9538b (fence lift): FOUND
- All 5 projection tests pass: CONFIRMED
- Prompt test passes: CONFIRMED
