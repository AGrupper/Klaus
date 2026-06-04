---
phase: 22-expert-coaching-knowledge-d-13-release
plan: 02
subsystem: api
tags: [coaching, system-prompt, tool-registration, gemini-caching, brain-direct]

# Dependency graph
requires:
  - phase: 22-01
    provides: docs/COACHING_GUIDE.md with SLIM_CORE markers and ten <!-- SECTION: slug --> anchors
provides:
  - "_load_coaching_guide_slim() startup loader extracting the SLIM_CORE marker block from docs/COACHING_GUIDE.md"
  - "{coaching_guide} injected as the FIRST (stable-prefix) substitution in render_smart_system, before {self_md}"
  - "read_coaching_guide(topic) brain-direct tool registered at all four core/tools.py sites, excluded from the worker"
  - "_handle_read_coaching_guide(topic) returning section JSON for known slugs and error JSON otherwise (no path interpolation)"
affects: [22-03, 22-04, autonomous, morning_briefing, proactive_alerts]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Slim-core marker extraction mirrors _load_self_md(): regex on HTML-comment markers, '' + logger.warning on failure"
    - "Brain-direct tool 4-site registration (SMART_AGENT_DIRECT_TOOLS / TOOL_SCHEMAS / WORKER exclusion / _HANDLERS)"

key-files:
  created: []
  modified:
    - core/main.py
    - core/tools.py
    - tests/test_main_render_smart_system.py
    - tests/test_tools.py

key-decisions:
  - "{coaching_guide} placed first in the render .replace() chain to preserve Gemini stable-prefix caching"
  - "topic is matched only against authored <!-- SECTION: slug --> anchors via regex — never joined into a filesystem path (T-22-04)"
  - "read_coaching_guide is brain-direct only; added to the WORKER_TOOL_SCHEMAS exclusion set (T-22-05, honors 'brain never routes through worker first')"

patterns-established:
  - "Coaching knowledge substrate: slim core on every brain call + brain-direct deep lookup on demand"

requirements-completed: [COACH-01]

# Metrics
duration: ~9min
completed: 2026-06-04
---

# Phase 22 Plan 02: Coaching Guide Reasoning-Substrate Wiring

**Slim coaching core injected as a stable-prefix on every brain call, plus a brain-direct `read_coaching_guide(topic)` deep-lookup tool registered at all four sites and excluded from the worker (COACH-01)**

## Performance

- **Duration:** ~9 min (executor; SUMMARY write was interrupted by a session limit and rescued by the orchestrator)
- **Tasks:** 2/2 (TDD — test→feat per task)
- **Files modified:** 4

## Accomplishments
- `_load_coaching_guide_slim()` in `core/main.py` extracts the `<!-- SLIM_CORE_START -->`…`<!-- SLIM_CORE_END -->` block from `docs/COACHING_GUIDE.md`, cached on the orchestrator at startup right after `_self_md_content`.
- `render_smart_system` resolves `{coaching_guide}` as the FIRST `.replace()` link (before `{self_md}`), preserving stable-prefix caching; placeholder never survives render when content is "".
- `read_coaching_guide` brain-direct tool registered at all four `core/tools.py` sites and added to the `WORKER_TOOL_SCHEMAS` exclusion set.
- `_handle_read_coaching_guide(topic)` normalizes the slug and regex-matches authored `<!-- SECTION: slug -->` anchors, returning `{"content": ...}` on hit and `{"error": ...}` on miss — never raises, never interpolates a path.

## Task Commits

1. **Task 1: Slim-core loader + render injection** — `284f904` (test) → `af5792c` (feat)
2. **Task 2: read_coaching_guide 4-site registration + handler** — `33ac2e9` (test) → `de70b60` (feat)

**Merge to main:** `84a6b76` (worktree merge) · **SUMMARY:** rescued + committed by orchestrator

## Files Created/Modified
- `core/main.py` — `_load_coaching_guide_slim()` + startup cache + `{coaching_guide}` render substitution (first in chain)
- `core/tools.py` — `read_coaching_guide` schema + `_handle_read_coaching_guide` + 4-site registration / worker exclusion
- `tests/test_main_render_smart_system.py` — coaching_guide substitution + slim-core-size guard tests
- `tests/test_tools.py` — `read_coaching_guide` 4-site + handler hit/miss tests (`TestPhase22CoachingGuideTool`)

## Decisions Made
None beyond plan — executed as specified. Slug→anchor regex (no path join) and worker exclusion were the planned T-22-04/T-22-05 mitigations.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
The executor subagent hit a session-usage limit immediately after committing the final feat commit (`de70b60`) but **before** writing `22-02-SUMMARY.md`. All code and tests were committed atomically and intact. The orchestrator rescued the missing SUMMARY: verified the five must-have wiring points on the merged `main` (loader, startup cache, render-chain order, 4-site registration, handler) and ran the full test suite (843 passed, 3 skipped) before authoring this file. No code was re-executed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- COACH-01 reasoning-substrate wiring is live on every brain call.
- `{coaching_guide}` placeholder is resolved by `render_smart_system`; Plan 04's `prompts/smart_agent.md` placeholder now has its substitution source.
- `read_coaching_guide` is available brain-direct for Plan 03's coaching-aware crons and for mini-lesson lookups.

---
*Phase: 22-expert-coaching-knowledge-d-13-release*
*Completed: 2026-06-04*
