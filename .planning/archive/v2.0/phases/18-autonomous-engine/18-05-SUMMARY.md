---
phase: 18-autonomous-engine
plan: 05
subsystem: infra
tags: [tick-brain, llm-client, autonomous, groq, qwen3, gemini, system-prompt, topic-key, repeat-suppression, cost-metering]

# Dependency graph
requires:
  - phase: 18-autonomous-engine/03
    provides: prompts/autonomous_triage.md (the system prompt that Plan 06 will pass via system_override)
  - phase: 14
    provides: core/tick_brain.py (Groq/Qwen3-32B primary + Gemini fallback chain) and LLMUsageStore purpose-bucketed cost metering
provides:
  - TickBrain.think(prompt, *, tools, system_override) — backward-compatible signature extension
  - _parse_response topic_key passthrough — 4th JSON field flows through when present and truthy
  - Layered purpose strings (tick / tick_fallback / tick_autonomous / tick_autonomous_fallback) for 4-bucket cost visibility
affects: [18-06 (autonomous orchestrator — calls think with system_override), 18-07 (cron route — heartbeat path unchanged), 18-08 (eval runner — exercises both paths)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Extend-with-optional-param: add new kwarg with sensible default (Phase 17 D-08 precedent) so existing callers remain untouched"
    - "Layered purpose strings: derive fallback purpose from primary purpose via suffix (primary + '_fallback') — preserves caller-distinguishing buckets in LLMUsageStore without N hardcoded literals"
    - "Falsy-guard passthrough: include optional LLM JSON field only when present AND truthy; downstream handlers synthesise fallback when absent"

key-files:
  created: []
  modified:
    - core/tick_brain.py — think() signature (3 params now: prompt, tools, system_override); active_system + primary_purpose + fallback_purpose locals; _parse_response topic_key block
    - tests/test_tick_brain.py — TestSystemOverrideAndTopicKey class with 10 new tests

key-decisions:
  - "Layered purpose strings over per-call literals — preserves Phase 14 INFRA-02 visibility into heartbeat-fallback rate without adding N hardcoded strings"
  - "Falsy guard on topic_key (treat empty string AND missing the same) — downstream autonomous.py synthesises a fallback slug, so the parser stays simple"
  - "system_override only when truly different from default — None is the sentinel, not empty-string, to keep caller intent explicit"

patterns-established:
  - "Optional-kwarg extension preserves backward compat: existing brain.think(prompt) callers (core/heartbeat.py:720) receive identical behavior via system_override=None default"
  - "WARNING 1 regression guard pattern: a dedicated test (test_fallback_purpose_preserves_tick_fallback_when_no_override) asserts the exact string 'tick_fallback' is still emitted by the no-override path, catching future drift"

requirements-completed: [AUTO-01, AUTO-07]

# Metrics
duration: 5min
completed: 2026-05-22
---

# Phase 18 Plan 05: Tick-Brain Extension Summary

**TickBrain.think() gains optional system_override kwarg + topic_key parser passthrough — unlocks the autonomous tick path while keeping heartbeat 100% backward-compatible and preserving 4-bucket LLM cost visibility (tick / tick_fallback / tick_autonomous / tick_autonomous_fallback).**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-05-22T20:46:06Z
- **Completed:** 2026-05-22T20:51:57Z
- **Tasks:** 1 (TDD: RED + GREEN commits)
- **Files modified:** 2

## Accomplishments

- `TickBrain.think()` now accepts `system_override: str | None = None` — autonomous orchestrator (Plan 06) can pass the rendered `prompts/autonomous_triage.md` while heartbeat keeps calling `brain.think(prompt)` unchanged.
- Layered purpose strings (WARNING 1 fix): `primary_purpose = 'tick_autonomous' if system_override else 'tick'`; `fallback_purpose = primary_purpose + '_fallback'`. Four buckets now exist in `LLMUsageStore`: `tick`, `tick_fallback`, `tick_autonomous`, `tick_autonomous_fallback`. The literal `"tick_fallback"` no longer appears anywhere in `core/tick_brain.py` (replaced by the variable).
- `_parse_response` passes through `topic_key` (the 4th JSON field from `prompts/autonomous_triage.md`) when present and truthy. Empty string / missing → omitted; non-string → coerced via `str()`. Safe-mode return unchanged.
- 10 new tests in `TestSystemOverrideAndTopicKey`, including an explicit WARNING 1 regression guard (`test_fallback_purpose_preserves_tick_fallback_when_no_override`).
- 27/27 in `tests/test_tick_brain.py` green; 69/69 in adjacent regression suites (`test_firestore_db.py`, `test_prompts.py`, `test_evals.py`) green.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing tests for system_override + topic_key** — `8289310` (test)
2. **Task 1 (GREEN): implementation in core/tick_brain.py** — `ddf9a50` (feat)

_Note: This was a single `tdd="true"` task — RED commit first (10 failing tests), then GREEN commit (implementation makes them pass). No refactor commit needed — implementation was already minimal and clean._

## Files Created/Modified

- `core/tick_brain.py` — `think()` signature gained `system_override` kwarg; `active_system` / `primary_purpose` / `fallback_purpose` locals replace hardcoded values at both call sites; `_parse_response` gained topic_key falsy-guarded passthrough block.
  - Modified lines (approx): 101–161 (think signature + flow), 174–192 (_parse_response result block).
- `tests/test_tick_brain.py` — appended `TestSystemOverrideAndTopicKey` class with 10 tests covering: backward-compat (default behavior), override path, WARNING 1 regression (fallback purpose stays 'tick_fallback'), autonomous fallback bucket, active_system carry-through, topic_key presence / absence / empty-string / safe-mode / non-string coercion.

## Decisions Made

- **Layered purpose strings (not a flat dict lookup):** `fallback_purpose = primary_purpose + '_fallback'` is a 1-line derivation that scales naturally if a third bucket is added (e.g., `tick_eval` would auto-yield `tick_eval_fallback`). Avoids adding a separate map.
- **Falsy guard on topic_key (empty string treated as missing):** keeps the parser simple — downstream `core/autonomous.py` will synthesise a fallback slug (per plan Pitfall 4) when absent.
- **`system_override is not None` sentinel (not truthiness):** allows passing an empty string as an override if needed, though no current caller does. Keeps intent explicit.

## Deviations from Plan

None - plan executed exactly as written.

**Minor variance from done-criteria (not a deviation):** The plan's done-criterion `grep -c "_TICK_SYSTEM_PROMPT" core/tick_brain.py == 2` is now `3` because the new `think()` docstring includes the line `system_override: When set, replaces _TICK_SYSTEM_PROMPT for this call`. The plan's intent (no stray `_TICK_SYSTEM_PROMPT` hardcoding in `.chat()` calls) is fully satisfied — both `.chat()` call sites use the `active_system` variable. The third reference is in an informative docstring, not runtime code.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 06 (autonomous orchestrator) can now call `tick_brain.think(triage_prompt, system_override=<rendered autonomous_triage.md>)` and rely on `result.get('topic_key')` for `outreach_log` repeat-suppression dedup (per D-07).
- Heartbeat caller at `core/heartbeat.py:720` is unchanged — `brain.think(prompt)` still emits `purpose='tick'` (primary) / `purpose='tick_fallback'` (fallback). Phase 14 INFRA-02 fallback-rate dashboards remain valid.
- 4 distinct purpose buckets will materialize in `LLMUsageStore` once Plan 06 ships and the autonomous cron fires (Plan 07).

## Self-Check: PASSED

- `core/tick_brain.py` modified — FOUND
- `tests/test_tick_brain.py` modified — FOUND
- RED commit `8289310` — FOUND on main
- GREEN commit `ddf9a50` — FOUND on main
- `pytest tests/test_tick_brain.py -x` — 27/27 passed
- Regression suites (`test_firestore_db.py`, `test_prompts.py`, `test_evals.py`) — 69/69 passed
- `grep -c '"tick_fallback"' core/tick_brain.py` == 0 (WARNING 1 satisfied)
- `system_override` signature inspection — OK (default is None)

---
*Phase: 18-autonomous-engine*
*Completed: 2026-05-22*
