---
status: passed
phase: 28-habits-supplements
source: [28-VERIFICATION.md]
started: "2026-06-30"
updated: "2026-07-02"
---

## Current Test

[complete — all items passed on device 2026-07-02, rev klaus-agent-00137-jq6]

## Tests

### 1. Habits tab visual layout (phone)
expected: Habits/supplements grouped by slot (Morning/Noon/Evening/Bedtime) with sticky headers, streak chips, 44px touch targets, phone FAB ("Add habit" on desktop).
result: pass

### 2. iOS bottom-sheet behavior (phone)
expected: Create/Edit + DoseEditSheet open above the BottomTabs, keyboard tracked via useVisualViewport, scroll-locked, dismiss buttons don't eat submits, no phone autoFocus.
result: pass

### 3. Check-off toggle + supplement dose sheet
expected: Tapping a habit toggles done/undone; tapping a supplement opens the dose-edit sheet and records dose-taken.
result: pass

### 4. ContributionGrid visual (per-habit history)
expected: 52+ column four-state grid, legend, streak label. WR-03 fixed 2026-07-02 (rev 00137) — cells weekday-aligned via leading pad, column count sized to pad+cells so today is never dropped, auto-scrolls to today. Today's check-off now shows as a filled cell.
result: pass

### 5. HabitsBand on Today timeline
expected: Today's scheduled habits/supplements render as a band right after DueTasksBand; renders nothing when none scheduled; tap toggles / opens dose sheet.
result: pass

### 6. GlanceRail Habits card (desktop)
expected: Habits streaks card desktop-only below the Tasks card, up to 4 streak leaders, "[N]-day streak" formatting, navigates to /habits. WR-04 fixed — updates live on check-off. Streaks required the records.habit_id COLLECTION_GROUP index (created 2026-07-02).
result: pass

### 7. Delete + undo toast + WR-02 zombie-doc
expected: Deleting shows an undo toast; undo within 4s restores; on expiry hard-deletes. WR-02 fixed server-side (reclaim_stale_deletions in list_active) + Bug-1 fix (UndoToast mounted globally in AppShell so /habits shows the toast). Navigate-away no longer strands the doc.
result: pass

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None — all items passed on device (rev klaus-agent-00137-jq6, 2026-07-02).

## Post-UAT fixes applied (all deployed + verified)

- Bug 1 — undo toast absent on /habits: `<UndoToast />` moved from TasksPage to AppShell (global). Commit f1ff47e.
- Bug 2 — streak/grid always empty: missing `records.habit_id` COLLECTION_GROUP Firestore index created; `get_history` failure logging hardened (WR-05). Commits 5da5f77 / f944e9b + index.
- WR-02 — zombie 'completing' docs: server-side `HabitStore.reclaim_stale_deletions()` from `list_active`. Commit 11c3064.
- WR-04 — stale summary: check-off invalidates `['habits','summary']`. Commit efe2289.
- WR-03 — grid dropped today's cell: weekday-aligned + fitted + auto-scroll ContributionGrid. Commit 1e4f215.
