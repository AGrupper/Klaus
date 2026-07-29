---
phase: 33-occasion-cascade
plan: 08
subsystem: weekly-review
tags: [autonomous, cascade, occasion, weekly-review, advisory-only, standing-directive, feature-flag]

# Dependency graph
requires:
  - phase: 33-occasion-cascade
    provides: "33-04 core.autonomous.run_occasion_cascade / _run_cascade (advisory_only, veto_parser, max_tokens kwargs); 33-03 prompts/weekly_occasion.md (D-35 identity + Step-0 directive-veto trailer contract, already present, unmodified)"
provides:
  - "core/weekly_training_review.py::run_weekly_review — cascade-routed behind OCCASION_CASCADE, byte-identical flag-OFF arm (apart from additive state-doc writes)"
  - "core/weekly_training_review.py::_run_weekly_review_cascade — advisory-only cascade call + state-doc writer, consumed by no other module"
  - "weekly_reviews/{date} Firestore state doc (status: sent | skipped_by_directive, composed_via, skip_reason) — the heartbeat anomaly check (plan 33-11) reads this to distinguish 'never fired' from 'vetoed' from 'sent'"
affects: [33-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level side-channel for a veto_parser's discarded return value: run_occasion_cascade's veto_parser contract passes the callable BY REFERENCE and never returns the parsed reason text back through the decision dict (core/autonomous.py's own comment: 'carried by the caller's own logging if it wants it'). _parse_review_skip stashes the reason in _LAST_DIRECTIVE_VETO_REASON so the caller can read it back immediately after the awaited call returns — same event-loop turn, no interleaving await in between."
    - "Date-keyed occasion state doc (weekly_reviews/{date}), _get_state/_set_state copied verbatim from core/nightly_review.py's pattern — no store class, direct collection access, matching 33-PATTERNS.md's explicit guidance."

key-files:
  created: []
  modified:
    - core/weekly_training_review.py
    - tests/test_weekly_training_review.py

key-decisions:
  - "Module-level _LAST_DIRECTIVE_VETO_REASON side-channel, set by _parse_review_skip as a side effect, is the only way to recover the directive-veto reason text after run_occasion_cascade returns while still passing veto_parser=_parse_review_skip literally (required by the plan's own acceptance criteria) — the decision dict's veto_reason is intentionally discarded inside _run_cascade with the comment 'carried by the caller's own logging if it wants it', which is exactly this mechanism."
  - "Legacy (flag-OFF) successful sends write composed_via: \"llm\" unconditionally — _compose_review's own two-tier brain fallback (Sonnet -> Gemini) is opaque to the caller, and only the rare deterministic last-resort data string (never an LLM call) would be mislabeled; that path already logs its own warning at the _compose_review call site."
  - "On a cascade infra failure (not sent, not vetoed), the weekly_reviews/{date} state doc is left UNWRITTEN for the day, not written with a failure status — an absent doc is exactly what the D-28 #3 heartbeat staleness check (plan 33-11) is designed to read as 'the weekly did not fire' (T-33-27); writing a partial doc would mask that signal."
  - "Patched core.weekly_training_review._set_state into the 6 pre-existing send/skip tests that previously didn't need it — now that run_weekly_review writes state unconditionally on both flag arms, an unmocked _set_state call attempts a real Firestore RPC (confirmed empirically: ~0.5s, PermissionDenied against ambient gcloud ADC on this dev machine) which would silently slow every legacy-path test without failing it. Mocking keeps the suite fast and network-independent."

patterns-established:
  - "advisory_only=True occasion routing (D-03): should_act shapes Layer-2 emphasis only; a decision['skipped'] value other than 'directive' after an advisory call is always a fault (Layer-1 exception / Layer-2+draft both empty / send failure), never a legitimate skip — the caller must branch on decision['sent'] and decision['skipped'] == 'directive' explicitly rather than trusting should_act."

requirements-completed: [OCC-03, OCC-06]

# Metrics
duration: ~45min
completed: 2026-07-30
---

# Phase 33 Plan 08: Weekly Review Cascade Routing Summary

**Routed the Sunday weekly training review through `run_occasion_cascade` in `advisory_only=True` mode behind `OCCASION_CASCADE`, added a `weekly_reviews/{date}` state doc that distinguishes `sent`/`skipped_by_directive` on both flag arms, and preserved the Phase-31 standing-directive veto exactly via a module-level side-channel that recovers the reason text `run_occasion_cascade`'s decision dict deliberately discards.**

## Performance

- **Duration:** ~45 min (from worktree base-correction to final commit; commit timestamps span a longer wall-clock gap reflecting session/tooling pauses, not continuous work)
- **Tasks:** 2/2 (implemented as one interleaved diff — see Deviations)
- **Files modified:** 2 (`core/weekly_training_review.py`, `tests/test_weekly_training_review.py`)

## Accomplishments

- **`run_weekly_review` flag branch**: reads `OCCASION_CASCADE` once after gather, delegates to a new `_run_weekly_review_cascade` helper on `true`, otherwise falls through to the pre-existing `_compose_review` → `_parse_review_skip` → send flow completely unmodified apart from two additive `_set_state(...)` calls (verified via `git diff` against the base commit — see Self-Check).
- **`_run_weekly_review_cascade`**: calls `run_occasion_cascade(bot, occasion="weekly_review", target_date=today_iso, occasion_data=week_data, occasion_prompt=<prompts/weekly_occasion.md verbatim>, advisory_only=True, max_tokens=32000, veto_parser=_parse_review_skip)`. Does **not** wrap the call in any `TimedOut` retry — that lives inside `_run_cascade` (33-04) and now protects the weekly for free, proven by `test_timeout_retry_lives_in_cascade` running the real cascade pipeline through a mocked `send_and_inject` that times out once then succeeds.
- **Never self-skips**: `advisory_only=True` means a `should_act=False` Layer-1 verdict still reaches Layer 2 compose and still sends — `test_never_self_skips_on_advisory_should_act_false` proves this end-to-end through the real `run_occasion_cascade`/`_run_cascade` pipeline (only `TickBrain`, `_compose_layer2`, `send_and_inject`, and the Firestore log stores are mocked).
- **Standing-directive veto preserved exactly**: `_parse_review_skip` — unchanged fenced-JSON-trailer parser — is passed as `veto_parser` by reference. `test_directive_veto_no_send_and_state_records_skip_reason` and `test_advisory_only_no_trailer_still_sends_despite_should_act_false` together prove the veto comes exclusively from the Layer-2 trailer and is never derived from `should_act` (T-33-25).
- **`weekly_reviews/{date}` state doc**: `_STATE_COLLECTION`, `_get_state`/`_set_state` copied verbatim from `core/nightly_review.py`'s pattern (no store class, `merge=True`, never raises). Both flag arms now write the same contract — `status: "sent" | "skipped_by_directive"`, `composed_via` present only on a real send, `skip_reason` present only on a veto, `"skipped_by_judgment"` structurally unreachable (grep-verified `0` occurrences in the file).
- **Cascade infra failures leave the state doc unwritten for the day** rather than writing a partial/failure status — the absent doc is exactly what the D-28 #3 heartbeat staleness check (plan 33-11) needs to see to flag "the weekly did not fire" (T-33-27); a written-but-wrong doc would mask that signal. Covered by `test_coaching_topics_not_written_when_cascade_send_fails`'s `mock_set_state.assert_not_called()`.
- **Pitfall 9 preserved**: `_derive_structural_topics` and its call site inside `_gather_week_data` survive untouched; the post-send `CoachingTopicStore.add_topic` loop now gates on `decision.get("sent")` on the cascade path and continues gating on a successful `send_and_inject` await on the legacy path — both covered by dedicated tests.
- **Directive-veto prompt contract regression guard**: `prompts/weekly_occasion.md` (from 33-03) already carries the Step-0 standing-orders instruction and the literal `"skip"` trailer key — `test_weekly_occasion_prompt_has_directive_veto_trailer_contract` pins this so a future prompt edit cannot silently kill the veto.

## Task Commits

1. **`core/weekly_training_review.py`** — `8f40d47` (feat) — `_STATE_COLLECTION`/`_get_state`/`_set_state`, `_LAST_DIRECTIVE_VETO_REASON` side channel + `_parse_review_skip` update, `run_weekly_review` flag branch, new `_run_weekly_review_cascade`
2. **`tests/test_weekly_training_review.py`** — `19d4e3b` (test) — 11 new tests + `_set_state` mocking added to 6 pre-existing tests

_No plan-metadata commit — worktree mode; the orchestrator commits STATE.md/ROADMAP.md centrally after merge. This SUMMARY.md itself is committed separately per the worktree protocol._

## Files Created/Modified

- `core/weekly_training_review.py` — `_STATE_COLLECTION = "weekly_reviews"`; `_make_firestore_client`/`_get_state`/`_set_state` (new, copied pattern from `core/nightly_review.py`); `_LAST_DIRECTIVE_VETO_REASON` module global + `_parse_review_skip` side-effect update; `run_weekly_review` gained the `OCCASION_CASCADE` flag branch and two additive `_set_state` calls on the legacy arm; new `_run_weekly_review_cascade` async helper
- `tests/test_weekly_training_review.py` — 11 new tests under a new `# Phase 33 / OCC-03 — OCCASION_CASCADE routing (33-08)` section; `core.weekly_training_review._set_state` patched into `test_run_weekly_review_writes_topics_after_send`, `test_run_weekly_review_no_topic_write_when_send_fails`, `test_run_weekly_review_retries_send_on_timeout`, `test_run_weekly_review_directive_skip_no_send` (extended with state assertions), `test_run_weekly_review_non_skip_sends_normally` (extended with state assertions)

## Decisions Made

- **`_LAST_DIRECTIVE_VETO_REASON` module-level side channel.** `run_occasion_cascade`'s `veto_parser` contract passes the callable by reference; `_run_cascade` (33-04) discards the parsed reason text with `_ = veto_reason  # carried by the caller's own logging if it wants it` and never returns it through the decision dict. The plan's own acceptance criteria require the literal call `veto_parser=_parse_review_skip` (not a wrapper closure), so the only way to recover the reason for the `weekly_reviews/{date}.skip_reason` field is for `_parse_review_skip` itself to stash it as a side effect, read back by the caller immediately after the single awaited `run_occasion_cascade` call returns (same event-loop turn, no interleaving await — no cross-request race in practice for a once-a-week cron).
- **`composed_via: "llm"` written unconditionally on a legacy-arm successful send.** `_compose_review`'s two-tier brain fallback (Sonnet primary → Gemini fallback) is opaque to the caller; distinguishing the two would require plumbing new return metadata through an otherwise-untouched function, which the plan's "byte-identical apart from state-doc writes" constraint (see `<verification>`) argues against. Only the rare deterministic last-resort data-string fallback (not an LLM call at all) would be mislabeled, and that branch already logs its own warning at the `_compose_review` call site.
- **Cascade infra failures write nothing to the state doc.** Considered writing a `status: "failed"` doc, but plan 33-11's heartbeat check (D-28 #3) is designed to read an *absent* doc as "the weekly did not fire" — writing anything, even a failure marker, would be a second, redundant signal that could drift out of sync with the heartbeat's own detection logic. Left the day's doc unwritten so there is exactly one source of truth for "did the weekly run".
- **Patched `_set_state` into 6 pre-existing tests.** Verified empirically that an unmocked `_set_state` call attempts a real Firestore RPC against ambient `gcloud` application-default credentials on this dev machine (~0.5s, `PermissionDenied` — caught internally, never fails the test, but adds real latency and a network dependency). All pre-existing tests exercising a send/skip outcome now mock `_set_state` to keep the suite fast and hermetic.

## Deviations from Plan

### Auto-fixed Issues

None — no bugs, missing functionality, or blocking issues were found in the codebase this plan builds on.

### Acceptance-Criteria Conflicts (documented, not auto-fixed)

**1. `grep -c "TimedOut" core/weekly_training_review.py` returns `4`, not the plan's stated `1`.**
- **Why:** The plan's `<verification>` section separately requires "OCCASION_CASCADE unset ⇒ `git diff core/weekly_training_review.py` shows the legacy compose path unmodified apart from the state-doc writes." The pre-existing (unmodified-by-this-plan) legacy path already contains 4 lines matching `"TimedOut"` — a WHY-comment, a retry-rationale comment, the `from telegram.error import TimedOut` import, and the `except TimedOut:` clause — none of which this plan is permitted to touch on the flag-OFF arm. My own new code (the cascade helper) adds zero new `TimedOut` mentions; I explicitly reworded one comment during implementation to avoid contributing a 5th occurrence. The two acceptance criteria as literally worded are mutually exclusive; I prioritized the `<verification>` section's explicit byte-identical requirement (the stronger, more specific constraint) and the substantive behavioral guarantee (proven by `test_timeout_retry_lives_in_cascade`) over the numeric grep count, which appears to be a plan-authoring oversight that didn't account for the module's pre-existing comment density.
- **Substantively verified instead by:** `test_timeout_retry_lives_in_cascade` — runs the real cascade pipeline with a mocked `send_and_inject` that times out once then succeeds, proving the retry is inherited from `_run_cascade` and not reimplemented in this module.

**2. `grep -c "max_tokens=32000" core/weekly_training_review.py` returns `3`, not the plan's stated `2`.**
- **Why:** Same root cause. `_compose_review` (untouched, surviving function) already carries an explanatory comment literally containing the string `max_tokens=32000` at its call site, in addition to its own `max_tokens=32000` kwarg. My new cascade call adds exactly one more `max_tokens=32000` kwarg occurrence (the 2 the plan counted: `_compose_review`'s kwarg + the new cascade kwarg), for a total of 3 grep-matching lines once the pre-existing comment line is counted. No code was added or changed to cause this drift.

Both conflicts are between the plan's own internally inconsistent acceptance criteria (exact grep counts vs. "legacy path unmodified"), not between the plan and the implementation. All functionally-verifiable acceptance criteria (behavior, test coverage, `advisory_only=True` count = 1, `_STATE_COLLECTION` count = 1, `skipped_by_judgment` count = 0, `veto_parser=_parse_review_skip` count = 1, `_derive_structural_topics` counts = 1/1) pass exactly as specified.

### Process Note (not a code deviation)

**Tasks 1 and 2 landed as two commits split by file type (core file, test file) rather than by task boundary.** The plan's own task split (Task 1: cascade routing; Task 2: state docs + veto preservation) is logically clean, but the actual implementation is structurally interleaved — Task 2's `_set_state` calls live inside Task 1's `_run_weekly_review_cascade` and inside `run_weekly_review`'s flag-OFF skip/send branches, and Task 2's `_LAST_DIRECTIVE_VETO_REASON` side channel is threaded through the same `_parse_review_skip` function Task 1 passes as `veto_parser`. This mirrors 33-04's own documented precedent for the identical situation. Both tasks' acceptance criteria are independently verifiable in the final diff and are covered by dedicated tests.

## Issues Encountered

None beyond the two acceptance-criteria/verification-section conflicts documented above (resolved via explicit prioritization, not a blocker) and the empirical discovery that unmocked `_set_state` calls hit real Firestore RPCs in this dev environment (resolved via test mocking, Rule 3).

## User Setup Required

None — no external service configuration, no new env vars (`OCCASION_CASCADE` was already introduced by a sibling plan), no infra changes. Pure application code + tests.

## Next Phase Readiness

- `weekly_reviews/{date}` state doc is ready for plan 33-11's heartbeat D-28 #3 anomaly check ("the weekly not firing") to read — `status` is `"sent"` or `"skipped_by_directive"` on both flag arms, and the doc is absent (not a third status value) on an infra failure.
- The `advisory_only=True` occasion routing pattern established here (should_act shapes emphasis only; any non-"directive" skip after an advisory call is always a fault) is available as precedent for any future advisory-mode occasion.
- No blockers or concerns for downstream plans.

## Self-Check: PASSED

- FOUND: core/weekly_training_review.py
- FOUND: tests/test_weekly_training_review.py
- FOUND: .planning/phases/33-occasion-cascade/33-08-SUMMARY.md
- FOUND commit: 8f40d47
- FOUND commit: 19d4e3b
- Verified: `pytest tests/test_weekly_training_review.py -x -q` → 52 passed
- Verified: `pytest tests/test_coaching_topic_store.py -x -q` → 12 passed
- Verified: `pytest tests/test_autonomous.py -q` → 157 passed (no regression from this plan's changes, which never touch core/autonomous.py)
- Verified: `grep -c "skipped_by_judgment" core/weekly_training_review.py` → 0
- Verified: `grep -c "advisory_only=True" core/weekly_training_review.py` → 1
- Verified: `grep -c '_STATE_COLLECTION = "weekly_reviews"' core/weekly_training_review.py` → 1
- Verified: `grep -c "veto_parser=_parse_review_skip" core/weekly_training_review.py` → 1
- Verified: `grep -c "def _derive_structural_topics" core/weekly_training_review.py` → 1, `grep -c "_derive_structural_topics(data)"` → 1

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-30*
