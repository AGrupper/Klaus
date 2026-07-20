---
phase: 31-standing-directives
plan: 03
subsystem: api
tags: [standing-directives, brain-direct-tools, prompt-injection, firestore, cache-safe-ordering]

# Dependency graph
requires:
  - phase: 31-standing-directives (Plan 01)
    provides: StandingDirectiveStore (memory/firestore_db.py) — add/list_active/list_all/cancel/supersede/expire
provides:
  - "3 brain-direct tools: set_standing_directive, list_standing_directives, cancel_standing_directive"
  - "render_standing_directives_block(directives, *, style) — the ONE shared formatter for all 5 injection sites"
  - "{standing_directives} placeholder in core/main.py::render_smart_system (chat path, DIR-03 site 1 of 5)"
  - "STANDING DIRECTIVES capture rule in prompts/smart_agent.md (D-01/D-02/D-03/D-06/D-16 + security scoping)"
affects: [31-04, 31-05, 31-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "3-site brain-direct tool registration (SMART_AGENT_DIRECT_TOOLS frozenset + worker-exclusion list + _HANDLERS dispatch) — replicated from schedule_followup/list_followups/cancel_followup"
    - "render_standing_directives_block(directives, *, style='prose'|'json') co-located in core/tools.py — one formatter, N call sites, no drift (mirrors _format_now_block in core/autonomous.py)"
    - "Best-effort orchestrator-level store attribute (_standing_directive_store, built via _build_standing_directive_store()) mirroring the existing _user_profile_store/_self_state_store/_journal_store convention"
    - "Cache-safe placeholder ordering: {standing_directives} inserted after {training_profile} and before {today_date} in both the .replace() chain and the prompt template, preserving the Anthropic prompt-caching stable prefix"

key-files:
  created: []
  modified:
    - core/tools.py
    - core/main.py
    - prompts/smart_agent.md
    - tests/test_tools.py
    - tests/test_main_render_smart_system.py

key-decisions:
  - "expires_at natural-language parse failures fall through to storing the raw string rather than erroring, since condition_text is the intended path for non-dated expiries and set_standing_directive has no error-return contract like schedule_followup's could_not_parse_when (the brain is expected to pass ISO or omit the field)"
  - "_standing_directive_store built as an orchestrator attribute (via _build_standing_directive_store(), mirroring _build_user_profile_store()) rather than reading the store fresh inside render_smart_system — keeps the unit-test convention (AgentOrchestrator.__new__ + manual attribute injection) consistent across all 4 sibling context blocks"
  - "context_quote defaults to the captured text itself in _handle_set_standing_directive (D-03: the triggering exchange IS the current restatement for 'I already told you...' triggers) rather than requiring a separate conversation-history lookup"

patterns-established:
  - "render_standing_directives_block is now the load-bearing shared dependency for Plans 04 (tick triage + Layer-2 compose), 05 (interim nightly/morning cron injection), and 06 (reflection self-directive proposals) — all must import it via 'from core.tools import render_standing_directives_block' rather than re-implementing formatting"

requirements-completed: [DIR-01, DIR-03, DIR-04, DIR-05]

# Metrics
duration: ~25min (active work; session context-reset once between Task 1 and Task 2)
completed: 2026-07-20
---

# Phase 31 Plan 03: Directive Capture — Chat Tools + Shared Formatter Summary

**Three brain-direct directive tools (set/list/cancel_standing_directive) wired into the chat path, plus the one shared `render_standing_directives_block()` formatter and `{standing_directives}` cache-safe chat-prompt injection that Plans 04/05/06 import.**

## Performance

- **Duration:** ~25 min active work
- **Started:** 2026-07-19T23:14:43+03:00
- **Completed:** 2026-07-20T08:41:22+03:00
- **Tasks:** 2 completed
- **Files modified:** 5

## Accomplishments
- `set_standing_directive`/`list_standing_directives`/`cancel_standing_directive` registered at all 3 required sites (`SMART_AGENT_DIRECT_TOOLS`, worker-exclusion list, `_HANDLERS`) with load-bearing "Call this directly — do NOT delegate to the worker." phrasing in every schema description
- Handlers back onto `StandingDirectiveStore` (Plan 01): capture defaults `origin="user_chat"` + `context_quote=text` (D-03 verbatim restatement), list defaults to `list_active()` with `include_history` opt-in to `list_all()` (D-17/D-18), cancel is idempotent
- `render_standing_directives_block(directives, *, style="prose"|"json")` added to `core/tools.py` — the single shared formatter Plans 04/05/06 will import for the remaining 4 injection sites (never re-implemented per-site)
- `{standing_directives}` wired into `core/main.py::render_smart_system` at the cache-safe position (after `{training_profile}`, before `{today_date}`) via a new best-effort `_standing_directive_store` orchestrator attribute
- `STANDING DIRECTIVES` capture-rule section added to `prompts/smart_agent.md`, covering D-01 (liberal capture), D-02 ("Standing order, Sir: …" ack format), D-03 ("I already told you…" restatement trigger), D-06 (conditionless soft-ask), D-16 (persona-conflict "which wins, Sir?" resolution), and an explicit security constraint scoping capture to live Amit chat turns only — never tool-read content
- 27 new tests (23 in `test_tools.py`, 4 in `test_main_render_smart_system.py`, including a load-bearing ordering assertion), full targeted suites green: `test_tools.py` 94/94, `test_main_render_smart_system.py` 40/40, `test_firestore_db.py` 61/61, `test_main.py` 27/27 — no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the three brain-direct directive tools + capture rule** - `fee39c5` (feat)
2. **Task 2: Shared formatter + {standing_directives} chat-prompt injection** - `870a01e` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `core/tools.py` - 3 tool schemas + 3 handlers (`_handle_set_standing_directive`, `_handle_list_standing_directives`, `_handle_cancel_standing_directive`) + `render_standing_directives_block()` formatter, registered at all 3 brain-direct sites
- `core/main.py` - `_build_standing_directive_store()` helper (mirrors `_build_user_profile_store`), `_standing_directive_store` attribute, `standing_directives_snippet` build + `.replace("{standing_directives}", ...)` insertion in `render_smart_system`
- `prompts/smart_agent.md` - `STANDING DIRECTIVES` section (after SELF-SCHEDULED FOLLOW-UPS, before CAPABILITY MANIFEST) + `{standing_directives}` placeholder line (after `{training_profile}`, before the `{today_date}` prose paragraph)
- `tests/test_tools.py` - `TestStandingDirectiveTools` (23 tests) + `_FakeStandingDirectiveStore`/`fake_directive_store` fixture mirroring `_FakeFollowupStore`/`fake_store`
- `tests/test_main_render_smart_system.py` - `TestStandingDirectivesRendering` (4 tests: non-empty render, empty-resolves-to-nothing, store-None, cache-prefix ordering assertion)

## Decisions Made
- `expires_at` natural-language parse failures fall through to storing the field as-received (not surfaced as a structured error like `schedule_followup`'s `could_not_parse_when`) — `condition_text` is the intended path for non-dated/event-based expiries, and the brain is expected to pass ISO 8601 where a hard date is genuinely known.
- `_standing_directive_store` follows the existing `_user_profile_store`/`_self_state_store`/`_journal_store` orchestrator-attribute convention (built once via a `_build_*` helper, guarded with `getattr(self, ..., None)` in `render_smart_system`) rather than instantiating `StandingDirectiveStore` fresh inline — keeps this plan's new test class consistent with the established `AgentOrchestrator.__new__` + manual-attribute unit-test pattern used by every sibling context block.
- `_handle_set_standing_directive` defaults `context_quote` to the captured `text` itself, satisfying D-03's "current restatement, no history digging" requirement without a separate conversation-history read.

## Deviations from Plan

None — plan executed exactly as written. Both tasks' acceptance criteria were verified verbatim: all 3 registration sites confirmed via grep, `Call this directly` count went from 10 → 13 (exactly +3), the `STANDING DIRECTIVES` section and `Standing order, Sir` phrase and explicit tool-scoping security constraint are present in `prompts/smart_agent.md`, `render_standing_directives_block` handles both `style="prose"` and `style="json"`, and the ordering assertion in `TestStandingDirectivesRendering` confirms `{standing_directives}` resolves strictly between the training-profile and today-date content.

## Issues Encountered

Session hit a usage-limit reset mid-execution, between committing Task 1 (`fee39c5`) and finishing Task 2's test additions. On resume, re-verified actual git state (`git status`/`git log`) rather than trusting prior context before continuing — confirmed Task 1 was committed and Task 2's `core/main.py`/`core/tools.py`/`prompts/smart_agent.md` edits were already made but uncommitted, then completed the remaining test file and committed. No rework was needed; not logged as a plan deviation since no code/scope changed.

## User Setup Required

None - no external service configuration required. Both tools read/write through the existing `StandingDirectiveStore` (Plan 01), which uses the schemaless `standing_directives` Firestore collection already provisioned.

## Next Phase Readiness

`render_standing_directives_block()` is now the load-bearing shared dependency for:
- **Plan 04** (autonomous tick triage snapshot + Step-0 veto, Layer-2 compose, follow-up compose) — imports via `from core.tools import render_standing_directives_block`
- **Plan 05** (interim `nightly_review`/`morning_briefing` direct injection with D-21/D-22 veto power)
- **Plan 06** (reflection learning loop's self-directive proposals, `origin="klaus_self"`)

The chat-path injection site (1 of 5 total per DIR-03) is complete and cache-safe. `set_standing_directive`/`list_standing_directives`/`cancel_standing_directive` are live end-to-end against the real `StandingDirectiveStore` in chat — Amit can now state a lasting wish and have Klaus capture, list, or cancel it directly in conversation. No blockers for downstream plans.

---
*Phase: 31-standing-directives*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: core/tools.py
- FOUND: core/main.py
- FOUND: prompts/smart_agent.md
- FOUND: tests/test_tools.py
- FOUND: tests/test_main_render_smart_system.py
- FOUND: .planning/phases/31-standing-directives/31-03-SUMMARY.md
- FOUND commit: fee39c5 (feat, Task 1)
- FOUND commit: 870a01e (feat, Task 2)
- FOUND commit: a9a1c3a (docs, plan metadata)
