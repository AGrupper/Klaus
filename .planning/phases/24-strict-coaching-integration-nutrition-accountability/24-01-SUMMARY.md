---
phase: 24-strict-coaching-integration-nutrition-accountability
plan: "01"
subsystem: memory-store + training-quality-derivation
tags: [firestore, coaching, training, quality, dedup, tdd]
dependency_graph:
  requires: []
  provides:
    - CoachingTopicStore (coaching_topics Firestore collection)
    - derive_session_quality (pure function, core/training_checkin.py)
    - TrainingLogStore.log_session quality param
  affects:
    - core/training_checkin.py (_silent_garmin_sync, handle_rpe_callback)
    - memory/firestore_db.py (TrainingLogStore.log_session payload)
tech_stack:
  added: []
  patterns:
    - OutreachLogStore per-day doc pattern (ArrayUnion, fail-open reads)
    - Pure function no-I/O pattern (derive_session_quality mirrors _slot_for)
    - TDD RED/GREEN per task
key_files:
  created:
    - tests/test_coaching_topic_store.py
  modified:
    - memory/firestore_db.py
    - core/training_checkin.py
    - tests/test_training_log_store.py
    - tests/test_training_checkin.py
decisions:
  - CoachingTopicStore uses plain list[str] ArrayUnion (not list[dict]) per Pitfall 3
  - feel=0 guard uses `is not None` not truthiness per Pitfall 4
  - quality derived in both _silent_garmin_sync and handle_rpe_callback per Pitfall 6
  - quality param placed after notes, before source in log_session signature
metrics:
  duration: "~25 minutes"
  completed: "2026-06-06"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 4
  files_created: 1
  tests_added: 37
  tests_passing: 81
---

# Phase 24 Plan 01: Storage Primitives — CoachingTopicStore + Session Quality Summary

## One-liner

Per-day cross-cron dedup gate (CoachingTopicStore with fail-open reads + ArrayUnion plain-string) and derived session quality label (derive_session_quality: feel/RPE/notes → strong/neutral/grind) wired into both Garmin-sync and Telegram-tap log paths.

## What Was Built

### Task 1: CoachingTopicStore + Wave-0 gate tests

Added `CoachingTopicStore` to `memory/firestore_db.py` immediately after `OutreachLogStore`. Mirrors the OutreachLogStore per-day-doc pattern exactly but with a different API contract — `has_topic` hard-blocks (returns True/False for proactive cron filtering), while OutreachLogStore's `topics_today` is informative-only.

Key implementation details:
- `_COLLECTION = "coaching_topics"` (lowercase, per CLAUDE.md §6)
- `has_topic` and `topics_today` are fail-open (return False/[] on any Firestore error — never raise)
- `add_topic` uses `firestore.ArrayUnion([topic_key])` with `merge=True` for atomic upsert; topic_key is a **plain string**, NOT a dict (Pitfall 3: dicts with SERVER_TIMESTAMP break ArrayUnion deep-equality)
- `updated_at: SERVER_TIMESTAMP` is at the doc level only, never inside the array element
- `add_topic` re-raises on write failure (caller-decides discipline, mirrors OutreachLogStore.append Phase 18 D-10)

12 tests added to `tests/test_coaching_topic_store.py`, all green.

### Task 2: derive_session_quality + log_session quality param

**In `memory/firestore_db.py`:**
- Added `quality: str | None = None` to `TrainingLogStore.log_session` signature after `notes`
- Added `"quality": quality` to the payload dict

**In `core/training_checkin.py`:**
- Added module-level constants: `_GARMIN_FEEL_LABELS`, `_QUALITY_STRONG_NOTES`, `_QUALITY_GRIND_NOTES`
- Added pure function `derive_session_quality(rpe, feel, notes=None) -> str | None`:
  - Returns None if both rpe and feel are None
  - Uses `feel is not None` guard (NEVER `if feel:`) — Pitfall 4: feel=0 (Very Weak) is falsy but valid
  - feel>=75 + rpe>=5 → "strong"; feel>=75 + rpe<5 → "neutral"; feel=50 → "neutral"; feel=0/25 → "grind"
  - RPE-only fallback: >=8 → "grind"; <=4 → "strong"; else "neutral"
  - Notes keyword override applied last (pb/pr/personal record → "strong"; cut short/struggled → "grind")
- Wired in `_silent_garmin_sync`: derives `_quality = derive_session_quality(rpe=perceived_exertion, feel=_feel)` before `log_session` call (Pitfall 6 — Garmin-only sessions must get quality)
- Wired in `handle_rpe_callback`: derives provisional `_quality = derive_session_quality(rpe=rpe_value, feel=None)` before `log_session` call
- `attach_note` NOT modified — notes override is embedded inside `derive_session_quality` and the next silent Garmin sync re-derives

25 tests added across `tests/test_training_log_store.py` (4 new) and `tests/test_training_checkin.py` (21 new), all green.

## Test Summary

| Test file | Tests added | All pass |
|-----------|-------------|----------|
| tests/test_coaching_topic_store.py | 12 (new file) | Yes |
| tests/test_training_log_store.py | 4 | Yes |
| tests/test_training_checkin.py | 21 | Yes |
| tests/test_firestore_db.py | 0 (regression check) | Yes (21 passing) |

**Total passing in this plan's scope: 81**

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 7fef983 | test | RED tests for CoachingTopicStore COACH-05 |
| 266832d | feat | CoachingTopicStore implementation |
| 3244c1f | test | RED tests for derive_session_quality + log_session quality PROG-04 |
| 69840ab | feat | derive_session_quality + log_session quality param |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Both primitives are fully implemented:
- `CoachingTopicStore` reads/writes real Firestore (mocked in tests)
- `derive_session_quality` is a pure function returning real quality values
- `log_session(quality=...)` persists real values to Firestore

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes at external trust boundaries. The `CoachingTopicStore` collection `coaching_topics` is an internal write (cron-derived topic keys, never user-supplied input). Threat model coverage per plan:

| Threat ID | Status |
|-----------|--------|
| T-24-01 | Mitigated — topic_key is always a plain string from internal vocabulary |
| T-24-02 | Accepted — notes originate from allowlisted Telegram user only |
| T-24-03 | Mitigated — has_topic/topics_today fail-open implemented |
| T-24-04 | Mitigated — error logs use exc_info=True + key/date only |

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| memory/firestore_db.py | FOUND |
| core/training_checkin.py | FOUND |
| tests/test_coaching_topic_store.py | FOUND |
| tests/test_training_log_store.py | FOUND |
| tests/test_training_checkin.py | FOUND |
| 24-01-SUMMARY.md | FOUND |
| Commit 7fef983 (RED CoachingTopicStore tests) | FOUND |
| Commit 266832d (feat CoachingTopicStore) | FOUND |
| Commit 3244c1f (RED Task 2 tests) | FOUND |
| Commit 69840ab (feat derive_session_quality + quality param) | FOUND |
