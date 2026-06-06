---
phase: 24-strict-coaching-integration-nutrition-accountability
plan: 03
subsystem: api
tags: [smart-loop, tool-iteration, coaching-guide, fuzzy-match, double-send-fix]

# Dependency graph
requires:
  - phase: 22-expert-coaching-knowledge
    provides: "_handle_read_coaching_guide + COACHING_GUIDE.md with SECTION anchors"
  - phase: 24-strict-coaching-integration-nutrition-accountability
    provides: "Phase 24 plans 01-02 (coaching stores, training quality)"

provides:
  - "Hardened _handle_read_coaching_guide: candidate count replaces first-hit fuzzy (WR-02)"
  - "MAX_TOOL_ITERATIONS raised 8→12 for data-heavy Phase-24 coaching turns"
  - "last_response_text double-send fix: substantive brain text at cap suppresses apologetic fallback"

affects:
  - phase-24-plans-04-05
  - coaching-query-path
  - smart-loop-exhaustion

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "candidate_anchors = re.findall(anchor_pattern) then len(candidate_anchors) == 1 guard for unambiguous fuzzy match"
    - "last_response_text tracker before smart loop; guard at exhaustion len > 100"

key-files:
  created:
    - tests/test_main.py
  modified:
    - core/tools.py
    - core/main.py
    - tests/test_tools.py

key-decisions:
  - "WR-02 fuzzy hardening: candidate count (findall) not first-hit search; skip words < 4 chars; only unambiguous (len==1) match returns content — ambiguous returns not-found so brain falls to slim core"
  - "Double-send fix: track last_response_text per iteration; at exhaustion return it when len > 100 chars instead of apologetic sentinel — preserves SC-1 (text is brain-composed) and CONNECTIVITY_ERROR_TEXT sentinel unchanged"
  - "Cap raised to 12 (from 8) to cover legitimate 6-tool data-gather coaching turns without prematurely hitting exhaustion"

patterns-established:
  - "TDD RED/GREEN per task: test committed before implementation for both tools.py and main.py changes"

requirements-completed: [COACH-03, COACH-04, COACH-05]

# Metrics
duration: 15min
completed: 2026-06-06
---

# Phase 24 Plan 03: Infrastructure Fixes — Fuzzy Match Hardening + Double-Send Fix Summary

**Hardened read_coaching_guide fuzzy match (candidate count, WR-02) and fixed smart-loop double-send by raising MAX_TOOL_ITERATIONS to 12 + last_response_text suppression at cap exhaustion**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-06-06T13:44:00Z
- **Completed:** 2026-06-06T13:54:49Z
- **Tasks:** 2 (both TDD: RED commit + GREEN commit each)
- **Files modified:** 4 (core/tools.py, core/main.py, tests/test_tools.py, tests/test_main.py created)

## Accomplishments

- WR-02 hardening: `_handle_read_coaching_guide` now uses `re.findall()` candidate count — only returns a fuzzy-matched section when exactly one section anchor matches the query word (≥4 chars). Ambiguous matches (multiple anchors) return the not-found JSON so the brain falls back to the slim core; prevents wrong sections being fed as authoritative (SC-1 preserved).
- Double-send fix: `MAX_TOOL_ITERATIONS` raised from 8 to 12 to accommodate legitimate 6-tool data-gather coaching turns. Added `last_response_text` tracker that captures any substantive brain text produced alongside tool calls; at loop exhaustion, if `len(last_response_text) > 100`, returns that text instead of the apologetic fallback (single message, no double-send).
- All existing tests pass (10 coaching guide tests, 4 new main.py tests, 2 sentinel tests in test_autonomous.py) — CONNECTIVITY_ERROR_TEXT sentinel string unchanged byte-for-byte.

## Task Commits

Each task committed in TDD order (RED → GREEN):

1. **Task 1 RED — WR-02 fuzzy hardening tests** - `278ed75` (test)
2. **Task 1 GREEN — WR-02 implementation** - `b3099d9` (feat)
3. **Task 2 RED — double-send fix tests** - `2d5901a` (test)
4. **Task 2 GREEN — cap 12 + last_response_text** - `a13aa75` (feat)

## Files Created/Modified

- `core/tools.py` — `_handle_read_coaching_guide` fuzzy fallback replaced with candidate count approach (lines ~1531-1551)
- `core/main.py` — `MAX_TOOL_ITERATIONS` 8→12 (line 47); `last_response_text` tracker before loop + exhaustion guard (lines ~549, ~591, ~685-691)
- `tests/test_tools.py` — `TestPhase24CoachingGuideFuzzyHardening` class: 3 tests (ambiguous, short-word-skip, unambiguous)
- `tests/test_main.py` — New file: `TestPhase24DoublesSendFix` class: 4 tests (cap value, substantive-returns-text, no-text-returns-sentinel, sentinel-unchanged)

## Decisions Made

- Used `re.findall()` on an anchor-only pattern (not the full section-capture pattern) for the candidate count — cleaner than searching twice; anchor regex is cheap.
- Short-word threshold set at `< 4` chars (not `<= 3`) matching the plan spec: avoids over-matching on articles like "run", "set".
- `len(last_response_text) > 100` guard: excludes trivial fragments ("Understood.") and ensures only genuinely substantive answers suppress the fallback.
- Test mock approach for `test_tools.py`: patched `pathlib.Path.read_text` to inject controlled guide content (monkeypatching `Path.resolve` doesn't intercept `read_text` calls on the already-resolved path).

## Deviations from Plan

None — plan executed exactly as written.

The test design for `test_ambiguous_word_returns_not_found` required one adjustment relative to the plan's example: using `zymbal-query` as the slug (where `zymbal` appears in two anchors, with no exact match) rather than `top-set-strength` (which has an exact match in the real guide). The spirit of the test is identical to the plan's spec; only the choice of test word was adapted for isolation.

## Issues Encountered

The first version of the `TestPhase24CoachingGuideFuzzyHardening` tests used `monkeypatch.setattr(pathlib.Path, 'resolve', ...)` to redirect to a temp file — same pattern as `TestPhase22CoachingGuideTool`. This failed because `_handle_read_coaching_guide` calls `guide_path.read_text()` on an already-constructed path (not via `resolve()`), so the monkeypatch didn't intercept the file read. Fixed by patching `pathlib.Path.read_text` directly to inject the in-memory guide content when `self_path.name == "COACHING_GUIDE.md"`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 24 Plans 04-05 can now depend on the 12-iteration cap without double-send risk
- `read_coaching_guide` calls in strict-coaching contexts (crons + chat) will correctly fall back when an ambiguous slug is given, preventing wrong-section authoritative injection
- Both infrastructure fixes are committed and test-covered

## Self-Check

- [x] `core/tools.py` contains `candidate_anchors` and `findall` (verified: line 1542)
- [x] `core/tools.py` contains `len(word) < 4` (verified: line 1536)
- [x] `core/main.py` contains `MAX_TOOL_ITERATIONS = 12` (verified: line 47)
- [x] `core/main.py` has `last_response_text` ≥ 3 hits (verified: 5 hits at lines 549, 591, 685, 689, 691)
- [x] `python -m pytest tests/test_tools.py tests/test_main.py -x -q` → 47 passed
- [x] `python -m pytest tests/test_autonomous.py -x -q -k "sentinel"` → 2 passed
- [x] T-22-04 slug normalization block at lines ~1519-1520 unchanged
- [x] CONNECTIVITY_ERROR_TEXT sentinel text unchanged (byte-identical)
- [x] No stubs or placeholders in modified code

## Self-Check: PASSED

---
*Phase: 24-strict-coaching-integration-nutrition-accountability*
*Completed: 2026-06-06*
