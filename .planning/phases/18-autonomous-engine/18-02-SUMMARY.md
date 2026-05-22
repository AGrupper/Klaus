---
phase: 18-autonomous-engine
plan: 02
subsystem: tool-registry
tags: [follow-ups, dateutil, FollowupStore, tool-registration, AUTO-05]

# Dependency graph
requires:
  - phase: 18-autonomous-engine
    provides: FollowupStore.add/list_pending/cancel (Plan 18-01)
provides:
  - schedule_followup brain-direct tool — Klaus schedules his own check-backs
  - list_followups brain-direct tool — Klaus inspects pending follow-ups
  - cancel_followup brain-direct tool — Klaus cancels follow-ups (idempotent)
  - WARNING 7 mitigation — ImportError on dateutil produces structured error
  - smart_agent.md SELF-SCHEDULED FOLLOW-UPS section
affects:
  - 18-06-autonomous-orchestrator (consumes FollowupStore.list_due via tick)
  - 18-09-deployment-docs (DEPLOYMENT.md follow-up tool documentation)

# Tech tracking
tech-stack:
  added: []   # No new dependencies — python-dateutil already pinned in Plan 01
  patterns:
    - "5-site direct-tool registration (Phase 15 self-inspect template applied verbatim)"
    - "Insertion-order append to SMART_AGENT_DIRECT_TOOLS (NOT alphabetical) — NOTE 4"
    - "Local imports inside handlers (FollowupStore, dateutil) — matches Plan 01 mock-friendly convention"
    - "Defensive ImportError catch in dateutil fallback — WARNING 7"

key-files:
  created:
    - tests/test_tools.py (319 lines, 13 TestFollowupTools tests)
  modified:
    - core/tools.py (3 tools registered at 5 sites = 15 edit points; 16 grep hits)
    - prompts/smart_agent.md (SELF-SCHEDULED FOLLOW-UPS section before CAPABILITY MANIFEST)

key-decisions:
  - "Appended to SMART_AGENT_DIRECT_TOOLS at the end (insertion order), not alphabetically — preserves git blame and matches Phase 15/16 convention (NOTE 4)"
  - "ImportError caught alongside ValueError/TypeError/OverflowError in dateutil fallback — structured error survives stale image deploys (WARNING 7)"
  - "list_followups strips created_at/status/origin from response — internal Firestore fields stay internal"
  - "cancel_followup forwards FollowupStore.cancel return value as {ok: bool} — idempotent semantics inherited from store (D-15)"
  - "Used local `from memory.firestore_db import FollowupStore` at handler call sites — matches FollowupStore's own mock-friendly inline-import convention"

patterns-established:
  - "15-edit-point grep verification (≥5 per tool name × 3 tools) at end of plan — mechanical proof that no site was missed"
  - "Test class with monkeypatched sys.modules['dateutil'] = None to simulate ImportError"

requirements-completed: [AUTO-05]

# Metrics
duration: 4min
completed: 2026-05-22
---

# Phase 18 Plan 02: Follow-up Tools Summary

**Three brain-direct follow-up tools (schedule_followup, list_followups, cancel_followup) wired at 15 registration sites with ImportError-resilient dateutil fallback for natural-language `when` parsing.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-22T20:28:56Z
- **Completed:** 2026-05-22T20:33:12Z
- **Tasks:** 1 (TDD — RED + GREEN gates)
- **Files modified:** 3 (`core/tools.py`, `prompts/smart_agent.md`, `tests/test_tools.py`)

## Accomplishments

- 3 new brain-direct tools registered at all 5 canonical sites in `core/tools.py` (15 edit points; grep shows 16 mentions across the file)
- `_handle_schedule_followup` accepts ISO 8601 AND natural-language strings via `dateutil.parser.parse` fallback (D-12); naive datetimes are normalised to UTC
- WARNING 7 fix: `ImportError` caught alongside `ValueError`/`TypeError`/`OverflowError` so a stale Cloud Run image without `python-dateutil` returns a structured `could_not_parse_when` error instead of crashing the chat with a 500
- `_handle_list_followups` strips `created_at`/`status`/`origin` from response — only `id`, `due_at`, `note`, `defer_count` surface
- `_handle_cancel_followup` is idempotent — `{ok: True}` whenever the doc exists (even when already cancelled), `{ok: False}` only when the id is missing (D-15)
- Worker agent CANNOT invoke any of the 3 tools — all excluded from `WORKER_TOOL_SCHEMAS`
- `prompts/smart_agent.md` advertises the new tools in a `SELF-SCHEDULED FOLLOW-UPS` section (between SELF-INSPECTION and CAPABILITY MANIFEST) with the proactive-outreach blurb from RESEARCH Open Question 3

## Task Commits

Each task was committed atomically (TDD RED + GREEN gates):

1. **Task 1 RED — failing tests** — `efec62d` (test)
2. **Task 1 GREEN — 15-edit-point registration + smart_agent.md** — `b99b3f1` (feat)

**Plan metadata commit:** (pending — added by `<final_commit>` step below)

## Files Created/Modified

- `tests/test_tools.py` — NEW (319 lines, 13 tests in `TestFollowupTools`)
- `core/tools.py` — MODIFIED at 5 sites:
  - Lines 49-51: SMART_AGENT_DIRECT_TOOLS frozenset (3 new entries appended at end)
  - Lines 678-715: TOOL_SCHEMAS list (3 new JSON schemas after `get_self_status`)
  - Lines 762-764: WORKER_TOOL_SCHEMAS exclusion set (3 new tool names)
  - Lines 1252-1331: 3 new `_handle_*` functions (with WARNING 7 `ImportError` catch at line 1281)
  - Lines 1358-1360: `_HANDLERS` dispatch dict (3 new lambdas)
- `prompts/smart_agent.md` — MODIFIED (added 14-line SELF-SCHEDULED FOLLOW-UPS section before CAPABILITY MANIFEST at line 107)

## Final grep verification (proves all 15 edit points)

```
schedule_followup: 5 hits
list_followups:    6 hits   (extra hit from cross-reference in cancel_followup schema description)
cancel_followup:   5 hits
TOTAL:             16 hits  (>= 15 required)
ImportError:       2 hits   (1 in _handle_schedule_followup, 1 in another file location)
```

## Confirmation: WARNING 7 fix

```python
# core/tools.py line 1281
except (ImportError, ValueError, TypeError, OverflowError) as exc:
    return json.dumps({"error": f"could_not_parse_when: {exc}"})
```

`ImportError` is the first item in the except tuple — explicitly handled.

## Confirmation: NOTE 4 — SMART_AGENT_DIRECT_TOOLS append order

The 3 new tool names appear at the **end** of the frozenset (lines 49-51), not interspersed alphabetically with `cancel_followup` before `get_self_status` or `read_own_source`. This matches the insertion-order convention established by Phases 15 and 16.

```python
SMART_AGENT_DIRECT_TOOLS: frozenset[str] = frozenset({
    "remember",
    "recall",
    "run_morning_briefing",
    "search_chat_history",
    "list_own_files",
    "read_own_source",
    "search_own_source",
    "get_self_status",
    # Phase 18 — self-scheduled follow-ups (D-15 / AUTO-05)
    "schedule_followup",
    "list_followups",
    "cancel_followup",
})
```

## Tests added

`tests/test_tools.py::TestFollowupTools` (13 tests, all pass):

1. `test_schedule_followup_iso_8601` — ISO 8601 input persists with `origin='klaus_self'`
2. `test_schedule_followup_natural_language` — naive datetime parses via dateutil; result is ISO-8601 UTC
3. `test_schedule_followup_invalid_when_returns_error` — "absolutely not a date" returns structured error
4. `test_schedule_followup_naive_datetime_assigned_utc` — naive datetime gets UTC tzinfo
5. `test_list_followups_strips_internal_fields` — created_at/status/origin stripped from output
6. `test_list_followups_empty` — empty pending list returns `"[]"`
7. `test_cancel_followup_idempotent_returns_ok_true` — `{ok: True}` on both first and repeat calls
8. `test_cancel_followup_nonexistent_returns_ok_false` — `{ok: False}` when FollowupStore.cancel returns False
9. `test_all_three_tools_in_smart_agent_direct_tools` — Site 1 registration
10. `test_all_three_tools_excluded_from_worker_schemas` — Site 3 exclusion
11. `test_all_three_tools_in_handlers_dispatch` — Site 5 registration
12. `test_all_three_tools_have_correct_schemas` — Site 2 schemas with correct `required` arrays
13. `test_schedule_followup_handles_dateutil_import_error` — **WARNING 7 regression** — `sys.modules['dateutil'] = None` forces ImportError; handler returns structured error, FollowupStore.add NOT called

## Decisions Made

- **Insertion-order append, not alphabetical (NOTE 4):** Matches Phases 15/16 frozenset pattern; preserves git blame clarity; explicitly noted in plan.
- **ImportError caught (WARNING 7):** Plan 01 added `python-dateutil>=2.8.2` to requirements.txt, but a stale Cloud Run image rollout could fail to sync the dep. Catching ImportError keeps the failure structured so Klaus's chat reply doesn't 500.
- **Local imports inside handlers:** Matches FollowupStore's own convention (it lazy-imports `uuid` and `datetime` inside methods so unit tests that mock `google.cloud.firestore` at sys.modules level work). Tests patch `memory.firestore_db.FollowupStore` and the handler's `from memory.firestore_db import FollowupStore` resolves to the patched class.
- **list_followups strips internal fields:** `created_at`, `status`, `origin` are FollowupStore implementation details. Klaus only needs id/due_at/note/defer_count to reason about pending follow-ups.

## Deviations from Plan

None — plan executed exactly as written. All 15 edit points + smart_agent.md + 13 tests landed in two commits (RED + GREEN) without scope creep.

## Issues Encountered

None during execution. Pre-existing test failures (`test_pinecone_embed`, `test_heartbeat`, `test_llm_client`, `test_reflection`) are out of scope for this plan — none touch `core/tools.py` or follow-ups, and all are caused by `google.genai` ModuleNotFound in the local dev venv. Logged to `deferred-items.md` is not required because these failures pre-date this plan.

## User Setup Required

None — no external service configuration required. Tools are wired and ready for the autonomous tick (Plan 18-06) to consume.

## Next Phase Readiness

- **Plan 18-03 (autonomous-prompts):** Ready — `schedule_followup` is now a real tool the autonomous prompts can reference.
- **Plan 18-06 (autonomous-orchestrator):** Ready — orchestrator can compose tick output that ends with "Sir, I'll check back at 15:00" knowing the tool exists.
- **Plan 18-07 (cron-route + heartbeat):** No coupling.
- **Worker exclusion verified:** `WORKER_TOOL_SCHEMAS.isdisjoint({schedule_followup, list_followups, cancel_followup})` confirmed at runtime.

---
*Phase: 18-autonomous-engine*
*Completed: 2026-05-22*

## Self-Check: PASSED

- core/tools.py exists and grep shows 16 total mentions of the 3 tool names
- prompts/smart_agent.md contains SELF-SCHEDULED FOLLOW-UPS section
- tests/test_tools.py exists with 13 passing tests in TestFollowupTools
- Commit efec62d (RED) and b99b3f1 (GREEN) both present in `git log --oneline`
