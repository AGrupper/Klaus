# Phase 28: Habits & Supplements - Research

**Researched:** 2026-06-26
**Domain:** Firestore HabitStore + streak computation + autonomous-tick extension + SLOT_SUPPLEMENTS rewire + React contribution grid
**Confidence:** HIGH (all findings grounded in the actual codebase; no external packages introduced)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Unified source of truth. HabitStore supplement check-offs feed the existing v4.0 supplement accountability. `core/proactive_alerts.py::SLOT_SUPPLEMENTS` rewired to read real check-off state.
- **D-02:** Slot→fueling-slot mapping under the hood. Simple time slot (Morning/Noon/Evening/Bedtime) maps to v4.0 fueling slot vocabulary. `SLOT_SUPPLEMENTS` dict superseded/fed by HabitStore items.
- **D-03:** Manual seeding — no seed data. Amit defines all habits/supplements himself.
- **D-04:** Two day-scheduling patterns only: daily OR specific weekdays. No every-N-days.
- **D-05:** Simple named time-of-day slots: Morning / Noon / Evening / Bedtime.
- **D-06:** One binary check-off per scheduled day. One slot per item.
- **D-07:** Tap toggles. Reversible. No undo toast for check-off itself.
- **D-08:** Check-off lives on both Today timeline and Habits tab.
- **D-09:** Dose editable at check-off; completion-log records dose actually taken.
- **D-10:** Pure reset. Any unmarked missed scheduled day resets streak to 0. No grace.
- **D-11:** Backfill previous day only.
- **D-12:** Miss confirmed at end of D+1 (pending-repair until then).
- **D-13:** Contribution grid has four states: `done` / `missed` / `not-scheduled` / `pending`.
- **D-14:** Rolling ~year (365 days), per-habit detail only. No all-habits overview grid.
- **D-15:** Per-slot salience nudge via existing autonomous tick. Reuse `CoachingTopicStore` for cross-cron dedup.
- **D-16:** Pass current streak into the gather for salience weighting.
- **D-17:** One nudge per item per day, max (CoachingTopicStore / OutreachLog topic_key per item-per-day).
- **D-18:** Bedtime-slot misses outside tick window (7-21) get no per-slot nudge; 21:30 alert covers pre-bed.
- **D-19:** Forward-only schedule edits. Effective-dated schedule. Past grid/streak unchanged.
- **D-20:** Hard delete + undo toast. No archive.
- **D-21:** `supplement` is just a `type` tag + dose. Same streak/check-off/grid/nudge as habits.

### Claude's Discretion
- `HabitStore` document/collection shape + daily completion-log structure.
- Effective-dated-schedule representation for D-19.
- Slot→fueling-slot mapping table mechanics (D-02) and how `SLOT_SUPPLEMENTS` is fed/superseded.
- DST-boundary streak handling + test fixtures proving it.
- Streak computation algorithm + four-state grid derivation (D-13).
- Undo-toast duration / soft-delete-then-hard-delete mechanics for D-20.
- react-query + optimistic-update + zustand wiring for check-offs.
- Repeat-suppression `topic_key` shape for D-17.
- All visual/layout/animation specifics → handled by `28-UI-SPEC.md`.

### Deferred Ideas (OUT OF SCOPE)
- Every-N-days / interval habit scheduling.
- Multiple slots per item / times-per-day targets.
- Skip/freeze/vacation mode + auto-grace streak allowance.
- Backfill older than yesterday.
- All-habits overview heatmap.
- Archive / habit history retention after delete.
- Stern supplement-specific accountability framing in nudges.
- Web Push delivery of nudges (Phase 29).
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HABIT-01 | Amit can define habits and supplements with name, type, optional dose, scheduled days, and time-of-day slot in Firestore `HabitStore` | HabitStore data model section covers document shape and CRUD patterns |
| HABIT-02 | Each item is checked off with a single tap (from the timeline or Habits tab), with dose shown as a label at check-off | Check-off toggle pattern + DoseEditSheet; mirrors Phase-27 TaskRow completion flow |
| HABIT-03 | Streaks count and break only on scheduled days, computed in Asia/Jerusalem local time with DST-boundary tests | Streak algorithm section; DST test fixtures; `_TZ = ZoneInfo("Asia/Jerusalem")` convention |
| HABIT-04 | The Habits tab shows a per-habit history grid (contribution-style) in the detail view | ContributionGrid section; pure-CSS/inline approach; no new charting library needed |
| HABIT-05 | Klaus can read habit/supplement adherence via tools, and the autonomous tick's Layer-0 gather includes today's pending check-offs | `_gather_habit_adherence` function design; `core/tools.py` `_HANDLERS` dispatch extension |
| TIME-06 | Habits and supplements due today appear on the timeline with one-tap check-off | HabitsBand mirrors DueTasksBand pattern exactly |
</phase_requirements>

---

## Summary

Phase 28 is the most technically novel phase in v5.0, but it is explicitly designed to mirror Phase 27 patterns at every integration point. The genuinely risky parts are:

1. **Streak math across DST boundaries.** Israel transitions to/from DST twice a year (last Sunday of October and last Friday before April 2). The streak algorithm must operate on local calendar dates, not UTC timestamps — already the codebase pattern (`datetime.now(_TZ).date().isoformat()`). The four-state grid derivation (done/missed/not-scheduled/pending) requires careful "yesterday-repair window" logic.

2. **Effective-dated schedules.** D-19 mandates that past grid/streak remain computed under the schedule that was active then. The recommended implementation is a `schedule_history` array of `{effective_from, days, slot}` objects appended (never mutated) on each forward edit. This is the simplest approach that preserves historical correctness without per-day snapshots.

3. **SLOT_SUPPLEMENTS rewire.** The `SLOT_SUPPLEMENTS` dict in `core/proactive_alerts.py` (lines 90-94) currently maps fueling-slot names to hardcoded supplement strings. The rewire makes this data-driven: at 21:30 alert time, fetch HabitStore supplements for the `pre-bed`-equivalent slot and check their completion status. The key insight is that `SLOT_SUPPLEMENTS` is consumed only by the `proactive_alert.md` prompt render path — the rewire is a targeted change at the `_gather_nutrition_data` / `_collect_detected_topics` callsites.

4. **Contribution grid without a new library.** The frontend has no charting library (verified: `package.json` has `@tanstack/react-query`, `lucide-react`, `zustand`, `react-router-dom`, `chrono-node` — no chart/heatmap lib). A 52×7 grid of `<div>` cells is the standard pure-CSS approach; each cell is 12px×12px with 2px gap (per UI-SPEC). No new dependency needed.

**Primary recommendation:** Model HabitStore as two Firestore collections (`habits/{habit_id}` for definitions, `habit_completions/{YYYY-MM-DD}/{habit_id}` for daily records), mirror every Phase-27 CRUD/auth/react-query/dedup pattern exactly, and introduce a pure-Python `compute_streak` function that is independently testable with DST fixtures.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Habit CRUD (create/edit/delete) | API / Backend (FastAPI `/api/*`) | Firestore `HabitStore` | Same pattern as TaskStore; session-cookie auth |
| Daily check-off / toggle | API / Backend | Firestore completion-log | PATCH endpoint; idempotent write keyed on (date, habit_id) |
| Streak computation | API / Backend (Python) | — | Pure function over Firestore data; must be DST-safe; not in the browser |
| Four-state grid derivation | API / Backend (Python) | — | Derived from completion-log + schedule-history; compute server-side |
| Habits tab / HabitsPage | Browser / Client (React/TS) | — | Route `/habits` (currently ComingSoon placeholder) |
| Today timeline HabitsBand | Browser / Client (React/TS) | — | Extends `TimelineDay.tsx`; mirrors `DueTasksBand.tsx` |
| GlanceRail streaks card | Browser / Client (React/TS) | — | Desktop only; extends `GlanceRail.tsx` |
| Contribution grid render | Browser / Client (React/TS) | — | Pure CSS 52×7 grid; data from `/api/habits/{id}/history` |
| Autonomous Layer-0 gather | API / Backend (Cloud Tasks request) | — | `_gather_habit_adherence()` added to `gather_situation()` thread pool |
| SLOT_SUPPLEMENTS rewire | API / Backend (`core/proactive_alerts.py`) | `HabitStore` (Firestore) | Data-driven supplement lookup replacing hardcoded dict |
| Klaus native tools | API / Backend (`core/tools.py`) | `HabitStore` | `_HANDLERS` dispatch following existing tool-schema convention |

---

## Standard Stack

### Core — backend

All existing; no new packages.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `google-cloud-firestore` | (existing) | `HabitStore` — definitions + completion-log | All other stores; `_jsonsafe_doc` pattern established |
| `zoneinfo` (stdlib) | Python 3.9+ | `ZoneInfo("Asia/Jerusalem")` for streak dates | Used everywhere: `_TZ = ZoneInfo("Asia/Jerusalem")` |
| FastAPI | (existing) | `/api/habits/*` CRUD + check-off endpoints | Same server; HUB-04 invariant: don't break existing routes |
| `google.cloud.firestore.Increment` / `ArrayUnion` | (existing) | Atomic writes in CoachingTopicStore / OutreachLogStore | Same pattern for dedup writes |

### Core — frontend

All existing; no new packages.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@tanstack/react-query` v5 | ^5.101.0 | `useHabits`, `useCheckOff`, `useHabitHistory` hooks | Same as `useTasks`, `useToday` |
| `zustand` | ^5.0.14 | `undoStore` slice for habit delete undo | Same `undoStore` used by tasks |
| `lucide-react` | ^1.18.0 | Icons: `Circle`, `CheckCircle2`, `MoreHorizontal` | Already used in `TaskRow.tsx`, `DueTasksBand.tsx` |
| `react-router-dom` | ^7.17.0 | `/habits` route (replace `ComingSoon`) | Already wired in `App.tsx` line 156 |
| Tailwind CSS | ^4.3.1 | Responsive layout, `md:hidden` guards | Design system locked; no new tokens |

### Contribution Grid — no new library

The GitHub-style contribution grid is a 52×7 grid of styled `<div>` elements. Each cell is `12px × 12px`, `borderRadius: 2px`, `gap: 2px`. Four fill colors from `tokens.ts`. This is standard practice for personal dashboards at this scale — no charting library needed and no new npm dependency is introduced. [VERIFIED: frontend/package.json shows no heatmap/chart lib is present; design confirmed in 28-UI-SPEC.md]

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure-CSS 52×7 grid | `react-calendar-heatmap` | Extra npm dep, not needed; pure CSS is 30 lines |
| Per-day completion subcollection | Single doc with `completions: dict` | Subcollection scales; dict → 1MB Firestore doc limit risk at year+ of data |
| Effective-dated schedule revisions list | Per-day snapshot | Snapshot = O(365) writes per schedule edit; revision list = 1 write |

**Installation:** None — no new packages.

---

## Package Legitimacy Audit

No external packages are introduced in this phase. All backend and frontend libraries are existing dependencies already installed and verified in the live deployment.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
[Habits Tab / Today Timeline] ──PATCH──► [FastAPI /api/habits/*]
         │                                        │
         │ (react-query optimistic update)         │ require_hub_session (P26)
         │                                         ▼
[ContributionGrid  ◄──GET /api/habits/{id}/history─── HabitStore (Firestore)
 HabitsBand                                        │     habits/{id}
 GlanceRail]                                       │     habit_completions/{date}/{id}
                                                   │
                                        ┌──────────┘
                                        │ read at gather time
                                        ▼
[autonomous.py gather_situation()] ── _gather_habit_adherence() ──► tick-brain triage
[proactive_alerts.py]              ── _get_supplement_checkoffs() ──► 21:30 alert compose
[core/tools.py _HANDLERS]          ── get_habit_adherence tool ──► brain on-demand read
```

### Recommended Project Structure

```
memory/
└── firestore_db.py         # Add HabitStore class (two collections: habits + habit_completions)
core/
├── autonomous.py           # Add _gather_habit_adherence() to gather_situation thread pool
├── proactive_alerts.py     # Rewire SLOT_SUPPLEMENTS read to HabitStore; add helper
└── tools.py                # Add get_habit_adherence + list_pending_habits tool schemas + handlers
interfaces/
└── web_server.py           # Add /api/habits/* routes (CRUD + check-off + history)
frontend/src/
├── api/habits.ts           # apiFetch wrappers for habit endpoints
├── hooks/useHabits.ts      # react-query hooks: useHabits, useCheckOff, useHabitHistory
├── components/
│   ├── habits/
│   │   ├── HabitsPage.tsx
│   │   ├── HabitRow.tsx
│   │   ├── HabitDetailView.tsx
│   │   ├── HabitCreateEditSheet.tsx
│   │   ├── DoseEditSheet.tsx
│   │   └── ContributionGrid.tsx
│   ├── timeline/
│   │   └── HabitsBand.tsx
│   └── layout/
│       └── GlanceRail.tsx  # (modify to add Habits card)
└── store/
    └── undoStore.ts        # (modify to add habit slice alongside task slice)
tests/
└── test_habit_store.py     # DST streak fixtures, completion-log, four-state grid
```

---

## Pattern 1: HabitStore Data Model

**What:** Two-collection layout mirroring MealStore's date-partitioned design.

**Collection 1 — Definitions:** `habits/{habit_id}`

```python
# Source: memory/firestore_db.py — MealStore.upsert + TaskStore.create conventions
{
    "id": "uuid4hex",                    # doc ID (same as TaskStore)
    "name": "Creatine",
    "type": "supplement",                # "habit" | "supplement"
    "dose": "5g",                        # None for type=="habit"
    "slot": "Evening",                   # "Morning"|"Noon"|"Evening"|"Bedtime"
    "schedule_history": [                # D-19: effective-dated schedule revisions
        {
            "effective_from": "2026-06-26",  # YYYY-MM-DD plain string — NOT a Timestamp
            "days": "daily",                 # "daily" | [0,1,2,3,4] (Mon=0 weekday ints)
        }
    ],
    "status": "active",                  # "active" | "completing" (soft-delete)
    "created_at": "2026-06-26T...",      # ISO-8601 UTC plain string (NOT SERVER_TIMESTAMP)
    "updated_at": SERVER_TIMESTAMP,      # stripped by _jsonsafe_doc before json.dumps
}
```

**Collection 2 — Daily completion log:** `habit_completions/{YYYY-MM-DD}/{habit_id}`

```python
# Source: MealStore path pattern ({date}/{source_id}) adapted for habits
{
    "habit_id": "uuid4hex",
    "date": "2026-06-26",               # YYYY-MM-DD Asia/Jerusalem (plain string)
    "done": True,
    "dose_taken": "4g",                 # D-09: dose actually taken; None for habits
    "logged_at": "2026-06-26T18:00:...",# ISO-8601 UTC plain string
    "updated_at": SERVER_TIMESTAMP,      # stripped by _jsonsafe_doc
}
```

**Key design decisions (Claude's Discretion):**

- `schedule_history` is an append-only list; a new edit adds an entry with `effective_from = today`. Past entries are never mutated. The `compute_streak` function selects the applicable schedule revision for each calendar date by finding the latest `effective_from <= target_date`.
- `days` field in a schedule revision: `"daily"` (string) or a list of Python weekday integers `[0,1,2,3,4,5,6]` where Mon=0 (Python `datetime.date.weekday()` convention). This is consistent with the `_advance_once` recurrence engine in `firestore_db.py` (lines 2415-2454) which already uses Python weekday math.
- `due_date`/`created_at`/`date` fields are **always plain strings** — same T-27-IV invariant as TaskStore (line 2519): "due_date/due_time are ALWAYS stored as plain strings — never as Firestore Timestamps."
- Subcollection for completions (not a dict field in the definition doc) — avoids the 1MB Firestore document limit for long-lived habits.

**`_jsonsafe_doc` usage:** All reads via `HabitStore` must apply `_jsonsafe_doc` to strip `updated_at` (`DatetimeWithNanoseconds`) before json-encoding. The helper is defined at `memory/firestore_db.py` line 885 and is already used by TrainingLogStore, StrengthSessionStore, RunDetailStore, TaskStore.

---

## Pattern 2: Streak Computation Algorithm

**What:** Pure function over the completion-log + schedule-history. Takes a list of completion records and schedule revisions; returns `(current_streak, grid_cells)`.

**Algorithm (D-10..D-13, DST-safe):**

```python
# Source: derived from D-10/D-11/D-12/D-13 + Asia/Jerusalem pattern from
# autonomous.py _gather_journal_digest (lines 314-327):
# "d = (now.astimezone(_TZ).date() - timedelta(days=days_back)).isoformat()"

from zoneinfo import ZoneInfo
from datetime import date, timedelta

_TZ = ZoneInfo("Asia/Jerusalem")

def _is_scheduled(target_date: date, schedule_history: list[dict]) -> bool:
    """Return True if target_date falls on a scheduled day under the active revision."""
    # Find latest revision whose effective_from <= target_date
    applicable = None
    for rev in sorted(schedule_history, key=lambda r: r["effective_from"]):
        if rev["effective_from"] <= target_date.isoformat():
            applicable = rev
    if applicable is None:
        return False  # No schedule defined yet for this date — not scheduled
    days = applicable["days"]
    if days == "daily":
        return True
    # days is a list of Python weekday ints (Mon=0)
    return target_date.weekday() in days


def compute_streak_and_grid(
    habit_id: str,
    schedule_history: list[dict],
    completions: dict[str, dict],  # keyed by YYYY-MM-DD
    today: date,
    window_days: int = 365,
) -> dict:
    """
    Returns:
      {
        "streak": int,                  # current streak count
        "grid": [                       # one entry per day, newest last
          {"date": "YYYY-MM-DD", "state": "done"|"missed"|"not-scheduled"|"pending"},
          ...
        ]
      }

    DST safety: all date arithmetic uses datetime.date objects (no time component);
    ZoneInfo("Asia/Jerusalem") applied only when converting 'now' to a local date
    before calling this function. This function receives a bare date object and
    never deals with wall-clock hours, so DST transitions are transparent.
    """
    yesterday = today - timedelta(days=1)
    grid = []

    for offset in range(window_days - 1, -1, -1):  # oldest to newest
        d = today - timedelta(days=offset)
        d_iso = d.isoformat()
        scheduled = _is_scheduled(d, schedule_history)

        if not scheduled:
            state = "not-scheduled"
        elif d > today:
            state = "not-scheduled"  # future — should not occur in window
        elif d == today:
            if d_iso in completions:
                state = "done"
            else:
                state = "pending"
        elif d == yesterday:
            # D-12: yesterday is still pending-repair until today ends
            if d_iso in completions:
                state = "done"
            else:
                state = "pending"  # still in backfill window
        else:
            # d < yesterday: miss is confirmed
            if d_iso in completions:
                state = "done"
            else:
                state = "missed"

        grid.append({"date": d_iso, "state": state})

    # Streak: walk grid backward from today; count consecutive "done" on scheduled days.
    # Pure reset (D-10): any "missed" (confirmed) terminates streak at 0.
    streak = 0
    for cell in reversed(grid):
        if cell["state"] == "done":
            streak += 1
        elif cell["state"] == "missed":
            break  # pure reset: stop counting
        # "not-scheduled" and "pending" are neutral — do not break streak
        # but "pending" for today/yesterday doesn't increment until confirmed done.
        elif cell["state"] == "pending":
            pass  # neutral; don't increment but don't break

    return {"streak": streak, "grid": grid}
```

**DST test fixtures required by HABIT-03:**

Israel DST transitions:
- **Spring-forward (ILST→IDT):** Last Friday before April 2. Clock jumps from 02:00 → 03:00. A UTC midnight that maps to 2:00 AM local on March 28 2026 would appear as March 27 local post-transition — but since all date logic uses `datetime.date` objects (no hour component), this is a non-issue for streak math. The test should verify that a habit scheduled for the Friday of spring-forward is counted correctly.
- **Fall-back (IDT→ILST):** Last Sunday of October. Clock falls back from 02:00 → 01:00. Again, `datetime.date` is immune. Test: a habit due on the fall-back Sunday still registers as exactly one day.

```python
# Example DST fixture (verify HABIT-03 mandate):
# Spring-forward 2026: March 27 (last Friday before April 2)
def test_streak_survives_spring_forward_dst():
    """Streak does not break across Israel's March DST transition."""
    from datetime import date
    schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
    completions = {
        "2026-03-26": {"done": True},
        "2026-03-27": {"done": True},  # Spring-forward day
        "2026-03-28": {"done": True},
    }
    result = compute_streak_and_grid(
        "h1", schedule, completions, today=date(2026, 3, 28)
    )
    assert result["streak"] >= 3  # Should not reset at DST boundary

# Fall-back 2026: October 25
def test_streak_survives_fall_back_dst():
    schedule = [{"effective_from": "2026-01-01", "days": "daily"}]
    completions = {
        "2026-10-24": {"done": True},
        "2026-10-25": {"done": True},  # Fall-back day
        "2026-10-26": {"done": True},
    }
    result = compute_streak_and_grid(
        "h1", schedule, completions, today=date(2026, 10, 26)
    )
    assert result["streak"] >= 3
```

**Why `datetime.date` is DST-safe:** Israel DST transitions affect the wall-clock hour, not the calendar date. A streak that spans a DST boundary always has one calendar date per solar day. `datetime.date` objects carry no time component and no tz info — the transition is invisible. The only risk is when converting a UTC timestamp to a local date ("what day is it in Jerusalem?"), which is already handled at the call site via `datetime.now(_TZ).date()`.

---

## Pattern 3: Autonomous Layer-0 Gather Extension

**What:** Add `_gather_habit_adherence()` to the thread pool in `gather_situation()`, following the existing pattern from `_gather_native_overdue` (lines 236-256 of `autonomous.py`).

**How the situation key threads through (Phase-27 `ticktick_overdue` → TaskStore template):**

Phase 27 replaced the TickTick gather with `_gather_native_overdue` (line 236). The key insight from the code (lines 443-461): each gather function is registered as a lambda under a situation key in the `jobs` dict. The tick-brain and compose layer receive the situation snapshot JSON, and the triage prompt references situation keys by name. To add habit adherence:

1. Add `_gather_habit_adherence()` — returns `list[dict]` of pending habits with streak info.
2. Add `"habit_pending"` key to the `jobs` dict (line 443-461 pattern).
3. Update `_is_empty_signals()` (lines 172-205): add `if situation.get("habit_pending"): return False` — pending items are a valid tick trigger (D-15: per-slot salience).
4. Update `_build_triage_prompt()` (lines 515-563): include `habit_pending` in the `snap` dict passed to tick-brain JSON.
5. Update `_compose_layer2()` (lines 663-713): include `habit_pending` in `snap_summary`.

**Dedup (D-17) with CoachingTopicStore:** Topic key shape for per-item-per-day suppression:

```python
topic_key = f"habit-nudge:{habit_id}:{today_iso}"
# Example: "habit-nudge:abc123def456:2026-06-26"
# CoachingTopicStore.has_topic(today_iso, topic_key) → True → skip this item
# CoachingTopicStore.add_topic(today_iso, topic_key) → written after send success
```

**`_gather_habit_adherence` function design:**

```python
def _gather_habit_adherence(now: datetime, project_id: str, database: str) -> list[dict]:
    """Layer-0 gather: today's pending habits/supplements with streak.

    Returns list of pending items: [
      {"habit_id", "name", "type", "slot", "streak", "dose"},
      ...
    ]
    Empty list on any error (sentinel pattern matches all other _gather_* functions).
    """
    try:
        from memory.firestore_db import HabitStore
        from zoneinfo import ZoneInfo
        today_iso = datetime.now(ZoneInfo("Asia/Jerusalem")).date().isoformat()
        store = HabitStore(project_id=project_id, database=database)
        pending = store.get_pending_today(today_iso)
        return pending
    except Exception:
        logger.warning("autonomous: habit_adherence gather failed", exc_info=True)
        return []
```

**`HabitStore.get_pending_today(today_iso)`** returns active habits scheduled for today that have no completion record for today. Each result includes current streak (computed). The function is also used by the native read tool (HABIT-05).

---

## Pattern 4: SLOT_SUPPLEMENTS Rewire

**What:** Replace the hardcoded `SLOT_SUPPLEMENTS` dict at `core/proactive_alerts.py` lines 90-94 with a data-driven read from `HabitStore` at alert time.

**Current SLOT_SUPPLEMENTS (lines 86-94):**

```python
SLOT_SUPPLEMENTS: dict[str, str] = {
    "post-am-run": "D3+K2/Omega-3",
    "pm-post-lift": "Creatine",
    "pre-bed": "Mg-Glycinate/Zinc/Copper",
}
```

This dict is currently referenced in:
- `tests/test_proactive_alerts.py` line 714 (test asserts it exists with correct mappings)
- `prompts/proactive_alert.md` lines 151-153 (prompt hardcodes the supplement names inline — NOT reading from the dict)

**Key insight:** `SLOT_SUPPLEMENTS` is used only in the test (structure check) and implicitly by the prompt (which hardcodes supplement names directly). The actual miss-detection logic in `_detect_slot_misses` (lines 366-432) only detects WHICH fueling slots were missed — it never looks up which supplements belong there. The supplement names appear only in the prompt text, not in code logic.

**Rewire strategy (D-01/D-02 — simplest approach):**

The 21:30 alert path (`run_proactive_alerts`) already calls `_gather_nutrition_data` which detects slot misses. The rewire adds a second read: after detecting slot misses, query HabitStore for supplements that (a) are active, (b) are scheduled for today, and (c) map to the detected missed fueling slot.

**Slot → fueling-slot mapping (D-02 — Claude's Discretion):**

```python
# Mapping from habit simple slot → v4.0 fueling slot vocabulary
# "Morning" post-run supplements → post-am-run
# "Evening"/"Noon" post-lift supplements → pm-post-lift
# "Bedtime" supplements → pre-bed
# NOTE: This mapping is approximate because the simple slots (Morning/Noon/Evening/Bedtime)
# don't perfectly align with the anchor-relative fueling slots (post-am-run depends on
# when the AM run finished). The recommended approach:
# - "Bedtime" → "pre-bed" (unambiguous)
# - For missed "post-am-run": check if any active supplement has slot "Morning"
# - For missed "pm-post-lift": check if any active supplement has slot "Evening" or "Noon"
_HABIT_SLOT_TO_FUELING: dict[str, list[str]] = {
    "Morning":  ["post-am-run"],
    "Noon":     ["pm-post-lift"],
    "Evening":  ["pm-post-lift"],
    "Bedtime":  ["pre-bed"],
}
```

**Where the rewire happens in `run_proactive_alerts`:**

After `nutrition_data = _gather_nutrition_data(today_iso, ...)` (line 868), add:

```python
# D-01/D-02: query HabitStore for supplement check-off state
# Enrich slot_misses with actual supplement names from HabitStore
try:
    supplement_status = _get_supplement_checkoffs(today_iso)
    alerts_context["supplement_checkoffs"] = supplement_status
except Exception:
    logger.warning("proactive_alerts: supplement checkoff gather failed", exc_info=True)
```

The `prompts/proactive_alert.md` prompt is then updated to use `supplement_checkoffs` to name specific supplements by their real HabitStore name (e.g. "you haven't logged your Creatine") instead of hardcoded strings.

**Backward compatibility:** Keep `SLOT_SUPPLEMENTS` as a fallback dict so the existing test (`test_slot_supplements_constant_exists`) continues to pass. The fallback is used when `HabitStore` returns no supplements (i.e., before Amit has defined any). The prompt template has fallback language for when no HabitStore data is available.

**D-15 cross-cron dedup (habit nudge vs 21:30 alert):** Both paths write to `CoachingTopicStore`. The habit nudge writes `"habit-nudge:{habit_id}:{date}"`. The 21:30 alert writes `"fueling-miss:pre-bed"` (existing pattern, `_collect_detected_topics` lines 653-682). These keys are distinct, so they do not block each other at the `has_topic` gate — correct behavior per D-15 (they "complement cleanly" per the design). The cross-cron dedup prevents double-nag of the SAME topic from two different crons, not different-topic coverage of the same supplement.

---

## Pattern 5: API Endpoints (`/api/habits/*`)

Follows Phase-26/27 `require_hub_session` + `apiFetch` pattern exactly.

```
GET    /api/habits                      → list active habits + today's completions
POST   /api/habits                      → create habit
PATCH  /api/habits/{id}                 → edit definition (forward-only schedule D-19)
DELETE /api/habits/{id}                 → soft-delete (status="completing"); hard-delete after undo toast
POST   /api/habits/{id}/checkin         → log/toggle completion for a date (defaults to today)
GET    /api/habits/{id}/history         → 365-day grid data: [{date, state}]
GET    /api/habits/summary              → {pending_today: N, streak_leaders: [...]} for GlanceRail
```

**D-07 toggle:** `POST /api/habits/{id}/checkin` accepts `{"date": "YYYY-MM-DD", "done": bool, "dose_taken": "..."}`. If `done=False` for a date that has a completion record, the record is deleted (un-check). Idempotent: checking already-checked returns 200.

**D-11 backfill gate:** The endpoint enforces that `date` must be today or yesterday (Asia/Jerusalem local date). Dates older than yesterday return 400.

**D-20 delete flow (mirrors TaskStore soft_delete + UndoToast):**

```
PATCH /api/habits/{id} {"status": "completing"}   # soft-delete
→ frontend shows undo toast (4s timer)
→ on undo: PATCH /api/habits/{id} {"status": "active"}
→ on expiry: DELETE /api/habits/{id}              # hard-delete + subcollection cleanup
```

The `DELETE` route hard-deletes both the definition doc and all `habit_completions/{date}/{habit_id}` subcollection docs (D-20: history deleted with the habit). Firestore subcollection recursive delete uses the Admin SDK `delete_collection` or an iterative approach.

---

## Pattern 6: ContributionGrid (React)

**No new library.** Pure `<div>` grid with inline styles from `tokens.ts`.

```tsx
// Source: 28-UI-SPEC.md § ContributionGrid + GitHub contribution grid convention
// 52 columns (weeks), 7 rows (Mon=0 top to Sun=6 bottom per Python weekday convention)
// Each cell: 12px × 12px, borderRadius: 2px, gap: 2px (named exception in UI-SPEC)

const CELL_COLORS = {
  done:          '#6366F1',  // accent
  missed:        '#3A1A1A',  // muted destructive tint
  'not-scheduled': '#1F1F1F', // skeleton
  pending:       '#2A2A2A',  // border
} as const

function ContributionGrid({ cells }: { cells: GridCell[] }) {
  // cells: array of 365 {date, state} objects, oldest-first
  // Arrange into 52 columns × 7 rows
  return (
    <div
      role="grid"
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(52, 12px)',
        gridTemplateRows: 'repeat(7, 12px)',
        gap: '2px',
        overflowX: 'auto', // phone: show ~12 weeks by default
      }}
    >
      {cells.map(cell => (
        <div
          key={cell.date}
          role="gridcell"
          aria-label={`${cell.date}: ${cell.state}`}
          style={{
            width: 12, height: 12,
            borderRadius: 2,
            backgroundColor: CELL_COLORS[cell.state],
          }}
        />
      ))}
    </div>
  )
}
```

**Grid fill direction:** Oldest cell top-left (week 0, Mon row), newest bottom-right (week 51, Sun row) — matches GitHub convention and renders correctly with a flat `cells` array ordered oldest-first.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-cron dedup (D-15/D-17) | Custom dedup logic | `CoachingTopicStore.has_topic` / `add_topic` | Already exists; handles ArrayUnion atomicity + SERVER_TIMESTAMP pitfall |
| Firestore JSON serialization | Custom datetime serializer | `_jsonsafe_doc` (line 885 of firestore_db.py) | Already handles `DatetimeWithNanoseconds` for all stores |
| Optimistic check-off update | Custom cache mutation | react-query `useMutation` + `queryClient.setQueryData` | Phase-27 `useCompleteTask` pattern in `hooks/useTasks.ts` |
| Undo toast | Custom toast + timer | `useUndoStore` zustand slice | Already exists for tasks; extend with `type: 'habit'` discriminator |
| Asia/Jerusalem date | Custom tz math | `datetime.now(ZoneInfo("Asia/Jerusalem")).date()` | Universal pattern in all crons/stores |
| Firestore concurrent writes | Lock / transaction | `firestore.ArrayUnion` / `merge=True` | Existing pattern in OutreachLogStore, CoachingTopicStore |

**Key insight:** Every problem in Phase 28 has an existing solution in the codebase. The phase's value comes from wiring, not inventing.

---

## Common Pitfalls

### Pitfall 1: `updated_at` in Completion Log Breaks `json.dumps`

**What goes wrong:** A completion-log doc read from Firestore has `updated_at: DatetimeWithNanoseconds`. If passed to `json.dumps` (e.g., in a `/api/*` response or an autonomous tick `snap_summary`), it raises `TypeError: Object of type DatetimeWithNanoseconds is not JSON serializable`.

**Why it happens:** `firestore.SERVER_TIMESTAMP` writes back as `DatetimeWithNanoseconds`. The same bug has bitten MealStore (fixed 2026-05-31), TrainingLogStore (v4.0), StrengthSessionStore, RunDetailStore.

**How to avoid:** Apply `_jsonsafe_doc` to every Firestore doc read. All `HabitStore` read methods must call `_jsonsafe_doc(snap.to_dict() or {})`.

**Warning signs:** `TypeError` in API route logs; `"updated_at"` appearing as a non-string in response JSON.

---

### Pitfall 2: `style={{ display }}` on Responsive Wrappers Leaks to Wrong Breakpoint

**What goes wrong:** Using `style={{ display: 'none' }}` or `style={{ display: 'block' }}` on a wrapper element overrides Tailwind's `md:hidden` / `hidden md:block` classes. Phone-only UI (FAB, HabitsBand mobile layout) leaks to desktop.

**Why it happens:** Inline styles have higher specificity than Tailwind utility classes. This bit Phase 27 UAT 4 times (FAB, header, BottomTabs, GlanceRail).

**How to avoid:** All responsive show/hide is driven by Tailwind classes (`<div className="md:hidden">`) or by a wrapper with no inline `display` property. This is a stated invariant in `28-UI-SPEC.md` (§ Responsive Layout, bottom).

**Warning signs:** HabitsBand or FAB visible on desktop; GlanceRail Habits card hidden on phone.

---

### Pitfall 3: iOS Bottom Sheet Keyboard / z-index Traps

**What goes wrong:** HabitCreateEditSheet, DoseEditSheet — any bottom sheet on iPhone Safari.

**Why it happens:** `position: fixed` doesn't track the iOS soft keyboard (layout viewport). Sheet gets pushed off-screen or overlapped. `z-index` below 100 (BottomTabs) makes sheet appear behind navigation. `autoFocus` triggers layout pan mid-slide animation. Blur-before-click eats submit.

**How to avoid:** Four mandatory patterns from `28-UI-SPEC.md` (§ Bottom Sheet iOS Traps):
1. Scrim z:190, sheet z:191 (above BottomTabs z:100).
2. No inline `display` on wrappers.
3. `useVisualViewport` hook (already in `frontend/src/hooks/useVisualViewport.ts`) for keyboard tracking.
4. `onMouseDown={(e) => e.preventDefault()}` on dismiss buttons.
5. No `autoFocus` on phone inputs.

**Warning signs:** Sheet disappears behind BottomTabs; text input causes sheet to jump left; "Save dose" button doesn't respond on first tap.

---

### Pitfall 4: SERVER_TIMESTAMP Inside ArrayUnion Breaks Dedup

**What goes wrong:** `CoachingTopicStore.add_topic` and `OutreachLogStore.append` use `firestore.ArrayUnion`. If any dict element inside the array contains `firestore.SERVER_TIMESTAMP`, ArrayUnion's deep-equality check treats each sentinel as a distinct object → duplicates accumulate, defeating dedup.

**Why it happens:** Each `SERVER_TIMESTAMP` sentinel is a freshly allocated Python object; two identical logical entries are not `==`.

**How to avoid:** Topic keys must be plain strings (`"habit-nudge:abc123:2026-06-26"`). Completion log entries written to `OutreachLogStore` must use static ISO strings for timestamps, not `SERVER_TIMESTAMP`. The class docstring for `OutreachLogStore` (line 1702) calls this out explicitly as "NOTE 2".

**Warning signs:** Coaching topic fires multiple times per day for the same habit; outreach log grows unbounded.

---

### Pitfall 5: Full pytest Suite Segfaults

**What goes wrong:** `pytest tests/` (full suite, single process) segfaults due to grpc/protobuf GC interaction (Python 3.13). Verified in STATE.md.

**How to avoid:** Run pytest per-file. The 1153+ passing baseline must hold after Phase 28. New tests go in `tests/test_habit_store.py`, `tests/test_habits_api.py` — run individually.

**Warning signs:** pytest process exits with signal 11 when running the full suite.

---

### Pitfall 6: Streak "Pending" State Should Not Break Streak

**What goes wrong:** Treating today's "pending" (not yet checked off) as a "miss" would zero out the streak at the end of every day, even for habits that will be completed later.

**Why it happens:** Naive implementation: `if not done: streak = 0`.

**How to avoid:** The `compute_streak_and_grid` algorithm above only terminates streak counting on `state == "missed"` (confirmed miss: past yesterday, no completion). `pending` (today + yesterday in repair window) is neutral — streak counting skips past it without incrementing or breaking.

**Warning signs:** Streak shows 0 every morning until the day's habit is checked off.

---

### Pitfall 7: Schedule Edit Retroactively Rewrites Grid

**What goes wrong:** If a habit's `days` field is updated in-place (not via `schedule_history` append), past grid cells are recomputed under the NEW schedule, turning previously-scheduled days into `not-scheduled` and erasing historical misses.

**Why it happens:** The streak algorithm reads `schedule_history` to determine scheduledness for each date. If there is only one revision and it is mutated, all past dates see the new schedule.

**How to avoid:** D-19 mandates forward-only edits. The API PATCH handler for schedule changes must append a new `{effective_from: today, days: new_days}` entry to `schedule_history` rather than overwriting `schedule_history[0].days`. The `effective_from` field gates which schedule applies to each date.

**Warning signs:** A habit's grid shows `not-scheduled` for days it was previously scheduled; historical streaks change retroactively.

---

### Pitfall 8: Bedtime Supplement Double-Nag from Two Channels

**What goes wrong:** The 21:30 proactive alert flags `pre-bed` supplement miss. The autonomous tick (if it happened to run at 20:40 or 21:00) also nudges for the same item. Amit receives two messages about the same supplement.

**Why it happens:** D-18 notes that Bedtime/`pre-bed` misses fall outside the tick window (7-21), so "the two complement cleanly" — but the 21:00 tick IS within window and covers pre-bed supplements if the HabitStore supplement has `slot == "Bedtime"`.

**How to avoid:** D-18 + D-15 dedup chain: The `_is_empty_signals` gate checks `CoachingTopicStore` before adding habit items as salient signals. If the 21:30 alert has already fired (it runs after 21:00 tick), `CoachingTopicStore` has `"fueling-miss:pre-bed"` recorded. But the habit nudge uses a different topic key (`"habit-nudge:{id}:{date}"`), so these don't directly block each other. The practical resolution: the autonomous tick runs at 21:00 at the latest (window is 7-21). The 21:30 alert runs at 21:30. So the tick cannot nag AFTER the alert fires — the race is tick→alert order only, never alert→tick. The 21:00 tick could nag pre-bed items before the 21:30 alert. D-18's accepted caveat explicitly allows this; the two are described as complementary. If double-nag from the 21:00 tick is a real concern in practice, the `_gather_habit_adherence` function can exclude `slot="Bedtime"` items from the salient signal list.

---

## Code Examples

### HabitStore.create (following TaskStore.create pattern)

```python
# Source: memory/firestore_db.py TaskStore.create (lines 2540-2570) — exact convention
def create(self, habit: dict) -> dict:
    import uuid
    from datetime import datetime, timezone

    habit_id = habit.get("id") or uuid.uuid4().hex
    payload = {
        "slot": "Morning",
        "status": "active",
        **habit,
        "id": habit_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    try:
        self._col.document(habit_id).set(payload)
    except Exception:
        logger.error("HabitStore.create failed (name=%r)", habit.get("name"), exc_info=True)
        raise
    result = {k: v for k, v in payload.items() if k != "updated_at"}
    return result
```

### HabitStore.log_completion (idempotent toggle)

```python
# Source: MealStore.upsert pattern (lines 741-776) — subcollection path with merge=True
def log_completion(
    self, date_str: str, habit_id: str, done: bool, dose_taken: str | None = None
) -> None:
    """Idempotent. If done=False and a record exists, deletes it (un-check). Re-raises on failure."""
    from datetime import datetime, timezone
    doc_ref = (
        self._client.collection("habit_completions")
        .document(date_str)
        .collection("records")
        .document(habit_id)
    )
    if not done:
        try:
            doc_ref.delete()
        except Exception:
            logger.error("HabitStore.log_completion: delete failed (%r, %r)", date_str, habit_id, exc_info=True)
            raise
        return
    payload = {
        "habit_id": habit_id,
        "date": date_str,
        "done": True,
        "dose_taken": dose_taken,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    try:
        doc_ref.set(payload, merge=True)
    except Exception:
        logger.error("HabitStore.log_completion failed (%r, %r)", date_str, habit_id, exc_info=True)
        raise
```

### CoachingTopicStore dedup in autonomous gather (D-17)

```python
# Source: core/proactive_alerts.py lines 882-914 — same pattern adapted for habit nudge
# in _gather_habit_adherence or the triage result handler

from memory.firestore_db import CoachingTopicStore
_cts = CoachingTopicStore(project_id=project_id, database=database)
today_iso = datetime.now(_TZ).date().isoformat()

pending_filtered = [
    h for h in pending_habits
    if not _cts.has_topic(today_iso, f"habit-nudge:{h['habit_id']}:{today_iso}")
]
# After send succeeds:
_cts.add_topic(today_iso, f"habit-nudge:{h['habit_id']}:{today_iso}")
```

### React check-off hook (react-query optimistic update)

```typescript
// Source: frontend/src/hooks/useTasks.ts useCompleteTask pattern (Phase 27)
export function useCheckOffHabit() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ habitId, date, done, doseTaken }: CheckOffArgs) =>
      apiFetch(`/api/habits/${habitId}/checkin`, {
        method: 'POST',
        body: JSON.stringify({ date, done, dose_taken: doseTaken }),
      }),
    onMutate: async ({ habitId, done }) => {
      await queryClient.cancelQueries({ queryKey: HABITS_QUERY_KEY })
      const prev = queryClient.getQueryData(HABITS_QUERY_KEY)
      // Optimistic: flip the done state
      queryClient.setQueryData(HABITS_QUERY_KEY, (old: Habit[]) =>
        old.map(h => h.id === habitId ? { ...h, done_today: done } : h)
      )
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      queryClient.setQueryData(HABITS_QUERY_KEY, ctx?.prev)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: HABITS_QUERY_KEY })
    },
  })
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TickTick as task source of truth | Native `TaskStore` Firestore (Phase 27) | Phase 27 (2026-06-24) | Same pattern for HabitStore in Phase 28 |
| Hardcoded `SLOT_SUPPLEMENTS` dict | Data-driven HabitStore read | Phase 28 | Klaus's supplement coaching reflects actual check-off state |
| `proactive_alerts.py` infers supplement miss from meal-slot miss | Direct HabitStore check-off query | Phase 28 | Eliminates false positives (took supplement without a post-run meal) |

**Deprecated/outdated:**
- `SLOT_SUPPLEMENTS` hardcoded dict at `core/proactive_alerts.py:90`: superseded by HabitStore query (kept as fallback for empty HabitStore).
- The inference that a missed fueling slot = a missed supplement: replaced by the explicit `habit_completions` record.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `HabitStore.get_pending_today` will be fast enough for the 20-min tick (no per-tick latency budget issue) | Pattern 3: Layer-0 gather | Tick latency could increase; mitigate with server-side Firestore filter |
| A2 | Israel DST spring-forward 2026 is March 27 (last Friday before April 2) | Pattern 2: DST fixtures | Test fixture targets wrong date; verify at `timeanddate.com/time/zone/israel` |
| A3 | Israel DST fall-back 2026 is October 25 (last Sunday of October) | Pattern 2: DST fixtures | Same; verify date |
| A4 | The `prompts/proactive_alert.md` supplement riders (lines 151-153) can be made data-driven without breaking the existing `test_proactive_alert_has_supplement_riders` test | Pattern 4: SLOT_SUPPLEMENTS rewire | Test fails if supplement names in prompt change; update test assertions when prompt is updated |

**If this table is empty for a claim:** All other claims in this research were verified by reading the actual codebase files.

---

## Open Questions (RESOLVED)

1. **Subcollection recursive delete on hard-delete (D-20)**
   - What we know: Firestore subcollections are not automatically deleted when a parent doc is deleted.
   - What's unclear: The cleanest Python approach — `google-cloud-firestore` v2+ provides `collection.recursive_delete()` but it requires an Admin SDK client or the `firebase_admin` package. The existing codebase uses `google-cloud-firestore` (not `firebase_admin`).
   - Recommendation: Implement iterative delete in `HabitStore.hard_delete` — query all docs under `habit_completions/{date}/{habit_id}` for all dates (query by `habit_id` field across the subcollection) and delete them in a batch. Acceptable for a personal-use store with at most 365 completion records per habit.

2. **`schedule_history` query for "habits scheduled today"**
   - What we know: Firestore cannot query inside a nested list field (schedule_history). Getting all habits scheduled for a given weekday requires either a client-side filter or a denormalized index field.
   - What's unclear: At what scale does a client-side filter become a problem? (Answer: never, for a single user with ~20 habits max.)
   - Recommendation: Fetch all active habits (`status == "active"`, server-side filter) and apply `_is_scheduled(today, schedule_history)` in Python. This is O(habits_count) Firestore reads — acceptable at personal scale.

3. **UndoStore for habits — extend existing or separate slice?**
   - What we know: `frontend/src/store/undoStore.ts` already exists for tasks (Phase 27). The `useUndoStore` is imported in `DueTasksBand.tsx` and `TaskRow.tsx`.
   - Recommendation: Add a `habit` discriminator to the existing undo store (add `type: 'habit' | 'task'` field to the undo action; habit delete uses a different API endpoint). This avoids a second zustand store while keeping undo behavior identical.

---

## Environment Availability

Step 2.6: SKIPPED (no new external tools/services/runtimes introduced — all dependencies are existing Cloud Run / Firestore infrastructure already deployed).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing; `tests/` directory, `tests/fakes.py`) |
| Config file | none explicit — `pytest tests/<file>.py` per-file (full-suite segfaults per STATE.md) |
| Quick run command | `pytest tests/test_habit_store.py -x -q` |
| Full suite (per-file) | `pytest tests/test_habit_store.py tests/test_habits_api.py tests/test_autonomous.py -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HABIT-01 | HabitStore.create / list / update / soft_delete | unit | `pytest tests/test_habit_store.py::TestHabitStore -x` | ❌ Wave 0 |
| HABIT-01 | log_completion toggle (done + undone) | unit | `pytest tests/test_habit_store.py::TestHabitCompletion -x` | ❌ Wave 0 |
| HABIT-02 | `/api/habits/{id}/checkin` endpoint returns 200; optimistic state correct | integration | `pytest tests/test_habits_api.py::TestCheckinEndpoint -x` | ❌ Wave 0 |
| HABIT-03 | `compute_streak_and_grid`: pure reset on miss; neutral non-scheduled days | unit | `pytest tests/test_habit_store.py::TestStreakComputation -x` | ❌ Wave 0 |
| HABIT-03 | DST spring-forward 2026 (March 27) does not break streak | unit | `pytest tests/test_habit_store.py::test_streak_survives_spring_forward_dst -x` | ❌ Wave 0 |
| HABIT-03 | DST fall-back 2026 (October 25) does not break streak | unit | `pytest tests/test_habit_store.py::test_streak_survives_fall_back_dst -x` | ❌ Wave 0 |
| HABIT-03 | Backfill yesterday repairs streak; older date returns 400 | unit+integration | `pytest tests/test_habit_store.py::test_yesterday_backfill_repairs_streak tests/test_habits_api.py::test_checkin_rejects_day_before_yesterday -x` | ❌ Wave 0 |
| HABIT-04 | `/api/habits/{id}/history` returns 365-day grid with correct four-state values | unit | `pytest tests/test_habit_store.py::TestGridDerivation -x` | ❌ Wave 0 |
| HABIT-05 | `_gather_habit_adherence` returns [] on error (sentinel pattern) | unit | `pytest tests/test_autonomous.py::test_habit_gather_returns_empty_on_error -x` | ❌ Wave 0 |
| HABIT-05 | `get_habit_adherence` tool schema registered in `core/tools.py` | unit | `pytest tests/test_tools.py -x -k habit` | ❌ Wave 0 |
| TIME-06 | `/api/today` response includes habits due today | integration | `pytest tests/test_api_today.py::test_today_includes_habits -x` | ❌ Wave 0 |
| SLOT_SUPPLEMENTS rewire | 21:30 alert reads HabitStore; falls back to hardcoded dict if empty | unit | `pytest tests/test_proactive_alerts.py -x -k supplement` | existing + extends |

### Sampling Rate

- **Per task commit:** `pytest tests/test_habit_store.py -x -q`
- **Per wave merge:** `pytest tests/test_habit_store.py tests/test_habits_api.py tests/test_autonomous.py tests/test_proactive_alerts.py -q`
- **Phase gate:** All per-wave tests green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_habit_store.py` — HabitStore CRUD + streak computation + four-state grid + DST fixtures (covers HABIT-01/02/03/04)
- [ ] `tests/test_habits_api.py` — FastAPI endpoints + auth + checkin toggle + backfill gate (covers HABIT-02, TIME-06 API side)
- [ ] Framework install: none — pytest already present

*(Existing `tests/test_autonomous.py` and `tests/test_proactive_alerts.py` must be extended — not replaced.)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `require_hub_session` (Phase 26) — all `/api/habits/*` routes behind session cookie |
| V3 Session Management | inherited | Phase 26 session cookie; no new session surface |
| V4 Access Control | yes | `require_hub_session` gates all writes; single-user — no cross-user data risk |
| V5 Input Validation | yes | Validate `slot` is one of 4 values; `days` is "daily" or list of 0-6 ints; `date` is valid ISO YYYY-MM-DD; `type` is "habit" or "supplement" |
| V6 Cryptography | no | No new crypto surface |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Backfill date injection (setting `date` to arbitrary past date) | Tampering | API enforces `date` ∈ {today, yesterday} (Asia/Jerusalem); 400 otherwise |
| Habit ID guessing (accessing another user's habits) | Elevation of privilege | Single-user system; `require_hub_session` gates all reads/writes to Amit's session |
| Dose field injection (XSS via `dose_taken`) | Tampering | Dose rendered as plain React text (never `dangerouslySetInnerHTML`); max length validation on API |
| Schedule history tampering (retroactive edit via API) | Tampering | PATCH validates that new schedule revision has `effective_from >= today_iso`; refuses past dates |

---

## Sources

### Primary (HIGH confidence — verified by reading actual source files)

- `memory/firestore_db.py` — TaskStore (lines 2500-2841), CoachingTopicStore (lines 1817-1928), OutreachLogStore (lines 1702-1814), MealStore (lines 711-882), `_jsonsafe_doc` (line 885)
- `core/autonomous.py` — `gather_situation` thread pool (lines 410-480), `_gather_native_overdue` (lines 236-256), `_is_empty_signals` (lines 172-205), `_build_triage_prompt` (lines 515-563), `_compose_layer2` (lines 663-713)
- `core/proactive_alerts.py` — `SLOT_SUPPLEMENTS` (lines 86-94), `_collect_detected_topics` (lines 653-682), `run_proactive_alerts` coaching dedup gate (lines 876-914)
- `frontend/package.json` — full dependency list (no chart/heatmap library present)
- `frontend/src/components/timeline/DueTasksBand.tsx` — band header pattern (lines 1-80)
- `.planning/phases/28-habits-supplements/28-CONTEXT.md` — 21 locked decisions D-01..D-21
- `.planning/phases/28-habits-supplements/28-UI-SPEC.md` — ContributionGrid cell dimensions, color tokens, iOS sheet z-index requirements
- `.planning/REQUIREMENTS.md` — HABIT-01..05, TIME-06

### Secondary (MEDIUM confidence — cross-referenced)

- `core/proactive_alerts.py:_to_naive_local` — DST handling pattern for Asia/Jerusalem naive datetime comparison
- `tests/test_coaching_topic_store.py` — ArrayUnion plain-string discipline verification
- `tests/test_task_store.py` — test patterns for Firestore store unit tests (fakes.py usage)
- `prompts/proactive_alert.md` lines 141-173 — supplement riders hardcoded in prompt text (not in `SLOT_SUPPLEMENTS` dict)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified by reading `package.json` and existing store classes
- Architecture: HIGH — all patterns grounded in Phase-26/27 code; no novel approaches
- Streak algorithm: HIGH — pure function; DST analysis confirmed via Python `datetime.date` properties; DST dates need external verification (A2, A3)
- SLOT_SUPPLEMENTS rewire: HIGH — full `proactive_alerts.py` read; rewire scope clearly bounded
- Autonomous gather extension: HIGH — `gather_situation` thread pool pattern fully documented
- ContributionGrid: HIGH — no library needed; pure CSS approach consistent with existing inline-style token system

**Research date:** 2026-06-26
**Valid until:** 2026-07-26 (stable stack; no fast-moving external dependencies)
