---
status: passed
phase: 27-tasks
source: [27-VERIFICATION.md]
started: 2026-06-24
updated: 2026-06-24
---

## Current Test

[Phase 27 features were verified live on the deployed Klaus Hub during the
2026-06-24 UAT session. The two phone-specific behaviours that were left pending
were exercised in a dedicated on-device (iPhone) round, which surfaced six
phone-only bugs — all fixed and re-verified live (see "Phone on-device UAT" below).]

## Tests

### 1. Completion micro-animation (150/150/200ms)
expected: checkbox tap → green circle fill → checkmark → row collapse
result: passed (confirmed live — "complete button works, task goes away")

### 2. Undo toast recovery
expected: delete/complete → 4s undo toast → "Undo" restores the task
result: passed (confirmed live after the soft-delete fix; undo restores)

### 3. Last-action-wins toast stacking (rapid second action)
expected: a second action before the first toast expires immediately hard-deletes the first
result: passed (complete/delete + undo verified live this session; the
        rapid second-action-fires-first-hard-delete path is covered by the
        undoStore last-action-wins unit tests — no regression)

### 4. Recurring task next-instance
expected: complete a Weekly task → next occurrence appears with the correct date
result: passed (confirmed live after the recurrence-save fix)

### 5. Quick-add live chip resolution — phone FAB bottom sheet
expected: typing in the FAB sheet resolves date/priority/list chips live
result: passed (verified live on iPhone after the bottom-sheet/keyboard +
        Add-task-submit fixes — chips resolve while typing
        e.g. "gym tomorrow #health !high", and "Add task" creates the task)

### 6. Quick-add N-key shortcut (desktop)
expected: N (when not in an input) focuses the persistent quick-add bar
result: passed (confirmed live; persistent desktop bar + N focus)

### 7. Today timeline "Due today" band
expected: band appears with today's tasks; hidden when none
result: passed (confirmed live — screenshot showed the band with a due task)

### 8. Glance rail Tasks section
expected: due-today / overdue counts match Firestore; overdue hides when 0
result: passed (confirmed live — "due today 1" matched)

## Phone on-device UAT (2026-06-24, iPhone)

The phone spot-checks surfaced six phone-only bugs (iOS-Safari mobile-web issues
that do not reproduce on desktop Chrome or in CI). All fixed and re-verified live:

1. Edit/detail sheet shifted off the left edge — FIXED
2. "Lists" picker buried behind the bottom tab bar — FIXED
3. Quick-add FAB sheet hidden behind the keyboard; tab bar floating mid-screen — FIXED
4. Kebab (⋯) row menu missing on phone — FIXED
5. "Save changes" below the fold / sheet scroll broken — FIXED
6. Quick-add "Add task" button did not submit on phone (blur-before-click race) — FIXED

Root causes + fixes (commits `089e6da`, `54cd5fa`):
- z-index: every phone bottom-sheet overlay sat below `BottomTabs` (z:100); raised
  scrims to z:190 / sheets to z:191 (nested recurring-scope to 200/201).
- iOS keyboard vs `position:fixed`: new `useVisualViewport` hook anchors the detail
  + quick-add sheets with `bottom: keyboardInset`; background scroll locked while
  open; detail-sheet Title `autoFocus` gated to desktop.
- detail sheet restructured so the body scrolls and the footer (Save) stays pinned.
- TaskRow ⋯ menu now renders on all breakpoints (swipe-to-delete kept).
- QuickAddBar "Add task" button: `preventDefault` on mousedown so the input keeps
  focus and the click submits (the onBlur no longer closes the sheet first).

Backend unchanged. Frontend build clean; 82 vitest tests pass (76 + 6 new
`useVisualViewport` specs).

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None. All eight tests pass; the two formerly-pending phone behaviours were
exercised on-device, and the six bugs that round surfaced are fixed and
re-verified live on the deployed hub.
