---
phase: 33-occasion-cascade
plan: 09
subsystem: api
tags: [firestore, self-accountability, brain-direct-tool, occasion-cascade]

# Dependency graph
requires:
  - phase: 33-01
    provides: "ActionLogStore (D-25 action audit) in memory/firestore_db.py"
  - phase: 33-04
    provides: "core/autonomous.py::_run_cascade — decision dict shape (skipped, sent, occasion, topic_key, draft, triage_reason, skip_cause, composed_via, final_text, trail) and the 'occasion:<name>' TickLogStore doc-id convention"
provides:
  - "core/tools.py::_handle_get_recent_decisions(days=2) — brain-direct read across TickLogStore, OutreachLogStore, ActionLogStore (OCC-07/D-26)"
  - "get_recent_decisions registered at all three touch points (TOOL_SCHEMAS, _HANDLERS, SMART_AGENT_DIRECT_TOOLS)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Whole-handler try/except returning {\"error\": str(exc)} as a second line of defence on top of each store's own never-raises contract"
    - "ASVS V5 numeric-arg clamp (max(1, min(int(days), 30))) applied before any store construction — first explicit example of this pattern in core/tools.py"

key-files:
  created: []
  modified:
    - core/tools.py
    - tests/test_tools.py

key-decisions:
  - "kind (\"tick\" vs \"occasion\") and the occasion name are derived from the TickLog entry's time doc id (\"occasion:<name>\" prefix), not from decision_trail's own \"occasion\" key — matches the plan's explicit instruction and is robust to legacy records that predate the occasion key existing"
  - "should_act and reason are pulled from the decision_trail's {\"layer1\": verdict} trail element (first match, defaulting to {} if absent) rather than decision_trail's own top-level triage_reason field, per the plan's explicit field-sourcing instruction — keeps the read faithful to what Layer 1 actually said even if a future decision-dict refactor renames the top-level mirror"
  - "OutreachLogStore entries' occasion field is normalized with `entry.get(\"occasion\") or \"\"` rather than a bare .get(..., \"\") default, because tick-originated entries store occasion=None explicitly (not a missing key) — a bare default would have let None leak into the JSON payload"
  - "Tasks 1 and 2 landed as one commit: the schema/registration touch points sit inline with the handler's own file region (TOOL_SCHEMAS/SMART_AGENT_DIRECT_TOOLS/_HANDLERS are each a few lines, not a separable diff), and all new tests exercise both handler behavior and registration in one test class — splitting would not have produced two genuinely isolated, independently-passing intermediate states (same rationale as plan 33-04's own Deviations note)"

patterns-established:
  - "Pattern: aggregate-read tool over N days' worth of doc-per-date stores — clamp days first (ASVS V5), build the date list once, loop stores per date, route every dict through _jsonsafe_doc, wrap the whole body in try/except returning a structured {\"error\": ...} rather than propagating"

requirements-completed: [OCC-07]

# Metrics
duration: 12min
completed: 2026-07-30
---

# Phase 33 Plan 09: get_recent_decisions Self-Accountability Tool Summary

**Brain-direct `get_recent_decisions(days=2)` tool reading TickLogStore + OutreachLogStore + ActionLogStore so Klaus can answer "why didn't you message me yesterday?" and "what did you change on my calendar?" from real production records, clamped to a 30-day window and immune to legacy-record KeyErrors.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-30T01:21:00+03:00 (worktree base-correction)
- **Completed:** 2026-07-30T01:32:50+03:00 (final commit)
- **Tasks:** 2/2 completed
- **Files modified:** 2

## Accomplishments

- `_handle_get_recent_decisions(days=2) -> str` — clamps `days` to `[1, 30]` (ASVS V5, T-33-29) before constructing any store, builds the last N Asia/Jerusalem calendar dates newest-first, and aggregates three lists: `decisions` (per-tick/per-occasion verdict + triage reasoning, sourced from `TickLogStore.ticks_for_date`'s `decision_trail`), `sent` (what actually shipped, full text, from `OutreachLogStore.get_today`), and `actions` (D-25 calendar/task writes, from `ActionLogStore.get_recent`). Every dict is routed through `_jsonsafe_doc` before `json.dumps`, and the whole handler is wrapped in a try/except that degrades to `{"error": str(exc)}` rather than propagating — a second line of defence on top of each store's own never-raises contract.
- `kind` classification (`"tick"` vs `"occasion"`) and the occasion name are derived from the TickLog entry's `time` doc id via the `"occasion:<name>"` prefix convention plan 33-04 established (`log_key = f"occasion:{occasion}"`), matching the interface's exact test case (`time == "occasion:nightly"` → `kind == "occasion"`, `occasion == "nightly"`).
- Legacy tick-log entries written before this phase — missing `skip_cause`/`composed_via`/`topic_key` or the entire `trail` list — degrade cleanly to `""`/`None`/`False` defaults rather than raising `KeyError`, verified by a dedicated test.
- Registered at all three touch points mirroring `forget_memory`: `TOOL_SCHEMAS` (with the "Call this directly — do NOT delegate to the worker" instruction), `_HANDLERS`, and `SMART_AGENT_DIRECT_TOOLS`. `get_smart_schemas()` required no change — it already filters by `SMART_AGENT_DIRECT_TOOLS` membership.
- D-27 is documented, not enforced, here: the handler's docstring explicitly notes it returns skip records faithfully with no filtering, and that the "never surface a skip unasked" rule lives upstream in `prompts/autonomous.md` and plan 33-04's compose context — so a future reader does not mistakenly add redaction logic to this handler.

## Task Commits

Tasks 1 and 2 landed as one commit (see key-decisions for why — the schema/registration touch points and the handler function sit in the same file region and are tested together):

1. **Task 1 + Task 2: get_recent_decisions handler + schema/registration triad** - `3961369` (feat)
2. **Process note: log pre-existing orphaned dead code as deferred** - `17df766` (docs)

_No TDD tasks in this plan — both tasks are `type="auto"` with tests written alongside the implementation._

## Files Created/Modified

- `core/tools.py` - Adds `_handle_get_recent_decisions` (placed after `_handle_run_morning_briefing`, the other Phase 33 handler in this file); adds the `get_recent_decisions` schema to `TOOL_SCHEMAS` (next to `forget_memory`'s schema); adds `"get_recent_decisions"` to `SMART_AGENT_DIRECT_TOOLS` and to `_HANDLERS`
- `tests/test_tools.py` - Adds `_FakeTickLogStore`, `_FakeOutreachLogStoreForDecisions`, a `get_recent` method on the existing `_FakeActionLogStore` (backward-compatible — plan 33-05's tests never call it), and a new `fake_decision_stores` fixture; adds `TestGetRecentDecisions` (11 tests): all-four-elements populated, occasion-vs-tick classification, days clamping (`1000`→`30`, `-5`→`1`, `"3"`→`3`), ISO-safety against a `DatetimeWithNanoseconds`-shaped value, legacy-record graceful degradation, a raising store degrading to `{"error": ...}`, and the full registration triad (direct-tools membership, `_HANDLERS`/`dispatch`, schema shape, `get_smart_schemas()` inclusion with the "do NOT delegate" wording, `days` kwarg forwarding through `dispatch`)

## Decisions Made

- `kind`/`occasion` classification reads the TickLog entry's `time` doc id (`"occasion:<name>"` prefix), not `decision_trail`'s own `occasion` key — per the plan's explicit instruction, and more robust since legacy records may lack the `occasion` key entirely while `time` is always present (it is the doc id itself).
- `should_act`/`reason` are pulled from the `{"layer1": verdict}` trail element specifically, not from `decision_trail`'s own top-level mirror fields — keeps the read faithful to exactly what Layer 1 said, per the plan's explicit field-sourcing instruction.
- `OutreachLogStore` entries' `occasion` field uses `entry.get("occasion") or ""` rather than a bare default, because tick-originated entries store `occasion=None` explicitly (the `_run_cascade` call site passes the tick's own `occasion` variable, which is `None`) — a bare `.get(..., "")` would have let `None` leak into the JSON payload since the key is present, just falsy.
- Tasks 1/2 committed together — see key-decisions above and the plan 33-04 precedent this mirrors.

## Deviations from Plan

### Auto-fixed Issues

None — no bugs, missing critical functionality, or blocking issues were found in this plan's own new code.

### Process Note (not a code deviation)

**Found a pre-existing, unrelated orphaned dead-code line in `core/tools.py`.** Between `_handle_forget_memory` and `_handle_run_morning_briefing` (roughly where Task 1's read_first pointed) there is a stray, unreachable `return json.dumps({"date": date, "logged": logged, "warnings": warnings})` statement — syntactically valid (Python's blank-line handling keeps it inside `_handle_forget_memory`'s block) but dead, and referencing names (`date`, `logged`, `warnings`) that don't exist in that function's scope. This predates this plan and is not touched by it (my insertion point was elsewhere in the file, before `_handle_notion_search`). Per the SCOPE BOUNDARY rule, logged to `.planning/phases/33-occasion-cascade/deferred-items.md` rather than fixed.

---

**Total deviations:** 0 auto-fixed. 1 out-of-scope discovery logged to `deferred-items.md`.
**Impact on plan:** None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Pure application code (new tool handler + registration) plus tests, reading only existing Firestore stores.

## Next Phase Readiness

- `get_recent_decisions` is live and ready for Amit to use in chat — "why didn't you message me yesterday?" and "what did you change on my calendar?" now resolve to real production records across ticks and occasions.
- This is also the phase's live debugging surface (D-28) alongside the heartbeat anomalies plan 33-11 adds — both read the same `ActionLogStore`/`TickLogStore` data this plan's handler reads, with no shape mismatch.
- No blockers or concerns for downstream plans. `core/autonomous.py` was not touched (owned by sibling plans 33-04/33-06/33-07/33-08 in prior waves).
- One pre-existing, unrelated dead-code line flagged in `deferred-items.md` for a future cleanup pass — not blocking.

---
*Phase: 33-occasion-cascade*
*Completed: 2026-07-30*
