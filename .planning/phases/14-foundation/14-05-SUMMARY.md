---
plan: 14-05
phase: 14-foundation
status: complete
subsystem: core
tags: [tick-brain, heartbeat, llm, judgment, gating, non-blocking]
dependency_graph:
  requires: ["14-04"]
  provides: ["tick-brain reasoning pass in run_tick()", "TICK-05"]
  affects: ["core/heartbeat.py"]
tech_stack:
  added: []
  patterns: ["Lazy import gating (import inside try/except)", "Additive insight postscript pattern", "Non-blocking LLM decorator over deterministic checklist"]
key_files:
  created: []
  modified:
    - core/heartbeat.py
decisions:
  - "_run_tick_brain_pass placed immediately before run_tick() — single insertion point, no refactor of other helpers needed"
  - "Insight appended only to critical ping message and fyi digest (not to warnings) — keeps warning messages actionable and clean"
  - "fyi insight gated on 'not to_ping and not warnings' — avoids insight duplication when critical block already carries it"
  - "TickBrain import inside try/except at call-time — heartbeat never fails to load even when tick_brain module is absent"
metrics:
  duration_seconds: 180
  completed_date: "2026-05-18"
  tasks_completed: 1
  files_created: 0
  files_modified: 1
  tests_added: 0
---

# Phase 14 Plan 05: Tick-Brain Heartbeat Integration Summary

## One-liner

Non-blocking tick-brain reasoning pass wired into run_tick() — gated on signals-exist or weekly, appends LLM insight to Telegram alert as postscript.

## What Was Built

Two surgical additions to `core/heartbeat.py`:

**1. `_run_tick_brain_pass(signals, *, weekly)` helper (lines 638-678)**

A standalone helper that:
- Returns `None` immediately on quiet ticks (no signals, not weekly) — 0 LLM cost
- Lazy-imports `TickBrain` inside `try/except` — init failure (e.g. missing `TICK_BRAIN_API_KEY`) logs a debug message and returns `None`
- Builds a compact signal summary string for the prompt
- Calls `brain.think(prompt)` inside `try/except` — any `LLMError` or `Exception` returns `None`
- Returns `result["draft"]` when `should_act=True` and draft is present; otherwise returns `result["reason"]` if it is not an error sentinel; otherwise `None`

**2. Call-site in `run_tick()` (lines 691-721)**

After `_collect_signals()` and its log line, `run_tick()` now:
- Computes `is_weekly = SEVERITY_FYI in tiers`
- Calls `_run_tick_brain_pass(signals, weekly=is_weekly)`
- Logs the insight at INFO level when truthy
- Appends `\n\n_Insight: {tick_insight}_` to the critical ping message when `tick_insight` is truthy
- Appends the same postscript to the fyi digest message when `tick_insight` is truthy AND there are no critical pings and no warnings (avoids duplication)

All deterministic checkers (`check_cron_health`, `check_tokens`, `check_degradation`, `check_deployment`, `check_code`) are completely unchanged. `_compose_message()` is completely unchanged.

## Key Files

- `core/heartbeat.py` — modified: 55 lines added, 2 lines changed (critical block and fyi block)

## Commits

- `5109f41` feat(14-05): add _run_tick_brain_pass() and wire tick-brain into run_tick()

## Verification

All acceptance criteria passed:

1. `grep -c "def _run_tick_brain_pass" core/heartbeat.py` → 1
2. `grep -c "TickBrain" core/heartbeat.py` → 2 (import + instantiation)
3. `grep -c "tick_insight" core/heartbeat.py` → 7 (assignment + 2 if-checks + 2 appends + 1 fyi gate + 1 fyi append)
4. `grep -c "not signals and not weekly" core/heartbeat.py` → 1 (gate)
5. `python3 -c "import ast; ast.parse(open('core/heartbeat.py').read())"` → exits 0
6. `grep -c "def _collect_signals" core/heartbeat.py` → 1 (unchanged)
7. `grep -c "def _compose_message" core/heartbeat.py` → 1 (unchanged)

## Deviations from Plan

None — plan executed exactly as written. All three code blocks (_run_tick_brain_pass helper, run_tick call-site, critical block update, fyi block update) match the spec verbatim.

## Known Stubs

None — _run_tick_brain_pass() fully functional; calls real TickBrain which calls real LLMClient. If TICK_BRAIN_API_KEY is absent in the environment, the function gracefully skips and returns None (documented behavior, not a stub).

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model:

| Flag | File | Description |
|------|------|-------------|
| (none) | — | T-14-12 (DoS) mitigated by double try/except in _run_tick_brain_pass; T-14-13 (info disclosure) accepted per plan |

## Self-Check: PASSED

Files exist:
- `core/heartbeat.py` — confirmed modified (55 insertions, 2 changes)

Commits exist:
- `5109f41` — confirmed in git log
