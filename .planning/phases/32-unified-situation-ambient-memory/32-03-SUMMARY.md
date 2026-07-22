---
phase: 32-unified-situation-ambient-memory
plan: 03
subsystem: memory
tags: [pinecone, memory-hygiene, reflection, brain-judged, mem-03]

# Dependency graph
requires:
  - phase: 32-unified-situation-ambient-memory
    provides: Phase 32 research + plan (Pinecone index, MemoryStore/MemoryTool, reflection directive_items pattern from Phase 31)
provides:
  - forget_memory tool (deliberate hard-delete of a Pinecone vector by id), registered brain-direct end-to-end
  - Brain-judged memory contradiction detection woven into the nightly reflection (memory_contradiction directive_items type)
  - Candidate-memory gather in core/reflection.py exposing vector ids (direct index query, not the public recall() shape)
affects: [32-06 (auto-recall — will likely want recall() output to eventually surface ids too), 33 (occasion cascade), 35 (hardening/subtraction)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deliberate-only deletion: forget_memory is the ONLY path that hard-deletes a Pinecone vector; reflection only flags, never deletes (D-04)"
    - "Index-accessor reuse: MemoryTool.forget_memory and core/reflection.py's candidate-memory gather both reach into MemoryStore._get_index()/_embed() directly rather than the public recall()/remember() wrappers, when the public shape doesn't carry what's needed (vector ids)"

key-files:
  created: []
  modified:
    - mcp_tools/memory.py (forget_memory method on MemoryTool)
    - core/tools.py (forget_memory: SMART_AGENT_DIRECT_TOOLS, TOOL_SCHEMAS, WORKER_TOOL_SCHEMAS exclusion, _handle_forget_memory, _HANDLERS)
    - core/reflection.py (candidate-memory gather in _gather_day; memory_contradictions -> directive_items mapping in run_reflection)
    - prompts/reflection.md (candidate_memories input, memory_contradictions output field + type rule, Contradiction detection instruction bullet)
    - prompts/nightly_review.md (memory_contradiction type doc + weaving instruction — added here; did not already exist despite plan text)
    - tests/test_tools.py (TestForgetMemory: 7 tests)
    - tests/test_reflection.py (5 new tests: gather success/failure, DETECTION mapping, empty-state, prompt-doc regression)

key-decisions:
  - "forget_memory reaches into MemoryStore._get_index() directly (not a new MemoryStore.forget() method) — plan explicitly scoped files_modified to exclude memory/pinecone_db.py, and the interface note directed 'via the existing MemoryStore index accessor'"
  - "Candidate-memory gather in core/reflection.py queries the Pinecone index directly (embed + index.query) instead of calling MemoryStore.recall() — recall()'s public return shape deliberately omits vector ids, locked by tests/memory/test_pinecone_recall.py::test_result_shape_unchanged; changing that shape was out of scope and would have broken an existing regression test"
  - "prompts/nightly_review.md's memory_contradiction weaving bullet was added in this plan, not inherited from a prior pass — despite the plan's action text claiming it 'already exists,' grep confirmed it did not; added it to satisfy the plan's own acceptance criteria (Rule 1/2 auto-fix)"

requirements-completed: [MEM-03]

duration: ~35min
completed: 2026-07-22
---

# Phase 32 Plan 03: Memory Hygiene — forget_memory + Contradiction Detection Summary

**Deliberate `forget_memory` Pinecone hard-delete tool (brain-direct, input-validated) plus brain-judged nightly memory-contradiction flagging that never auto-deletes — the correction half of ambient memory, landing before Plan 06's auto-recall.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 2/2 completed
- **Files modified:** 6 (mcp_tools/memory.py, core/tools.py, core/reflection.py, prompts/reflection.md, prompts/nightly_review.md, tests/test_tools.py, tests/test_reflection.py — 7 total incl. both test files)

## Accomplishments

- `MemoryTool.forget_memory(vector_id)` hard-deletes a Pinecone vector by id via the stock `index.delete(ids=[...])` call — validated as a non-empty string first, returns a clean error dict on malformed input, never raises
- `forget_memory` registered at all 3 `core/tools.py` sites (`SMART_AGENT_DIRECT_TOOLS`, `TOOL_SCHEMAS`, `_HANDLERS`) plus excluded from `WORKER_TOOL_SCHEMAS` — brain-only, like `remember`/`recall`
- Reflection now gathers a bounded (`k=5`) candidate-memory set each night, keyed on today's conversation content, exposing vector ids alongside text
- The reflection LLM can flag a stored memory as contradicted by something newer via a new `memory_contradictions` output field; `core/reflection.py` maps this into a `type: "memory_contradiction"` `directive_items` entry, mirroring the existing `prune_flags` pattern exactly — narrative-only, never auto-actioned
- `prompts/nightly_review.md` now phrases the contradiction as a plain question ("I still have you down as X — drop that?"), with `forget_memory` as the confirmed-deletion path

## Task Commits

Each task was committed atomically:

1. **Task 1: forget_memory handler + 3-site tool registration + vector_id validation** — `2adf519` (feat)
2. **Task 2: Brain-judged contradiction detection in reflection → memory_contradiction directive_items → nightly phrasing** — `b1ee67e` (feat)

_TDD: RED/GREEN were done together per-task (tests written and implementation verified in the same commit) rather than as separate test→feat commits — both tasks' behavior and tests were developed iteratively against the real interfaces before committing, per the plan's tdd="true" flag with no pre-existing failing-test baseline to gate against._

## Files Created/Modified

- `mcp_tools/memory.py` — `MemoryTool.forget_memory(vector_id)`: validates input, calls `self._store._get_index().delete(ids=[vector_id])`
- `core/tools.py` — `forget_memory` schema + 3-site registration + `WORKER_TOOL_SCHEMAS` exclusion + `_handle_forget_memory`
- `core/reflection.py` — `_gather_day` step (f): direct Pinecone index query for `candidate_memories`; `run_reflection`: `candidate_memories` in `brain_input`, `memory_contradictions` → `directive_items` mapping
- `prompts/reflection.md` — `candidate_memories` input doc, `memory_contradictions` output field + type rule, "Contradiction detection (D-04/MEM-03)" instruction bullet
- `prompts/nightly_review.md` — `memory_contradiction` type doc + weaving instruction bullet
- `tests/test_tools.py` — `TestForgetMemory` (7 tests: valid delete, empty/non-string vector_id, dispatch-by-name, 3 registration checks)
- `tests/test_reflection.py` — 5 new tests (candidate-memory gather success + isolated failure, contradiction→directive_items mapping with no-delete assertion, empty-state, prompt-doc grep-equivalent regression); `_default_gathered_day()` extended with `candidate_memories: []`; existing `test_gather_day_uses_recent_window_not_stale_get` updated to mock `memory.pinecone_db.MemoryStore` (avoids a real network call from the new gather step)

## Decisions Made

- **`forget_memory` reaches into `MemoryStore._get_index()` directly** rather than adding a new public `MemoryStore.forget()` method — the plan's `files_modified` explicitly excluded `memory/pinecone_db.py`, and the interface note directed use of "the existing MemoryStore index accessor." Mirrors the pattern already used elsewhere in the codebase for thin-wrapper index access.
- **Candidate-memory gather bypasses `MemoryStore.recall()`** and queries the Pinecone index directly (embed + `index.query`) inside `core/reflection.py`. `recall()`'s public return shape (`{kind, content, score, ts}`) deliberately omits vector ids — this is locked by an existing regression test (`tests/memory/test_pinecone_recall.py::test_result_shape_unchanged`). Modifying `recall()`'s shape was out of the plan's file scope and would have broken that locked contract; querying the index directly (matching `MemoryStore.recall`'s internal implementation) was the safe path that stays within scope.
- **`prompts/nightly_review.md`'s memory-contradiction weaving bullet did not already exist.** The plan's action text for Task 2 claimed "the phrasing half already added last pass" (referencing an earlier commit `6c77c15`), but that commit only revised `32-03-PLAN.md` itself — no prompt file was touched. Verified via `grep` before starting; added the weaving bullet as part of Task 2 to satisfy the plan's own acceptance criteria (Rule 1/2 auto-fix — a missing piece the plan's acceptance criteria requires).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1/2 - Bug/Missing] `prompts/nightly_review.md` memory_contradiction weaving instruction did not pre-exist**
- **Found during:** Task 2, before starting the edit (grep check)
- **Issue:** Plan's action text claimed the nightly phrasing half was "already added last pass," referencing commit `6c77c15` ("wire brain-judged contradiction detection"). Inspecting that commit showed it only revised `32-03-PLAN.md`'s text, not any prompt file — `grep -rn "memory_contradiction" prompts/` returned nothing before this plan's edits.
- **Fix:** Added the `directive_items` type doc line (mentioning `memory_contradiction`) and a full "Memory contradictions" weaving bullet to `prompts/nightly_review.md`'s "Directive housekeeping" section, matching the style of the existing Proposals/Expiries/Prune-flags bullets.
- **Files modified:** `prompts/nightly_review.md`
- **Verification:** `grep -n "memory_contradiction" prompts/nightly_review.md` — present; `tests/test_reflection.py::test_prompts_document_memory_contradiction_input_and_output` passes.
- **Committed in:** `b1ee67e` (Task 2 commit)

**2. [Rule 3 - Blocking] `MemoryStore.recall()`'s public shape can't carry vector ids needed for the contradiction flag**
- **Found during:** Task 2, while designing the candidate-memory gather
- **Issue:** The plan's interface note said to gather `candidate_memories: [{id, text}]` "via `MemoryStore.recall`," but `recall()`'s return dicts only carry `{kind, content, score, ts}` — no vector id. Without an id, a `memory_contradiction` entry can't carry a `vector_id` for the eventual `forget_memory` confirmation (the whole point of Task 2's `directive_items` entry per the plan's own `<action>` text). Modifying `recall()`'s shape was ruled out because `tests/memory/test_pinecone_recall.py::test_result_shape_unchanged` explicitly locks it to exactly `{kind, content, score, ts}`, and `memory/pinecone_db.py` was outside this plan's `files_modified`.
- **Fix:** `_gather_day`'s new candidate-memory step queries the Pinecone index directly (`MemoryStore._embed()` + `MemoryStore._get_index().query()`), mirroring `recall()`'s internal implementation but keeping `m.id` in the mapped result. `recall()` itself is untouched.
- **Files modified:** `core/reflection.py`
- **Verification:** `tests/test_reflection.py::test_gather_day_includes_candidate_memories` asserts `{"id": "vec-1", "text": ...}` shape; `tests/memory/test_pinecone_recall.py` (all tests, including `test_result_shape_unchanged`) still green.
- **Committed in:** `b1ee67e` (Task 2 commit)

**3. [Rule 3 - Blocking] Existing gather test would trigger a real network call**
- **Found during:** Task 2, before running the test suite
- **Issue:** `test_gather_day_uses_recent_window_not_stale_get` exercises `_gather_day` directly without mocking `memory.pinecone_db.MemoryStore`. With the new candidate-memory gather step added, this test would attempt a real `google.genai` embedding call (using the fake `SMART_AGENT_API_KEY` from the test env), risking a slow/flaky network-dependent test.
- **Fix:** Added `with patch("memory.pinecone_db.MemoryStore", side_effect=RuntimeError("skip")):` to that test's context managers, consistent with how the other gather sources in the same test are already skipped.
- **Files modified:** `tests/test_reflection.py`
- **Verification:** Test still passes and completes in milliseconds (no network I/O attempted).
- **Committed in:** `b1ee67e` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (1x Rule 1/2, 2x Rule 3)
**Impact on plan:** All three were necessary to make Task 2's stated behavior actually work end-to-end and to keep the existing test suite fast/isolated. No scope creep — `memory/pinecone_db.py` itself was never modified; only `core/reflection.py`'s consumption of it changed.

## Issues Encountered

None beyond the deviations above.

## User Setup Required

None — no external service configuration required. `forget_memory` uses the existing `PINECONE_API_KEY`/`PINECONE_INDEX_NAME` env vars already configured for `remember`/`recall`.

## Next Phase Readiness

- `forget_memory` is live end-to-end (brain-callable, tested) — ready for Amit to say "forget that" in chat once Plan 06's auto-recall makes stale memories visible in conversation, or via the nightly's own contradiction question.
- The nightly contradiction flow only *asks*; the actual `forget_memory` call happens on Klaus's next turn after Amit confirms in chat — no additional wiring needed, `forget_memory` is already brain-direct.
- Note for Plan 06 (ambient auto-recall): `MemoryStore.recall()`'s public shape still does not carry vector ids. If Plan 06's auto-injected recall needs ids for any reason (e.g. so Klaus can call `forget_memory` immediately after an auto-recalled fact comes up in conversation), it will need either the same direct-index-query pattern used here, or a deliberate, tested change to `recall()`'s shape (which would need to update `test_result_shape_unchanged`).

---
*Phase: 32-unified-situation-ambient-memory*
*Completed: 2026-07-22*
