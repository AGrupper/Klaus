---
phase: 33-occasion-cascade
plan: 02
subsystem: agent-orchestration
tags: [python, llm-tool-loop, sonnet-5, docs-generation]

# Dependency graph
requires:
  - phase: 30.5-brain-upgrade-sonnet-5
    provides: claude-sonnet-5 as smart_agent, max_tokens-aware LLMClient.chat() across all backends
provides:
  - "_run_smart_loop max_tokens passthrough (threadable per-compose output budget)"
  - "D-22 tools-stripped forced-final turn on MAX_TOOL_ITERATIONS exhaustion"
  - "docs/SELF.md MAX_TOOL_ITERATIONS line sourced live from core.main, never hardcoded again"
affects: [33-04, 33-08, 35-hardening-subtraction]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy cross-module import with a documented numeric fallback, for docs generators that must survive a dev/CI environment without the full dependency stack"
    - "Tools-stripped forced-final LLM turn as the last resort before an apologetic fallback string (purpose='smart_forced_final')"

key-files:
  created: []
  modified:
    - core/main.py
    - core/self_manifest.py
    - tests/test_main.py
    - tests/test_docs.py
    - docs/SELF.md

key-decisions:
  - "max_tokens threaded only into the two self.smart_agent.chat() call sites named in the plan (in-loop primary + forced-final) — not into the fallback/tertiary chat() calls, matching the plan's interface contract literally and the acceptance-criteria test scope."
  - "Forced-final sentinel check reuses the existing CONNECTIVITY_ERROR_TEXT constant already defined in core/main.py rather than importing autonomous.py's _SMART_LOOP_ERROR_SENTINELS, avoiding a main.py -> autonomous.py import (autonomous.py already imports from main.py)."
  - "docs/SELF.md regenerated as part of this plan (plan explicitly preferred this over leaving a stale committed copy) — picked up an unrelated pre-existing drift (Phase 31/32 tools missing from the 'Other' category) as a byproduct of running the generator honestly."

requirements-completed: [OCC-05]

# Metrics
duration: ~35min
completed: 2026-07-29
---

# Phase 33 Plan 02: Forced Final Answer + max_tokens Passthrough Summary

**`_run_smart_loop` takes a tools-stripped forced-final turn on iteration exhaustion (D-22) instead of downgrading to an apology, gained a threadable `max_tokens` kwarg for oversized composes (D-21), and `docs/SELF.md`'s tool-iteration cap line now reads live from `core.main` instead of a stale hardcoded 8.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-29T13:55Z
- **Tasks:** 2/2 completed
- **Files modified:** 5 (core/main.py, core/self_manifest.py, tests/test_main.py, tests/test_docs.py, docs/SELF.md)

## Accomplishments

- Layer 2 (`_run_smart_loop`) no longer silently discards a thorough compose that used its full 12-iteration tool budget: on exhaustion it now takes exactly one more `tools=None` turn (`purpose="smart_forced_final"`) and returns real brain-composed text if that turn succeeds, falling through to the pre-existing `last_response_text`/apology chain only if it also fails.
- `MAX_TOOL_ITERATIONS = 12` is unchanged and remains the sole runaway guard (D-21) — no occasion-specific cap was introduced anywhere.
- `_run_smart_loop` gained an optional `max_tokens: int | None = None` kwarg, threaded into the in-loop primary call and the new forced-final call, so a future caller (the 33-04/33-08 weekly-review cascade compose) can raise the output budget for one compose without a global change.
- `core/self_manifest.py`'s "Max tool iterations per conversation" line in `docs/SELF.md` now lazy-imports `MAX_TOOL_ITERATIONS` from `core.main` at generate time (with a documented `12` fallback if the import fails in a dependency-light dev/CI run), so it can never drift from the real constant again. `docs/SELF.md` was regenerated.

## Task Commits

Each task was committed atomically:

1. **Task 1: Forced final answer on iteration exhaustion (D-22) + max_tokens passthrough** - `29323ec` (feat)
2. **Task 2: Fix the stale MAX_TOOL_ITERATIONS = 8 in the SELF.md generator** - `b5e9e69` (fix)

**Plan metadata:** (this SUMMARY commit, made by the orchestrator's worktree-merge flow)

## Files Created/Modified

- `core/main.py` - `_run_smart_loop` gained `max_tokens` param (threaded to the in-loop call) and the D-22 forced-final turn before the exhaustion fallback chain
- `core/self_manifest.py` - `_render_manifest` lazy-imports `core.main.MAX_TOOL_ITERATIONS` instead of hardcoding "8", with a `12` fallback and a `logger.warning` on import failure
- `tests/test_main.py` - 4 new tests: forced-final success (asserts `tools=None` + `purpose="smart_forced_final"` on the 13th call), forced-final exception fallback to `last_response_text`, forced-final empty-text fallback to the apology, and `max_tokens=32000` passthrough onto the in-loop call
- `tests/test_docs.py` - new test asserting the generated manifest contains `str(core.main.MAX_TOOL_ITERATIONS)` and never the literal stale `"iterations per conversation:** 8"` substring
- `docs/SELF.md` - regenerated (new sha, new `generated_at`, corrected cap line 8→12)

## Decisions Made

- `max_tokens` is threaded only into the two `self.smart_agent.chat(...)` call sites the plan's `<interfaces>` block names explicitly (the in-loop primary call and the new forced-final call) — not into the `smart_agent_fallback`/`smart_agent_tertiary` chat calls, which are different attributes and out of the plan's stated scope. This matches the acceptance-criteria test, which only asserts the in-loop call.
- The forced-final turn's sentinel guard reuses `CONNECTIVITY_ERROR_TEXT` (already defined in `core/main.py`) rather than importing `core.autonomous._SMART_LOOP_ERROR_SENTINELS` — `autonomous.py` already imports from `main.py`, so importing the reverse direction would risk a cycle; the two constants are definitionally the same string.
- `docs/SELF.md` was regenerated per the plan's stated preference. Doing so surfaced an unrelated, pre-existing drift (Phase 31/32's `forget_memory`/`set_standing_directive`/`list_standing_directives`/`cancel_standing_directive` tools were never reflected in the "Other" category because nobody had regenerated the file since those phases shipped). This is an honest byproduct of running the generator, not scope creep — the file's own header says "Do not edit manually — changes will be overwritten."

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**Local test environment lacked project dependencies.** This worktree ships without a Python venv, and the system `python3` here is 3.14 (which the project's own `CLAUDE.md`/memory explicitly forbids — grpc/protobuf native-wheel GC segfaults). Running the plan's required `pytest` verification commands against bare system Python 3.14 surfaced 2 pre-existing, unrelated failures (`ModuleNotFoundError: No module named 'openai'`/`'googleapiclient'` in `TestThreeTierFallbackChain`) that have nothing to do with this plan's code paths. To get a trustworthy verification run, a throwaway Python 3.13 venv was created under the scratchpad directory (`/private/tmp/.../scratchpad/venv313`, never committed) and `pip install -r requirements.txt` run into it. With the correct dependency stack, all 192 tests across `tests/test_main.py` (40), `tests/test_docs.py` (17), and `tests/test_autonomous.py` (135) pass, including the two previously-"failing" tertiary-client tests — confirming those were purely a missing-package artifact of the bare worktree, not a regression from this plan's changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 33-04 and 33-08 (the occasion cascade Layer-2 composes) can now call `_run_smart_loop(..., max_tokens=32000)` for the weekly-review-sized compose and rely on D-22's forced-final turn to prevent a silent downgrade to the free triage draft when the agentic loop uses its full 12-iteration budget.
- No blockers. `docs/SELF.md` is now self-correcting for this specific field going forward.

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-29*
