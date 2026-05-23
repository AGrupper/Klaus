---
phase: 14-foundation
plan: "01"
subsystem: cost-metering
tags: [pricing, firestore, llm-usage, tdd]
dependency_graph:
  requires: []
  provides: [core/pricing.py, LLMUsageStore]
  affects: [core/llm_client.py, core/main.py]
tech_stack:
  added: []
  patterns: [firestore.Increment atomic counters, log-once unknown-model pattern]
key_files:
  created:
    - core/pricing.py
    - tests/test_pricing.py
    - tests/test_llm_usage_store.py
  modified:
    - memory/firestore_db.py
decisions:
  - "MODEL_PRICING hard-codes 4 entries (2 Gemini, 2 Haiku); free/open-weight models absent by design returning 0.0"
  - "LLMUsageStore uses firestore.Increment for all numeric fields — concurrent-call safe without read-modify-write"
  - "Tests mock google.cloud.firestore via sys.modules injection to run without GCP credentials in local dev"
metrics:
  duration_minutes: 4
  completed_date: "2026-05-18"
  tasks_completed: 2
  files_changed: 4
---

# Phase 14 Plan 01: Cost Metering Foundation Summary

## One-liner

Pricing lookup table + Firestore atomic usage store for per-model USD cost metering on every LLM call.

## What Was Built

### Task 1 — `core/pricing.py`

Created the pricing module with:

- `MODEL_PRICING` dict: 4 entries mapping model IDs to `{input, output}` USD-per-1M-token rates
  - `gemini-3-flash-preview` → $0.075 / $0.30
  - `gemini-2.5-flash` → $0.075 / $0.30
  - `claude-haiku-4-5` → $0.80 / $4.00
  - `claude-haiku-4-5-20251001` → $0.80 / $4.00
  - Free/open-weight models intentionally absent (return 0.0)
- `compute_cost(model, in_tokens, out_tokens) -> float`: looks up pricing, logs unknown models once (not on repeat), never raises
- 9 unit tests covering known prices, versioned aliases, free models, unknown models, fractional tokens, and log-once semantics

### Task 2 — `LLMUsageStore` in `memory/firestore_db.py`

Appended `LLMUsageStore` class after `IncidentStore` (before `_smoke_test`):

- Collection: `llm_usage`, one document per day (`YYYY-MM-DD`)
- `record(model, purpose, in_tokens, out_tokens, cost)`: writes atomically using `firestore.Increment` for all numeric fields (`total_in_tokens`, `total_out_tokens`, `total_cost_usd`, `call_count`, `{purpose}_calls`); swallows all exceptions
- `summary(period)`: returns dict for `"today"` (single doc) or `"month"` (aggregated); returns `{}` on error
- Follows exact `_make_firestore_client` + exception-swallowing patterns from existing stores
- 11 unit tests using sys.modules-level Firestore mock (no GCP credentials needed)

## Commits

| Task | Phase | Hash | Message |
|------|-------|------|---------|
| 1 | RED | 38a7c67 | test(14-01): add failing tests for core/pricing.py |
| 1 | GREEN | 223c1ba | feat(14-01): implement core/pricing.py with MODEL_PRICING and compute_cost() |
| 2 | RED | 6d249e1 | test(14-01): add failing tests for LLMUsageStore |
| 2 | GREEN | daa2995 | feat(14-01): add LLMUsageStore to memory/firestore_db.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Adapted test mocking strategy for local dev environment**

- **Found during:** Task 2 RED phase
- **Issue:** `google-cloud-firestore` not installed in local test environment; raw `from memory.firestore_db import LLMUsageStore` failed at collection time with `ModuleNotFoundError: No module named 'google.cloud'`
- **Fix:** Added `_install_firestore_mock()` at top of `tests/test_llm_usage_store.py` that injects a full `google.cloud.firestore` mock hierarchy into `sys.modules` before the module is imported. This is consistent with how existing tests in the project handle the same limitation.
- **Files modified:** `tests/test_llm_usage_store.py`
- **Commit:** 6d249e1

## TDD Gate Compliance

- RED gate: `test(14-01)` commits exist for both tasks (38a7c67, 6d249e1)
- GREEN gate: `feat(14-01)` commits exist after each RED (223c1ba, daa2995)
- REFACTOR: Not needed — code was clean from the start

## Known Stubs

None — both modules provide complete, working implementations.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. `core/pricing.py` is a pure in-memory computation module. `LLMUsageStore` writes to Firestore within the existing trust boundary (already covered by T-14-02/T-14-03 in the plan's threat register).

## Self-Check: PASSED

- `core/pricing.py` exists: FOUND
- `tests/test_pricing.py` exists: FOUND
- `tests/test_llm_usage_store.py` exists: FOUND
- `memory/firestore_db.py` contains `class LLMUsageStore`: FOUND at line 519
- Commit 38a7c67 exists: FOUND
- Commit 223c1ba exists: FOUND
- Commit 6d249e1 exists: FOUND
- Commit daa2995 exists: FOUND
