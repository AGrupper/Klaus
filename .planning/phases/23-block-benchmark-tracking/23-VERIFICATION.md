---
phase: 23-block-benchmark-tracking
verified: 2026-06-06T09:00:00Z
status: passed
score: 4/4
overrides_applied: 0
re_verification: null
gaps: []
deferred: []
human_verification: []
---

# Phase 23: Block & Benchmark Tracking — Verification Report

**Phase Goal:** Klaus tracks the current training block (week number, phase, dates) and surfaces that context in all coaching messages; at block end he prompts a standardized benchmark test session with a biometric validity gate; results are recorded per-facet and compared across blocks to show improvement over time.
**Verified:** 2026-06-06T09:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | BlockStore.get_current() returns the active block with week number derived from plan_start_date 2026-06-21; cron messages include "Week N of 16, [phase name]" framing | VERIFIED | `BlockStore.get_current()` uses date-range resolution (start_date <= today <= end_date, D-01). `get_week_num("2026-06-21", today)` formula verified: week 1 for 2026-06-21, week 2 for 2026-06-28, None pre-cycle. Morning briefing (`core/morning_briefing.py:286`) and weekly review (`core/weekly_training_review.py:206`) gather block state and derive week_num inline. Prompts `morning_briefing.md` (l.161) and `weekly_training_review.md` (l.25) both instruct "Week {N} of 16". |
| 2 | The end-of-block benchmark prompt fires within 3 days of stored block_end_date via the existing 21:30 cron — no new cron job created | VERIFIED | `_evaluate_benchmark_state()` in `core/proactive_alerts.py` fires when `days_left <= 3`. Block-end check runs before `_already_sent()` (line 178 vs line 197). No new cron route in `web_server.py`. CLAUDE.md still documents 7 Cloud Scheduler jobs (unchanged). |
| 3 | The benchmark prompt includes a biometric validity gate: defers when HRV < 70% of 7-day baseline or ACWR > 1.2 | VERIFIED | `_evaluate_benchmark_state()` at line 132: `gate_fail = (hrv_pct is not None and hrv_pct < 0.70) or (acwr_ratio is not None and acwr_ratio > 1.2)`. Returns `benchmark_deferred` with literal `hrv_overnight` and `hrv_pct` numbers. Gate-unknown (None biometrics) errs toward prompting (PASS). Block 4 race week is excluded via `"Race" in label or end_date == "2026-10-10"`. Stale-window fires once with caveat when `today_iso > end_date`. All three states rendered in `prompts/proactive_alert.md`. Logic verified by direct code walk-through matching the spec exactly. |
| 4 | Klaus records a benchmark result via log_benchmark and can surface a facet's history across blocks | VERIFIED | `BenchmarkStore.log_benchmark()` writes `{date}_{facet}` doc with `merge=True` idempotently. Validates facet against `_BENCHMARK_FACETS` 5-facet closed set — raises `ValueError` on unknown. `get_facet_history(facet, n)` streams all, filters by facet, sorts date-desc, caps at n. `get_benchmark_history` tool registered in `_HANDLERS` and `SMART_AGENT_DIRECT_TOOLS`. |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `memory/firestore_db.py` | BlockStore + BenchmarkStore + get_week_num + current_block_id | VERIFIED | `class BlockStore` at line 1521, `class BenchmarkStore` at line 1698, `get_week_num()` at line 1488, `current_block_id: None` in UserProfileStore._SCAFFOLD at line 149 |
| `scripts/seed_training_blocks.py` | Idempotent 4-block seed with --dry-run/--force | VERIFIED | `build_blocks_list()` at line 81, `seed_if_absent()` at line 145, `--dry-run` verified to output 4 blocks with correct labels/dates. `load_dotenv(override=True)` invariant present. |
| `core/tools.py` | 6 brain-direct block/benchmark tools + handlers + dispatch | VERIFIED | All 6 in `SMART_AGENT_DIRECT_TOOLS` (lines 63-68), all 6 excluded from `WORKER_TOOL_SCHEMAS`, all 6 handlers defined (`_handle_get_plan`, `_handle_get_block_status`, etc.), all 6 in `_HANDLERS` (lines 1854-1859). `update_plan` not duplicated. |
| `core/proactive_alerts.py` | _evaluate_benchmark_state + block-end trigger + widened early-return | VERIFIED | `_evaluate_benchmark_state` at line 91. Block-end check (line 178) before `_already_sent` (line 197). Widened guard at lines 252-255: `... and benchmark_state is None`. Single `fetch_garmin_today` call (grep count = 1). |
| `prompts/proactive_alert.md` | benchmark_window_open / benchmark_deferred / benchmark_stale rendering | VERIFIED | All three state names present (lines 54, 63, 70). Numeric defer message references `benchmark.hrv_overnight` and `benchmark.hrv_pct`. "When absent: no framing" rule at line 79. |
| `core/morning_briefing.py` | Best-effort BlockStore.get_current() gather + pre-cycle countdown | VERIFIED | BlockStore gather at lines 278-299. `if block:` guard. Pre-cycle countdown branch. Wrapped in `try/except logger.warning`. |
| `core/weekly_training_review.py` | Best-effort BlockStore + BenchmarkStore gather in _gather_week_data | VERIFIED | Section 6 at lines 193-222. `current_block` and `block_benchmarks` keys set. Pre-cycle countdown. Exception defaults to `current_block=None`, `block_benchmarks=[]`. |
| `prompts/morning_briefing.md` | "Week N of 16" conditional section | VERIFIED | `## Current Training Block` section at line 158. "Week {block.week_num} of 16" at line 161. pre_cycle_countdown rendering at line 167. Explicit omit-when-absent rule at line 169. |
| `prompts/weekly_training_review.md` | current_block + block_benchmarks data-key rendering | VERIFIED | `current_block` key at line 19, `block_benchmarks` at line 20. "Week N of 16" framing at line 25. "RAW deltas only — do NOT project" rule present. |
| Test files | 101 new/extended tests covering all stores, tools, and crons | VERIFIED | `tests/test_block_store.py` (19), `tests/test_benchmark_store.py` (13), `tests/test_seed_blocks.py` (11), `tests/test_tool_registration_phase23.py` (9), `tests/test_proactive_alerts.py` (+10 new), `tests/test_morning_briefing.py` (+4 new), `tests/test_weekly_training_review.py` (+3 new) — all pass under `.venv/bin/python3` (3.13). |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `BlockStore.get_current()` | `training_blocks` collection | date-range resolution (start_date <= today <= end_date) — no status filter | WIRED | Source at firestore_db.py:1578-1590. Stream all blocks, filter by date range. Verified D-01 automatic inter-block transition — Block 2 returned with no `start_block` call, status "pending". |
| `BenchmarkStore` read paths | `_jsonsafe_doc` | every `snap.to_dict()` | WIRED | All 3 read paths (`get_facet_history:1793`, `get_block_benchmarks:1821`, `get_all:1604`) wrap `snap.to_dict()` with `_jsonsafe_doc`. grep count = 9 in firestore_db.py. |
| `_HANDLERS` | `BlockStore / BenchmarkStore` | handler functions import stores via `_block_stores()` | WIRED | `_block_stores()` helper at tools.py:~1700 constructs all three stores from env vars. Handlers call store methods directly. |
| `SMART_AGENT_DIRECT_TOOLS` | `WORKER_TOOL_SCHEMAS` exclusion | all 6 new tool names in exclusion set | WIRED | All 6 names found in both the inclusion frozenset (lines 63-68) and the exclusion set in `WORKER_TOOL_SCHEMAS` comprehension (lines ~1044-1049). |
| `block-end check` | `_already_sent` dedup gate | runs before the gate | WIRED | BlockStore import at line 178, `_already_sent()` call at line 197. Source-order verified. |
| `benchmark_state` evaluation | `fetch_garmin_today` + `compute_acwr_from_db` | single Garmin fetch shared by gate and recovery_concern | WIRED | `grep -c fetch_garmin_today core/proactive_alerts.py` = 1. `garmin_data` reused on lines 235-236 for HRV extraction and line 278 for `compute_recovery_concern`. |
| `benchmark-only night` | `send path` | widened early-return `... and benchmark_state is None` | WIRED | Lines 252-255: the no-alert early return includes `benchmark_state is None`. `test_benchmark_only_night_still_sends` passes, asserting `send_message` is called when weather/overload/travel alerts are all falsy but benchmark_state is window_open. |
| `_gather_data / _gather_week_data` | `BlockStore.get_current()` | best-effort try/except with `if block:` guard | WIRED | `morning_briefing.py:279-299`, `weekly_training_review.py:200-222`. Both wrap BlockStore in `try/except logger.warning`. Both use `if block:` guard before computing week_num. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `_evaluate_benchmark_state` | `block` (from `BlockStore.get_current()`) | Firestore `training_blocks` collection, seeded by `seed_training_blocks.py` | Yes — full 4-block seeded dataset | FLOWING |
| `_handle_get_block_status` | `facet_deltas` | `BenchmarkStore.get_facet_history()` cross-block delta computation | Yes — real Firestore query with `block_id` FieldFilter | FLOWING |
| `morning_briefing _gather_data` | `data["block"]` | `BlockStore.get_current()` date-range resolution | Yes — live Firestore read | FLOWING |
| `weekly_training_review _gather_week_data` | `data["current_block"]`, `data["block_benchmarks"]` | `BlockStore.get_current()` + `BenchmarkStore.get_block_benchmarks()` | Yes — live Firestore reads | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Seed script outputs 4 blocks with correct dates | `python3 scripts/seed_training_blocks.py --dry-run` | 4 blocks: Aerobic Base (2026-06-21→2026-07-18), Capacity Build (2026-07-19→2026-08-15), Deep Waters→Peak Engine (2026-08-16→2026-09-12), Race Specificity→Taper→Race Week (2026-09-13→2026-10-10). All `benchmark_due=False`. | PASS |
| Date contiguity: blocks cover 2026-06-21 to 2026-10-10 with 1-day gaps | Python date arithmetic | Gaps between consecutive blocks: 1 day each. No overlaps. Total coverage verified. | PASS |
| Week number formula: plan_start=2026-06-21 | Python calculation | day 0 = week 1, day 6 = week 1, day 7 = week 2, pre-cycle = None | PASS |
| _evaluate_benchmark_state: Block 4 returns None | Logic trace | `"Race" in "Race Specificity → Taper → Race Week"` → returns None | PASS |
| _evaluate_benchmark_state: HRV 55/80 (68.75%) → deferred | Logic trace | hrv_pct=0.6875 < 0.70 → gate_fail=True → benchmark_deferred | PASS |
| _evaluate_benchmark_state: ACWR 1.35 → deferred | Logic trace | 1.35 > 1.2 → gate_fail=True → benchmark_deferred | PASS |
| _evaluate_benchmark_state: gate-unknown (None biometrics) → window_open | Logic trace | hrv_pct=None, acwr=None → gate_fail=False → benchmark_window_open | PASS |
| Full test suite | `.venv/bin/python3 -m pytest -q` | 911 passed, 3 skipped | PASS |

---

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` found for this phase. Phase is a Firestore/Python implementation, not a migration/CLI tooling phase. Behavioral spot-checks (Step 7b) cover the runnable entry points.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| BLOCK-01 | Plans 01, 02, 04 | Klaus tracks the current training block (start date 2026-06-21, week number, phase name) and surfaces block context in coaching messages | SATISFIED | BlockStore.get_current() date-range resolution (D-01); get_week_num() D-03 formula; 6 brain-direct tools including get_plan/get_block_status; morning briefing + weekly review block gathers; "Week N of 16" prompt framing |
| BLOCK-02 | Plan 03 | At block ends Klaus prompts a benchmark test session with a standardized protocol — no periodic mid-block testing | SATISFIED | _evaluate_benchmark_state() fires within 3 days of block_end_date; all three states (window_open/deferred/stale) implemented; validity gate (HRV/ACWR); Block 4 exclusion; widened early-return so benchmark-only nights send; no new cron job |
| BLOCK-03 | Plans 01, 02, 04 | Klaus records benchmark results and compares them across blocks to show per-facet improvement | SATISFIED | BenchmarkStore.log_benchmark() with 5-facet validation; get_facet_history() cross-block history; get_benchmark_history brain-direct tool; _handle_get_block_status computes raw facet_deltas vs prior block; weekly review surfaces block_benchmarks |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `core/proactive_alerts.py` | 283 | `# silent omit — no "all clear" placeholder` | INFO | Comment documenting intentional behavior (D-13 guardrail). Not a stub. |
| `memory/firestore_db.py` | 597 | `non-empty placeholder would break silent-omit` | INFO | Comment on `UserProfileStore`, not phase-23 code. Pre-existing. |
| `core/morning_briefing.py` | 246 | `# silent omit — no "all clear" placeholder` | INFO | Comment documenting intentional behavior. Pre-existing pattern. |

No TBD, FIXME, or XXX markers found in any phase-23 modified files.

**Debt marker gate:** PASSED — no unreferenced debt markers.

Note on known review warnings (from 23-REVIEW.md, 0 blockers):
- WR-01 (hardcoded 2026-06-21 in cron gathers): deliberate per locked decision D-03 — the plan explicitly requires this constant to ensure week_num is "never read from a stored field". The `get_plan` tool correctly reads `plan_start_date` from profile; the cron gathers use the constant to minimize Firestore reads in the best-effort gather path. Acceptable divergence documented in review.
- WR-02 (created_at overwrite): low-severity, single-user system. Not a functional defect.
- WR-03 (Block-4 detection by label/end_date): deliberate per locked decision D-02. Documented in review.

---

### Human Verification Required

None. All must-haves are verifiable from the codebase and test suite.

---

### Gaps Summary

No gaps. All 4 success criteria are met by the implementation. The full test suite (911 passed, 3 skipped) runs clean on `.venv/bin/python3` (Python 3.13). The three review warnings (WR-01 through WR-03) are acknowledged deliberate design decisions per locked plan decisions D-02 and D-03, not defects.

---

_Verified: 2026-06-06T09:00:00Z_
_Verifier: Claude (gsd-verifier)_
