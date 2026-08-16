---
phase: 31-standing-directives
plan: 06
subsystem: agent-core
tags: [reflection, nightly-review, self-directives, learning-loop, firestore]

# Dependency graph
requires:
  - phase: 31-standing-directives (Plan 01)
    provides: StandingDirectiveStore (memory/firestore_db.py) — add/list_active/list_all/cancel/supersede/expire
  - phase: 31-standing-directives (Plan 02)
    provides: FirestoreConversationStore.get_recent_window(user_id, hours=24, max_messages=60)
  - phase: 31-standing-directives (Plan 03)
    provides: render_standing_directives_block(directives, *, style) shared formatter
provides:
  - "core/reflection.py: 24h-windowed reaction-pairing learning loop — proposes origin='klaus_self' directives, judges event-based expiry, flags prune candidates, all non-fatal to the journal write"
  - "core/nightly_review.py: standing_directives_block (raw active directives, rendered) + directive_items (derived housekeeping) both reach _compose_nightly, distinct keys"
affects: [35-hardening-subtraction]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "directive_items stashed directly on the JournalStore entry dict — the existing _ensure_reflection re-read in core/nightly_review.py carries it through to the nightly compose with zero extra plumbing"
    - "Isolated per-write-target try/except for directive writes (add/expire), matching the existing JournalStore/Pinecone/SelfStateStore discipline — a directive write failure never blocks the journal write"
    - "D-13 veto dedup guard: exact case/whitespace-insensitive text match against StandingDirectiveStore.list_all() status=='vetoed' entries, applied in code (not solely prompt-trusted)"

key-files:
  created: []
  modified:
    - core/reflection.py
    - prompts/reflection.md
    - core/nightly_review.py
    - prompts/nightly_review.md
    - tests/test_reflection.py
    - tests/test_nightly_review.py

key-decisions:
  - "directive_items is written onto the journal entry itself (JournalStore doc), not passed through a separate return value or Firestore collection — reuses the existing _ensure_reflection→journal-re-read handoff verbatim, no new interface needed"
  - "The vetoed-directive re-propose guard (D-13) is enforced in code via an exact-match text comparison against StandingDirectiveStore.list_all(), as defense-in-depth alongside the prompt-level instruction not to re-propose — belt and suspenders since a misread here would silently re-annoy Amit with something he already vetoed"
  - "active_directives and outreach_today reads are both best-effort (isolated try/except, sentinel []) feeding the SAME existing brain-reflect call — no second LLM call added, per the plan's explicit constraint"
  - "standing_directives_block is rendered inside _compose_nightly (not _gather_tomorrow) so the raw StandingDirectiveStore.list_active() list stays available as plain data in `tomorrow` for any other consumer, with rendering happening once at the point of use"

patterns-established:
  - "Journal-entry-as-handoff: any future cross-cron payload that needs to travel from reflection to nightly compose can piggyback on the same JournalStore doc rather than inventing a new store/collection"

requirements-completed: [DIR-02, DIR-03, DIR-06, DIR-07]

# Metrics
duration: ~45min
completed: 2026-07-20
---

# Phase 31 Plan 06: Reflection Learning Loop + Nightly Directive Weave Summary

**Fixed live bug B3 (nightly reflection reading an empty 6h conversation window) and built the DIR-06/07 self-correction loop: Klaus pairs each self-initiated outreach with Amit's reaction, proposes active-immediately self-directives from a single signal, judges event-based expiry, and weaves it all into the nightly narrative with a one-line veto — nightly stays exempt from directive veto power throughout.**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-07-20
- **Completed:** 2026-07-20
- **Tasks:** 3 completed
- **Files modified:** 6

## Accomplishments

- **Bug B3 fixed:** `core/reflection.py::_gather_day` now reads `FirestoreConversationStore.get_recent_window(user_id, hours=24)` instead of the stale 6h-session-idle `get()`, which was empty on most nights by the time reflection ran (22:00 cron or the 01:00 backstop)
- `run_reflection`'s `brain_input` now carries the 24h windowed `conversation`, today's `outreach_today` (from `OutreachLogStore.get_today`), and `active_directives` (from `StandingDirectiveStore.list_active()`) — all feeding the SAME existing brain-reflect call, no second LLM call
- `_parse_reflection_json` gained 3 optional keys (`directive_proposals`, `prune_flags`, `expiry_notes`), each defaulting to `[]` on missing/wrong type, following the exact isinstance-guard discipline already used for `highlights`
- `run_reflection` applies the brain's directive judgments: proposals write via `StandingDirectiveStore.add(origin="klaus_self")` (D-09 — active immediately, no pending state), a single strong signal is sufficient (D-10/D-11/D-12), and a proposal matching a previously-vetoed directive's text is never re-proposed (D-13, enforced in code via exact-match text comparison against `list_all()` status=`vetoed` entries)
- Judged expiry notes trigger `StandingDirectiveStore.expire()` (D-05/D-08); prune-flags are carried forward as narrative items only — never auto-actioned (D-04)
- Every directive write is isolated in its own try/except, non-fatal to the journal write, mirroring the existing JournalStore/Pinecone/SelfStateStore per-write-target discipline
- The resulting `directive_items` (proposals + expiries + prune-flags) is stored directly on the journal entry, so `core/nightly_review.py::_ensure_reflection`'s existing re-read carries it through to the nightly compose with zero new plumbing
- `core/nightly_review.py::_gather_tomorrow` now reads `StandingDirectiveStore.list_active()` into `standing_directives` — the 5th and final `render_standing_directives_block()` injection site (DIR-03) — as interim CONTEXT only; the nightly remains fully EXEMPT from directive veto (D-21), a gather failure sentinels to `[]`
- `_compose_nightly`'s payload carries two DISTINCT directive-related keys: `standing_directives_block` (raw active directives, rendered via the shared formatter, as behavioral context) and `directive_items` (derived housekeeping — proposals/expiries/prune-flags)
- `prompts/reflection.md` and `prompts/nightly_review.md` updated with the new inputs, the reaction-pairing/judgment task, the 3 optional output keys, and a "Directive housekeeping" weave-into-narrative section (one-line veto on every proposal, always-stated expiries, no fixed "Directives:" section — D-19/D-20)
- 20 new tests across the two test files (11 in `test_reflection.py`, 9 in `test_nightly_review.py`); full targeted suites green: `test_reflection.py` 17/17, `test_nightly_review.py` 26/26, `test_tools.py` 94/94 (unaffected) — no regressions

## Task Commits

Each task was committed atomically (Tasks 1+2 combined — both modify `run_reflection`'s same input-assembly/output-processing flow in `core/reflection.py` and are tightly sequential; splitting them into separate commits would have required an artificial mid-function checkpoint):

1. **Tasks 1+2: Fix the stale read, assemble reaction-pairing input, self-directive proposals/judged-expiry/prune-flags** — `82bee07` (feat)
2. **Task 3: Weave directive items into the nightly narrative** — `68aff6a` (feat)

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified

- `core/reflection.py` — `_gather_day`'s stale-read fix; `_parse_reflection_json` +3 optional keys; `run_reflection` reads outreach log + active directives into `brain_input`, applies proposals/expiries/prune-flags into `directive_items`, writes it onto the journal entry
- `prompts/reflection.md` — new inputs documented (`conversation`, `outreach_today`, `active_directives`), reaction-pairing/self-directive-judgment task section, Output Format extended from "EXACTLY 5 keys" to "5 required + 3 optional"
- `core/nightly_review.py` — `_gather_tomorrow` reads `standing_directives`; `_compose_nightly` payload gains `standing_directives_block` + `directive_items`
- `prompts/nightly_review.md` — documents both new payload keys + a "Directive housekeeping" narrative-weaving section
- `tests/test_reflection.py` — 2 tests for the stale-read fix + reaction-pairing input assembly, 3 tests for the optional-key schema extension, 4 tests for proposal/veto-dedup/expiry/prune-flag write behavior
- `tests/test_nightly_review.py` — 2 tests for the `_gather_tomorrow` standing-directives read, 5 tests for `_compose_nightly`'s payload shape (rendered block, proposal veto context, always-stated expiry, empty-activity silence, never-skip nightly-exemption)

## Decisions Made

- Combined Tasks 1 and 2 into a single commit: both edit the same `run_reflection` function in one continuous sequence (Task 2's directive-proposal input — `active_directives` — is assembled right alongside Task 1's outreach/conversation input, and Task 2's write logic sits immediately after Task 1's `entry` construction). Splitting them would have required committing a mid-function, partially-wired state. Both tasks' individual acceptance criteria are independently verified and pass.
- `directive_items` travels via the journal entry itself rather than a new interface — reuses the plan's own suggested "via the `_ensure_reflection` result" handoff exactly, with no new store or collection.
- The D-13 veto-dedup guard is implemented in code (exact case/whitespace-insensitive text match) as well as documented in the prompt — belt-and-suspenders, since a prompt-only guard could silently regress and re-annoy Amit with something he already vetoed.
- `standing_directives_block` is rendered inside `_compose_nightly` (not pre-rendered in `_gather_tomorrow`) so `tomorrow["standing_directives"]` stays available as plain, unrendered data for any other future consumer of `_gather_tomorrow`'s output.

## Deviations from Plan

None that changed scope — plan executed as written. One commit-granularity deviation, documented above (Tasks 1+2 combined into one commit rather than two, due to tight code-level coupling within a single function).

## Issues Encountered

- `pytest tests/test_nightly_review.py` (and the full-suite run) segfaults (exit 139) at interpreter teardown AFTER all tests report PASSED with `-v`/verbose output — confirmed this is a **pre-existing environment issue, not caused by this plan's changes**: reproduced identically by reverting to the pre-plan `core/nightly_review.py`/`tests/test_nightly_review.py` (via `git checkout --`) and re-running, which segfaults the same way even though nothing in this plan touched those files at that point. Consistent with the project's known grpc/protobuf native-wheel teardown fragility noted in CLAUDE.md/MEMORY.md. Out of scope per the executor's Scope Boundary rule — not fixed. Verified via `-v` output and explicit `PASSED`/`FAILED` grep counts that all 26 tests in that file pass before the crash; this is a teardown-only crash, not a test failure.

## User Setup Required

None — no external service configuration required. All directive reads/writes go through the already-provisioned `standing_directives` Firestore collection (Plan 01) and the existing `outreach_log`/`journal` collections.

## Next Phase Readiness

- DIR-02 (judged-condition expiry), DIR-03 (5th and final `render_standing_directives_block()` injection site — nightly), DIR-06 (24h reaction-pairing), and DIR-07 (self-directive proposals with one-line veto) are all live and test-covered.
- Phase 31's directive lifecycle is now fully wired end-to-end: capture (Plan 03) → injection at all 5 sites (Plans 03/04/05/06) → self-correction loop (this plan) → list/cancel (Plan 03).
- Phase 35 (hardening + subtraction) is the natural next touchpoint for tightening the D-13 veto-dedup guard (currently exact-text match; a future pass could consider fuzzy/semantic matching) if that proves too strict or too loose in practice — no blocker for now.

---
*Phase: 31-standing-directives*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: core/reflection.py
- FOUND: prompts/reflection.md
- FOUND: core/nightly_review.py
- FOUND: prompts/nightly_review.md
- FOUND: tests/test_reflection.py
- FOUND: tests/test_nightly_review.py
- FOUND: .planning/phases/31-standing-directives/31-06-SUMMARY.md
- FOUND commit: 82bee07 (feat, Tasks 1+2)
- FOUND commit: 68aff6a (feat, Task 3)
- FOUND commit: 238dd72 (docs, plan metadata)
