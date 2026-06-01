---
phase: 20-accountability-crons-recovery-briefing
reviewed: 2026-06-01T00:00:00Z
depth: deep
files_reviewed: 15
files_reviewed_list:
  - memory/firestore_db.py
  - core/tools.py
  - core/training_checkin.py
  - core/proactive_alerts.py
  - core/morning_briefing.py
  - core/weekly_training_review.py
  - core/scheduled_message.py
  - core/heartbeat.py
  - core/self_manifest.py
  - interfaces/_router.py
  - interfaces/web_server.py
  - mcp_tools/calendar_tool.py
  - scripts/bootstrap_shifu_crons.sh
  - prompts/weekly_training_review.md
  - prompts/morning_briefing.md
findings:
  critical: 2
  warning: 5
  info: 0
  total: 7
status: issues_found
verdict: fix-first
---

# Phase 20: Code Review Report

**Reviewed:** 2026-06-01
**Depth:** deep
**Files Reviewed:** 15
**Status:** issues_found
**Verdict:** fix-first — two blockers must be resolved before this ships to production

## Summary

Phase 20 adds the training check-in engine, recovery concern computation, weekly training
review, and associated Firestore stores. The architecture is sound: Pattern-C error
boundaries are applied consistently, OIDC is correctly wired to the new cron route, the
TTL enforcement on PendingPromptStore is solid, and the D-10 Garmin coverage matching
logic is correct for real-world Garmin startTimeLocal strings. The recovery concern
severity rules implement D-12 faithfully.

Two blockers prevent safe shipping: (1) the "Other — tell me" skip-reason path is
structurally broken — the user's free-text reply is never captured and the session orphans
until TTL; (2) the manual chat log path for multiple same-day workouts silently clobbers
data. Both are contained to the check-in module and have surgical fixes.

---

## Critical Issues

### CR-01: `awaiting_skipreason_other` free-text reply is never routed — session orphans

**Files:**
- `memory/firestore_db.py:1011`
- `core/training_checkin.py:841`
- `interfaces/_router.py:203`

**Issue:**
`handle_skipreason_callback` transitions the pending session to state
`awaiting_skipreason_other` when the user taps "Other — tell me" (line 841 of
`training_checkin.py`). The user is then expected to reply with free text. However,
`PendingPromptStore.get_open_note_session` (line 1011 of `firestore_db.py`) hard-filters
for `state == "awaiting_notes"` only. When the router calls `get_open_note_session` to
handle the reply-to, it returns `None` for `awaiting_skipreason_other` sessions (line 203
of `_router.py`). The free-text falls through to the brain as a regular message, the
training session is never logged, and the pending-prompts document lives until the 20h TTL
before it is garbage-collected.

End-to-end consequence: every user who taps "Other — tell me" gets a silent failure. Their
skip reason goes unrecorded and the check-in loop considers the session unresolved.

**Fix — two-part:**

Part 1 — extend `get_open_note_session` to also match `awaiting_skipreason_other`:

```python
# memory/firestore_db.py  ~line 1011
if data.get("state") not in ("awaiting_notes", "awaiting_skipreason_other"):
    continue
```

Part 2 — add a dedicated handler in `training_checkin.py` that is called from `attach_note`
(or a new router branch) when the session state is `awaiting_skipreason_other`. It should
log `completed=False, skipped_reason="other", notes=note_text` (NOT `completed=True`, see
CR-02 below for the latent defect):

```python
# core/training_checkin.py — replace the attach_note Firestore write for skipreason_other
async def attach_skipreason_other_note(orchestrator, user_id, session, note_text):
    session_key = session.get("session_key", "")
    if not session_key:
        return
    event_date = session.get("event_date", session_key.split("_")[0])
    tls = TrainingLogStore()
    tls.log_session(
        date=event_date,
        slot=session_key.split("_", 1)[1] if "_" in session_key else session_key,
        session_type=session.get("session_type"),
        planned=True,
        completed=False,          # skip, not done
        skipped_reason="other",
        notes=note_text,
        source="telegram",
    )
    pps = PendingPromptStore()
    pps.delete(session_key)
```

Dispatch from the router by checking `session.get("state")` before calling
`attach_note` vs `attach_skipreason_other_note`.

---

### CR-02: `slot="manual"` collision silently clobbers data when two workouts logged on the same day via chat

**File:** `core/tools.py:1404`

**Issue:**
`_handle_log_training` sets `kwargs["slot"] = "manual"` whenever the caller omits `slot`.
Firestore document ID becomes `{date}_manual`. If the user reports two workouts on the
same calendar day via free-form chat (e.g., morning run and evening gym), both calls
produce doc_id `{date}_manual`. The second call's `set(..., merge=True)` overwrites the
`session_type`, `rpe`, and `notes` fields of the first, silently destroying the first
record. There is no error, no log warning, and no acknowledgement to the user.

```python
# Reproduce: two sequential tool calls on the same date
log_training(date="2026-06-01", session_type="run",  completed=True, rpe=6)  # doc: 2026-06-01_manual
log_training(date="2026-06-01", session_type="gym",  completed=True, rpe=8)  # SAME doc: overwrites
# Firestore now shows session_type="gym", rpe=8. The run is gone.
```

**Fix — use a timestamp-based fallback slot instead of the literal string "manual":**

```python
# core/tools.py  ~line 1403
if "slot" not in kwargs or not kwargs.get("slot"):
    from datetime import datetime, timezone
    kwargs["slot"] = datetime.now(timezone.utc).strftime("manual_%H%M%S")
```

This produces unique doc IDs like `2026-06-01_manual_073042` and `2026-06-01_manual_193115`,
preserving both entries. Alternatively, use `uuid.uuid4().hex[:8]` for a shorter suffix.

---

## Warnings

### WR-01: `attach_note` writes `completed=True` unconditionally — latent defect once CR-01 is fixed

**File:** `core/training_checkin.py:877`

**Issue:**
`attach_note` unconditionally writes `completed=True, notes=note_text` (line 877). This
is correct for `awaiting_notes` sessions (RPE was logged first, workout done). However, if
CR-01 is fixed by routing `awaiting_skipreason_other` replies through `attach_note`, the
function would write `completed=True` for a workout the user explicitly told Klaus they
skipped. The fix for CR-01 already shows the correct approach (a separate handler), but
this code path needs to be kept separate even after the fix to avoid the latent bug
becoming active.

**Fix:** Ensure CR-01's fix dispatches to a separate `attach_skipreason_other_note`
function (as shown in CR-01). Do not reuse `attach_note` for `awaiting_skipreason_other`.

---

### WR-02: SQL built with f-string interpolation in `_gather_week_data`

**File:** `core/weekly_training_review.py:124`

**Issue:**
The biometrics query is constructed via f-string interpolation:

```python
sql = (
    "SELECT date, hrv_status, resting_hr, sleep_hours, sleep_score "
    "FROM daily_biometrics "
    f"WHERE date >= '{last_start_str}' AND date <= '{week_end.isoformat()}' "
    "ORDER BY date ASC"
)
```

Both `last_start_str` and `week_end.isoformat()` are computed from server-side date
arithmetic and are not user-controlled, so there is no practical injection vector today.
However, `query_health_database` accepts any string and the pattern normalises the wrong
lesson — other callers of `query_health_database` may introduce user-controlled input.
The `database_tool.py` security filter is a keyword-block rather than a full parse, so
injection via a date-shaped crafted value remains theoretically possible if this function
were ever generalised.

**Fix:** Use `psycopg2`'s parameter substitution via `query_health_database` directly, or
at minimum document the invariant that `last_start_str` and `week_end` are always
server-generated dates:

```python
# Preferred: pass params alongside the SQL
rows = query_health_database(
    "SELECT date, hrv_status, resting_hr, sleep_hours, sleep_score "
    "FROM daily_biometrics "
    "WHERE date >= %s AND date <= %s "
    "ORDER BY date ASC",
    params=(last_start_str, week_end.isoformat()),
)
```

If `query_health_database` does not support parameters today, extend its signature.

---

### WR-03: Dead code — `logged_by_slot` `source=="garmin"` check can never be true

**File:** `core/training_checkin.py:573`

**Issue:**
The `logged_by_slot` dict is keyed by calendar event ID (or fallback `YYYYMMDDHHmm`). The
silent Garmin sync (`_silent_garmin_sync`) writes training log entries using
`activity_id` as the slot (line 468), not the calendar event ID. Therefore,
`logged_by_slot.get(slot)` where `slot` is a calendar event ID can never return an entry
with `source == "garmin"`. The condition on line 573 is always bypassed:

```python
# This branch is dead — Garmin sync uses activity_id slot, not event id
if existing.get("rpe") is not None or existing.get("source") == "garmin":
```

The actual Garmin coverage detection works correctly via the live `_garmin_covers()`
call on line 578. The dead check is misleading to readers.

**Fix:** Remove the `or existing.get("source") == "garmin"` clause and update the comment:

```python
existing = logged_by_slot.get(slot)
if existing and existing.get("rpe") is not None:
    # Already logged with RPE (from a prior Telegram button tap) — covered.
    logger.debug("training_checkin: %s covered by existing log", slot)
    continue
```

---

### WR-04: Unused import in `PendingPromptStore()` factory function

**File:** `core/training_checkin.py:255`

**Issue:**
The `PendingPromptStore()` factory function imports `_pending_expiry` from
`memory.firestore_db` but never uses it:

```python
def PendingPromptStore():  # noqa: N802
    from memory.firestore_db import PendingPromptStore as _PPS
    from memory.firestore_db import _pending_expiry   # <-- imported but not used
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _PPS(project_id, database)
```

The local `_pending_expiry` shadow function is defined three lines later (line 261) and
is what the call sites use. The import is a residue from an earlier refactor.

**Fix:** Remove the unused import from the factory body:

```python
def PendingPromptStore():  # noqa: N802
    from memory.firestore_db import PendingPromptStore as _PPS
    project_id = os.environ["GCP_PROJECT_ID"]
    database = os.getenv("FIRESTORE_DATABASE", "(default)")
    return _PPS(project_id, database)
```

---

### WR-05: "A couple of items" copy is grammatically wrong for three or more prompts

**File:** `core/training_checkin.py:612`

**Issue:**
The intro message for multiple pending prompts reads:

```python
else:
    intro = f"Good evening, sir. A couple of items to log before the day closes."
```

"A couple" implies exactly two. A user with three simultaneous unlogged workouts (e.g.,
morning run, afternoon gym, evening basketball) would receive a factually incorrect intro
that subtly undermines the framing.

**Fix:**

```python
if count == 1:
    intro = "Good evening, sir. One item to close out the training log."
elif count == 2:
    intro = "Good evening, sir. A couple of items to log before the day closes."
else:
    intro = f"Good evening, sir. {count} items to log before the day closes."
```

---

_Reviewed: 2026-06-01_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

---

## Resolution (2026-06-01, commit d602745)

All blockers and the actionable warnings were fixed inline during execute-phase.

| ID | Status | Fix |
|----|--------|-----|
| CR-01 | ✅ Fixed | `get_open_note_session` now matches `awaiting_skipreason_other` too; router dispatches by state to a new `attach_skipreason_other_note` handler that records `completed=False, skipped_reason="other", notes=<text>`. The skip is now recorded and the free-text captured. +3 tests. |
| CR-02 | ✅ Fixed | `_handle_log_training` derives a unique `manual_%H%M%S` slot instead of the literal `manual`, so same-day chat logs no longer collide. +1 regression test. |
| WR-01 | ✅ Fixed | CR-01 fix uses a separate handler (`completed=False`), not `attach_note` (`completed=True`). |
| WR-03 | ✅ Fixed | Removed the dead `source=="garmin"` coverage clause. |
| WR-04 | ✅ Fixed | Removed the unused `_pending_expiry` import. |
| WR-05 | ✅ Fixed | Intro copy uses the actual count for ≥3 items. |
| WR-02 | ⏸ Accepted | SQL f-string in `weekly_training_review._gather_week_data` uses server-generated dates only — no injection vector. Left as-is; parameterizing `query_health_database` is a broader change for a future pass. |

**Post-fix verdict: ship-ready.** All affected test files pass per-file
(test_training_checkin 30, test_pending_prompt_store 17, test_tool_registration_phase20 14,
test_router_callback_query 15).
