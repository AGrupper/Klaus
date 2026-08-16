---
phase: 33-occasion-cascade
plan: 03
subsystem: prompts
tags: [prompt-engineering, tick-brain, groq, token-budget, occasion-cascade, cascade-judgment]

# Dependency graph
requires:
  - phase: 32-unified-situation-ambient-memory
    provides: conversation_tail/training_reality render slots, Groq token-budget guard test at 7,146/7,200 baseline
provides:
  - "prompts/autonomous_triage.md: skip_cause field in the Layer-1 output contract"
  - "prompts/occasion_triage_addendum.md: D-01/D-02/D-03 occasion judgment (speak-by-default, four skip causes, weekly never self-skips), to be rendered into the triage USER message only when situation.get(\"occasion\") is set"
  - "prompts/autonomous.md: fold-around-outreach (D-16/D-17), write-and-disclose (D-23/D-24/D-25), silence-stays-silent (D-27), corrected MAX_TOOL_ITERATIONS=12"
  - "prompts/nightly_occasion.md, prompts/morning_occasion.md, prompts/weekly_occasion.md: identity + one standing question each (D-35), weekly carries the Step-0 directive-veto trailer verbatim"
affects: [33-04, 33-05, 33-06, 33-07, 33-08, 33-09, 33-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Token-budget arbitration fallback: when a shared system prompt on the Groq hot path cannot absorb new content within its admission-ceiling margin, move the content verbatim to a sibling addendum file rendered conditionally into the USER message instead of the SYSTEM prompt — one shared file (D-36) stays true even when it can't physically be one shared block."

key-files:
  created:
    - prompts/occasion_triage_addendum.md
    - prompts/nightly_occasion.md
    - prompts/morning_occasion.md
    - prompts/weekly_occasion.md
  modified:
    - prompts/autonomous_triage.md
    - prompts/autonomous.md
    - tests/test_prompts.py

key-decisions:
  - "Task 1 token-budget arbitration took the ADDENDUM branch (not the inline branch) — see 'Branch Taken' section below. This is binding for plan 33-04."
  - "skip_cause enum values (directive, already_covered, nothing_happened, reaction_history) are documented in the Output-contract line of autonomous_triage.md AND fully explained in occasion_triage_addendum.md — the former satisfies the interface contract with TickBrain._parse_response's shape, the latter carries the actual judgment guidance."

patterns-established:
  - "One-line HTML comment at the top of a short prompt file names the decision it implements (D-35), kept genuinely one line so it doesn't inflate the file's body-line count used by shape tests."

requirements-completed: [OCC-04, OCC-05]

# Metrics
duration: 8min
completed: 2026-07-29
---

# Phase 33 Plan 03: Occasion Judgment Prompts Summary

**Shared cascade prompts taught D-01/D-02/D-03 occasion judgment (speak-by-default,
four skip causes, weekly never self-skips) and D-16/D-17/D-23/D-24/D-25/D-27
fold-in/write-and-disclose behavior; three new few-line occasion identity prompts
(nightly/morning/weekly) created — all under the Groq 7,200-token admission ceiling,
which forced the D-02/D-03 detail into a new sibling addendum file rather than inline.**

## Performance

- **Duration:** 8 min (measured from Task 1 commit to Task 3 commit; ~20 min including
  full context read + verification)
- **Started:** 2026-07-29T16:52:21+03:00 (Task 1 commit)
- **Completed:** 2026-07-29T16:56:49+03:00 (Task 3 commit)
- **Tasks:** 3/3
- **Files modified:** 7 (2 edited + 1 addendum created in Task 1/2 combined; 3 occasion
  prompts created + 1 test file edited across all three tasks)

## Accomplishments

- `prompts/autonomous_triage.md`'s Output contract gained the `skip_cause` field
  (directive | already_covered | nothing_happened | reaction_history) with a pointer
  to the new addendum file — 40 tokens, leaving a 14-token margin under the
  7,200-token Groq admission target (`tests/test_token_budget.py` still green,
  `_GROQ_REQUEST_TOKEN_TARGET` untouched at 7200).
- `prompts/occasion_triage_addendum.md` (new) carries the full D-01 (speak-by-default
  on an occasion) / D-02 (exactly four skip causes) / D-03 (weekly governs shape,
  never whether it fires) content — not rendered on the Groq hot path; plan 33-04
  must wire it into the triage USER message only when `situation.get("occasion")`
  is set.
- `prompts/autonomous.md` gained three sections — Fold around what I already said
  (D-16/D-17), Write, then disclose (D-23/D-24/D-25, mandating
  `Created:`/`Moved:`/`Deleted:` action lines and the pre-create idempotency check),
  Silence stays silent (D-27) — plus the `MAX_TOOL_ITERATIONS` correction (8 → 12,
  matching `core/main.py:50`).
- Three new occasion prompts (`nightly_occasion.md`, `morning_occasion.md`,
  `weekly_occasion.md`), each a few lines of identity + one standing question (D-35).
  The weekly prompt carries the Step-0 directive-veto trailer copied verbatim from
  `prompts/weekly_training_review.md` so `core.weekly_training_review._parse_review_skip`
  (and plan 33-08's `veto_parser` hook) keeps working unchanged.
- `tests/test_prompts.py` grew from 21 to 36 tests covering all of the above.

## Branch Taken — Task 1 Token-Budget Arbitration (binding for plan 33-04)

**ADDENDUM branch.** The maximal rendered triage prompt measured 7,146/7,200 tokens
before this plan (54-token margin) — too tight to hold the full D-01/D-02/D-03
occasion-judgment prose inline (measured at ~220 tokens for even a tightly-worded
version). Per the plan's pre-authorized fallback:

- `prompts/autonomous_triage.md` keeps only the `skip_cause` output-contract line
  (40 tokens; new margin 14/7200) plus a pointer to the sibling file by name.
- `prompts/occasion_triage_addendum.md` (new) carries the full D-01/D-02/D-03 text.
- **Plan 33-04 must render `occasion_triage_addendum.md`'s content into the Layer-1
  triage USER message — not the system prompt — and only when
  `situation.get("occasion")` is truthy.** This keeps D-36's "one shared file, one
  place to change behavior" intact while the always-on `*/20` tick pays nothing for
  it.
- `_GROQ_REQUEST_TOKEN_TARGET` was NOT raised (remains 7200, `grep -c` confirms exactly
  1 occurrence in `tests/test_token_budget.py`).

## Task Commits

Each task was committed atomically:

1. **Task 1: Occasion judgment in the shared triage prompt (D-01, D-02, D-03, D-36)** -
   `af0d759` (feat) — addendum branch taken, `skip_cause` field, new sibling file
2. **Task 2: Fold-in and write-and-disclose in the shared compose prompt (D-16, D-17,
   D-23, D-24, D-25, D-27, D-36)** - `0093f53` (feat)
3. **Task 3: Three occasion prompts — identity and one standing question each (D-35)** -
   `03db7ba` (feat)

_No plan-metadata commit — worktree mode; the orchestrator commits STATE.md/ROADMAP.md
centrally after merge. This SUMMARY.md itself is committed separately per the worktree
protocol._

## Files Created/Modified

- `prompts/autonomous_triage.md` - `skip_cause` field added to the Output contract JSON
  schema, pointing to the new addendum file
- `prompts/occasion_triage_addendum.md` (new) - D-01/D-02/D-03 occasion judgment,
  rendered into the triage user message only on occasion runs (33-04's job to wire)
- `prompts/autonomous.md` - fold-around-outreach, write-and-disclose,
  silence-stays-silent sections; `MAX_TOOL_ITERATIONS` corrected to 12
- `prompts/nightly_occasion.md` (new) - wind-down identity + standing question
- `prompts/morning_occasion.md` (new) - wake-up identity + standing question + D-20
  weekly-deferral note
- `prompts/weekly_occasion.md` (new) - weekly-review identity + standing question +
  always-fires framing (D-03) + Step-0 directive-veto trailer (verbatim from
  `prompts/weekly_training_review.md`)
- `tests/test_prompts.py` - 15 new tests across the three tasks (skip_cause presence,
  addendum pointer/content, weekly shape-not-whether, write-and-disclose contract,
  fold-in instruction, MAX_TOOL_ITERATIONS correction, occasion-prompt existence/
  load/placeholder/length/D-20/D-03/trailer/D-33-no-checklist checks)

## Decisions Made

- **Addendum branch taken for Task 1** (see "Branch Taken" section above) — the
  54-token pre-edit margin could not absorb the full occasion-judgment block inline
  at any reasonable tightness (~220 tokens minimum for a version that still satisfied
  the acceptance criteria's four-skip-cause + weekly-shape requirements). This is a
  plan-anticipated branch, not a deviation.
- `skip_cause`'s enum values were kept in the Output-contract line of
  `autonomous_triage.md` itself (not only in the addendum) so `grep`-level acceptance
  criteria checking for `directive`/`already_covered`/`nothing_happened`/
  `reaction_history` in the main triage file are satisfied without needing a second,
  more expensive inline block — this is the cheapest way to keep the interface
  contract (`skip_cause` field name + its enum) visible in the file
  `core.tick_brain.TickBrain._parse_response` will eventually read from, while the
  judgment prose itself stays off the hot path.
- Occasion prompt HTML comments were written as genuinely single-line (not wrapped)
  so the `grep -v '^<!--'` body-line-count acceptance checks aren't polluted by a
  wrapped second comment line being counted as body content.

## Deviations from Plan

None — plan executed exactly as written, including its own pre-authorized
token-budget fallback branch (Task 1), which is documented above as the expected
outcome given the pre-existing 54-token margin, not an unplanned deviation.

## Issues Encountered

None. The token-budget arbitration in Task 1 proceeded exactly per the plan's
documented decision tree (attempt inline → measure → confirm insufficient even at
minimum-viable tightness → move to `prompts/occasion_triage_addendum.md`).

## User Setup Required

None - no external service configuration required. This plan is prompt-content only;
no code, no new env vars, no infra changes.

## Next Phase Readiness

- Plan 33-04 has everything it needs to wire `occasion_triage_addendum.md` into the
  triage USER message (conditional on `situation.get("occasion")`), thread `skip_cause`
  through `core.tick_brain.TickBrain._parse_response`, and route the three new occasion
  prompts (`nightly_occasion.md`/`morning_occasion.md`/`weekly_occasion.md`) as literal
  text into the Layer-2 compose user message.
- `tests/test_token_budget.py` currently has a 14-token margin under the 7,200-token
  Groq admission target — any further growth to `prompts/autonomous_triage.md`'s
  SYSTEM-prompt content (not the addendum, which is user-message-only and occasion-only)
  must be measured carefully; there is essentially no headroom left.
- The weekly prompt's directive-veto trailer format (`\`\`\`json {"skip": true,
  "reason": "..."} \`\`\``) is confirmed byte-compatible with
  `core.weekly_training_review._parse_review_skip`'s regex, which plan 33-08's
  `veto_parser` hook depends on.
- No blockers or concerns for downstream plans.

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-29*
