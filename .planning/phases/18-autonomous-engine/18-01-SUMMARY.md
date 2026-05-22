---
phase: 18-autonomous-engine
plan: 01
subsystem: database
tags: [firestore, follow-ups, outreach-log, tick-log, dateutil, repeat-suppression, autonomous-tick]

# Dependency graph
requires:
  - phase: 17-reflection-journal
    provides: JournalStore class pattern (date-keyed Firestore stores, never-raise reads, raise-on-writes) — directly cloned for FollowupStore and OutreachLogStore
  - phase: 16-self-model-state-awareness
    provides: SelfStateStore class pattern (singleton state, _make_firestore_client wrapper)
provides:
  - FollowupStore class (memory/firestore_db.py) — 7 methods backing AUTO-04 scheduled follow-ups
  - OutreachLogStore class (memory/firestore_db.py) — 3 methods backing AUTO-03 repeat-suppression
  - TickLogStore class (memory/firestore_db.py) — 1 method backing Plan 06 _write_tick_log (NOTE 1 wrapper)
  - python-dateutil>=2.8.2 pinned in requirements.txt for Plan 02 schedule_followup NL parsing
  - 21 unit tests in tests/test_firestore_db.py with reusable FakeFirestore mock pattern
affects: [18-02-followup-tools, 18-06-autonomous-orchestrator, 18-09-deployment-docs]

# Tech tracking
tech-stack:
  added: [python-dateutil]
  patterns:
    - "Per-instance Firestore client + collection ref (matches JournalStore/SelfStateStore)"
    - "Never-raise reads / raise-on-writes — except TickLogStore.write which is best-effort"
    - "Composite Firestore index (status, due_at) — to be created on first deploy"
    - "ArrayUnion atomic-append with merge=True for daily aggregate docs"
    - "NOTE 2 docstring regression guard pattern (test asserts docstring content)"

key-files:
  created:
    - "tests/test_firestore_db.py — 21 tests covering all 3 new stores"
    - ".planning/phases/18-autonomous-engine/deferred-items.md — log of out-of-scope findings"
  modified:
    - "memory/firestore_db.py — added FollowupStore (185 lines), OutreachLogStore (115 lines), TickLogStore (81 lines)"
    - "requirements.txt — added python-dateutil>=2.8.2"

key-decisions:
  - "TickLogStore lives in memory/firestore_db.py (NOTE 1) — keeps the wrapper-class pattern consistent across all stores instead of letting Plan 06 reach into the private _make_firestore_client helper."
  - "OutreachLogStore.append docstring includes an explicit warning that ArrayUnion's deep-equality dedup breaks if callers embed firestore.SERVER_TIMESTAMP inside entry dicts (NOTE 2)."
  - "TickLogStore.write is the ONLY write in this module that swallows exceptions — matches Plan 06's '_write_tick_log never raises' contract. Every other store write logs and re-raises."
  - "FollowupStore.cancel is idempotent (returns True on re-cancel) — per D-15's explicit contract."

patterns-established:
  - "Date-keyed-doc-with-array-field: outreach_log/{date} aggregates many ticks' entries atomically via ArrayUnion + merge=True — pattern reusable for any other 'append daily' Firestore collection."
  - "Sub-collection write under a date doc: tick_logs/{date}/ticks/{HH:MM} — keeps a day's worth of small docs under one parent for cheap retention pruning."
  - "Docstring regression guard via __doc__ inspection (TestOutreachLogStore.test_append_docstring_warns_about_server_timestamp) — keeps a critical comment from silently being removed in future refactors."

requirements-completed: [AUTO-03, AUTO-04]

# Metrics
duration: 7min
completed: 2026-05-22
---

# Phase 18 Plan 01: Follow-up + Outreach + Tick-Log Stores Summary

**Three new Firestore stores (FollowupStore + OutreachLogStore + TickLogStore) backing the autonomous-engine repeat-suppression and follow-up loops, plus python-dateutil pinned for NL `when` parsing.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-05-22T20:17:40Z
- **Completed:** 2026-05-22T20:24:16Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 3 (memory/firestore_db.py, requirements.txt, tests/test_firestore_db.py)
- **Files created:** 2 (tests/test_firestore_db.py, .planning/phases/18-autonomous-engine/deferred-items.md)

## Accomplishments

- **FollowupStore (AUTO-04)** with 7 methods — add (uuid4 pending doc), list_due (composite-index query on status+due_at for the 20-min autonomous tick), list_pending (UI listing), mark_done, idempotent cancel, atomic-Increment defer (force-fire after defer_count >= 3 per D-14), and a `_COLLECTION = "followups"` constant.
- **OutreachLogStore (AUTO-03)** with 3 methods — atomic ArrayUnion append (concurrent-tick-safe), get_today never-raise read, topics_today helper that pulls just the topic_keys for the tick-brain triage prompt's repeat-suppression context.
- **TickLogStore (NOTE 1, D-21)** with 1 method — best-effort write to `tick_logs/{date}/ticks/{HH:MM}` that **never raises**, matching Plan 06's `_write_tick_log` contract. Strips the transient `empty` flag from situation snapshots before persisting (so the eval fixtures stay clean).
- **python-dateutil>=2.8.2** pinned in requirements.txt for the `schedule_followup(when, note)` direct tool that Plan 02 will implement (D-12: ISO first, NL fallback).
- **21 unit tests** in `tests/test_firestore_db.py` — 11 FollowupStore + 8 OutreachLogStore + 2 TickLogStore. Mock pattern mirrors `tests/test_llm_usage_store.py` exactly: sys.modules-level Firestore mock with distinguishable `_Increment` / `_ArrayUnion` / `_FieldFilter` sentinels.
- **NOTE 2 regression guard** — `test_append_docstring_warns_about_server_timestamp` asserts the SERVER_TIMESTAMP warning stays in `OutreachLogStore.append.__doc__` so a future refactor can't silently drop it.

## Task Commits

Each task ran the full TDD red/green cycle:

1. **Task 1 RED:** test(18-01): add failing tests for FollowupStore + python-dateutil dep — `5a808b2`
2. **Task 1 GREEN:** feat(18-01): implement FollowupStore for scheduled follow-ups — `bf6fd38`
3. **Task 2 RED:** test(18-01): add failing tests for OutreachLogStore + TickLogStore — `7a4895c`
4. **Task 2 GREEN:** feat(18-01): implement OutreachLogStore + TickLogStore — `884eb1a`

REFACTOR step skipped — implementation was already clean (matches JournalStore/SelfStateStore conventions verbatim; docstrings comprehensive; no duplication worth extracting).

## Files Created/Modified

- `memory/firestore_db.py` — appended three new classes (lines 776–1156):
  - `FollowupStore` (lines 776–959, ~185 lines): 7 methods
  - `OutreachLogStore` (lines 961–1074, ~115 lines): 3 methods
  - `TickLogStore` (lines 1076–1156, ~81 lines): 1 method
- `requirements.txt` — added `python-dateutil>=2.8.2` on line 35 (Runtime utilities section)
- `tests/test_firestore_db.py` (NEW, 619 lines) — 3 test classes covering all the truths from the plan frontmatter
- `.planning/phases/18-autonomous-engine/deferred-items.md` (NEW) — logs a pre-existing test-ordering issue in `tests/test_heartbeat.py` (sys.modules pollution from other store-test mocks; reproduced on HEAD with our changes stashed — not caused by this plan)

## Decisions Made

- **NOTE 1 wrapper class chosen over private helper reach-in** — the plan flagged that Plan 06 was originally going to call `_make_firestore_client` directly from `core/autonomous.py`. Adding `TickLogStore` here keeps every Firestore-backed feature in Phase 18 behind a wrapper class, matching JournalStore/SelfStateStore/FollowupStore/OutreachLogStore. Plan 06's executor should `from memory.firestore_db import TickLogStore` rather than reach into a private helper.
- **NOTE 2 inline warning + test regression guard** — `firestore.SERVER_TIMESTAMP` is a sentinel object; each call creates a distinct instance, so `ArrayUnion`'s deep-equality dedup would treat "identical" entries as different and silently break repeat-suppression. The warning lives both inline in the `OutreachLogStore.append` docstring and is enforced by `test_append_docstring_warns_about_server_timestamp` — future devs can't drop the warning without breaking tests.
- **Composite index requirement documented inline** — `FollowupStore.list_due` requires a composite Firestore index on `(status, due_at)` for the autonomous tick's repeated lookup. Flagged in the method's docstring; will be ratified in Plan 09's DEPLOYMENT.md §Firestore Composite Indexes.
- **TickLogStore.write is the lone exception to "writes raise"** — every other store in this module re-raises on Firestore failure. Tick-log writes are best-effort because Plan 06's contract is that `_write_tick_log` must never abort the autonomous tick (a logging hiccup must not cost us an outreach decision).
- **`__init__.set._COLLECTION` constants over inline strings** — every new class follows the same `_COLLECTION = "..."` pattern as JournalStore/SelfStateStore, making it grep-able and easy to find which class owns which Firestore collection.

## Deviations from Plan

### Out-of-scope discovery (not auto-fixed; logged for later)

**1. [Rule 4 — pre-existing test ordering] tests/test_heartbeat.py::test_cron_heartbeat_rejects_unauthenticated fails when run after tests/test_llm_usage_store.py or tests/test_reflection.py**
- **Found during:** Task 2 GREEN verification
- **Issue:** Cross-test sys.modules pollution — once any `test_*_store.py` file installs its `google.cloud.firestore` mock, the test_heartbeat module imports a degenerate firestore namespace
- **Verified pre-existing:** Reproduced on commit `7a4895c` with our changes stashed via `git stash`; failure happens identically. Not caused by this plan.
- **Disposition:** Out of scope per the executor's scope boundary rule (only auto-fix issues directly caused by current task's changes). Logged in `.planning/phases/18-autonomous-engine/deferred-items.md` with a remediation recommendation (per-module conftest cleanup of `sys.modules['google.cloud.firestore']`).

**No in-scope deviations.** Plan executed exactly as written for everything Task 1 and Task 2 were responsible for.

---

**Total deviations:** 0 auto-fixed, 1 deferred out-of-scope (pre-existing).
**Impact on plan:** None — every plan truth, artifact, and key-link was implemented as specified; all 21 tests pass; all 6 plan-verification commands return as expected.

## Issues Encountered

- **autouse fixture initially used `importlib.reload`** — my first pass copied `test_llm_usage_store.py`'s pattern verbatim, but its `_install_firestore_mock()` deletes `memory.firestore_db` from `sys.modules` to force a clean re-bind. `importlib.reload` requires the module to still BE in sys.modules, so it crashed with `ImportError: module memory.firestore_db not in sys.modules`. Fixed by switching the fixture to `importlib.import_module("memory.firestore_db")` which handles the re-bind correctly. Caught and fixed during RED verification before the first commit.
- **dateutil installed in `.venv/`, not system Python 3.14** — `python3` at `/opt/homebrew/bin/python3` does not have dateutil; `/Users/amitgrupper/Desktop/Klaus/.venv/bin/python` does. All verification ran via the venv-pinned interpreter.

## Cross-references for downstream plans

- **Plan 02 (followup-tools):** Imports `FollowupStore` for the `schedule_followup` / `list_followups` / `cancel_followup` direct tools. NL `when` parsing uses `from dateutil import parser` per D-12 (ISO first, NL fallback).
- **Plan 06 (autonomous-orchestrator):** `_write_tick_log` should `from memory.firestore_db import TickLogStore` and call `TickLogStore(project_id, database).write(date_str, tick_time, situation, decision)` — do NOT reach into `_make_firestore_client` (NOTE 1). Also imports `FollowupStore.list_due`, `OutreachLogStore.append`, and `OutreachLogStore.topics_today`.
- **Plan 09 (deployment-docs):** Must add the composite Firestore index on `followups(status, due_at)` to the §Firestore Composite Indexes section of `docs/DEPLOYMENT.md`. Without it, `FollowupStore.list_due` will 400 on the first deploy with the missing-index error message.

## Next Phase Readiness

- Three new stores ready for downstream consumption by Plans 02, 06, and 09.
- 21 tests green, no regressions in `tests/test_llm_usage_store.py` or `tests/test_reflection.py`.
- One pre-existing test-ordering glitch in `tests/test_heartbeat.py` documented but NOT blocking — it's reproducible without our changes.
- `python-dateutil` available to importers; venv has it installed; CI will install it from `requirements.txt`.

## Self-Check: PASSED

- File `memory/firestore_db.py` exists and contains `^class FollowupStore:` at line 776, `^class OutreachLogStore:` at line 961, `^class TickLogStore:` at line 1076 — verified.
- File `tests/test_firestore_db.py` exists with 3 test classes (TestFollowupStore, TestOutreachLogStore, TestTickLogStore) and 21 passing tests — verified.
- File `requirements.txt` contains `python-dateutil>=2.8.2` at line 35 — verified.
- File `.planning/phases/18-autonomous-engine/deferred-items.md` exists — verified.
- Commits exist in git log: `5a808b2`, `bf6fd38`, `7a4895c`, `884eb1a` — verified.
- All 6 verification commands from `<verification>` block pass — verified.

---
*Phase: 18-autonomous-engine*
*Plan: 01-followup-outreach-stores*
*Completed: 2026-05-22*
