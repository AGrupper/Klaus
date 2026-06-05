---
phase: 22-expert-coaching-knowledge-d-13-release
plan: 03
subsystem: api
tags: [coaching, crons, morning-briefing, proactive-alerts, autonomous, prompt-injection]

# Dependency graph
requires:
  - phase: 22-02
    provides: AgentOrchestrator._coaching_guide_content cached slim core + render_smart_system {coaching_guide} substitution
provides:
  - "{coaching_guide} placeholder in prompts/morning_briefing.md, prompts/proactive_alert.md, prompts/autonomous.md"
  - "_compose_briefing injects the slim core before {today_date} (stable-prefix ordering)"
  - "_compose_alert injects the slim core before {today_date}"
  - "autonomous Layer-2 receives the slim core via its existing render_smart_system call (autonomous.py unchanged)"
  - "no-literal-placeholder unit tests for both compose paths"
affects: [autonomous, morning_briefing, proactive_alerts]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cron compose-time injection: function-local import of the orchestrator singleton + .replace('{coaching_guide}', ...) before volatile {today_date}"

key-files:
  created: []
  modified:
    - prompts/morning_briefing.md
    - prompts/proactive_alert.md
    - prompts/autonomous.md
    - core/morning_briefing.py
    - core/proactive_alerts.py
    - tests/test_main_render_smart_system.py

key-decisions:
  - "Crons that compose their own prompts (briefing, alert) inject the slim core at compose time; autonomous Layer-2 only needs the placeholder because it already passes through render_smart_system"
  - "D-05 cost bias: morning_briefing.md and autonomous.md carry an explicit 'stay on the cheap core; only call read_coaching_guide on why?/uncovered-protocol' steer"
  - "Import _get_orchestrator from core.autonomous (its actual home), not core.main as the plan interface stated — corrected to prevent a runtime ImportError crash in both crons"

patterns-established:
  - "Every proactive coaching touchpoint (briefing, evening alert, autonomous tick) carries the slim coaching core"

requirements-completed: [COACH-01, COACH-02]

# Metrics
duration: ~partial (executor socket-dropped mid-task-2; orchestrator completed + fixed + merged)
completed: 2026-06-05
---

# Phase 22 Plan 03: Coaching-Aware Proactive Crons

**Morning briefing, evening alert, and autonomous tick all carry the slim coaching core — injected at compose time for the two self-composing crons, via render_smart_system for autonomous — with a D-05 cost-bias steer and no literal placeholder leaking (COACH-01/02)**

## Performance

- **Tasks:** 2/2
- **Files modified:** 6
- **Note:** The executor subagent completed Task 1 (committed) and authored all of Task 2's edits, but a socket disconnect dropped the agent before it could run the Task-2 tests, commit, or write this SUMMARY. The orchestrator verified the edits, caught and fixed a plan-interface defect (see Deviations), ran the tests green, committed Task 2, and merged.

## Accomplishments
- `{coaching_guide}` placeholder added near the top of all three cron templates (before any `{today_date}`), preserving stable-prefix ordering.
- `morning_briefing.md` and `autonomous.md` carry the D-05 cost-bias instruction (stay on the cheap slim core; `read_coaching_guide(topic)` only for "why?" / uncovered protocols).
- `_compose_briefing` and `_compose_alert` inject `_get_orchestrator()._coaching_guide_content` via `.replace("{coaching_guide}", ...)` before `{today_date}`; OSError plain-text fallbacks preserved.
- `core/autonomous.py` left untouched — its `render_smart_system` call resolves the placeholder once the template carried it.
- Added `test_briefing_no_literal_placeholder` and `test_alert_no_literal_placeholder` (T-22-08): assert no literal `{coaching_guide}` survives compose.

## Task Commits

1. **Task 1: {coaching_guide} placeholders in cron templates** — `cc7cfd0` (feat)
2. **Task 2: compose-time slim-core injection + no-literal-placeholder tests** — `3ff5460` (feat, includes the interface-fix deviation)

## Files Created/Modified
- `prompts/morning_briefing.md` — `{coaching_guide}` placeholder + cost-bias steer
- `prompts/proactive_alert.md` — `{coaching_guide}` placeholder
- `prompts/autonomous.md` — `{coaching_guide}` placeholder + cost-bias steer
- `core/morning_briefing.py` — compose-time injection in `_compose_briefing`
- `core/proactive_alerts.py` — compose-time injection in `_compose_alert`
- `tests/test_main_render_smart_system.py` — two no-literal-placeholder tests

## Decisions Made
See key-decisions frontmatter. Core call: self-composing crons inject at compose time; the render_smart_system-backed autonomous path only needs the template placeholder.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Incorrect plan interface] `_get_orchestrator` import source was wrong**
- **Found during:** Task 2 (compose-time injection) — surfaced by `test_briefing_no_literal_placeholder` raising `AttributeError: module 'core.main' has no attribute '_get_orchestrator'`.
- **Issue:** The plan's `<interfaces>` block stated `core/main.py:_get_orchestrator()`. In the actual codebase `_get_orchestrator()` is defined in `core/autonomous.py`. The executor coded `from core.main import _get_orchestrator` verbatim — which would raise `ImportError` and **crash both the morning-briefing and proactive-alert crons at runtime**, not just fail the tests.
- **Fix:** Changed the function-local import in both `_compose_briefing` and `_compose_alert` to `from core.autonomous import _get_orchestrator`, and repointed the two test patches to `core.autonomous._get_orchestrator`. Confirmed `core/autonomous.py` imports only stdlib at module level, so the function-local import carries no circular-import risk.
- **Verification:** `pytest tests/test_main_render_smart_system.py -k "no_literal_placeholder or coaching_guide" tests/test_proactive_alerts.py tests/test_morning_briefing.py` → 8 passed.
- **Committed in:** `3ff5460` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 incorrect plan interface)
**Impact on plan:** Essential for correctness — the planned import would have crashed the two crons in production. No scope creep.

## Issues Encountered
Executor socket disconnect mid-Task-2 (after all edits were written, before commit/SUMMARY). Resolved by the orchestrator without re-executing: verified the in-worktree edits, fixed the interface defect, ran tests green, committed, and merged.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- COACH-01/02 reach every proactive coaching touchpoint; SC-2 (briefing/alert name the specific session + load) is unblocked.
- Phase 22 code work is complete pending 22-04's live D-13 smoke test (SC-1/SC-3/SC-4).

---
*Phase: 22-expert-coaching-knowledge-d-13-release*
*Completed: 2026-06-05*
