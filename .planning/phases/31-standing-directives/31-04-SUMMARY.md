---
phase: 31-standing-directives
plan: 04
subsystem: autonomous-engine
tags: [standing-directives, autonomous-tick, triage-veto, layer2-compose, context-only-gather]

# Dependency graph
requires:
  - phase: 31-standing-directives (Plan 01)
    provides: StandingDirectiveStore (memory/firestore_db.py) — add/list_active/list_all/cancel/supersede/expire
  - phase: 31-standing-directives (Plan 03)
    provides: render_standing_directives_block(directives, *, style) — the shared formatter
provides:
  - "_gather_standing_directives context-only Layer-0 job in core/autonomous.py"
  - "Step-0 STANDING ORDERS topic-scoped veto in prompts/autonomous_triage.md"
  - "standing_directives snapshot key in _build_triage_prompt, _compose_layer2, _compose_followup_layer2"
affects: [31-05, 31-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_gather_standing_directives mirrors the _gather_due_followups try/except -> [] sentinel shape"
    - "standing_directives deliberately excluded from _is_empty_signals with a documented comment (mirrors training_status/acwr precedent) — context-only, never a Layer-0 trigger (Pitfall 4)"
    - "render_standing_directives_block(style='json') parsed via json.loads() into the triage/compose snapshot dicts for parity across all 3 sites; style='prose' for the human-readable triage prompt section"
    - "Step-0 veto inserted above the existing Step-1 vetoes block in prompts/autonomous_triage.md — topic-scoped ('stated scope plausibly covers'), not blanket (Pitfall 1); scope uncertainty suppresses + flags for reflection (D-15)"

key-files:
  created: []
  modified:
    - core/autonomous.py
    - prompts/autonomous_triage.md
    - tests/test_autonomous.py

key-decisions:
  - "Both Layer-2 compose snap dicts (_compose_layer2, _compose_followup_layer2) use the same json.loads(render_standing_directives_block(..., style='json')) shape as the triage snapshot, rather than the raw StandingDirectiveStore dict — keeps all 3 reasoning-surface snapshots byte-identical in shape, so a directive reads the same regardless of which layer is judging it"
  - "The triage prompt's 'Active standing directives:' prose section renders '(none active)' rather than omitting the section entirely when there are no active directives — keeps the prompt's fixed input-block shape stable across ticks (unlike the chat-path {standing_directives} placeholder from Plan 03, which omits entirely for a cache-safe empty state; the triage prompt is not cache-optimized the same way and tick-brain benefits from a consistent section list)"
  - "core/autonomous.py's prompts/autonomous_triage.md '## Inputs (rendered at runtime)' block is documentation of the shape _build_triage_prompt produces, not a literal .format() template — added the standing_directives line there for documentation parity, and the actual runtime text is produced directly by _build_triage_prompt's return statement (matches the existing pattern for every other input block)"

requirements-completed: [DIR-03]

# Metrics
duration: ~20min
completed: 2026-07-20
---

# Phase 31 Plan 04: Autonomous Tick — Standing Directives Injection Summary

**Wires DIR-03's tick/compose sites: a context-only `_gather_standing_directives` Layer-0 job that can never wake the free tier on its own, plus a topic-scoped Step-0 "STANDING ORDERS" veto in the triage prompt and a `standing_directives` snapshot key in both Layer-2 composes.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-20T05:35:00Z
- **Completed:** 2026-07-20T05:52:00Z
- **Tasks:** 2 completed
- **Files modified:** 3

## Accomplishments
- `_gather_standing_directives(project_id, database)` added to `core/autonomous.py`, following the `_gather_due_followups` try/except → `[]` sentinel shape; registered in `gather_situation`'s jobs dict as `"standing_directives"`
- `_is_empty_signals` carries a new documented comment explaining `standing_directives` is deliberately excluded (context-only, mirrors `training_status`/`acwr`) — verified by grep: no `situation.get("standing_directives")` check exists inside the function body
- `prompts/autonomous_triage.md` gained a new `Step 0 — STANDING ORDERS` block immediately above the existing `Step 1 — vetoes`: a directive vetoes the current tick's topic only if its stated scope plausibly covers what's about to be raised (topic-scoped, not blanket, Pitfall 1); triage names which directive it applied; genuine scope uncertainty suppresses now and flags for tonight's reflection (D-15). An "Active standing directives:" line was added to the Inputs block for documentation parity.
- `_build_triage_prompt` lazily imports `render_standing_directives_block`, adds a `standing_directives` JSON snapshot key (parsed via `json.loads(render_standing_directives_block(..., style="json"))`), and appends a prose "Active standing directives:" section (rendering `(none active)` when empty) to the returned prompt
- `_compose_layer2` and `_compose_followup_layer2` both gained a `standing_directives` key in their inline snap dicts for parity — the chat-style system-prompt injection for these two paths already flows automatically through `render_smart_system` per Plan 03, so no separate system-prompt wiring was needed here
- 9 new tests across two new test classes (`TestStandingDirectivesGather` — 5 tests, `TestStandingDirectivesTriageAndCompose` — 4 tests): sentinel-on-failure, key-present-in-assembled-situation, empty-gate-stays-empty-with-only-directives, triage-prompt-includes/omits directive text, and both composes carry the snapshot key. Full `tests/test_autonomous.py` suite green: 89 passed (80 baseline + 9 new). No regressions in `tests/test_prompts.py`, `tests/test_tick_brain.py`, `tests/test_evals.py`, `tests/test_tools.py`, `tests/test_main.py`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Context-only `_gather_standing_directives` job (never a trigger)** - `b4fe3db` (feat)
2. **Task 2: Step-0 STANDING ORDERS veto + Layer-2/follow-up compose injection** - `58a02e1` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `core/autonomous.py` — `_gather_standing_directives` job, `standing_directives` entry in `gather_situation`'s jobs dict, documented context-only exclusion comment in `_is_empty_signals`, `standing_directives` snapshot key + prose section in `_build_triage_prompt`, `standing_directives` key in `_compose_layer2` and `_compose_followup_layer2` snap dicts (3 lazy imports of `render_standing_directives_block`)
- `prompts/autonomous_triage.md` — new `Step 0 — STANDING ORDERS` block above `Step 1 — vetoes`; `Active standing directives:` line in the Inputs block
- `tests/test_autonomous.py` — `TestStandingDirectivesGather` (5 tests: sentinel-on-failure, active-directives-returned, key-in-assembled-situation, empty-gate-stays-empty-with-directives, empty-gate-stays-empty-with-none) + `TestStandingDirectivesTriageAndCompose` (4 tests: prompt-includes/omits directive text, both composes carry the key)

## Decisions Made
- Both `_compose_layer2` and `_compose_followup_layer2` use the identical `json.loads(render_standing_directives_block(..., style="json"))` shape as the triage snapshot, rather than passing the raw `StandingDirectiveStore` dict list, so all 3 reasoning surfaces see byte-identical directive shape regardless of which layer is judging.
- The triage prompt's "Active standing directives:" section renders `(none active)` rather than being omitted for an empty list — unlike the cache-optimized chat-path `{standing_directives}` placeholder from Plan 03 (which omits entirely to preserve prompt-cache stability), the triage prompt is rebuilt fresh every tick and benefits from a stable, predictable input-block list for tick-brain.
- The "## Inputs (rendered at runtime)" section of `prompts/autonomous_triage.md` documents the shape `_build_triage_prompt` produces — it is not a literal string-substitution template. Added the `{standing_directives_block}` line there purely for documentation parity with the other 4 existing input labels; the runtime text itself is produced directly by `_build_triage_prompt`'s return statement, matching the file's existing convention.

## Deviations from Plan

None — plan executed exactly as written. Both tasks' acceptance criteria were verified verbatim: `def _gather_standing_directives` and the `standing_directives` jobs-dict entry are present, the context-only comment sits at the `_is_empty_signals` site with zero actual `standing_directives` checks in the function body, `Step 0` / `STANDING ORDERS` / `stated scope plausibly covers` all appear in `prompts/autonomous_triage.md`, `_build_triage_prompt` references `render_standing_directives_block` and carries the snapshot key, both composes' snap dicts contain `standing_directives`, and `pytest tests/test_autonomous.py -x` exits 0 (89 passed).

## Issues Encountered

None. Worktree had no local `.venv`; used the main repo's `/Users/amitgrupper/Desktop/Klaus/.venv` (Python 3.13) for all `pytest` invocations per the environment note — no code or config change required.

## User Setup Required

None — no external service configuration required. This plan only consumes the already-provisioned `StandingDirectiveStore` (Plan 01) and `render_standing_directives_block` (Plan 03).

## Next Phase Readiness

The tick/compose sites of DIR-03 are fully live: an active standing directive now reaches tick triage as a topic-scoped Step-0 veto, and reaches both Layer-2 compose paths (proactive nudge + follow-up) as context. Combined with Plan 03's chat-path injection, DIR-03 has 3 of its 5 total injection sites complete (chat, tick triage, Layer-2 compose, follow-up compose — 4 of 5; the interim legacy nightly/morning-briefing cron injection is Plan 05's scope). The `_gather_standing_directives` context-only precedent (and its exact test pattern) is ready for Plan 05 to reuse for the interim `nightly_review`/`morning_briefing` direct injection with D-21/D-22 veto power, and for Plan 06's reflection learning-loop self-directive proposals. No blockers.

---
*Phase: 31-standing-directives*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: core/autonomous.py
- FOUND: prompts/autonomous_triage.md
- FOUND: tests/test_autonomous.py
- FOUND: .planning/phases/31-standing-directives/31-04-SUMMARY.md
- FOUND commit: b4fe3db (feat, Task 1)
- FOUND commit: 58a02e1 (feat, Task 2)
