---
phase: 23-block-benchmark-tracking
reviewed: 2026-06-06T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - memory/firestore_db.py
  - scripts/seed_training_blocks.py
  - core/tools.py
  - core/proactive_alerts.py
  - core/morning_briefing.py
  - core/weekly_training_review.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 23: Code Review Report

**Reviewed:** 2026-06-06T00:00:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the Phase 23 additions: `BlockStore` + `BenchmarkStore` + `get_week_num` + `UserProfileStore.current_block_id` in `memory/firestore_db.py`; the `seed_training_blocks.py` script; 6 new brain-direct block/benchmark tools in `core/tools.py`; the `_evaluate_benchmark_state` state machine + benchmark trigger in `core/proactive_alerts.py`; and the best-effort block gathers in `core/morning_briefing.py` and `core/weekly_training_review.py`.

The core architecture is sound. The D-01 date-range resolution contract, T-23-01 facet validation, the `benchmark_due` flag state machine, the HRV/ACWR validity gate, and the idempotency discipline (merge=True) are all correctly implemented. The multi-night re-prompt cadence (each evening in the 3-day window) is intentional per D-08 — not a bug.

Three warnings and two info items were found. No blockers. The most actionable fix is WR-01: the week-number divergence between the cron paths and `get_plan`.

---

## Warnings

### WR-01: `week_num` hard-codes `"2026-06-21"` anchor instead of reading `plan_start_date` from profile

**File:** `core/morning_briefing.py:286`, `core/weekly_training_review.py:206`

**Issue:** Both cron paths compute `week_num` by subtracting the hardcoded date `"2026-06-21"` from today, bypassing the `plan_start_date` field in the user profile and the `get_week_num()` helper in `firestore_db.py`. By contrast, `core/tools.py:1722–1723` (`_handle_get_plan`) correctly reads `profile.get("plan_start_date") or _PLAN_START_DEFAULT` and calls `get_week_num()`. If `plan_start_date` is ever updated in the profile (via `update_plan`), the morning briefing and weekly review will silently report the wrong week number while `get_plan` reports the right one — a silent divergence the user will notice without understanding why.

**Fix:**
```python
# In morning_briefing.py _gather_data, replace lines 286 and 295:
from memory.firestore_db import BlockStore, UserProfileStore, get_week_num
bs = BlockStore(...)
profile = UserProfileStore(...).load()
plan_start = profile.get("plan_start_date") or "2026-06-21"
block = bs.get_current()
if block:
    week_num = get_week_num(plan_start, today_iso)
    data["block"] = {
        ...
        "week_num": week_num,  # None if pre-cycle (get_week_num guards this)
        ...
    }
else:
    days_until = (date.fromisoformat(plan_start) - date.fromisoformat(today_iso)).days
    if days_until > 0:
        data["pre_cycle_countdown"] = days_until
```
Apply the same refactor to `weekly_training_review.py:206`.

---

### WR-02: `BlockStore.upsert` always overwrites `created_at` with `SERVER_TIMESTAMP`, including on re-runs

**File:** `memory/firestore_db.py:1625–1629`

**Issue:** The `upsert` method unconditionally stamps `"created_at": firestore.SERVER_TIMESTAMP` in the payload before calling `.set(..., merge=True)`. Because `merge=True` writes every field present in the payload, `created_at` is overwritten on every call — including `--force` re-seeds and any future programmatic upserts. The first-seed timestamp is permanently lost, making audit ("when was this block created?") unreliable.

**Fix:** Use a Firestore `SetOptions` partial merge or check existence before writing `created_at`. The lightest fix is to guard the field in `upsert`:
```python
def upsert(self, block: dict) -> None:
    doc_id = block["block_id"]
    doc_ref = self._col.document(doc_id)
    # Only stamp created_at when the document does not yet exist.
    snap = doc_ref.get()
    payload = {
        **block,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    if not snap.exists:
        payload["created_at"] = firestore.SERVER_TIMESTAMP
    try:
        doc_ref.set(payload, merge=True)
    except Exception:
        logger.error("BlockStore.upsert(%r) failed", doc_id, exc_info=True)
        raise
```
Alternatively, use `firestore.transforms.SERVER_TIMESTAMP` only once and store it in a separate initialization step. This is low-severity in a single-user system with a one-time seed, but correctness of `created_at` is expected by the schema docstring.

---

### WR-03: Block 4 race-week exclusion uses fragile substring match + hardcoded date

**File:** `core/proactive_alerts.py:115`, `core/proactive_alerts.py:187`

**Issue:** Both `_evaluate_benchmark_state` and the `set_benchmark_due` trigger in `run_proactive_alerts` exclude Block 4 from benchmarking using two guards:
```python
if "Race" in label or end_date == "2026-10-10":
```
This is brittle in two ways. (1) Any block whose label happens to contain the word "Race" (e.g., a hypothetical "Race-themed CrossFit Day") would be silently excluded. (2) If the Block 4 dates are ever corrected via `--force` re-seed, the hardcoded `"2026-10-10"` guard becomes stale — and if the label is also changed, the exclusion breaks entirely, causing Block 4 to receive an unwanted benchmark prompt.

**Fix:** Add a dedicated `skip_benchmark` boolean field to the block schema and check it instead of relying on label substring + hardcoded date:
```python
# In seed_training_blocks.py, Block 4:
{
    ...,
    "skip_benchmark": True,   # D-02: race week is never benchmarked
}

# In _evaluate_benchmark_state:
if block.get("skip_benchmark"):
    return None

# In run_proactive_alerts trigger section:
if _end and not current_block.get("skip_benchmark"):
    ...
```
This makes the intent explicit, survives label/date changes, and is readable without knowing the D-02 design decision.

---

## Info

### IN-01: Dead unreachable `return` statement inside `_handle_search_chat_history` — pre-existing

**File:** `core/tools.py:1237`

**Issue:** Line 1237 contains:
```python
    return json.dumps({"date": date, "logged": logged, "warnings": warnings})
```
This is 4-space indented, placing it inside `_handle_search_chat_history` as dead code after the `return json.dumps(result)` at line 1232. The variables `date`, `logged`, and `warnings` are not defined in that function's scope — if somehow reached, this would raise `NameError`. The line is unreachable in all normal execution paths, so it causes no runtime error today. This appears to be a leftover from a refactor of `_handle_log_training` (which uses those variable names) that was not cleaned up.

This is a pre-existing issue (present in the `diff_base` commit). Not introduced by Phase 23.

**Fix:** Delete line 1237 and the surrounding blank lines.

---

### IN-02: `BenchmarkStore.log_benchmark` does not validate the `date` parameter format

**File:** `memory/firestore_db.py:1730`

**Issue:** The `facet` parameter is validated against `_BENCHMARK_FACETS` (T-23-01), but `date` is used directly in the Firestore document ID (`doc_id = f"{date}_{facet}"`) with no format check. An LLM-supplied malformed date (e.g., `"2026/07/18"` with slashes, or `"18-07-2026"`) would either (a) produce a confusingly-named document ID or (b) be rejected by the Firestore SDK with a path-resolution error (slashes are path separators in Firestore). The SDK error is caught and returned as structured `{"error": ...}` JSON to the LLM, so this is not a data-loss risk, but it produces a confusing error message rather than the clear `ValueError` that facet validation gives.

**Fix:**
```python
from datetime import date as _date_type
try:
    _date_type.fromisoformat(date)
except ValueError:
    raise ValueError(
        f"Invalid date {date!r}. Expected YYYY-MM-DD format."
    )
```
Add this immediately after the facet validation in `log_benchmark`.

---

_Reviewed: 2026-06-06T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
