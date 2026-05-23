---
phase: 17-reflection-journal
plan: 02
subsystem: core
tags: [reflection, journal, llm, firestore, pinecone, cron, tdd, first-person]

# Dependency graph
requires:
  - phase: 17-01
    provides: JournalStore in firestore_db.py; remember_self() in pinecone_db.py; Wave 0 test scaffold

provides:
  - core/reflection.py with run_reflection(target_date) synchronous orchestrator
  - prompts/reflection.md first-person Klaus diary prompt (D-17)
  - _parse_reflection_json hardened JSON helper (D-03 / Pitfall 3)
  - _summarize_conversation worker LLM call (D-02) with 6h-window degradation
  - _brain_reflect brain + fallback chain (D-13)
  - _minimal_fallback_entry D-13 doc when both LLM calls fail
  - _gather_day best-effort gather from 5 sources (D-01)
  - 3-day rolling recent_context window in SelfStateStore (D-05)
  - 4 formerly-skipped tests now implemented and green (JOUR-01, D-03, D-13)

affects:
  - 17-03-PLAN (cron route depends on run_reflection; digest tests depend on JournalStore)
  - 17-04-PLAN (SELF.md generator + get_self_status journal field depend on JournalStore)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_parse_reflection_json: strip json fences → slice {..} → json.loads → validate 5 D-03 keys → default missing → cap highlights at 5"
    - "Patch strategy: patch _gather_day and _brain_reflect at core.reflection.* (internal helpers); patch JournalStore/MemoryStore/SelfStateStore at their source modules (memory.firestore_db.*, memory.pinecone_db.*)"
    - "Rolling 3-day recent_context: JSON-list stored in SelfStateStore; json.loads existing, append tagged entry, trim to [-3:]"
    - "D-13 fallback: _brain_reflect returns None → _minimal_fallback_entry; JournalStore.set still called with summary='reflection unavailable'"
    - "6h conversation window degradation: _summarize_conversation returns sentinel string on empty list — never makes LLM call"

key-files:
  created:
    - core/reflection.py
    - prompts/reflection.md
  modified:
    - tests/test_reflection.py

key-decisions:
  - "Patch _gather_day and _brain_reflect directly in tests (not individual source modules) — avoids deep import chains into mcp_tools and google.cloud which require external credentials in dev"
  - "run_reflection is synchronous (not async) — D-13/RESEARCH A2; to be called from web_server via loop.run_in_executor"
  - "JournalStore and SelfStateStore imported inside run_reflection body (deferred) — tests patch at memory.firestore_db.JournalStore source"
  - "Tasks-completed metric uses count of today's due tasks from get_today_tasks()['today'] — no 'completed today' accessor exists (RESOLVED per plan)"
  - "Test env vars patched via patch.dict('os.environ', ...) inside _mock_gather_sources context — avoids KeyError on GCP_PROJECT_ID"

patterns-established:
  - "Internal-helper patching: mock the orchestrating helper (_gather_day, _brain_reflect) rather than individual external dependencies to keep tests fast and stable"
  - "D-13 fallback via None sentinel: _brain_reflect returns None on total LLM failure; run_reflection checks and falls through to _minimal_fallback_entry"

requirements-completed: [JOUR-01]

# Metrics
duration: ~9min
completed: 2026-05-19
---

# Phase 17 Plan 02: Reflection Orchestrator Summary

**`core/reflection.py` — the gather-reflect-persist loop: `run_reflection(target_date)` gathers 5 best-effort sources, summarizes conversation on the worker model, reflects on the brain model into strict JSON, and writes JournalStore + Pinecone + SelfStateStore with a rolling 3-day `recent_context` window**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-05-19T12:04:06Z
- **Completed:** 2026-05-19T12:13:26Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 extended)

## Accomplishments

- `prompts/reflection.md` created: first-person Klaus diary prompt with `{today_date}` placeholder, strict JSON instruction, all 5 D-03 keys named, D-18 continuity section, JARVIS/C-3PO tone
- `core/reflection.py` created with full gather-reflect-persist orchestrator:
  - `_gather_day`: 5 isolated sources (LLMUsageStore, FirestoreConversationStore, GoogleCalendarManager, get_today_tasks, heartbeat ledger), each in its own `try/except` (12 total `except Exception` blocks)
  - `_summarize_conversation`: worker model (WORKER_AGENT_*) with `purpose="reflect_summary"`; degrades to sentinel string on empty/stale 6h window
  - `_parse_reflection_json`: strips ```json fences, slices `{`..`}`, validates and defaults all 5 D-03 keys, caps highlights at 5, returns None on total failure
  - `_brain_reflect`: brain model (SMART_AGENT_*) with fallback chain (SMART_AGENT_FALLBACK_*); returns None when both fail
  - `_minimal_fallback_entry`: D-13 minimal doc with `summary="reflection unavailable"` + raw metrics
  - `run_reflection`: synchronous orchestrator writing 3 targets in order (JournalStore → Pinecone remember_self → SelfStateStore), each isolated so one failure does not block the others
  - Rolling 3-day `recent_context` window: reads current JSON list, appends tagged entry, trims to last 3
  - D-18 continuity: loads `journal/{yesterday}` and injects `summary` + `current_focus` into brain input; graceful when absent (first run)
  - `_cli`: `--dry-run` / `--date` smoke test flags
- `tests/test_reflection.py` extended: 4 formerly-skipped stubs replaced with real tests; `test_run_reflection_writes_entry` extended with Task 3 assertions (remember_self called, SelfStateStore.set called, rolling 3-day window ≤3 entries)

## Task Commits

Each task was committed atomically:

1. **Task 1: prompts/reflection.md** — `205592f` (feat)
2. **Task 2 RED: failing tests** — `b69f7d4` (test)
3. **Task 2 GREEN: core/reflection.py** — `75e09e6` (feat)
4. **Task 3: extended test assertions** — `2a4266c` (feat)

## Files Created/Modified

- `prompts/reflection.md` — 51-line first-person Klaus diary system prompt; all 5 D-03 keys named; strict JSON instruction; `{today_date}` placeholder; D-18 continuity section
- `core/reflection.py` — 497 lines; `run_reflection`, `_gather_day`, `_summarize_conversation`, `_parse_reflection_json`, `_brain_reflect`, `_minimal_fallback_entry`, `_minimal_fallback_entry`, `_cli`
- `tests/test_reflection.py` — extended: 4 stubs replaced with real tests; `test_run_reflection_writes_entry` extended with Task 3 assertions

## Decisions Made

- **Patch at internal helpers in tests:** `_gather_day` and `_brain_reflect` are patched at `core.reflection.*` rather than deep dependencies. This avoids import chains into `mcp_tools.calendar_tool`, `mcp_tools.ticktick_tool`, `google.cloud` — all require external credentials in dev/CI.
- **Patch source-module stores:** `JournalStore`, `SelfStateStore`, `MemoryStore` are patched at `memory.firestore_db.*` / `memory.pinecone_db.*` since they are imported inside function bodies (deferred imports).
- **rolling recent_context as JSON list:** stored as a JSON-serialized list string in the `SelfStateStore` `recent_context` field. Existing plain-string values (legacy) are wrapped into a list on first read.
- **run_reflection is synchronous:** per D-13/RESEARCH A2; web_server will call it via `loop.run_in_executor`.
- **tasks_completed = today's due task count:** per the RESOLVED decision in `<resolved_open_questions>` — `get_today_tasks()["today"]` length, no new TickTick accessor.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test patch targets adjusted for deferred imports**
- **Found during:** Task 2 GREEN (tests failed with `AttributeError: module 'core.reflection' does not have the attribute 'LLMUsageStore'`)
- **Issue:** Original test design patched `core.reflection.LLMUsageStore` etc., but `reflection.py` uses deferred `from X import Y` inside function bodies — no module-level names to patch.
- **Fix:** (a) Replaced 5-patch gather mock with a single `patch("core.reflection._gather_day")` call; (b) replaced `core.reflection.JournalStore` / `LLMClient` patches with patches at source (`memory.firestore_db.JournalStore`, `core.reflection._brain_reflect`); (c) added `patch.dict("os.environ", ...)` for GCP_PROJECT_ID and related env vars.
- **Files modified:** `tests/test_reflection.py`
- **Commits:** `75e09e6`, `2a4266c`

## Known Stubs

- `test_cron_reflect_route` — remains skipped; implemented in 17-03 (cron route plan)
- `test_journal_digest_assembly` — remains skipped; implemented in 17-03/04 (digest injection plan)

These stubs are intentional scaffolding for the next wave.

## Threat Flags

No new network endpoints or auth paths introduced. `core/reflection.py` is a cron-triggered module (not an HTTP handler) — it reads from Firestore/Pinecone and writes back. Trust boundary analysis per plan's threat model:
- T-17-04 (Tampering via brain JSON): mitigated — `_parse_reflection_json` validates all 5 keys and types; LLM output never executed
- T-17-05 (DoS via gather failures): mitigated — 12 `except Exception` blocks + D-13 minimal fallback; a total LLM outage cannot leave a journal gap
- T-17-06 (Information disclosure via conversation read): accepted — 6h SESSION_TIMEOUT_HOURS gate naturally limits scope; single-user trusted system

## Self-Check: PASSED

- FOUND: core/reflection.py
- FOUND: prompts/reflection.md
- FOUND: .planning/phases/17-reflection-journal/17-02-SUMMARY.md
- FOUND: commit 205592f (feat: prompts/reflection.md)
- FOUND: commit b69f7d4 (test: RED failing tests)
- FOUND: commit 75e09e6 (feat: core/reflection.py implementation)
- FOUND: commit 2a4266c (feat: Task 3 extended assertions)
- No unexpected file deletions
