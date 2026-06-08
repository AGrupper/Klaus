---
phase: 25-progress-projection-benchmark-trend-reporting
verified: 2026-06-08T00:00:00Z
status: passed
score: 3/3 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
deferred: []
human_verification: []
---

# Phase 25: Progress Projection & Benchmark Trend Reporting — Verification Report

**Phase Goal:** Klaus projects strength and pace trends against the dated Oct/Nov goals and reports on-track or behind; per-facet benchmark results are surfaced as improvement trajectories in the Sunday weekly review; this is the highest dependency-chain feature in the milestone.
**Verified:** 2026-06-08
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Klaus answers "am I on track for my October bench target?" by computing a trend from TrainingLogStore top-set history (or BenchmarkStore results) and projecting it to the deadline — not by citing the goal alone | VERIFIED | `_handle_get_goal_projection` in `core/tools.py:1823` calls `project_goal_progress` with real BenchmarkStore history; `project_goal_progress` computes LSQ trend and returns `projected_value`, `gap`, `on_track`; smart_agent prompt (lines 91–97) instructs brain to cite computed number+gap when data available |
| 2 | The Sunday weekly review surfaces a pace-to-deadline status for at least one goal facet: "current trend puts you at [X] by [date] — on track / N weeks behind" | VERIFIED | `_gather_week_data` block #8 (`core/weekly_training_review.py:243–271`) loops over all 5 facets and injects `data["projections"]`; `prompts/weekly_training_review.md` lines 37–42 contain the "Pace-to-deadline projection (PROG-02)" instruction with on-track/behind framing |
| 3 | The projection explicitly distinguishes blueprint target (Tier A) from current measured trend (Tier B) — no fabricated convergence claims | VERIFIED | `project_goal_progress` returns `projected_value=None` for 0/1-point histories (no fabricated number); `weekly_training_review.md` line 41 states "Tier A target (blueprint) is always distinguished from Tier B measured trend"; `smart_agent.md` line 97 carries the same instruction; the pure function never invents a number (stdlib-only, zero I/O) |

**Score:** 3/3 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/projection.py` | `project_goal_progress` pure function + `FACET_DIRECTION` + `GOAL_METRIC_TO_FACET` | VERIFIED | 333 lines; defines all three exports; stdlib-only imports confirmed; zero I/O; `today_iso` parameter only (no `date.today()` in executable code) |
| `tests/test_projection.py` | 8 unit tests covering 0/1/2/3-point cases, both directions, HM conversion, same-date dedup | VERIFIED | Exactly 8 named functions present: `test_project_0_points`, `test_project_1_point`, `test_project_2_points`, `test_project_3_points`, `test_higher_is_better`, `test_lower_is_better`, `test_hm_time_conversion`, `test_dedup_same_date`; all pass |
| `core/pace_history.py` | `fetch_dense_pace_history` — Postgres activities → BenchmarkStore-shaped threshold_pace points | VERIFIED | 93 lines; derives pace via `duration_sec/distance_m*1000`; `avg_pace` column not read (appears only in comment "Do NOT read"); fails open to `[]`; lazy import of `query_health_database` |
| `core/tools.py` | `get_goal_projection` registered at all 4 sites + `_handle_get_goal_projection` handler | VERIFIED | Line 70: in `SMART_AGENT_DIRECT_TOOLS`; lines 989–1010: schema in `TOOL_SCHEMAS`; line 1076: in `WORKER_TOOL_SCHEMAS` exclusion set; line 1943: in `_HANDLERS`; `_handle_get_goal_projection` at line 1823 |
| `prompts/smart_agent.md` | `get_goal_projection` tool description + updated projection-language permission | VERIFIED | 2 occurrences of `get_goal_projection`; old "projection — directional only" restriction replaced with conditional (cite computed number when available, directional fallback otherwise) |
| `prompts/weekly_training_review.md` | Fence lifted + "Pace-to-deadline" projection instruction; "Week N of 16" preserved | VERIFIED | 0 occurrences of "PHASE 25 FENCE" or "ABSOLUTELY FORBIDDEN"; "Pace-to-deadline projection (PROG-02)" block at line 37; "Week" framing preserved at multiple lines |
| `tests/test_tool_registration_phase25.py` | 5 registration tests covering all 4 sites + handler callable | VERIFIED | 5 test methods confirmed: `test_tool_in_direct`, `test_tool_excluded_from_worker`, `test_tool_in_handlers`, `test_tool_has_schema`, `test_handler_callable`; all pass |
| `tests/test_weekly_training_review.py` (new tests) | 4 new projection tests: gather, fail-open, dense-pace-source, derive-topics | VERIFIED | `test_gather_includes_projections`, `test_projection_gather_fails_open`, `test_threshold_pace_uses_dense_garmin`, `test_derive_projection_topics` all present and passing |
| `tests/test_prompts.py` (new test) | `test_no_phase25_fence` asserting fence absent, "Week" present | VERIFIED | Function at line 227; passes |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `core/tools.py::_handle_get_goal_projection` | `core/projection.py::project_goal_progress` | `from core.projection import project_goal_progress` (line 1845) + call at line 1863 | WIRED | Lazy import inside handler; result passed to `json.dumps` |
| `core/tools.py::_handle_get_goal_projection` | `core/pace_history.py::fetch_dense_pace_history` | `from core.pace_history import fetch_dense_pace_history` (line 1855) + call at line 1856 | WIRED | threshold_pace branch only; empty result triggers BenchmarkStore fallback |
| `core/tools.py::_handle_get_goal_projection` | `_BENCHMARK_FACETS` | `from memory.firestore_db import _BENCHMARK_FACETS, _jsonsafe_doc` (line 1837); guard at line 1838 | WIRED | Facet validated before any store access |
| `core/tools.py::_handle_get_goal_projection` | `ZoneInfo("Asia/Jerusalem")` | `datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()` (line 1847) | WIRED | No `date.today()` call |
| `core/weekly_training_review.py::_gather_week_data` | `core/projection.py::project_goal_progress` | Lazy import at line 250 + per-facet call at line 267 | WIRED | All 5 facets in gather block #8 |
| `core/weekly_training_review.py::_gather_week_data` | `core/pace_history.py::fetch_dense_pace_history` | Lazy import at line 251 + call at line 262 | WIRED | threshold_pace dense-prefer, BenchmarkStore fallback when empty |
| `core/weekly_training_review.py::_derive_structural_topics` | `CoachingTopicStore` (post-send loop in `run_weekly_review`) | `coaching_topics_included` key flows through `week_data` unchanged; `add_topic` called at line 426 only after `send_and_inject` | WIRED | No `add_topic` call inside `_gather_week_data` or `_derive_structural_topics` — write-after-send invariant preserved |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `_handle_get_goal_projection` | `history` (benchmark points) | `BenchmarkStore.get_facet_history` (Firestore) or `fetch_dense_pace_history` (Postgres) | Yes — real Firestore/Postgres reads; `dated_goals` from `UserProfileStore.load()` wrapped in `_jsonsafe_doc` | FLOWING |
| `core/projection.py::project_goal_progress` | `history`, `dated_goals`, `today_iso` | Caller-supplied; pure function — no internal I/O | Real data from caller | FLOWING |
| `core/weekly_training_review.py` gather block #8 | `data["projections"]` | `project_goal_progress` called per facet with real BenchmarkStore + Garmin Postgres history | Yes — fail-open to `{}` (empty dict, not None) on exception | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `project_goal_progress` 0-point branch returns `no_data` | `python -c "from core.projection import project_goal_progress; r=project_goal_progress('bench_press_1rm',[],[],\"2026-06-08\"); assert r['confidence']=='no_data'"` | Inferred from 8 passing unit tests | PASS (via test suite) |
| `_handle_get_goal_projection` is callable | `tools._handle_get_goal_projection` is callable | Confirmed by `test_handler_callable` | PASS (via test suite) |
| `fetch_dense_pace_history` never reads `avg_pace` | `grep -c "avg_pace" core/pace_history.py` | 1 (comment only, "Do NOT read") | PASS |
| Fence lifted from `weekly_training_review.md` | `grep -E "PHASE 25 FENCE|ABSOLUTELY FORBIDDEN" prompts/weekly_training_review.md` | 0 matches | PASS |
| Projection instruction in weekly review prompt | `grep -i "pace-to-deadline" prompts/weekly_training_review.md` | Matches line 37 | PASS |

---

### Test Suite Execution

**Command:** `.venv/bin/python -m pytest tests/test_projection.py tests/test_tool_registration_phase25.py tests/test_weekly_training_review.py tests/test_prompts.py -q`

**Result:** 55 passed in 11.17s — all green.

| Test File | Tests | Result |
|-----------|-------|--------|
| `tests/test_projection.py` | 8 | All pass |
| `tests/test_tool_registration_phase25.py` | 5 | All pass |
| `tests/test_weekly_training_review.py` | ~35 (including 4 new projection tests) | All pass |
| `tests/test_prompts.py` | ~7 (including `test_no_phase25_fence`) | All pass |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| PROG-02 | Plans 01, 02, 03 | Klaus projects strength/pace trends toward dated Oct/Nov goals and reports on-track/behind | SATISFIED | `project_goal_progress` pure function (Plan 01) + `get_goal_projection` reactive tool (Plan 02) + `_gather_week_data` block #8 Sunday projection (Plan 03) + fence lifted in `weekly_training_review.md` |

REQUIREMENTS.md line 43: `[x] **PROG-02**` — marked complete.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `core/projection.py` | 5, 176 | `date.today()` / `datetime.now()` appear in docstring comments only — not in executable code | Info | None — docstrings explicitly state "NEVER call"; executable body uses `today_iso` parameter throughout |
| `core/pace_history.py` | 9 | `avg_pace` appears in a "Do NOT read" comment | Info | None — comment is a prohibition, not usage; SQL derives pace from `duration_sec/distance_m*1000` |
| `tests/test_weekly_training_review.py` | 452 | `test_weekly_review_prompt_forbids_dated_projection` — Phase 24 guard test with comment noting it will be "superseded" | Info | Non-blocking; test still passes because the prompt uses "on-track/behind" rather than the exact phrases it checks for; `test_no_phase25_fence` (test_prompts.py:227) is the authoritative Phase 25 check |

No `TBD`, `FIXME`, or `XXX` markers found in phase-modified files.

---

### Human Verification Required

None. All three success criteria are verifiable from code and test results.

---

### Gaps Summary

No gaps. All three success criteria are fully verified against the codebase:

1. **Reactive projection path** — `get_goal_projection(facet)` is a brain-direct tool registered at all four sites in `core/tools.py`, validated against `_BENCHMARK_FACETS`, computing `today_iso` via `ZoneInfo("Asia/Jerusalem")`, sourcing dense Garmin Postgres history for `threshold_pace` (D-04) and BenchmarkStore for strength facets, calling `project_goal_progress` which performs a linear LSQ projection and returns `projected_value`, `gap`, `on_track`, `confidence`, and `confidence_label`.

2. **Proactive Sunday path** — `_gather_week_data` block #8 in `core/weekly_training_review.py` loops all 5 facets, applies the same D-04 dual-source logic, injects `data["projections"]`, and fails open to `{}`. `_derive_structural_topics` emits `structural-critique:projection:<facet>` dedup keys for facets with data, which flow through the existing post-send COACH-05 write loop.

3. **Tier A vs Tier B distinction** — `project_goal_progress` returns `projected_value=None` for histories with 0 or 1 data point (no fabricated number); the prompt in `weekly_training_review.md` explicitly states "Tier A target (blueprint) is always distinguished from Tier B measured trend"; `smart_agent.md` carries the same instruction. No fabricated convergence is possible.

The Phase 24 fence has been cleanly lifted from `prompts/weekly_training_review.md` (0 occurrences of "PHASE 25 FENCE" or "ABSOLUTELY FORBIDDEN"); the projection instruction is in place per D-01/D-02 framing; "Week N of 16" block framing is preserved.

---

_Verified: 2026-06-08_
_Verifier: Claude (gsd-verifier)_
