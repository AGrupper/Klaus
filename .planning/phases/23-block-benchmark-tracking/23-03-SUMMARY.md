---
phase: 23-block-benchmark-tracking
plan: "03"
subsystem: core/proactive-alerts
tags: [cron, benchmark, validity-gate, state-machine, tdd, prompt]
dependency_graph:
  requires: [BlockStore, get_current, set_benchmark_due]
  provides: [_evaluate_benchmark_state, benchmark-cron-trigger]
  affects: [core/proactive_alerts.py, prompts/proactive_alert.md]
tech_stack:
  added: []
  patterns: [pure-state-machine, best-effort-try-except, single-garmin-fetch, conditional-prompt-section, os-environ-isolation-fixture]
key_files:
  created: []
  modified:
    - core/proactive_alerts.py
    - prompts/proactive_alert.md
    - tests/test_proactive_alerts.py
decisions:
  - "_evaluate_benchmark_state is a pure module-level fn (block, today_iso, hrv_overnight, hrv_baseline, acwr_ratio) -> dict|None — unit-testable without the cron"
  - "Block 4 race week never benchmarks: detected by 'Race' in label OR end_date == 2026-10-10 (D-02)"
  - "Validity gate (D-07): defer if HRV/baseline < 0.70 OR ACWR > 1.2; gate-unknown (missing data) => PASS (err toward prompting)"
  - "Three states: benchmark_window_open / benchmark_deferred (carries hrv_overnight + hrv_pct for D-08) / benchmark_stale (today > end_date, D-09)"
  - "Block-end check + set_benchmark_due run BEFORE the _already_sent dedup gate (Pitfall 3 / T-23-11)"
  - "fetch_garmin_today called exactly once, shared by the benchmark gate and recovery_concern (Pitfall 5) — used `from mcp_tools import garmin_tool as _garmin` so grep -c stays 1"
  - "No-alert early return widened to `... and benchmark_state is None` so a benchmark-only deload night still composes+sends (BLOCK-02 SC / T-23-10)"
  - "Added an autouse os.environ snapshot/restore fixture to test_proactive_alerts.py — stops the load_dotenv(override=True) GCP_PROJECT_ID leak from bleeding across tests"
metrics:
  duration: "~30 minutes"
  completed: "2026-06-06"
  tasks_completed: 3
  tasks_total: 3
  files_created: 0
  files_modified: 3
requirements: [BLOCK-02]
---

# Phase 23 Plan 03: End-of-Block Benchmark Trigger Summary

## One-liner

A pure benchmark state machine wired into the existing 21:30 proactive-alerts cron: detects end-of-block windows (Blocks 1-3 only), gates on HRV/ACWR, emits `benchmark_window_open` / `benchmark_deferred` / `benchmark_stale`, and keeps a benchmark-only deload night in the send path.

## What Was Built

### `_evaluate_benchmark_state(block, today_iso, hrv_overnight, hrv_baseline, acwr_ratio)` (`core/proactive_alerts.py`)
Pure, module-level. Returns `None` for no-block / Block-4 / >3-days-out; `benchmark_stale` when `today > end_date`; `benchmark_deferred` (with `hrv_overnight`, `hrv_pct`, `acwr`) when the gate fails (HRV < 70% baseline OR ACWR > 1.2); else `benchmark_window_open`. Gate-unknown (missing biometrics) → PASS.

### `run_proactive_alerts` restructure
- **Block-end check before the dedup gate** (Pitfall 3): best-effort `BlockStore.get_current()` (date-range resolved); if a near-end Block 1-3 with `benchmark_due` not yet set, calls `set_benchmark_due(...)`. `current_block` kept for the gate.
- **Single Garmin fetch** (Pitfall 5): `fetch_garmin_today()` called once via `from mcp_tools import garmin_tool as _garmin`; reused by both the benchmark gate and `compute_recovery_concern` (the second fetch was removed). `grep -c fetch_garmin_today` == 1.
- **Benchmark gate evaluation** moved before the no-alert early return; `_acwr` from `compute_acwr_from_db().ratio`.
- **Widened early return**: `if not weather_alerts and not overload_alert and not travel_alerts and benchmark_state is None:` — a benchmark-only night no longer short-circuits to no-send (BLOCK-02 correctness).
- `alerts_context["benchmark"] = benchmark_state` when non-None.

### `prompts/proactive_alert.md`
New `## Benchmark Reminder` conditional section rendering all three states (window_open prompts all 5 facets with Epley framing; deferred uses the literal `hrv_overnight`/`hrv_pct` numbers and notes nightly re-check; stale prompts once with a tested-under-fatigue caveat) plus the explicit "when absent: no framing" rule.

## Tests Written (10 new, file total 17 passing)

`tests/test_proactive_alerts.py`:
- `TestEvaluateBenchmarkState` (9 unit tests): Block-4 None, >3-days None, None-block, gate pass → window_open, HRV fail → deferred, ACWR fail → deferred, stale window, gate-unknown → window_open, deferred numeric payload
- `test_benchmark_check_before_dedup_gate` — set_benchmark_due fires even when `_already_sent` True (ordering)
- `test_benchmark_only_night_still_sends` — no weather/overload/travel alert + near-end Block 1 + passing gate → `send_message` called once, `alerts_context["benchmark"].state == "benchmark_window_open"`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] load_dotenv GCP_PROJECT_ID leak broke sibling tests**
- **Found during:** Task 2 GREEN run — existing `test_recovery_concern_injected_into_alert_context` failed only when run after other tests in the file (passed in isolation).
- **Root cause:** the new block-end check constructs `BlockStore` → `_make_firestore_client` runs `load_dotenv(override=True)`, leaking `GCP_PROJECT_ID=klaus-agent` from `.env` into `os.environ`. The next test's top-of-function `run_training_checkin` then saw a real project and attempted real Firestore I/O (MagicMock value → `TypeError`). The existing tests assume `GCP_PROJECT_ID` stays unset.
- **Fix:** Added an autouse `_restore_environ` fixture that snapshots/restores `os.environ` around each test (consistent with the project's established test-isolation approach). The two new integration tests scope `GCP_PROJECT_ID` via `patch.dict` and neutralize the check-in with `patch("core.training_checkin.run_training_checkin", new=AsyncMock())`.
- **Files modified:** `tests/test_proactive_alerts.py`

## Known Stubs

None.

## TDD Gate Compliance

- RED gate: commit adding 10 failing tests (`_evaluate_benchmark_state` ImportError)
- GREEN gate: state machine + cron restructure → all 17 file tests pass

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: dos-resilience | core/proactive_alerts.py | All block/gate logic best-effort try/except; gate-unknown → PASS (never silent skip); widened early-return keeps a benchmark state from being dropped (T-23-10) |
| threat_flag: ordering | core/proactive_alerts.py | set_benchmark_due before dedup gate; idempotent merge (T-23-11) |

## Self-Check: PASSED

Files verified:
- FOUND: core/proactive_alerts.py (`_evaluate_benchmark_state`)
- FOUND: prompts/proactive_alert.md (3 benchmark states)
- FOUND: tests/test_proactive_alerts.py
- FOUND: .planning/phases/23-block-benchmark-tracking/23-03-SUMMARY.md

Guards verified:
- set_benchmark_due appears before `_already_sent(` in source order
- no-alert early-return guard includes `benchmark_state is None`
- `grep -c fetch_garmin_today` == 1
