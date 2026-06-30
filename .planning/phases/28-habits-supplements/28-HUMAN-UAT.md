---
status: partial
phase: 28-habits-supplements
source: [28-VERIFICATION.md]
started: "2026-06-30"
updated: "2026-06-30"
---

## Current Test

[awaiting human testing on physical iPhone + desktop browser]

## Tests

### 1. Habits tab visual layout (phone)
expected: Habits/supplements grouped by slot (Morning/Noon/Evening/Bedtime) with sticky headers, streak chips, 44px touch targets, phone FAB ("Add habit" on desktop).
result: [pending]

### 2. iOS bottom-sheet behavior (phone)
expected: Create/Edit + DoseEditSheet open above the BottomTabs (z-index chain scrim:190/sheet:191/dose:192), keyboard tracked via useVisualViewport, scroll-locked, dismiss buttons don't eat submits (onMouseDown preventDefault), no phone autoFocus.
result: [pending]

### 3. Check-off toggle + supplement dose sheet
expected: Tapping a habit toggles done/undone (accent fill + checkmark, ~150ms); tapping a supplement opens the dose-edit sheet and records dose-taken.
result: [pending]

### 4. ContributionGrid visual (per-habit history)
expected: 52-column four-state grid (done/missed/not-scheduled/pending), legend, streak label. KNOWN DEFECT WR-03: backend emits 365 cells starting from an arbitrary weekday, so row-N is not a fixed weekday and a 365th cell can overflow the 52×7 (364-slot) grid — data is correct, layout is cosmetically off.
result: [pending]

### 5. HabitsBand on Today timeline
expected: Today's scheduled habits/supplements render as a band right after DueTasksBand; renders nothing when none scheduled; tap toggles / opens dose sheet.
result: [pending]

### 6. GlanceRail Habits card (desktop)
expected: Habits streaks card appears desktop-only below the Tasks card, up to 4 streak leaders, "[N]-day streak" formatting, navigates to /habits, empty state "No habits defined."
result: [pending]

### 7. Delete + undo toast + WR-02 zombie-doc
expected: Deleting shows an undo toast; undo within 4s restores; on expiry it hard-deletes definition + history. KNOWN BUG WR-02: navigating away during the 4s window leaves the habit in status='completing' — permanently invisible, never deleted, no restore path (the "server GC" comment describes a GC that does not exist). Decide whether to fix.
result: [pending]

## Summary

total: 7
passed: 0
issues: 0
pending: 7
skipped: 0
blocked: 0

## Gaps
