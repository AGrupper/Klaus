---
status: partial
phase: 27-tasks
source: [27-VERIFICATION.md]
started: 2026-06-24
updated: 2026-06-24
---

## Current Test

[Phase 27 features were verified live on the deployed Klaus Hub during the
2026-06-24 UAT session, across multiple deploy/fix rounds, before the TickTick
cutover was approved. Two phone-specific behaviours were not explicitly
exercised — see Tests below.]

## Tests

### 1. Completion micro-animation (150/150/200ms)
expected: checkbox tap → green circle fill → checkmark → row collapse
result: passed (confirmed live — "complete button works, task goes away")

### 2. Undo toast recovery
expected: delete/complete → 4s undo toast → "Undo" restores the task
result: passed (confirmed live after the soft-delete fix; undo restores)

### 3. Last-action-wins toast stacking (rapid second action)
expected: a second action before the first toast expires immediately hard-deletes the first
result: pending (not explicitly exercised in UAT)

### 4. Recurring task next-instance
expected: complete a Weekly task → next occurrence appears with the correct date
result: passed (confirmed live after the recurrence-save fix)

### 5. Quick-add live chip resolution — phone FAB bottom sheet
expected: typing in the FAB sheet resolves date/priority/list chips live
result: pending (desktop quick-add confirmed; phone FAB sheet not explicitly tested)

### 6. Quick-add N-key shortcut (desktop)
expected: N (when not in an input) focuses the persistent quick-add bar
result: passed (confirmed live; persistent desktop bar + N focus)

### 7. Today timeline "Due today" band
expected: band appears with today's tasks; hidden when none
result: passed (confirmed live — screenshot showed the band with a due task)

### 8. Glance rail Tasks section
expected: due-today / overdue counts match Firestore; overdue hides when 0
result: passed (confirmed live — "due today 1" matched)

## Summary

total: 8
passed: 6
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps

None blocking. The two pending items (rapid last-action-wins stacking; phone FAB
quick-add sheet) are low-risk behaviours with passing automated coverage
(undoStore last-action-wins unit-tested; parseTaskInput unit-tested). Spot-check
on a phone at leisure; not a release blocker.
